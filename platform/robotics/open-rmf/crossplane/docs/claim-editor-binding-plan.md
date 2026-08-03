# OpenRMF claim-editor binding plan

**Ticket:** OK-99  
**Scope:** planning only; no RoleBinding in this repository is applied or shipped as a manifest

## The gap

[`openrmf-claim-editor`](../rbac/claim-editor-role.yaml) is a namespaced Role in
`openkubes-system`. It grants CRUD, list and watch only for `openrmfclaims`. A
Role grants nothing until a RoleBinding names an authenticated subject, and
`ok-mgmt` is the cluster that must authenticate that subject because it hosts
both the namespace and the CRD.

The missing binding is deliberate, not an omitted scaffold file. The subject
belongs to the `ok-mgmt` authentication owner, and no subject was confirmed
when the Role was added. Adding a RoleBinding now would therefore bind a guess.

Repository history also needs human reconciliation outside this plan. Commit
`d00ac05` (subject tagged `OK-60`) is already in the merged tree; branch
`feat/ok-60-render-rbac` contains `0a81040`, which re-adds byte-identical
content with trailer `Jira: OK-99`. The branch name and trailer disagree, and
the latter commit adds no RoleBinding either. OK-99 is the ticket for this
plan. Do not delete or merge the duplicate branch as part of this work.

## Dependency chain

The current-state entries below were verified for OK-99 on 2026-08-03. They
must be rechecked immediately before execution because they describe live
clusters, not repository guarantees.

