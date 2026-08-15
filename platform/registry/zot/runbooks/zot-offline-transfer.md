# Transfer a named OpenKubes release offline

This procedure exports one declared OpenKubes release from `registry-default` on `ok-shared`,
verifies its bytes and complete OCI descriptor/referrer closure without source-registry access,
imports it into a registry that has never held it, and pulls every declared member by immutable
digest. It reads but never writes, scales or restarts the live registry.

This is the operational offline-portability proof required by ADR-Platform-028 §8.8. It is not an
`air-gapped` Constraint Envelope qualification. ADR-Platform-017 defines no such envelope, and
ADR-Platform-028 explicitly defers that formalisation.

## The representative release

The version-controlled declaration is
[`../releases/ok-138-representative-v1.json`](../releases/ok-138-representative-v1.json). Its two
top-level members are:

| Member | Kind and role | Immutable source reference |
| --- | --- | --- |
| `openkubes-contract-image` | container image / workload | `openkubes/machine/conformance-ok138-smoke-live3@sha256:23efd2c1ae875dac645390029d3d8513a768f141c2835710a8f6a42b17b8b43e` |
| `openkubes-contract-chart` | OCI Helm chart / deployment chart | `openkubes/machine/charts/demo-ok138-smoke-live3@sha256:73da6072ebb313ee19de6a94eddc92ab37d252cc0427a9ddc09773fb81323d8f` |

The image has an OCI referrer at
`sha256:ee2f44dcd62dafc22d759c09047e5004c2fa107d3d1221509f72f9f9b85f762a`.
It is an SPDX SBOM artifact (`artifactType: application/spdx+json`) produced by the registry
contract exercise. The exporter discovers
that edge through the Referrers API and includes the referrer's own descriptors. The set is
representative because it exercises both artifact classes required by the registry contract,
multiple repositories, immutable roots, normal config/layer closure and a subject-to-referrer
graph. It is deliberately small enough for an operator to inspect and transfer repeatedly; it is
not a claim that these fixtures are a product release offered to users.

The declaration records that SBOM as a required referrer, including its subject digest, immutable
referrer digest and artifact type. An empty or incomplete Referrers API response is therefore an
export failure, not a smaller release that happens to remain self-consistent.

Membership is an explicit JSON list, not a repository prefix or a mutable tag. If this declaration
is replaced for a later release, publish OCI-format content with podman or buildx, then read each
authoritative digest back from zot's `Docker-Content-Digest` response header before recording it.
Classic Docker Schema2 pushes are rejected by this zot profile, and zot may re-serialise a
manifest on write, changing a locally predicted digest.

## Completeness boundary

Starting at every declared `repository@digest`, `release-export` walks to a fixed point:

- child manifests named by an OCI index's `manifests` descriptors;
- each manifest's `config`, `layers` and `blobs` descriptors;
- OCI referrers for every visited manifest, including referrers of referrers;
- every child and blob descriptor owned by those referrer manifests.

Export fails before publication if a declared root, required referrer, child manifest or
descriptor blob is absent, has an unsupported digest, has a mismatched declared media/artifact
type, or does not hash to its descriptor. The archive embeds the normalized
release set plus the observed manifest/blob closure and referrer edges. `verify-release` recomputes
that closure from the extracted OCI layout and fails if any referenced item is absent, even when
the detached checksum and every byte still present are valid.

This proves closure of the declared roots and the referrer graph returned by the source. It does
not discover an unattached manifest outside that graph, a cross-repository referrer, or a referrer
that a compromised source omitted from its API response. Descriptor URLs are not an offline
fallback: required bytes must be in the layout. Detached SHA-256 proves integrity, not
authenticity; replacing both archive and detached manifest remains outside this proof.

## 1. Record the live boundary

Run from an attended shell at the workspace root. `oks` selects
`/mnt/d/kubernauts/kubeconfig/ok-shared.yaml`; do not export `KUBECONFIG` manually.

```bash
ZOT_SHELF="$PWD/openkubes/platform/registry/zot"
RELEASE_SET="$ZOT_SHELF/releases/ok-138-representative-v1.json"
TRANSFER_DIR="/path/on/operator-retained-storage/ok-138-representative-v1"
install -d -m 700 "$TRANSFER_DIR"

oks && LIVE_POD_BEFORE="$(kubectl -n zot get pod zot-0 \
  -o jsonpath='{.metadata.uid}{"  "}{.metadata.creationTimestamp}{"  "}{.status.containerStatuses[0].restartCount}')"
oks && LIVE_PVC_BEFORE="$(kubectl -n zot get pvc zot-pvc-zot-0 \
  -o jsonpath='{.metadata.uid}{"  "}{.metadata.creationTimestamp}')"
printf 'LIVE_POD_BEFORE=%s\nLIVE_PVC_BEFORE=%s\n' "$LIVE_POD_BEFORE" "$LIVE_PVC_BEFORE"
```

Retain both lines. A successful procedure ends with byte-for-byte identical values.

## 2. Export the declared release

```bash
oks && make -C "$ZOT_SHELF" release-export \
  KUBECONFIG="$KUBECONFIG" \
  RELEASE_SET="$RELEASE_SET" \
  TRANSFER_DIR="$TRANSFER_DIR"
```

The target uses `registry-defaults.sh` for reachability and reads the existing machine identities
from Kubernetes without printing or persisting their values. Success atomically publishes the
same two-file format used by backup: an OCI-layout tar containing `inventory.json`, and a detached
integrity JSON. No parallel transfer archive format is introduced; the separate release-set schema
exists only to define selection.

Copy the two printed paths exactly:

