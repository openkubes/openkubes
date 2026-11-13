# ADR-Platform-043 — Independent Console client identity CA, leaf delivery and trust distribution

- **Status:** Proposed
- **Date:** 2026-10-27
- **Date updated:** 2026-11-13
- **Decision scope:** Console client identity to the observed-state producer; design only
- **Tracking:** https://kubernauts.atlassian.net/browse/OK-210
- **Related:** ADR-Platform-025, ADR-Platform-037

## Context

The Console observed-state client identity is
`spiffe://openkubes.io/ns/openkubes-console/sa/ok-console`. The producer requires
that URI among the client certificate's URI SANs; the proposed signing role also
excludes extra SANs. The repository declaration is
[producer manifests](../../platform/console/observed-state-producer/manifests.yaml).
The live client declaration is in the ok-console repository:
`deploy/kubernetes/overlays/ok-shared-live/certificates.yaml` (Certificate
`ok-console-observed-state-client`, the URI above, ClusterIssuer
`ok-shared-internal-ca`); `deploy/kubernetes/overlays/ok-shared-live/producer-deployment.yaml`
projects that Secret's `ca.crt` as `client-ca.crt` and mounts
`observed-state-producer-server-tls`. Human authentication remains separate under ADR-Platform-037.

The [existing ClusterIssuer](../../platform/networking/cert-manager/cluster-issuer-internal-ca.yaml)
documents copying the shared server CA key from `vault` to `cert-manager`.
Any holder can sign the Console identity outside cert-manager; renaming the issuer
or adding CertificateRequest admission does not isolate that signing path.
The [Vault reachability declaration](../../platform/secrets/vault/crossplane/reachability.yaml)
contains the original server-CA chain. Current bindings, approval configuration,
key holders and installed ownership require confirmation rather than inference.
The six CA-key readers, cluster-wide Pod create and cert-manager 1.17.2 are
from a read-only observation on 2026-10-22; to re-confirm.
The version is also declared in [cert-manager example](../../platform/cluster-management/crossplane/examples/ok1-certmanager.yaml).

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
| Residual authority (cnpg-manager) | NOT accepted unreviewed; scoped Pod Security and RBAC assessment plus explicit trusted signers/readers/approvers first. | Constrain reachable Pod/token/key paths and preserve database operations; architecture owner explicitly reviews any remaining authority before cutover. | Assessment below, effective namespace/admission coverage, denied crafted Pods and successful reconciliation/failover; explicit trusted signers, readers and approvers. | Assessment and explicit review required |
| Proof and cutover | One disposable-cluster proof and a minimal staged cutover. | Resolve a failed gate before bounded overlap and new-only; broader server-CA work stays separate. | Exact URI, foreign identity rejection, renewal at 3 days, outage behaviour and rollback in one proof; separately authorized live stages. | Proposed sequence; no live authorization |

### CSI selection criteria

**CSI driver to be selected** by the identity integration maintainer;
cert-manager csi-driver / csi-driver-spiffe remain candidates, not a selection.
Selection must establish a pinned compatible Kubernetes/cert-manager/Vault and
approver combination, exact non-overridable URI generation, no API Secret leaf
key, minimum issuance rights, Pod identity admission and atomic cert/key reload.
Do not assume Certificate/Secret semantics apply unchanged to a CSI driver.

### Pilot security requirements

The pilot proposes a dedicated PKI mount on [ok-mgmt transit Vault](../../platform/secrets/vault/transit/README.md).
Shared administrators may change policies or read Vault storage; a shared outage
or unseal failure can stop both signing and ok-shared unseal. Mount separation
alone is not administrative or availability independence.

| Pilot security requirement | Pass criterion before adoption |
|:---|:---|
| Independent custody | Identity CA key absent from ok-shared Kubernetes Secrets; enumerate Vault storage, backup, unseal and administrative holders. No deferred server-CA/Keycloak path reaches a trusted administrator without explicit residual review. |
| Exclusive signing path | Complete policy/auth/token and mount-configuration inventory permits only the exact sign role; no export, root, sign-verbatim, issuer override or alternate issuance protocol. Foreign identity and second-cluster tokens fail; exact identity succeeds. |
| Signer endpoint trust | Dedicated serving CA key outside ok-shared and ok-mgmt Kubernetes Secrets; endpoint impersonation with either shared server CA or transit CA fails before login. Inventory DNS/Service/EndpointSlice redirect authority. |
| Least authority and audit | Only inventoried signer/auth principals can reach the mount; provisioning grants retired before cutover; issuance and denied requests auditable without keys/tokens. Shared administrators explicitly assessed. |
| Recovery custody | Backups and unseal recovery preserve signer isolation; backup key holders are identity-CA key holders. |

