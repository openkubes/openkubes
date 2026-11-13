# ADR-Platform-043 — Independent Console client identity CA, leaf delivery and trust distribution

- **Status:** Proposed
- **Date:** 2026-10-27
- **Date updated:** 2026-11-13
- **Decision scope:** Console client identity to the observed-state producer; design only
- **Related:** ADR-Platform-025, ADR-Platform-037

## Context

The Console identity is `spiffe://openkubes.io/ns/openkubes-console/sa/ok-console`.
The [producer](../../platform/console/observed-state-producer/manifests.yaml) requires
that URI among SANs; the signing role additionally forbids extra SANs. Human auth
remains separate under ADR-Platform-037. The ok-console live overlay declares
Certificate ok-console-observed-state-client through ClusterIssuer ok-shared-internal-ca;
its producer Deployment projects the leaf Secret's ca.crt as client trust.

The [existing ClusterIssuer](../../platform/networking/cert-manager/cluster-issuer-internal-ca.yaml)
documents copying the shared server CA key from vault to cert-manager; any holder
can sign this identity outside cert-manager. [Vault reachability](../../platform/secrets/vault/crossplane/reachability.yaml)
contains the original chain. Installed bindings, key holders and approval need confirmation.
The [cert-manager example](../../platform/cluster-management/crossplane/examples/ok1-certmanager.yaml)
declares 1.17.2; the proof must pin and confirm its installed combination.

## Decision matrix

The architecture owner's direction of 2026-10-29 is recorded below as a **Proposed
design direction**, not implementation approval or live authorization. Adoption
requires the evidence and explicit residual-authority review in this record.
Only the Direction column is the owner's; all other columns, numbers (47 h,
15 min, 24 h) and criteria are this record's proposal.

| Decision | Direction (architecture owner) | Fallback / condition | Evidence required before adoption | Status |
|:---|:---|:---|:---|:---|
| Leaf delivery | CSI leaf delivery first to keep delivery lean; namespace separation fallback. | This record proposes retaining placement and pinning the selected driver; isolated Secret delivery if CSI fails proof, preserving the exact URI or separately reviewing a contract change. | Exact URI SAN, foreign identity denied, no API Secret leaf key, reload and CNPG/ingress continuity; select and pin the driver. | Proposed direction; proof required |
| Signer hosting | Dedicated PKI mount on existing ok-mgmt Vault for the first pilot. | Independent Vault only if the pilot fails the explicit security requirements below; shared administrators and shared unseal/outage availability remain risks. | Signer isolation, exact-role/auth denial, dedicated serving trust and administrator-path assessment; outage recovery within the tested budget. | Proposed pilot; security gates required |
| Leaf lifetime | 7-day leaf TTL, renew at 3 days remaining: hypothesis validated by rotation and outage tests. | Revise lifetime/headroom if rotation or outage tests fail; architecture owner reviews the revised exposure/recovery budget. | Two scheduled renewals with reload and uninterrupted traffic; 47-hour signer outage from the renewal threshold, alert within 15 minutes, recovery with at least 24 hours before expiry; expiry fails closed. | Hypothesis; adoption gated |
| Residual authority (cnpg-manager) | NOT accepted unreviewed; scoped Pod Security and RBAC assessment plus explicit trusted signers/readers/approvers first. | Confine cnpg-manager below the trust boundary, or architecture owner explicitly accepts it as a trusted, cluster-admin-equivalent Console identity holder. | Installed-binding kubectl auth can-i evidence of confinement, or explicit owner acceptance; preserve reconciliation/failover and inventory trusted signers/readers/approvers. | Cutover blocked until one is chosen |
| Proof and cutover | One disposable-cluster proof and a minimal staged cutover. | Resolve a failed gate before bounded overlap and new-only; broader server-CA work stays separate. | Exact URI, foreign identity rejection, renewal at 3 days, outage behaviour and rollback in one proof; separately authorized live stages. | Proposed sequence; no live authorization |

### CSI selection criteria

The identity integration maintainer must select/pin the CSI driver and compatible
Kubernetes/cert-manager/Vault/approver combination. Require exact non-overridable URI,
no API Secret leaf key, minimum rights, Pod identity admission and atomic reload.

### Pilot security requirements

The pilot proposes a dedicated PKI mount on [ok-mgmt transit Vault](../../platform/secrets/vault/transit/README.md).
Shared administrators may change policies or read Vault storage; a shared outage
or unseal failure can stop both signing and ok-shared unseal. Mount separation
alone is not administrative or availability independence.