| Order | Link needed for a human to create a Claim | Verified current state | Blocker class | Exit condition |
|---:|---|---|---|---|
| 1 | Claim API and least-privilege Role exist on the authenticating cluster | `openkubes-system`, the `openrmfclaims.platform.openkubes.ai` CRD, and Role `openrmf-claim-editor` are on `ok-mgmt`; the Role grants no Secret access | Ready | Keep the Role unchanged |
| 2 | Choose a subject Kubernetes can authenticate | No `User` or `Group` is confirmed. This is the deliberately deferred decision | **Missing decision** | Authentication owner approves either the interim ServiceAccount below or the target OIDC group |
| 3 | Give Keycloak a stable OIDC issuer | Keycloak phase 1 is running on `ok-shared`, but `KC_HOSTNAME=http://localhost:8080` and access is by port-forward. Authorization-code + PKCE, client credentials, and JWKS verification have passed in the conformance realm ([run log](../../../../identity/keycloak/PHASE1-RUNLOG.md)) | **Absent infrastructure** | Issuer is an HTTPS URL whose discovery document reports the identical URL and whose discovery/JWKS endpoints are reachable from every `ok-mgmt` control-plane node |
| 4 | Make the issuer name resolvable and reachable | **Reachability exists** — ok-shared runs no MetalLB by design; traffic arrives at **192.168.100.207:443** (MetalLB on the infra cluster) → Traefik → TLS passthrough. **Resolution does not**: nothing under `.internal` resolves and ok-mgmt's CoreDNS only forwards to `/etc/resolv.conf`, so `keycloak.ok-shared.internal` is not yet a usable issuer name. Pinned to that IP for now; proper DNS is **OK-57** | **Absent infrastructure** | Stable DNS resolves from `ok-mgmt` control-plane nodes and traffic reaches Keycloak without a port-forward |
| 5 | Present a certificate the API server trusts | **Resolved 2026-08-03:** `ClusterIssuer/ok-shared-internal-ca` is `Ready` and reuses the ADR-025 CA; a probe certificate for `keycloak.ok-shared.internal` was issued from another namespace and chains to `CN=ok-shared-internal-ca`. The CA private key now also exists in the `cert-manager` namespace, which is the accepted cost. Remaining: ok-mgmt must be given this CA as `--oidc-ca-file`. Previously: OK-81 phase 1 deliberately excluded ingress, TLS and the certificate decision ([§6](../../../../../docs/ok81-keycloak-deployment.md#6-deliberately-not-in-phase-1)) | **Missing decision**, then **absent infrastructure** | Certificate authority and issuance path are approved; certificate SAN covers the issuer host; the chain verifies from `ok-mgmt` |
| 6 | Create the production Keycloak realm/client and emit groups | The conformance realm is a disposable test artifact, not a consumer realm. No Kubernetes client or approved claim-editor group exists | **Missing decision** | Dedicated realm, public Kubernetes client, human group, membership owners and lifecycle are approved; ID token contains the expected `groups` claim via a group-membership mapper |
| 7 | Configure `ok-mgmt` to accept those tokens | Its API server has neither `--oidc-*` arguments nor `--authentication-config`; a Keycloak token is not a Kubernetes identity there today | **Absent infrastructure after an opt-in decision** | An approved Talos machine-config patch configures the issuer, client ID, username claim/prefix, groups claim/prefix and CA trust on every control-plane node; API server restart completes healthy |
| 8 | Bind the exact authenticated subject to the existing Role | No RoleBinding exists, correctly, while the subject is unresolved | Depends on order 2 and either the interim path or orders 3–7 | Site-specific RoleBinding on `ok-mgmt` refers to the existing Role and the approved subject exactly |
| 9 | Exercise the real identity and both authorization boundaries | No human can use Keycloak against `ok-mgmt` yet, so the end-to-end proof has not run | Depends on all preceding target-state links | A real human identity creates the approved Claim and receives `Forbidden` when reading Secrets |

Central OIDC remains opt-in under
[ADR-Platform-020 §4](../../../../../architecture/decisions/ADR-Platform-020-shared-platform-services.md#4-relationship-to-adr-018--strictly-additive).
Enabling it on `ok-mgmt` for this implementation profile does not make it a
platform default. Making it default-on would require an ADR amendment and is
outside OK-99.

## Reassessment (2026-08-03): prefer OIDC, skip the interim

The interim recommendation below was written when the certificate story was unsolved and the OIDC
chain looked long. It is now materially shorter, and the balance has flipped. Verified since:

- **Certificates: solved.** `ClusterIssuer/ok-shared-internal-ca` is Ready and issues for
  `keycloak.ok-shared.internal` from any namespace (tested).
- **Keycloak serving TLS: proven.** Brought up on `https://0.0.0.0:8443` with that certificate;
  a client using SNI `keycloak.ok-shared.internal` and the internal CA verified the chain
  (`ssl_verify_result=0`) and got `200` on the discovery document. Rolled back only because OK-81
  phase 1 excludes ingress by decision — the shape is known to work, not hoped to.
- **DNS for the API server does not need OK-57.** A CoreDNS `hosts` entry on ok-mgmt pointing
  `keycloak.ok-shared.internal` at the infra ingress address is sufficient for the API server. OK-57
  (real DNS, plus CA distribution) is for humans and browsers.
- **The route has a working precedent** — Vault already reaches consumers through the infra Traefik as
  an `IngressRouteTCP` with TLS passthrough and HostSNI.
- **OIDC is additive to x509.** ok-mgmt authenticates with `client-certificate-data` today, so adding
  `--oidc-*` cannot lock anyone out of authentication; existing kubeconfigs keep working.

What is left is configuration plus **one** privileged step: the Talos machine-config patch that sets
`--oidc-issuer-url`, `--oidc-client-id`, `--oidc-groups-claim`/`--oidc-groups-prefix` and
`--oidc-ca-file`, which restarts the API server. ok-mgmt has a **single** control-plane node
(`ok-mgmt-cp-6nc84`), so that is a brief management-plane outage needing a window.

Against one window, the interim ServiceAccount costs a bearer credential with no human identity in the
audit log, an issuance/rotation/revocation procedure nobody owns, and later retirement work — waste if
OIDC lands in the same window, and the weaker posture until it does. **Take the OIDC path.** The
interim is justified only if a Claim must be submitted before an ok-mgmt window can be scheduled.

Two risks to plan for rather than discover: a malformed `--oidc-*` argument can prevent the API server
from starting (recover by reverting the Talos patch; prove the issuer is reachable *from the
control-plane node* first), and a missing group-membership mapper makes the RoleBinding match nobody
with no error anywhere. Note also that the passthrough-vs-termination question in
[ADR-010](../../../../../docs/ok81-keycloak-deployment.md#32-tls-shape--decided-passthrough-keycloak-serves-its-own-certificate)
is now on the critical path, because a stable issuer needs that route.

## Interim option and its cost

If OK-99 must proceed before OIDC, use a dedicated ServiceAccount in
`openkubes-system`, bound only to `openrmf-claim-editor`. Mint a short-lived,
audience-bound token through the TokenRequest API; do not create a legacy
`kubernetes.io/service-account-token` Secret. Set a removal date and delete
the interim binding and ServiceAccount after OIDC proof passes.

This is the recommended interim subject only for a time-boxed, controlled
Claim submission. It is not human self-service. The token is a bearer
credential: whoever holds it is the ServiceAccount. The API audit log records
`system:serviceaccount:openkubes-system:openrmf-claim-editor-interim`, not the
human using it. TokenRequest provides an expiry mechanism, but the team still
needs a secure issuance, delivery, renewal and revocation procedure. If that
credential lifecycle is not owned, waiting for OIDC is safer than handing out
a long-lived token.

The alternative interim is an x509 `User`/`Group`. It would put a human CN in
the audit log and can have a short certificate lifetime, but it requires the
privileged `ok-mgmt` client CA signing path, secure private-key delivery and a
revocation/renewal procedure that does not exist here. Creating a per-user CA
workflow solely for this gap costs more and leaves more security machinery to
retire, so it is not recommended.

Illustration only — **not applied and not a standalone manifest**:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: openrmf-claim-editor-interim
  namespace: openkubes-system
subjects:
  - kind: ServiceAccount
    name: openrmf-claim-editor-interim
    namespace: openkubes-system
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: openrmf-claim-editor
```

## OIDC target state

### Minimum issuer route

The API server does not require the full ADR-010 ingress implementation. It
requires one stable issuer URL that is HTTPS, resolvable and reachable from
every `ok-mgmt` control-plane node, with a certificate whose chain it can
verify. A narrower dedicated L4/L7 route can satisfy OIDC if it preserves the
issuer hostname and exposes discovery, authorization, token and JWKS paths.

Using the existing standard `Ingress` with explicit `ingressClassName:
ok-ingress` is nevertheless the preferred implementation because it follows
[ADR-Platform-010](../../../../../architecture/decisions/ADR-Platform-010-ingress-contract.md)
and reuses the proven ok-shared traffic path. The minimum work is:

1. approve a certificate authority and issue a certificate for the stable
   issuer hostname;
2. publish DNS that resolves from all `ok-mgmt` control-plane nodes;
3. expose Keycloak through a stable TLS route and change `KC_HOSTNAME` to the
   stable external Keycloak URL (`https://keycloak.ok-shared.internal`); the
   dedicated realm's discovery document then reports the full issuer URL; and
4. if the certificate is issued by a private CA, place only that CA certificate
   where the kube-apiserver container can read it and configure
   `--oidc-ca-file`. A publicly trusted chain needs no private CA file.

Ingress is therefore one valid implementation of the reachability link, not
a protocol dependency that must be completed in its ideal final form first.

### Realm, client and claims

Create a dedicated production realm for Kubernetes consumers (proposed realm
name: `kubernetes`). Do not put the client in `master`: compromise or
misconfiguration there widens blast radius into Keycloak administration. Do
not reuse the conformance realm: it is test state and may be recreated. A
dedicated realm isolates signing keys, client scopes, session policy and realm
administration from both surfaces.

Create a public client for the Kubernetes API server and use authorization
code + PKCE for human login. The identity owner must approve the exact client
ID, redirect URIs, realm administrators and membership owners. Configure a
group-membership mapper so the token carries a `groups` claim. Configure
`ok-mgmt` with matching `--oidc-groups-claim=groups` and a non-empty
`--oidc-groups-prefix` to prevent collision with Kubernetes-native group
names. Configure an explicit username claim and prefix as well; the chosen
claim must be unique and governed against reassignment.

The Talos patch should produce this coherent set of kube-apiserver arguments;
the values remain proposals until the authentication owner approves them:

| Argument | Proposed value and constraint |
|---|---|
| `--oidc-issuer-url` | `https://keycloak.ok-shared.internal/realms/kubernetes`; must exactly match discovery `.issuer` |
| `--oidc-client-id` | `kubernetes`; must exactly match the token audience |
| `--oidc-ca-file` | Path to the private issuer CA visible inside kube-apiserver; omit only for a chain already trusted by its system roots |
| `--oidc-username-claim` | `preferred_username`; approve a no-reassignment policy before relying on it for audit identity |
| `--oidc-username-prefix` | `oidc:`; prevents collisions with existing Kubernetes usernames |
| `--oidc-groups-claim` | `groups`; must match the Keycloak mapper's token claim |
| `--oidc-groups-prefix` | `oidc:`; prevents collisions with Kubernetes-native groups |

The group name below is a **proposal, not a decision**. With proposed prefix
`oidc:` and proposed token group value `openrmf-claim-editors`, the subject
seen by Kubernetes would be `oidc:openrmf-claim-editors`. Inspect a real token
and the API audit record before creating the binding; do not infer the value
from the Keycloak console.

Illustration only — **not applied and not a standalone manifest**:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: openrmf-claim-editor-oidc
  namespace: openkubes-system
subjects:
  - kind: Group
    # PROPOSED: identity owner must approve the mapper value and prefix.
    name: oidc:openrmf-claim-editors
    apiGroup: rbac.authorization.k8s.io
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: openrmf-claim-editor
```

## Privileged human-owned steps

The following must stay with a human operator. They are not delegated to an
automation session:

1. approve the interim credential lifecycle or approve the production realm,
   client, group name, membership ownership, claims and prefixes;
2. create the interim ServiceAccount, apply its RoleBinding, mint/deliver its
   token, and later remove it on `ok-mgmt`;
3. approve and apply DNS, certificate authority/`ClusterIssuer`, certificate
   and stable Keycloak route changes on `ok-shared` or its network/DNS
   infrastructure;
4. create/configure the Keycloak production realm, client, mapper and group,
   and assign real human membership using Keycloak administrative access;
5. author, review and apply the Talos machine-config patch to every
   `ok-mgmt` control-plane node, including private-CA file/mount handling when
   required;
6. supervise the resulting kube-apiserver restart/rolling control-plane
   change and prove API availability and rollback readiness; and
7. apply the final site-specific RoleBinding on `ok-mgmt` only after the token
   claims are observed and approved.

Steps 2, 3, 5 and 7 are privileged applies. Step 6 restarts the control plane.
None is performed by this planning change.

## End-to-end proof

Run the proof with a real member of the approved Keycloak group, not with
administrator impersonation and not only with `kubectl auth can-i`:

1. From every `ok-mgmt` control-plane node, resolve the issuer hostname and
   retrieve its discovery document using the configured trust chain. Assert
   that `.issuer` exactly equals the kube-apiserver issuer URL and retrieve the
   advertised JWKS URI.
2. Complete authorization code + PKCE as the human using the same client used
   by `kubectl`. Decode only non-secret token claims locally and assert the
   approved group value is present. Do not log the token.
3. With that human's kubeconfig, run a server-side dry-run create first. Then,
   during the approved OK-99 rollout, create the reviewed
   `OpenRMFClaim` in `openkubes-system` and read it back. Record the audit
   username and groups so the proof ties the action to the human identity.
4. With the same kubeconfig, run
   `kubectl get secrets -n openkubes-system`. It must fail with Kubernetes
   `Forbidden`, not merely an empty list, network error or authentication
   error. Also verify `kubectl auth can-i get secrets -n openkubes-system`
   returns `no`.
5. Verify the positive is narrow: the user can create/get/update/delete only
   the approved `openrmfclaims` resource and cannot read Secrets, XRDs,
   Compositions, Releases, ProviderConfigs or Functions. Record any Claim or
   downstream release created by the rollout and its separately approved
   cleanup/ownership disposition.

The positive proves the authentication, mapper, API-server and RoleBinding
chain. The Secret denial proves the Role still provides the isolation it was
created for. Either half failing rejects the binding.

## Reverification commands

Run these read-only checks immediately before implementation:

```bash
# Switch and command must remain in the same shell invocation.
okm && kubectl get namespace openkubes-system
okm && kubectl get crd openrmfclaims.platform.openkubes.ai
okm && kubectl get role openrmf-claim-editor -n openkubes-system -o yaml

# Parse each kube-apiserver container's command/args and reject any unexpected
# --oidc-* or --authentication-config entry; do not grep merged stderr.
okm && kubectl get pods -n kube-system -l component=kube-apiserver -o json

oks && kubectl get statefulset keycloak -n keycloak -o json
oks && kubectl get clusterissuers.cert-manager.io -o json
```

Use structured JSON parsing for the assertions. The absence of flags is not
proof that a future run will find the same state; if either OIDC mechanism is
present, stop and revise this plan against the live configuration before any
binding is applied.