Only failure of these explicit security requirements triggers independent-Vault review.
Stage 3 requires a read-only inventory of the real ok-mgmt Vault: policies, tokens,
auth mounts, root/admin token use and backup key holders. A synthetic disposable
Vault cannot satisfy this gate.

### Availability adoption gate

Rotation/outage failures require a revised recovery budget; 7d/3d remains subject to both proof modes.

## Scoped Pod Security and RBAC risk assessment (cnpg-manager)

Repository-grounded preliminary assessment; installed authority needs read-only confirmation.

| Authority or path | Source / confirmation | Risk and required mitigation |
|:---|:---|:---|
| Operator installation and declared grants | [Keycloak Makefile](../../platform/identity/keycloak/Makefile) tag-verifies cnpg-1.30.0 and assumes cnpg-system. The [pinned release](https://github.com/cloudnative-pg/cloudnative-pg/releases/download/v1.30.0/cnpg-1.30.0.yaml) declares ClusterRole cnpg-manager plus ClusterRoleBinding. | Cluster-wide: secrets get/list/create/patch; pods and pods/exec create; configmaps create/patch/update; serviceaccounts create/patch; roles/rolebindings create/patch; services write. Installed equals pinned remains to confirm. |
| Current identity consequence | As declared, cnpg-manager can read both copies of the ok-shared-internal-ca key today. | It holds the current Console identity until new-only; assess effective additional grants, bindings, aggregates and wildcards read-only. |
| Privileged/hostPath Pods | to confirm on ok-shared (read-only, approved window): effective Pod Security labels/version, exemptions and admission wherever cnpg-manager can create Pods, plus who can change them. | If admitted, privileged/hostPath Pods can expose node credentials and mounted leaf material beyond namespace gates. Require restricted enforcement with pinned version and explicit compatibility review; labels alone are insufficient. |
| Console namespace and leaf mounts | ok-console repository: `deploy/kubernetes/overlays/ok-shared-live/namespace.yaml` declares enforce: restricted, enforce-version: latest; `producer-deployment.yaml` mounts observed-state-producer-server-tls and the client Secret's ca.crt. | latest is not pinned and fails this ADR's pinned-version requirement; confirm installed policy/exemptions. Protect identity accounts, templates, volumes and trust paths. |
| Existing CA key | from repo `platform/networking/cert-manager/cluster-issuer-internal-ca.yaml` and `platform/secrets/vault/crossplane/reachability.yaml`: CA Secret in vault, documented copy into cert-manager. | Declared cnpg-manager reads reach both Secrets; installed equals pinned remains to confirm. Any direct reader or indirect Pod/exec holder can sign the accepted URI while the old root is trusted. |
| Database credential route | from repo `platform/identity/keycloak/manifests/database.template.yaml`: CNPG reads a namespaced bootstrap/managed-role credential Secret; `docs/ok-mgmt-oidc-rollout.md` documents management OIDC trust. | to confirm on ok-shared (read-only, approved window): exec/credential reach to Keycloak realm signing material and onward administrator access. Count reachable administrators as identity holders until constrained. |
| CSI mitigation | to confirm on ok-shared (read-only, approved window): installed Pod/template/token admission and driver boundaries against the selected design. | CSI removes API Secret leaf-key exposure; it does not prevent choosing ok-console/issuer-auth service accounts, mounting identity CSI volumes or node compromise. Deny those paths for foreign Pods/controllers, including CNPG Cluster/Pooler-mediated creation. |
| Isolated Secret fallback | to confirm on ok-shared (read-only, approved window): namespace-scoped CNPG/ingress rights and indirect Pod/exec/token paths against the fallback design. | Separation works only if broad Secret readers and Pod creators lose reach into the identity namespace; a database move alone leaves ingress readers. Preserve database reconciliation, failover, credential/TLS rotation and ingress renewal. |

The security reviewer owns effective-authority assessment; the database maintainer
owns compatible restrictions. No cnpg-manager allowlist merely to pass a gate;
the architecture owner must explicitly review residual authority before cutover.

## Trusted principals

The identity integration maintainer must inventory and resolve each binding before adoption; this is not a blanket allowlist.

| Principal role / ServiceAccount | Authority | Definition or confirmation required |
|:---|:---|:---|
| Dedicated Vault PKI signer administrator | Provision mount/role; retire provisioning rights before cutover | Proposed integration; existing host context in `platform/secrets/vault/transit/README.md`; exact policies and administrative holders to confirm. |
| cert-manager controller / console-identity-issuer-auth | Sole issuer-auth TokenRequest caller / dedicated Vault authentication identity | Proposed namespaced Issuer openkubes-console/console-identity-v1; binding and controller ServiceAccount to confirm. CSI requester/approver may differ and must be inventoried. |
| Existing CA-key readers | Direct or indirect signing while old root is trusted | Key locations from `platform/networking/cert-manager/cluster-issuer-internal-ca.yaml`; effective readers to confirm, including cnpg-system/cnpg-manager, ingress/traefik, kube-system/cilium-operator, observability operator, VSO controller and cert-manager cainjector. The six-reader list is from a read-only observation on 2026-10-22; to re-confirm, not trusted exceptions. |
| New identity CA-key readers | Vault storage/backup key holders, recovery and administrative access | Proposed external custody; exact Vault roles and infrastructure ServiceAccounts to confirm, including shared ok-mgmt administrators. |
| Certificate / CertificateRequest writers | Original Certificate submitters, direct CSR authors and cert-manager controller | Existing ClusterIssuer from `platform/networking/cert-manager/cluster-issuer-internal-ca.yaml`; all effective writers and new CSI requester roles to confirm. Console runtime receives no token-minting rights. |
| CertificateRequest approvers | Default cert-manager approver and any driver-specific approver | Installed default approval, approveSignerNames exclusions, driver approver ServiceAccount and signer scope to confirm; no approver-policy installation inferred. |
| Client-trust bundle writers | Add a root and mint the exact URI; cnpg-manager has declared cluster-wide ConfigMap write | Approved writer binding and denial for every other writer required; hot-reload bypasses template admission. |
| pods/exec holders | Steal cert-manager controller credentials or Console leaf material | Identity holders until exec into both controller and Console Pods is constrained; bindings to confirm. |
| Privileged-namespace Pod creators | hostPath on the Console's node exposes credentials across namespaces | Identity holders until all reachable namespaces have effective constraints, including outside openkubes-console. |
| ok-shared kubeconfig Secret readers on ok-mgmt | Reach ok-shared via crossplane-system/ok-shared-kubeconfig | [Onboarding guideline](../../docs/ok-shared-onboarding-guideline.md); readers and credential authority to confirm. |
| Crossplane resource authors targeting ok-shared | Indirect workload, RBAC and credential operations | Inventory author and provider authority, including resources using the registered ok-shared credential. |
| ok-mgmt OIDC admin groups | Potential management/Vault administrative reach | [OIDC rollout](../../docs/ok-mgmt-oidc-rollout.md): platform-admins; effective binding and indirect Keycloak reach to confirm. |
| Transit endpoint redirect operators | Redirect signer path through ok-infra | [Service ok-mgmt/vault-transit-lb](../../platform/secrets/vault/transit/40-ok-infra-lb.yaml); inventory Service/EndpointSlice/DNS and host authority. |
| CSR validating webhook or approver-policy | Parse and authorize CertificateRequest CSR identity | Required because ValidatingAdmissionPolicy CEL lacks x509 parsing; inventory controller/policy authors and serving-cert trust path. |
| Vault stored reviewer JWT holders (option A) | TokenReview against ok-shared API | Stored reviewer credential custody/rotation and RBAC to confirm; protect its readers. |
| issuer-auth SA with system:auth-delegator (option B) | TokenReview using login JWT against ok-shared API | Alternative to stored reviewer JWT; explicitly review added delegation authority and binding. |
| Approved deployer; policy/RBAC/admission and namespace administrators | Change identity workloads, trust and enforcement | Exact roles/ServiceAccounts and protected credential homes to confirm; no personal identities recorded here. |
| Node/control-plane and management operators | Access mounted material or override controls | Exact roles and indirect server-CA/Keycloak credential paths to confirm; neither CSI nor external custody removes this trust. |

## Issuance and trust contract

Proposed implementation requirements, subject to selection and proof:
| Control | Proposed contract |
|:---|:---|
| External signer | Independent identity root/key, with namespaced in-tree Vault Issuer openkubes-console/console-identity-v1. No identity CA key, static Vault token or AppRole SecretID in ok-shared. |
| Signer host | Dedicated PKI mount on existing ok-mgmt Vault for the pilot, gated by the security requirements above. Independent Vault is conditional, not a parallel open decision. |
| Authentication | Dedicated console-identity-issuer-auth SA; cert-manager controller is sole issuer-auth TokenRequest caller. Vault Kubernetes auth uses TokenReview against ok-shared API, not issuer validation as the control: require ok-mgmt→ok-shared API connectivity and either a stored reviewer JWT or system:auth-delegator for issuer-auth. Bind exact SA/namespace and only the Issuer-derived audience; prove pinned audience compatibility and second-cluster rejection. Deny foreign token/Secret acquisition and Pods selecting issuer-auth or controller SA, including indirect CNPG/VSO paths. No VSO TokenRequest exception; cover VaultAuth, VaultAuthGlobal, VaultConnection and Vault*Secret token relay. |
| Signing role | Exact Console URI only; client-auth EKU, non-CA, approved algorithm/key size/TTL. Deny absent/null/wrong-type/extra/foreign SANs, DNS/IP/email, CA=true, export, root, sign-verbatim, issuer override and alternate protocols. Stolen auth token cannot sign another identity. |
| Lifetime | 7d/3d hypothesis; actual configured schedule required, accelerated tests supplementary. Adopt only after rotation and both outage modes pass or recovery budget includes operator-triggered re-issue. |
| Certificate admission | Match Certificate spec.uris and parsed CertificateRequest spec.request across all issuer references. A validating webhook or approver-policy is required: ValidatingAdmissionPolicy CEL provides no x509 parser. Inventory its principal and serving-cert trust path. Enforce issuerRef/group/kind, identity/usages/duration and original submitter on create/spec update/direct CSR; allow necessary GC/status, no spec bypass. |
| Issuer protection | Only openkubes-console/console-identity-v1 may reference issuer-auth; forbid extra audiences and protect endpoint/auth fields. Dedicated serving CA key outside both clusters' Secrets; shared-server/transit CA impersonation must fail before login. Inventory CA holders plus address redirect authority (Service/EndpointSlice/DNS/node); reject issuer switching, stale desired objects and identity ingress-shim. |
| Default approver | Confirm installed approveSignerNames and admission/signing boundaries before retaining default approval for in-tree Vault. Broad approval cannot widen exact-role rights; platform-wide replacement is a follow-up. |
| CSI variant | Prove exact non-overridable generated URI with selected pinned driver; inventory requester/approver and signer-specific default-approver exclusion. If needed, grant only certificaterequests create under exact identity/requester admission; no runtime token-minting rights. Prove reload rather than assume Certificate/Secret equivalence. |
| Workload template admission | Approved submitters only; pin image digest, command, SA, identity/trust volumes/paths and TLS identity/CA environment. Deny foreign Pods selecting ok-console or controller/auth SAs, including ReplicaSets. Controller exception permits restart annotation only. Protect trust ConfigMap writes separately: hot-reload never reaches template admission. |

### Public trust distribution and mount split

Declare public PEM in Git with approved fingerprint, generation and expiry metadata.
Render separate observed-state-client-trust and observed-state-server-trust ConfigMaps.
No privileged publisher or CA-Secret read is required. CI/render checks must reject
private-key PEM. An owner and runbook must alert on expiry and submit the next approved
PEM before expiry. Root changes require approval, not automatic acceptance by label.

Protect ConfigMap writes, namespace selection and Git/release authority. Public
data is still security-sensitive trust. Confirm CNPG, observability and VSO rights:
workload patches can replace identity templates or producer trust paths. Apply
all-Pod controls to controller-created Pods, including ReplicaSets, while preserving
restart-annotation-only controller rollouts.

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
| 1 — CSI-first integration | Select/pin driver; split public client/server trust; dedicated pilot PKI mount, exact issuance and Pod/template admission. | Resolve owned questions below; scoped assessment and trusted-principal inventory reviewed. If CSI fails, review isolated Secret fallback before implementation. Preserve existing database/ingress placement on the CSI path. |
| 2 — one disposable-cluster proof | Synthetic independent CAs, pinned compatible components, no live key import; one proof covering the cases below. | Denials plus working authenticated controls, rotation/outage/rollback pass; explicit residual review before live cutover. Rendering is preflight only. |
| 3 — bounded overlap | Producer loads old+new client roots first; switch Console leaf/delivery second. Keep server trust separate and unchanged. | Real ok-mgmt Vault read-only security inventory above passes; separately authorized window, named operator role and fixed overlap deadline; every backend authenticates with consistent cert/key/trust generations and readiness/drain budget. Old CA holders retain identity authority during overlap. |
| 4 — new-only | Remove old client root from every producer context and drain old connections. | Old-CA/same-URI fails; new-CA/exact-URI succeeds on every replica, renewal/reload and traffic continue. Rollback re-issues from the new CA; re-trusting old root requires fresh residual review and maintenance authorization. No automatic old-root fallback or silent overlap extension. |

### Single disposable-cluster proof

The identity integration maintainer owns this proof: capture pinned versions,
images, flags, securityContexts, quota, sanitized logs and hashes; preflight compatibility.
Duration: ≥ 2 real renewals ≈ 8 days plus outage/expiry cycles. Acceleration is
allowed for every row except Renewal at 3 days, Outage within headroom and Outage through expiry.

cert-manager v1.17.2 [Vault request handling](https://github.com/cert-manager/cert-manager/blob/v1.17.2/pkg/controller/certificaterequests/vault/vault.go)
marks sign errors Failed, login errors Pending (fast retry). [Failed issuance backoff](https://github.com/cert-manager/cert-manager/blob/v1.17.2/pkg/controller/certificates/trigger/trigger_controller.go)
is 1, 2, 4, 8, 16, 32 h: a 47 h sign-path outage starting at the threshold
next retries at ~63 h, only 9 h before expiry. Both modes on pinned versions,
or a recovery budget including operator-triggered re-issue, are an adoption gate.

| Test | Pass criterion |
|:---|:---|
| Exact identity and signing | New CA/exact URI produces authenticated observed-state traffic. Absent/null/wrong-type/extra/foreign SANs, DNS/IP/email, CA=true, wrong EKU/TTL, issuer switches and direct/stale requests fail admission/signing with no leaf. Valid issuer-auth token cannot sign another identity. |
| Foreign identity and material | Wrong requester/namespace/service account/audience and matching second-cluster token fail. Foreign CSI mounts, issuer-auth Pods, crafted CNPG Pods/Cluster/Pooler and ingress-shim identity requests denied; no API Secret client leaf key on CSI path. Genuine database reconciliation/failover and ingress renewal succeed. |
| Token, template and trust paths | Deny direct/indirect token acquisition, including VSO resources with foreign VaultConnection endpoints; deny unapproved image/command/service-account/volume/trust/env changes and resulting controller-created Pods. Preserve approved deployer updates and restart-annotation-only controller actions. Protect namespace policy and trusted credential homes. |
| Client-trust ConfigMap writes | Non-approved principal, including a cnpg-manager-equivalent binding, cannot patch client-trust bundle; approved writer succeeds and expected trust reloads. Template admission alone cannot pass this case. |
| Controller and node credentials | Separately deny (a) Pod selecting cert-manager controller SA, (b) exec into controller Pod, (c) exec into ok-console Pod, (d) hostPath Pod outside openkubes-console on Console node. Pair each with an approved positive control; restricted workload/database continuity succeeds. |
| CSR enforcement principal | Direct CertificateRequest with exact/foreign CSR exercises webhook or approver-policy, including alternative issuer; approved request succeeds, forbidden CSR fails. Serving-cert trust/rotation succeeds; untrusted serving cert cannot bypass enforcement. |
| Signer custody, TokenReview and endpoint | Synthetic policy/auth/token/mount and custody controls pass; shared-server/transit-CA endpoint impersonation fails before login, dedicated serving-CA control succeeds. Exercise ok-mgmt→ok-shared API path and selected reviewer option with successful login and foreign/second-cluster denial. Real pilot inventory remains a separate stage-3 gate. |
| Producer denial | Old CA/same URI fails TLS; new CA/wrong URI and no certificate return HTTP 403. Pair every denial with successful authenticated observed-state traffic so unavailability cannot pass a denial. |
| Renewal at 3 days | Confirm actual 168-hour TTL and 72-hour remaining renewal configuration; two scheduled renewals change serial/generation, load consistent cert/key and sustain traffic without manual restart. Accelerated scheduling alone does not establish the 7d/3d hypothesis. |
| Outage within headroom | On pinned versions run both login failure (Pending) and sign failure (Failed), each for 47 h from 72 h remaining; existing leaf sustains traffic, alert within 15 min. Require reload within one hour of restoration and ≥24 h before expiry, or explicitly budget/test operator-triggered re-issue. Record retry schedule/recovery latency; missed availability bounds require revised recovery budget before adoption. |
| Outage through expiry | Keep signer unavailable beyond expiry: expired credentials cannot authenticate and an alert remains active; restoring signer recovers authenticated traffic using a valid new leaf. |
| Rollback | Exercise bounded overlap then new-only on every replica. Re-issue with new CA and restore approved revision without old-root fallback; include recovery-overlay trust inheritance in the implementation inventory. |

Effective-authority evidence must join complete, authenticated Roles, ClusterRoles,
RoleBindings and ClusterRoleBindings for the target, timestamped within 24 hours,
with resourceVersions and no pagination, duplicates or unresolved references.
Include wildcard/aggregate rules, impersonation, nodes/proxy, bind/escalate,
CSR/signing/approval, indirect controllers and admission/namespace administrators.
Invalid exports fail closed; include approved scoped positive controls. Static RBAC
alone cannot establish admission, external groups, historic credentials, loaded TLS
contexts or node compromise. Pair it with the scoped runtime proof.
Each implementation guard needs its invalid-input case observed failing when the
guard is removed, then restored alongside the successful positive control.

## Open questions and owners

| Remaining question | Owner role | Resolution gate |
|:---|:---|:---|
| Which CSI driver/version, issuance API, approver and minimum requester rights satisfy the exact identity contract? | Identity integration maintainer | Before integration; prove generated identity, required CertificateRequest rights and reload behaviour without unnecessary runtime issuance/token grants. |
| Which signer address, serving-CA custody and redirect administrators meet pilot requirements? | PKI operator | Before signer provisioning; inventory endpoint, backup and administrative authority. |
| What are the effective cnpg-manager namespaces, Pod Security exceptions, key/token paths and trusted-principal bindings? | Security reviewer with database operator maintainer | Approved read-only inventory first; architecture owner reviews residual authority before cutover. |
| Does 7d/3d meet recovery/exposure requirements, and who owns alerts and the overlap deadline? | Service reliability owner with architecture owner | Test the explicit hypothesis; name operator roles, alert route and deadline in the separately reviewed maintenance plan. |

## Proposed follow-up

Shared server-CA custody, reader narrowing, default-approval replacement and
server-root rotation remain a separate multi-consumer change. Preserve Keycloak/OIDC,
zot/Talos, Console ingress, producer HTTPS, Vault HTTPS and webhook injection.
Management OIDC trust needs separately approved coordination; see
[management OIDC plan](../../docs/ok-mgmt-oidc-rollout.md).
Defer these only after new-only client trust and closure or explicit review of
paths to trusted administrators. They remain Console exposure during overlap.
No server-CA follow-up may restore server-root trust for Console client authentication.

## Scope of this record

**Applies to:** Proposed design direction and repository declarations only. No
cluster observation was performed for this revision; installed authority and
enforcement remain subject to the owned confirmation gates above.

The threat paths are those identified in design review; each implementation PR
requires its own threat review against the chosen option, signer host and versions.
Console→producer server trust stays on the old shared CA until the server-CA
follow-up; old-CA readers keep the identity until new-only. The pilot needs the
transit Vault every ~4 days, instead of only at unseal. The producer accepts the
URI among SANs; exactness is enforced only in the signing role.

**Shown in:** this proposed contract, repository-grounded assessment, decision matrix
and future verification gates. Repository paths establish source existence, not
installed ownership or runtime enforcement.

**Follow-ups:** authorized ownership/principal inventory and residual-authority review,
pinned signer/CSI/admission implementation, controller continuity and renewal/traffic
proof, and separate server-CA work. No live PKI, RBAC or cluster change is made or
authorized by this ADR.