| Pilot security requirement | Pass criterion before adoption |
|:---|:---|
| Independent custody | Identity CA key absent from ok-shared Kubernetes Secrets; enumerate Vault storage, backup, unseal and administrative holders. No deferred server-CA/Keycloak path reaches a trusted administrator without explicit residual review. |
| Exclusive signing path | Complete policy/auth/token and mount-configuration inventory permits only the exact sign role; no export, root, sign-verbatim, issuer override or alternate issuance protocol. Foreign identity and second-cluster tokens fail; exact identity succeeds. |
| Signer endpoint trust | Dedicated serving CA key outside ok-shared and ok-mgmt Kubernetes Secrets; endpoint impersonation with either shared server CA or transit CA fails before login. Inventory redirect and serving leaf-key holders; resolve separate listener vs shared seal trust before provisioning. |
| Least authority and audit | Only inventoried signer/auth principals can reach the mount; provisioning grants retired before cutover; issuance and denied requests auditable without keys/tokens. Shared administrators explicitly assessed. |
| Recovery custody | Backups and unseal recovery preserve signer isolation; backup key holders are identity-CA key holders. |

Only failure of these requirements triggers independent-Vault review. Stage 3 needs
real ok-mgmt Vault policy/token/auth/admin/backup inventory; synthetic proof is insufficient.

## Trust boundary

Principals that can directly, or through delegated grants, read cluster Secrets,
create Pods/controllers in arbitrary namespaces, exec into Pods, write RBAC or patch
admission configuration are **cluster-admin-equivalent for this identity**.
This set includes node/control-plane and management operators, cluster administrators,
and cnpg-system/cnpg-manager as declared by the pinned release. No in-cluster control
in this ADR (CSI, namespace separation, admission or webhooks) defends against them.
They must be trusted or confined; the negative proof concerns non-admin principals.

### cnpg-manager assessment and cutover decision

