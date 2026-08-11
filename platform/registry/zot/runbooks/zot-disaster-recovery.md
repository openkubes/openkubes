# Recover registry-default after namespace or PVC loss

This is the disaster-recovery half of the `registry-default` operating procedure. For initial
installation, use [zot-bootstrap.md](zot-bootstrap.md). For export retention, integrity limits and
the isolated restore drill, use [zot-backup-restore.md](zot-backup-restore.md). This document
sequences those existing mechanisms into recovery of the production service; it does not define a
second content format or restore algorithm.

## Scope and proof boundary

**Covered disaster:** complete loss of namespace `zot`, including its `local-path` PVC, on an
otherwise recoverable `ok-shared`. The same procedure covers a lost PVC after an outage owner has
removed the unusable release and recreated a clean `zot` namespace. Recovery requires Git, the
pinned local chart, and a valid off-cluster OCI export plus its detached integrity manifest. It
also requires Keycloak, the `ok-shared-internal-ca` issuer, Traefik, `local-path`, the
infrastructure-published ingress path and the cluster observability APIs to have survived or been
recovered first.

**Not covered end to end:** loss of the whole `ok-shared` cluster or of those prerequisite
services. Their owners must recover the cluster, central identity, CA, ingress and storage
capabilities before this procedure starts. Recreating `ok-shared` is explicitly two phase: create
it without `registryTrust.enabled`, recover the CA and registry, then apply consumer trust. The
Talos mechanics, replacement-node caveats and effect checks live only in
[`ok-cluster/docs/registry-trust.md`](https://github.com/openkubes/ok-cluster/blob/main/docs/registry-trust.md).
Whole-cluster recovery has not been exercised by this profile and no RTO is claimed.

The current interim storage decision remains `local-path` plus off-cluster export until OK-81
provides MinIO. This procedure does not turn a workstation directory into production-approved
retention and does not satisfy or change the storage acceptance criterion.

The isolated restore drill has exercised artifact verification, dependency-ordered import,
Referrers recovery, immutable-digest pull and scratch cleanup. It has not exercised destructive
namespace loss, production import, credential propagation, CA replacement or whole-cluster
recreation. Every production step below is therefore labelled **UNEXERCISED** until an approved
outage drill records its effects.

## What the backup cannot recover

Git reconstructs rendered configuration and authorization policy. The OCI export reconstructs
artifact manifests, blobs, tags and subject-to-referrer relationships. Neither reconstructs a
secret value.

- `zot-htpasswd` and `zot-machine-identities` are an inseparable bcrypt/cleartext pair. Exact
  recovery would preserve the `zot-machine`, `zot-puller` and `zot-metrics` passwords, but no such
  escrow exists today. If either Secret is absent or incomplete, `make identities` regenerates
  both and rotates all three passwords. Every publisher, image-pull Secret and metrics consumer
  holding an old value then fails authentication and must receive the new value.
- Zot parses htpasswd only at startup. If identities are rotated while an old zot pod remains
  running, the new credentials return 401 until `statefulset/zot` restarts. In the namespace-loss
  sequence identities are created before zot starts, so no extra restart is expected. A different
  order creates an avoidable authentication outage.
- `zot-oidc` has no independent backup today: neither its client secret nor its session keys are
  in Git or the OCI export. If central Keycloak survived, `make oidc-client` reads the current
  `registry-default` client secret back from Keycloak and writes it into the new namespace; it
  creates new session keys because the old keys are gone. Existing browser sessions are then
  invalid. If Keycloak was recreated, the client secret also changes and only the newly reconciled
  value is valid.
- Zot-generated human API keys are registry authentication state, not OCI artifacts. After PVC
  loss users must authenticate through a browser again and mint replacement API keys.
- `zot-conformance-identities` is regenerated when absent; `make oidc-client` resets the two
  dedicated Keycloak test-user passwords to those new values. These are conformance identities,
  not reusable automation credentials. Ordinary CI, publishers and pullers must use the htpasswd
  `zot-machine` or `zot-puller` identities: a `registry-writers` OIDC user cannot use plain
  user/password with Docker, Podman or ORAS before completing browser OIDC and minting an API key.
  The guarded backup/recovery tooling is a narrow exception: it drives the browser login flow for
  the dedicated conformance writer and holds only a process-scoped session cookie so it can cover
  `openkubes/human/**`; it does not turn that password into a reusable registry credential.
- Recovered OCI signatures, SBOMs and attestations are artifact content. They do not recover a
  signing private key or an external verification policy. No registry-held signing key is
  configured by this profile; signing-key custody remains with the producing system.
- A reissued leaf certificate under the same recovered CA preserves consumer trust. A replaced CA
  does not: every opted-in consumer must receive the new root before it can pull.

Regeneration restores the same identity names and repository permissions, not the old credential
values. Service is not recovered until credential holders and trust consumers have converged.

## Recovery order and why it is strict

The order is: verify retained content; recover platform prerequisites; pause writers; recreate the
namespace; establish identities and OIDC; issue the certificate and route; start an empty zot;
restore content; register metrics; prove the endpoint; then update trust and credentials before
resuming consumers.

Identities precede zot because its first process must mount and parse the final htpasswd. Identity
and certificate prerequisites precede content because the production restore uses the same
authorization and TLS configuration consumers will use. Content precedes consumer release because
an empty but Ready registry correctly authenticates and still returns `manifest unknown`. Trust,
name resolution and rotated pull credentials precede consumer release because restored bytes are
irrelevant to a kubelet that cannot establish TLS or authenticate.

## 1. Select and verify the recovery point

**Effect gate:** the chosen pair verifies without cluster access, and the operator records its
timestamp and limitations. Detached SHA-256 proves integrity against that manifest, not
authenticity: an attacker who replaces both files can construct another self-consistent pair. The
catalog also cannot prove absence of repositories invisible to the two scoped export identities,
and an export concurrent with writes is not transactional.

Use the retained pair created by [zot-backup-restore.md](zot-backup-restore.md), not files recovered
from the lost PVC:

```bash
ZOT_SHELF="$PWD/openkubes/platform/registry/zot"
RESTORE_ARTIFACT="/retained/path/zot-<timestamp>-<pid>.tar"
INTEGRITY_MANIFEST="/retained/path/zot-<timestamp>-<pid>.integrity.json"

make -C "$ZOT_SHELF" verify-backup \
  RESTORE_ARTIFACT="$RESTORE_ARTIFACT" \
  INTEGRITY_MANIFEST="$INTEGRITY_MANIFEST"
```

Stop if the verifier does not print `RESULT: PASS`. If no valid retained export exists, artifact
content is not recoverable by this profile; Git can produce an empty configured service only.

## 2. Recover and prove prerequisites

**Effect gate — UNEXERCISED as a DR sequence:** `oks` selects
`ok-shared-admin@ok-shared`; all expected nodes are Ready; Keycloak and the internal issuer are
reachable; `ClusterIssuer/ok-shared-internal-ca` is Ready; Traefik and `StorageClass/local-path`
exist; and the registry address discovery used by the shelf succeeds. If the CA or published
address changed, keep consumers stopped until step 7 reconciles them.

```bash
oks && test "$(kubectl config current-context)" = ok-shared-admin@ok-shared
oks && kubectl wait node --all --for=condition=Ready --timeout=30s
oks && kubectl wait clusterissuer/ok-shared-internal-ca \
  --for=condition=Ready --timeout=30s
oks && kubectl get storageclass local-path -o json | \
  jq -e '.metadata.name == "local-path"'
oks && kubectl wait statefulset/keycloak-keycloakx -n keycloak \
  --for=jsonpath='{.status.readyReplicas}'=1 --timeout=30s
oks && kubectl wait deployment/traefik -n ingress \
  --for=condition=Available --timeout=30s
oks && REGISTRY_LB_KUBECONFIG="$HOME/.kube/ok-infra.yaml" && \
  . "$ZOT_SHELF/tooling/registry-defaults.sh" && \
  test -n "$REGISTRY_LB" && \
  curl --fail --silent --show-error \
    --resolve "keycloak.ok-shared.internal:443:$REGISTRY_LB" \
    --cacert <(kubectl get secret keycloak-server-tls -n keycloak \
      -o jsonpath='{.data.ca\.crt}' | base64 -d) \
    https://keycloak.ok-shared.internal/realms/openkubes/.well-known/openid-configuration | \
  jq -e '.issuer == "https://keycloak.ok-shared.internal/realms/openkubes"'
RENDERED_ZOT="$(mktemp /tmp/ok138-zot-dr-rendered.XXXXXX.yaml)"
trap 'rm -f -- "$RENDERED_ZOT"' EXIT INT TERM
make -C "$ZOT_SHELF" render >"$RENDERED_ZOT"
python3 -c 'import sys,yaml; list(yaml.safe_load_all(open(sys.argv[1]))); print("rendered YAML parsed")' \
  "$RENDERED_ZOT"
```

Do not start with `registryTrust.enabled: true` when recreating `ok-shared`; the registry CA and
endpoint do not exist yet. Resume here only after the first cluster bootstrap and shared-service
prerequisites are healthy.

## 3. Fence writers and confirm namespace loss

**Effect gate — UNEXERCISED:** publishers, promotion jobs and human writers are paused, and
`kubectl get namespace zot` returns NotFound. Do not delete a surviving namespace or PVC merely to
make it match this runbook; destructive cleanup needs its own outage approval and backup decision.

There is no registry-wide executable writer-fence in this profile today. Record the owners and
jobs paused, keep the recovery inside an announced maintenance window, and stop if any writer
cannot be accounted for. The target rechecks both visible catalogs immediately before its first
write, but catalog-check plus import is not atomic; this is a residual race, not a claimed lock.

The recreated endpoint becomes reachable before content import because the TLS Secret is required
when zot starts. Pausing writers prevents a valid but incomplete new registry from accepting
content before the restore's empty-catalog guard. Keep consumers in outage/maintenance state too;
an empty registry returns `manifest unknown` even though readiness and authentication work.

## 4. Recreate configuration and identities

**Effect gate — UNEXERCISED:** namespace `zot` exists; the machine htpasswd/cleartext pair and
conformance Secret contain their required keys; the Certificate is Ready; the central OIDC client,
groups mapper and profile groups reconcile; `zot-oidc` contains the current Keycloak client secret
and fresh or recovered session keys; the pinned StatefulSet is Ready on one newly created PVC.

Run the existing targets in their dependency order. Do not use aggregate `install`: recovery must
record each effect separately and capture the new PVC identity before content writes.

```bash
oks && make -C "$ZOT_SHELF" namespace KUBECONFIG="$KUBECONFIG"
oks && make -C "$ZOT_SHELF" identities KUBECONFIG="$KUBECONFIG"
oks && make -C "$ZOT_SHELF" reachability KUBECONFIG="$KUBECONFIG"
oks && make -C "$ZOT_SHELF" oidc-client \
  KUBECONFIG="$KUBECONFIG" APPROVE_OIDC_CLIENT=yes
oks && make -C "$ZOT_SHELF" zot KUBECONFIG="$KUBECONFIG"

oks && EXPECTED_PVC_UID="$(kubectl get pvc zot-pvc-zot-0 -n zot \
  -o jsonpath='{.metadata.uid}')"
test -n "$EXPECTED_PVC_UID"
printf 'EXPECTED_PVC_UID=%s\n' "$EXPECTED_PVC_UID"
```

Record whether exact Secret escrow was used or credentials were regenerated. Do not print any
secret value. The PVC UID is not a credential; the guarded restore requires it to bind approval to
the newly inspected destination.

## 5. Restore artifact content into the replacement

**Effect gate — UNEXERCISED on production `zot/zot`:** the guarded target re-verifies the retained
pair before cluster mutation; binds `service/zot` to its single Ready `zot-0` endpoint, reviewed
image/image ID, configuration and Secret mounts, and the exact expected PVC UID; sees zero
repositories through both current machine and human catalog views; reaches only that Service
through a loopback port-forward; restores blobs and manifests in dependency order; reasserts
Referrers relationships without retaining drill-only synthetic tags; and pulls the recorded
immutable digest with returned bytes hashing to that digest.

Run from the same attended shell that set `EXPECTED_PVC_UID`:

```bash
oks && make -C "$ZOT_SHELF" disaster-recovery \
  KUBECONFIG="$KUBECONFIG" \
  RESTORE_ARTIFACT="$RESTORE_ARTIFACT" \
  INTEGRITY_MANIFEST="$INTEGRITY_MANIFEST" \
  EXPECTED_PVC_UID="$EXPECTED_PVC_UID" \
  APPROVE_DISASTER_RECOVERY=yes
```

The empty-catalog assertion covers the normal `openkubes/{machine,human}/**` views available to
the exporter; it cannot certify registry-wide absence of a repository visible only to
`platform-admins`. Stop on a non-empty view: either a writer escaped the fence or this is not the
fresh destination approved in step 4. The target is for first import into a replacement PVC, not
routine synchronization or an existing live release.

The import is fail-closed but not transactional. If it fails after the first content write, do
not bypass the now-nonempty catalog guard and do not try to infer which objects landed. Keep all
writers and consumers paused, retain the failure transcript, remove only this known-incomplete
replacement release/PVC through the exact-UID reset below, and repeat steps 4 and 5 with the new
PVC UID. The reset is one fail-closed action: it revalidates the Bound PVC UID, uninstalls only the
exact Helm release, proves both the StatefulSet and pod absent, then asks the Kubernetes API to
delete only `zot-pvc-zot-0` with an atomic `DeleteOptions.preconditions.uid` matching the approved
UID and proves that claim absent:

```bash
oks && make -C "$ZOT_SHELF" reset-incomplete-disaster-recovery \
  KUBECONFIG="$KUBECONFIG" \
  EXPECTED_PVC_UID="$EXPECTED_PVC_UID" \
  INTEGRITY_MANIFEST="$INTEGRITY_MANIFEST" \
  APPROVE_INCOMPLETE_RECOVERY_RESET=yes
```

Never use that reset sequence against a healthy or uncertain original PVC. It is permitted here
only because the original was already lost, the replacement is known incomplete, and step 1
proved the retained recovery pair before any write.

That warning is not the guard, because prose cannot stop a paste. The UID precondition only
promises to delete *exactly the object you named*, and step 4 above hands you a UID — if the claim
was never actually lost, `make zot` rebinds the **original** and that is the UID you now hold.
So `INTEGRITY_MANIFEST` is required here too: the tool refuses unless the claim was created
**after** the recovery point it records. A replacement made during this recovery postdates the
backup; the original predates it. If you see that refusal, stop and re-establish whether the
original PVC was ever lost — do not look for a way around it.

## 6. Register metrics and prove the recovered service

**Effect gate — UNEXERCISED as a DR sequence:** ServiceMonitor admission succeeds; `post-check`
proves the pod and certificate Ready, same-name TLS route, authenticated registry API and metrics,
and selector/port agreement. A separate Prometheus query must show the target Up and real
`zot_*` series; `post-check` alone does not prove collection.

```bash
oks && make -C "$ZOT_SHELF" metrics KUBECONFIG="$KUBECONFIG"
oks && make -C "$ZOT_SHELF" post-check KUBECONFIG="$KUBECONFIG"
oks && PROM_API='/api/v1/namespaces/ok-observability/services/http:ok-observability-prometheus:9090/proxy/api/v1/query' && \
  kubectl get --raw "$PROM_API?query=up%7Bnamespace%3D%22zot%22%2Cservice%3D%22zot%22%7D" | \
  jq -e '.status == "success" and (.data.result | length) == 1 and .data.result[0].value[1] == "1"'
oks && PROM_API='/api/v1/namespaces/ok-observability/services/http:ok-observability-prometheus:9090/proxy/api/v1/query' && \
  kubectl get --raw "$PROM_API?query=count%28%7Bnamespace%3D%22zot%22%2Cservice%3D%22zot%22%2C__name__%3D~%22zot_.%2A%22%7D%29" | \
  jq -e '.status == "success" and (.data.result | length) == 1 and (.data.result[0].value[1] | tonumber) > 0'
```

Retain the disaster-recovery output line containing the pulled reference, computed SHA-256 and
exact recorded digest. That is the required content proof; pod readiness by itself is not.

## 7. Reconcile credentials and consumer trust

**Effect gate — UNEXERCISED:** every automation holder uses the new `zot-machine` or `zot-puller`
password if rotation occurred; humans can complete browser OIDC and replace API keys; each opted-in
cluster resolves `registry.ok-shared.internal`, trusts the current CA on every node, and can pull a
recovered artifact by immutable digest. Old credentials must return 401 after rotation; accepting
one means an old password remains deployed somewhere.

Use `ok-cluster/docs/registry-trust.md` for review, dry-run, apply and node readback. Do not copy its
Talos commands here. Rerun it for every new or replaced node and whenever the CA or infrastructure
address changed. Apply trust only after the registry exists; otherwise the self-referential
`ok-shared` bootstrap fails.

Resume publishers and consumers only after their credential/trust owners report the effects above.
The final consumption proof must be an uncached pull of a recovered immutable digest by a real
consumer. It is not proven by a local curl, a cached image or a Ready pod.

## 8. Record the recovery result

Record the export timestamp (achieved RPO), start/end times (observed RTO), restored representative
digest, PVC UID, whether machine/OIDC/session credentials were recovered or regenerated, every
credential holder updated, CA fingerprint continuity or rotation, consumer clusters/nodes
reconciled, Prometheus result, and any residual scratch or retained work directory.

Do not describe this runbook as fully tested until an approved namespace/PVC-loss rehearsal has
executed steps 2 through 7. The existing scratch transcript proves the artifact-content mechanism
only. It does not by itself satisfy ADR-Platform-028 §4.8's configuration, authorization,
signing/trust, ingress/certificate and machine-identity recovery obligations.