```bash
TRANSFER_ARTIFACT="<printed BACKUP_ARTIFACT path>"
TRANSFER_INTEGRITY_MANIFEST="<printed INTEGRITY_MANIFEST path>"
test -r "$RELEASE_SET" \
  && test -r "$TRANSFER_ARTIFACT" \
  && test -r "$TRANSFER_INTEGRITY_MANIFEST"
```

Carry all three files to the disconnected site. The release declaration is review evidence; the
tar embeds the canonical copy and the verifier rejects any mismatch in its closure.

## 3. Verify without the source

On the receiving host, make the source kubeconfig and registry routing unavailable for this
command. The verifier accepts only local paths and does not load cluster defaults, credentials or
network clients:

```bash
env -u KUBECONFIG -u REGISTRY_LB -u REGISTRY_LB_KUBECONFIG \
  make -C "$ZOT_SHELF" verify-release \
    TRANSFER_ARTIFACT="$TRANSFER_ARTIFACT" \
    TRANSFER_INTEGRITY_MANIFEST="$TRANSFER_INTEGRITY_MANIFEST"
```

PASS must state both integrity and release completeness. Do not import an archive for which this
step did not pass.

## 4. Import into a registry that never held the release

Return to the `oks` operator shell for the acceptance drill:

```bash
oks && make -C "$ZOT_SHELF" offline-transfer-drill \
  KUBECONFIG="$KUBECONFIG" \
  TRANSFER_ARTIFACT="$TRANSFER_ARTIFACT" \
  TRANSFER_INTEGRITY_MANIFEST="$TRANSFER_INTEGRITY_MANIFEST" \
  APPROVE_RESTORE_DRILL=yes
```

The approval is attended because it creates and deletes cluster objects. The tool generates a
unique `zot-restore-drill-*` namespace and first proves it does not exist. It installs the pinned
zot image with `persistence=false`, no auth, no TLS, no ingress and a `ClusterIP` Service, then
constructs its only destination as a loopback `kubectl port-forward`. There is no operator-supplied
destination address and the live `zot/zot` namespace/release is rejected.

The scratch registry is empty by construction and its empty catalog is asserted before import.
After import the drill requests every declared member and every recorded recursive referrer by its
immutable digest, hashes their manifest bytes and every child/config/layer/blob payload, and
re-queries every recorded Referrers edge. PASS therefore applies to both release roots and the
SPDX payload, not an arbitrary representative item.

Default cleanup uninstalls scratch, deletes its namespace and proves it absent. For diagnosis only,
`RETAIN_SCRATCH=yes` transfers prompt cleanup responsibility to the operator; use the exact removal
commands printed by the drill and prove the namespace is gone.

## 5. Prove cleanup and live isolation

```bash
# ALL_NS must be non-empty on success, so a failed query cannot masquerade as
# "no scratch namespaces". Never derive absence from an empty result alone.
oks && ALL_NS="$(kubectl get namespaces -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}')"
SCRATCH_REMAINS="$(printf '%s\n' "$ALL_NS" | grep '^zot-restore-drill-' || true)"
oks && LIVE_POD_AFTER="$(kubectl -n zot get pod zot-0 \
  -o jsonpath='{.metadata.uid}{"  "}{.metadata.creationTimestamp}{"  "}{.status.containerStatuses[0].restartCount}')"
oks && LIVE_PVC_AFTER="$(kubectl -n zot get pvc zot-pvc-zot-0 \
  -o jsonpath='{.metadata.uid}{"  "}{.metadata.creationTimestamp}')"
oks && make -C "$ZOT_SHELF" post-check KUBECONFIG="$KUBECONFIG"

# Two failure modes, both of which have produced false "verified" here before:
#  - a bare `test` does not stop a following printf in a shell without set -e;
#  - a failed kubectl leaves its variable EMPTY, and empty equals empty, so an
#    unobserved before/after pair would compare equal and read as "unchanged".
# Hence every observation must be non-empty AND equal, in one statement.
if test -n "$LIVE_POD_BEFORE" && test -n "$LIVE_PVC_BEFORE" \
  && test -n "$LIVE_POD_AFTER" && test -n "$LIVE_PVC_AFTER" \
  && test -n "$ALL_NS" \
  && test -z "$SCRATCH_REMAINS" \
  && test "$LIVE_POD_AFTER" = "$LIVE_POD_BEFORE" \
  && test "$LIVE_PVC_AFTER" = "$LIVE_PVC_BEFORE"; then
  printf 'SCRATCH_ABSENT=yes\nLIVE_POD_UNCHANGED=yes\nLIVE_PVC_UNCHANGED=yes\n'
else
  printf 'FAIL: live isolation NOT proven (an empty value means the query itself failed)\n  NAMESPACES_QUERIED=%s\n  SCRATCH_REMAINS=%s\n  POD  before=%s\n  POD  after =%s\n  PVC  before=%s\n  PVC  after =%s\n' \
    "$(test -n "$ALL_NS" && echo yes || echo NO)" \
    "${SCRATCH_REMAINS:-<none>}" \
    "${LIVE_POD_BEFORE:-<unobserved>}" "${LIVE_POD_AFTER:-<unobserved>}" \
    "${LIVE_PVC_BEFORE:-<unobserved>}" "${LIVE_PVC_AFTER:-<unobserved>}" >&2
  (exit 1)
fi
```

`make post-check` is its own evidence and must print `RESULT: PASS`; the block above
never reports success on its behalf. The block leaves `$?` non-zero when it fails, so a
transcript can be checked by status rather than by reading its prose.

Retain the release declaration, archive, detached manifest and full command transcript together.
Do not tick or rewrite any ADR-Platform-028 §8 criterion from this procedure alone; acceptance and
the evidence record remain owner-reviewed.