The [Keycloak Makefile](../../platform/identity/keycloak/Makefile) pins
[cnpg-1.30.0](https://github.com/cloudnative-pg/cloudnative-pg/releases/download/v1.30.0/cnpg-1.30.0.yaml).
Its cnpg-manager ClusterRole and cluster-wide ClusterRoleBinding grant Secrets
read/write, pods/exec, Pod/Deployment/Job creation, ConfigMap write/delete,
ServiceAccount/Role/RoleBinding write and admission webhook-configuration patch.
These declared grants meet the boundary above; installed bindings remain to confirm.

Before cutover, either (a) confine cnpg-manager, for example with a namespace-scoped
operator installation or reduced ClusterRole, until it no longer meets that boundary,
proven by `kubectl auth can-i` on installed bindings; or (b) the architecture owner
explicitly accepts it as a trusted, cluster-admin-equivalent principal holding the
Console identity. **Until one is chosen, cutover is blocked.** CSI and namespace
separation alone cannot satisfy this decision. The security reviewer and database
maintainer own the assessment and compatibility proof; preserve reconciliation,
failover and credential/TLS rotation.

## Trusted principals

Inventory effective bindings and custody before adoption; this table grants no authority.

| Principal role / ServiceAccount | Authority | Definition or confirmation required |
|:---|:---|:---|
| Cluster-admin-equivalent set | Hold or mint the Console identity; override in-cluster controls | Node/control-plane and management operators, cluster administrators, and pinned cnpg-system/cnpg-manager; inventory effective bindings and indirect administrative reach. Confine or explicitly trust each. |
| Signer administrators | Configure issuance or recover signer keys | Include ok-mgmt Vault administrators, storage/unseal recovery and backup holders; inventory policies, tokens, auth mounts and recovery custody; retire provisioning grants. |
| Console identity requesters | Request exact-URI leaves and issuer-auth tokens | cert-manager controller / console-identity-issuer-auth or selected CSI driver SA; confirm requester, TokenRequest and signer bindings. Console runtime has no token-minting rights. |
| Client-trust bundle writers | Add roots accepted for Console authentication | Inventory approved Git/release and ConfigMap writers and effective bindings; authorize trust reload explicitly. |
| Signer-endpoint path holders | Redirect login/signing traffic or impersonate the listener | Inventory Service/EndpointSlice/LB/DNS redirect authority on ok-infra/ok-mgmt AND serving leaf-key holders. [Transit values](../../platform/secrets/vault/transit/20-helm-values.yaml) mount the listener key from an ok-mgmt Kubernetes Secret; include its readers. Separate listener vs shared remains open: changing the single listener's serving cert also changes the trust used by ok-shared's seal. |
| Approvers/admission owners | Approve requests or change CSR/identity enforcement | Inventory default/driver approvers, approveSignerNames, webhook/policy authors, serving-cert trust and policy/RBAC administrators. |
| ok-mgmt reach | Reach workload or signer authority through management credentials | Inventory ok-shared kubeconfig Secret readers, Crossplane authors/provider authority and OIDC admin groups; use the [onboarding guideline](../../docs/ok-shared-onboarding-guideline.md) and [OIDC plan](../../docs/ok-mgmt-oidc-rollout.md). |

## Issuance and trust contract

| Control | Proposed contract |
|:---|:---|
| External signer | Independent identity root/key, with namespaced in-tree Vault Issuer openkubes-console/console-identity-v1. No identity CA key, static Vault token or AppRole SecretID in ok-shared. |
| Authentication | Dedicated console-identity-issuer-auth SA; cert-manager controller is sole issuer-auth TokenRequest caller. Option A: Vault Kubernetes auth with stored reviewer JWT, protected custody/rotation and TokenReview RBAC; requires ok-mgmt→ok-shared API connectivity. Alternative: Vault JWT auth validates ok-shared JWKS/OIDC discovery, avoiding TokenReview; prove pinned integration compatibility. Bind exact SA/namespace and only the Issuer-derived vault:// audience. The login JWT lacks the API audience and cannot serve as TokenReview bearer credential; no issuer-auth auth-delegator option. Reject extra serviceAccountRef audiences; prove second-cluster rejection. |
| Signing role | Exact Console URI only; client-auth EKU, non-CA, approved algorithm/key size/TTL. Deny absent/null/wrong-type/extra/foreign SANs, DNS/IP/email, CA=true, export, root, sign-verbatim, issuer override and alternate protocols. Stolen auth token cannot sign another identity. |
| Certificate admission | Match Certificate spec.uris and parsed CertificateRequest spec.request across all issuer references. With default approval retained for this signer, CSR identity enforcement requires a validating webhook (CEL has no x509 parser); approver-policy is an alternative only if approveSignerNames excludes this signer. Inventory its principal and serving-cert trust path. Enforce issuerRef/group/kind, identity/usages/duration and original submitter on create/spec update/direct CSR; allow necessary GC/status, no spec bypass. |
| Issuer protection | Only openkubes-console/console-identity-v1 may reference issuer-auth; forbid extra audiences and protect endpoint/auth fields. Dedicated serving CA key outside both clusters' Secrets; shared-server/transit CA impersonation must fail before login. Inventory CA holders plus address redirect authority (Service/EndpointSlice/DNS/node); reject issuer switching, stale desired objects and identity ingress-shim. |
| CSI variant | Prove exact non-overridable generated URI with selected pinned driver; inventory requester/approver and signer-specific default-approver exclusion. If needed, grant only certificaterequests create under exact identity/requester admission; no runtime token-minting rights. Prove reload rather than assume Certificate/Secret equivalence. |
| Workload template admission | Approved submitters only; pin image digest, command, SA, identity/trust volumes/paths and TLS identity/CA environment. Enforce the non-admin identity boundary for controller-created Pods too. Protect trust ConfigMap writes separately: hot-reload never reaches template admission. |

### Public trust distribution and mount split

Declare public PEM in Git with approved fingerprint, generation and expiry metadata.
Render separate observed-state-client-trust and observed-state-server-trust ConfigMaps.
No privileged publisher or CA-Secret read is required. CI/render checks must reject
private-key PEM. An owner and runbook must alert on expiry and submit the next approved
PEM before expiry. Root changes require approval, not automatic acceptance by label.

Protect ConfigMap writes, namespace selection and Git/release authority: public
data is security-sensitive trust. Apply identity admission to controller-created
Pods while preserving approved rollouts; the trust boundary above still applies.

| Direction | Source declaration | Required change |
|:---|:---|:---|
| Producer validates Console client | ok-console repository: `deploy/kubernetes/overlays/ok-shared-live/producer-deployment.yaml` | Replace the leaf Secret ca.crt projection with the client-trust ConfigMap: existing public CA, bounded old+new, then new-only. |
| Console validates producer server | ok-console repository: `deploy/kubernetes/overlays/ok-shared-live/kustomization.yaml` | Split the coupled CA/cert/key projection. Keep existing server CA in the server-trust ConfigMap at OK_CONSOLE_OBSERVED_STATE_CA_FILE; change only client cert/key delivery. |
| Producer reload | `openkubes/platform/console/observed-state-producer/app.py` | Trust context is created at startup. Prove reload or automatic guarded rollout with consistent generations. |
| Console reload | ok-console repository: `bff/adapters/mtlsFetch.mjs` | Trust context is created at source construction. Secret/CSI replacement alone is insufficient; prove consistent cert/key/trust loading. |

## Recommended PR sequence and cutover gates

These are future repository changes. **No live operation is authorized by this record.**
Each ok-shared certificate issuance, trust-root change, credential/CA/RBAC mutation
and rollout requires a separate reviewed maintenance authorization naming exact
revisions, target, window, rollback and privileged signer actions. Workload approval
does not authorize ok-mgmt operations or Vault policy/auth/role changes.

| Stage | Minimal change | Required gate |
|:---|:---|:---|
| 1 — CSI-first integration | Select/pin driver; split public client/server trust; dedicated pilot PKI mount, exact issuance and Pod/template admission. | Resolve owned questions below; confine-or-accept decision and trusted-principal inventory reviewed. If CSI fails, review isolated Secret fallback before implementation. Preserve existing database/ingress placement on the CSI path. |
| 2 — one disposable-cluster proof | Synthetic independent CAs, pinned compatible components, no live key import; one proof covering the cases below. | Denials plus working authenticated controls, rotation/outage/rollback pass; explicit residual review before live cutover. Rendering is preflight only. |
| 3 — bounded overlap | Producer loads old+new client roots first; switch Console leaf/delivery second. Keep server trust separate and unchanged. | Real ok-mgmt Vault read-only security inventory above passes; separately authorized window, named operator role and fixed overlap deadline; every backend authenticates with consistent cert/key/trust generations and readiness/drain budget. Old CA holders retain identity authority during overlap. |
| 4 — new-only | Remove old client root from every producer context and drain old connections. | Old-CA/same-URI fails; new-CA/exact-URI succeeds on every replica, renewal/reload and traffic continue. Rollback re-issues from the new CA; re-trusting old root requires fresh residual review and maintenance authorization. No automatic old-root fallback or silent overlap extension. |

### Single disposable-cluster proof

The identity integration maintainer owns this proof: capture pinned versions,
images, flags, securityContexts, quota, sanitized logs and hashes; preflight compatibility.
Duration: ≥ 2 real renewals ≈ 8 days plus outage/expiry cycles. Acceleration is
allowed for every row except Renewal at 3 days, Outage within headroom and Outage through expiry.

For the **Certificate/Secret fallback only**, cert-manager v1.17.2 [Vault request handling](https://github.com/cert-manager/cert-manager/blob/v1.17.2/pkg/controller/certificaterequests/vault/vault.go)
marks sign errors Failed, login errors Pending (fast retry). [Failed issuance backoff](https://github.com/cert-manager/cert-manager/blob/v1.17.2/pkg/controller/certificates/trigger/trigger_controller.go)
is 1, 2, 4, 8, 16, 32 h: a 47 h sign-path outage starting at the threshold
next retries at ~63 h, only 9 h before expiry. For CSI, the selected driver's own retry schedule governs; every Pod start/reschedule
needs fresh issuance. Record that schedule and restart/reschedule a Console replica
during each outage mode. Both paths require a tested recovery budget.

| Test | Pass criterion |
|:---|:---|
| Exact identity and signing | New CA/exact URI produces authenticated observed-state traffic. Absent/null/wrong-type/extra/foreign SANs, DNS/IP/email, CA=true, wrong EKU/TTL, issuer switches and direct/stale requests fail admission/signing with no leaf. Valid issuer-auth token cannot sign another identity. |
| Installed trust-boundary decision | On installed bindings, kubectl auth can-i confirms cnpg-manager is confined below the boundary (including indirect grants), or explicit architecture-owner acceptance records it as a trusted cluster-admin-equivalent Console identity holder. Include complete effective RBAC inventory and successful database reconciliation/failover; block cutover if neither holds. |
| Non-admin negative set | A namespaced principal with ordinary workload rights in another namespace cannot obtain a cert for the exact URI through Certificate/direct CSR, CSI volume, issuer-auth TokenRequest, client-trust bundle write or signer-endpoint redirect. Each denial has an authorized positive control with authenticated traffic; include foreign/second-cluster token rejection and no API Secret leaf key for CSI. |
| Issuer audience | An extra serviceAccountRef audience on the Issuer is rejected; the sole Issuer-derived audience succeeds. |
| CSR enforcement | With default approval retained, exact/foreign direct CSRs exercise the validating webhook; exact succeeds, foreign fails. Test serving-cert rotation and denial with untrusted serving trust. |
| Signer custody, auth and endpoint | Synthetic policy/auth/custody controls pass; shared-server/transit-CA endpoint impersonation fails before login, dedicated serving-trust control succeeds. Selected stored-reviewer TokenReview or JWT/JWKS auth succeeds; foreign/second-cluster tokens fail. Real pilot inventory remains a stage-3 gate. |
| Producer denial | Old CA/same URI fails TLS; new CA/wrong URI and no certificate return HTTP 403. Pair every denial with successful authenticated observed-state traffic so unavailability cannot pass a denial. |
| Renewal at 3 days | Confirm actual 168-hour TTL and 72-hour remaining renewal configuration; two scheduled renewals change serial/generation, load consistent cert/key and sustain traffic without manual restart. Accelerated scheduling alone does not establish the 7d/3d hypothesis. |
| Outage within headroom | Run login and sign failure separately, each for 47 h from 72 h remaining; existing leaves sustain traffic, alert within 15 min. For fallback record Pending/Failed retries; for CSI record driver retries and restart/reschedule a replica during each mode, recording fresh-issuance failure and recovery. Require reload within one hour of restoration and ≥24 h before expiry, or explicitly budget/test operator-triggered re-issue. Record retry schedule/recovery latency; missed availability bounds require revised recovery budget before adoption. |
| Outage through expiry | Keep signer unavailable beyond expiry: expired credentials cannot authenticate and an alert remains active. For CSI restart/reschedule a replica in each login/sign outage mode; record driver retries and fresh-issuance failure. Restoration recovers traffic with a valid new leaf. |
| Rollback | Exercise bounded overlap then new-only on every replica. Re-issue with new CA and restore approved revision without old-root fallback; include recovery-overlay trust inheritance in the implementation inventory. |

Effective-authority evidence joins complete, authenticated Roles/ClusterRoles and
bindings, timestamped within 24 hours with resourceVersions; resolve wildcard,
aggregate, impersonation and indirect grants, external groups and historical credentials.
Invalid exports fail closed. Installed authorization checks and runtime positive controls
complement the inventory. Each implementation guard needs an invalid-input case
observed failing when removed, then restored alongside its positive control.

## Open questions and owners

| Remaining question | Owner role | Resolution gate |
|:---|:---|:---|
| Which CSI driver/version, issuance API, approver and minimum requester rights satisfy the exact identity contract? | Identity integration maintainer | Before integration; prove generated identity, required CertificateRequest rights and reload behaviour without unnecessary runtime issuance/token grants. |
| Which signer address, serving-CA/leaf-key custody and redirect administrators meet pilot requirements; separate listener vs shared? | PKI operator | Before provisioning; resolve seal trust impact of changing the shared listener, endpoint custody and administrative authority. |
| Will cnpg-manager be confined below the trust boundary or explicitly trusted? | Security reviewer with database operator maintainer | Installed-binding authorization proof or explicit architecture-owner acceptance before cutover. |
| Does 7d/3d meet recovery/exposure requirements, and who owns alerts and the overlap deadline? | Service reliability owner with architecture owner | Test the explicit hypothesis; name operator roles, alert route and deadline in the separately reviewed maintenance plan. |

## Proposed follow-up

Shared server-CA custody, reader narrowing, default-approval replacement and server-root
rotation remain separate. Preserve Keycloak/OIDC, zot/Talos, Console ingress, producer
HTTPS, Vault HTTPS and webhook injection; coordinate [management OIDC](../../docs/ok-mgmt-oidc-rollout.md).
Defer only after new-only and explicit review of administrative reach; never restore
server-root trust for Console client authentication. Old-root holders retain identity during overlap.

## Scope of this record

**Applies to:** Proposed design and repository declarations only; no cluster observation
or live change for this revision. Installed authority/enforcement require the gates above.
Each implementation requires review against the trust boundary, selected host and versions.
Console→producer server trust stays on the old shared CA pending the separate follow-up.
Under CSI, transit Vault is needed per replica per renewal AND at every Pod start/reschedule.
The producer accepts the URI among SANs; signing enforces exactness.

**Shown in:** Contract, assessment, matrix and future proof gates. Repository declarations
establish source existence, not installed ownership or runtime enforcement.

**Follow-ups:** Principal inventory and explicit residual review, pinned implementation,
continuity/renewal/outage proof and separate server-CA work. No live authorization.
