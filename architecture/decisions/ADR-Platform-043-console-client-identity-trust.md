# ADR-Platform-043 — Independent Console client identity CA, leaf delivery and trust distribution

- **Status:** Proposed
- **Date:** 2026-10-27
- **Date updated: 2026-11-13**
- **Decision scope:** Console client identity to the observed-state producer; design only
- **Tracking:** https://kubernauts.atlassian.net/browse/OK-210
- **Related:** ADR-Platform-025, ADR-Platform-037

## Context

The Console observed-state client identity is
`spiffe://openkubes.io/ns/openkubes-console/sa/ok-console`. The producer requires
that URI among the client certificate's URI SANs; the proposed signing role also
excludes extra SANs. The repository declaration is
[producer manifests](../../platform/console/observed-state-producer/manifests.yaml).
Human authentication remains separate under ADR-Platform-037.

The [existing ClusterIssuer](../../platform/networking/cert-manager/cluster-issuer-internal-ca.yaml)
documents copying the shared server CA key from `vault` to `cert-manager`.
Any holder can sign the Console identity outside cert-manager; renaming the issuer
or adding CertificateRequest admission does not isolate that signing path.
The [Vault reachability declaration](../../platform/secrets/vault/crossplane/reachability.yaml)
contains the original server-CA chain. Current bindings, approval configuration,
key holders and installed ownership require confirmation rather than inference.

## Decision matrix

The architecture owner's direction of 2026-10-29 is recorded below as a **Proposed
design direction**, not implementation approval or live authorization. Adoption
requires the evidence and explicit residual-authority review in this record.

| Decision | Direction (architecture owner) | Fallback / condition | Evidence required before adoption | Status |
|:---|:---|:---|:---|:---|
| Leaf delivery | Investigate pinned CSI leaf delivery first; keep delivery lean and retain placement. | Namespace separation with isolated Secret delivery if CSI fails identity/admission proof; preserve the exact URI or separately review a contract change. | Exact URI SAN, foreign identity denied, no API Secret leaf key, reload and CNPG/ingress continuity; select and pin the driver. | Proposed direction; proof required |
| Signer hosting | Dedicated PKI mount on existing ok-mgmt Vault for the first pilot. | Independent Vault only if the pilot fails the explicit security requirements below; shared administrators and shared unseal/outage availability remain risks. | Signer isolation, exact-role/auth denial, dedicated serving trust and administrator-path assessment; outage recovery within the tested budget. | Proposed pilot; security gates required |
| Leaf lifetime | 7-day leaf TTL, renew at 3 days remaining: design HYPOTHESIS. | Revise lifetime/headroom if rotation or outage tests fail; architecture owner reviews the revised exposure/recovery budget. | Two scheduled renewals with reload and uninterrupted traffic; 47-hour signer outage from the renewal threshold, alert within 15 minutes, recovery with at least 24 hours before expiry; expiry fails closed. | Hypothesis; adoption gated |
| Residual authority (cnpg-manager) | NOT accepted unreviewed; scoped Pod Security and RBAC assessment first. | Constrain reachable Pod/token/key paths and preserve database operations; architecture owner explicitly reviews any remaining authority before cutover. | Assessment below, effective namespace/admission coverage, denied crafted Pods and successful reconciliation/failover; explicit trusted signers, readers and approvers. | Assessment and explicit review required |
| Proof and cutover | One disposable-cluster proof and a minimal staged cutover. | Resolve a failed gate before bounded overlap and new-only; broader server-CA work stays separate. | Exact URI, foreign identity rejection, renewal at 3 days, outage behaviour and rollback in one proof; separately authorized live stages. | Proposed sequence; no live authorization |

### Delivery and pilot security requirements

**CSI driver to be selected** by the identity integration maintainer. No selected
identity driver or installation was found in this repository. The former ADR's
cert-manager csi-driver / csi-driver-spiffe names were candidates, not a selection.
Selection must establish a pinned compatible Kubernetes/cert-manager/Vault and
approver combination, exact non-overridable URI generation, no API Secret leaf
key, minimum issuance rights, Pod identity admission and atomic cert/key reload.
Do not assume Certificate/Secret semantics apply unchanged to a CSI driver.

The first pilot uses the existing [ok-mgmt transit Vault](../../platform/secrets/vault/transit/README.md)
with a new dedicated PKI mount; this is not an already deployed identity signer.
Shared administrators may change policies or read Vault storage; a shared outage
or unseal failure can stop both signing and ok-shared unseal. Mount separation
alone is not administrative or availability independence.

| Pilot security requirement | Pass criterion before adoption |
|:---|:---|
| Independent custody | Identity CA key absent from ok-shared Kubernetes Secrets; enumerate Vault storage, backup, unseal and administrative holders. No deferred server-CA/Keycloak path reaches a trusted administrator without explicit residual review. |
| Exclusive signing path | Complete policy/auth/token and mount-configuration inventory permits only the exact sign role; no export, root, sign-verbatim, issuer override or alternate issuance protocol. Foreign identity and second-cluster tokens fail; exact identity succeeds. |
| Signer endpoint trust | Dedicated serving CA key outside ok-shared and ok-mgmt Kubernetes Secrets; endpoint impersonation with either shared server CA or transit CA fails before login. Inventory DNS/Service/EndpointSlice redirect authority. |
| Least authority and audit | Only inventoried signer/auth principals can reach the mount; provisioning grants retired before cutover; issuance and denied requests auditable without keys/tokens. Shared administrators explicitly assessed. |
| Recovery | Rotation/outage tests in the matrix pass; backups and unseal recovery preserve signer isolation. A security failure triggers architecture-owner review of independent Vault; availability failure also requires a revised recovery budget. |

## Scoped Pod Security and RBAC risk assessment (cnpg-manager)

This is a repository-grounded preliminary assessment. Each row identifies its
source or the approved read-only confirmation needed; it is not live evidence.

| Authority or path | Source / confirmation | Risk and required mitigation |
|:---|:---|:---|
| Operator installation | from repo `platform/identity/keycloak/Makefile`: pins external `releases/cnpg-1.30.0.yaml` at v1.30.0, defaults operator namespace to cnpg-system and installs it in the database target. | The upstream RBAC blob is external to this repo; installer intent does not establish effective cnpg-manager grants. |
| Pod create, exec and Secret access; namespaces | to confirm on ok-shared (read-only, approved window): join effective Roles/ClusterRoles and bindings for cnpg-system/cnpg-manager, including aggregates/wildcards; enumerate every Pod-create namespace, exec, Secret and token grant. | Treat cluster-wide Pod creation and CA-key reads as unresolved risk until scoped. Operator home namespace does not bound workload authority. |
| Privileged/hostPath Pods | to confirm on ok-shared (read-only, approved window): effective Pod Security labels/version, exemptions and admission wherever cnpg-manager can create Pods, plus who can change them. | If admitted, privileged/hostPath Pods can expose node credentials and mounted leaf material beyond namespace gates. Require restricted enforcement with pinned version and explicit compatibility review; labels alone are insufficient. |
| Console namespace and leaf mounts | from repo `platform/console/observed-state-producer/manifests.yaml`: openkubes-console Namespace has no Pod Security labels; producer mounts observed-state-producer-tls Secret and requires the exact ok-console URI. | This file neither proves installed namespace policy nor declares a Console client CSI mount. Protect identity service accounts, templates, volumes and trust paths under either delivery option. |
| Existing CA key | from repo `platform/networking/cert-manager/cluster-issuer-internal-ca.yaml` and `platform/secrets/vault/crossplane/reachability.yaml`: CA Secret in vault, documented copy into cert-manager. | to confirm on ok-shared (read-only, approved window): cnpg-manager's reach to both Secrets, direct reads or Pod mounts/exec. Any such holder can sign the accepted URI while the old root is trusted. |
| Database credential route | from repo `platform/identity/keycloak/manifests/database.template.yaml`: CNPG reads a namespaced bootstrap/managed-role credential Secret; `docs/ok-mgmt-oidc-rollout.md` documents management OIDC trust. | to confirm on ok-shared (read-only, approved window): exec/credential reach to Keycloak realm signing material and onward administrator access. Count reachable administrators as identity holders until constrained. |
| CSI mitigation | to confirm on ok-shared (read-only, approved window): installed Pod/template/token admission and driver boundaries against the selected design. | CSI removes API Secret leaf-key exposure; it does not prevent choosing ok-console/issuer-auth service accounts, mounting identity CSI volumes or node compromise. Deny those paths for foreign Pods/controllers, including CNPG Cluster/Pooler-mediated creation. |
| Isolated Secret fallback | to confirm on ok-shared (read-only, approved window): namespace-scoped CNPG/ingress rights and indirect Pod/exec/token paths against the fallback design. | Separation works only if broad Secret readers and Pod creators lose reach into the identity namespace; a database move alone leaves ingress readers. Preserve database reconciliation, failover, credential/TLS rotation and ingress renewal. |

Required disposition: the security reviewer owns the effective-authority assessment;
the database operator maintainer owns compatible restrictions. Do not allowlist
cnpg-manager merely to pass a gate. Residual Pod/node/CA-key authority needs the
architecture owner's explicit review before cutover; it is not accepted here.

## Trusted principals

These are roles to inventory, not a blanket allowlist. The identity integration
maintainer must resolve each proposed or unconfirmed binding before adoption.

| Principal role / ServiceAccount | Authority | Definition or confirmation required |
|:---|:---|:---|
| Dedicated Vault PKI signer administrator | Provision mount/role; retire provisioning rights before cutover | Proposed integration; existing host context in `platform/secrets/vault/transit/README.md`; exact policies and administrative holders to confirm. |
| cert-manager controller / console-identity-issuer-auth | Sole issuer-auth TokenRequest caller / dedicated Vault authentication identity | Proposed namespaced Issuer openkubes-console/console-identity-v1; binding and controller ServiceAccount to confirm. CSI requester/approver may differ and must be inventoried. |
| Existing CA-key readers | Direct or indirect signing while old root is trusted | Key locations from `platform/networking/cert-manager/cluster-issuer-internal-ca.yaml`; effective readers to confirm, including cnpg-system/cnpg-manager, ingress/traefik, kube-system/cilium-operator, observability operator, VSO controller and cert-manager cainjector. These are assessment candidates, not verified grants or trusted exceptions. |
| New identity CA-key readers | Vault storage/backup, recovery and administrative access | Proposed external custody; exact Vault roles and infrastructure ServiceAccounts to confirm, including shared ok-mgmt administrators. |
| Certificate / CertificateRequest writers | Original Certificate submitters, direct CSR authors and cert-manager controller | Existing ClusterIssuer from `platform/networking/cert-manager/cluster-issuer-internal-ca.yaml`; all effective writers and new CSI requester roles to confirm. Console runtime receives no token-minting rights. |
| CertificateRequest approvers | Default cert-manager approver and any driver-specific approver | Installed default approval, approveSignerNames exclusions, driver approver ServiceAccount and signer scope to confirm; no approver-policy installation inferred. |
| Approved deployer; policy/RBAC/admission and namespace administrators | Change identity workloads, trust and enforcement | Exact roles/ServiceAccounts and protected credential homes to confirm; no personal identities recorded here. |
| Node/control-plane and management operators | Access mounted material or override controls | Exact roles and indirect server-CA/Keycloak credential paths to confirm; neither CSI nor external custody removes this trust. |

## Issuance and trust contract

The following controls are proposed implementation requirements, subject to the
matrix, driver selection and behavior proof below.

| Control | Proposed contract |
|:---|:---|
| External signer | Independent identity root/key, with namespaced in-tree Vault Issuer openkubes-console/console-identity-v1. No identity CA key, static Vault token or AppRole SecretID in ok-shared. |
| Signer host | Dedicated PKI mount on existing ok-mgmt Vault for the pilot, gated by the security requirements above. Independent Vault is conditional, not a parallel open decision. |
| Authentication | Dedicated console-identity-issuer-auth service account; short-lived TokenRequest; minimal token grant to the cert-manager controller as the sole issuer-auth TokenRequest caller. Use a dedicated Vault Kubernetes auth mount bound to ok-shared's token issuer and API CA, with exact service account and namespace binding. Bind the Vault role only to the issuer-derived default audience for openkubes-console/console-identity-v1. Deny every Pod selecting the auth account, including controller-created Pods. Deny token and token-Secret acquisition in protected namespaces and trusted-account homes by every other caller, direct or controller-mediated. In particular, deny TokenRequest for console-identity-issuer-auth (and, under CSI delivery, ok-console) via VSO VaultAuth, VaultAuthGlobal, VaultConnection and Vault*Secret resources as well as directly; there is no VSO TokenRequest exception in openkubes-console. Confirm effective VSO TokenRequest rights and CR-author reach to serviceAccount/audiences and foreign VaultConnection addresses; deny token relay/replay paths. Prove cert-manager 1.17.2/Vault audience compatibility and rejection of an otherwise matching second-cluster token. |
| Signing role | Exact Console URI only; client-auth EKU; non-CA; approved algorithm and key size. Reject absent, null, wrong-type, extra or foreign SANs, DNS/IP/email, CA=true, excessive TTL and alternate signing paths. No export, root, sign-verbatim or issuer-override privilege. A stolen auth token must not sign another identity. |
| Lifetime | 7-day TTL / renewal at 3 days remaining is a design hypothesis; adopt only after the matrix tests. Recovery headroom trades against stolen-leaf exposure. Accelerated tests supplement, rather than replace, verification of the actual configured schedule. |
| Certificate admission | Match the Console URI in Certificate spec.uris and in the parsed CSR of CertificateRequest spec.request, including requests referencing another issuer. Enforce exact issuerRef/group/kind, identity, usages, duration and approved original submitter for create/spec update and direct CertificateRequests. cert-manager as CSR creator is not the original Certificate submitter. Preserve necessary GC metadata/status behavior without allowing spec bypass. |
| Issuer protection | Admission denies any Issuer other than openkubes-console/console-identity-v1 that references console-identity-issuer-auth, and denies extra serviceAccountRef.audiences on that Issuer. Confirm issuer-derived and extra-audience behaviour for the pinned cert-manager version. Another Issuer could otherwise copy an audience while referencing the same auth account. Protect endpoint/auth fields. The Issuer caBundle must contain only a dedicated signer-serving CA whose key is outside both ok-shared and ok-mgmt Kubernetes Secrets. The repository declares shared-CA serving trust and a transit selfSigned-to-CA chain; confirm installed endpoints before integration. Neither is an acceptable signer-serving trust anchor. Count dedicated CA key holders and anyone able to redirect the signer address as identity holders in the residual-authority review: a CA key holder with a redirect position can impersonate the signer, receive cert-manager's legitimate token and replay it. The identity integration maintainer must specify how ok-shared addresses the signer (IP or in-cluster name), which determines redirect authority, including Service/EndpointSlice/DNS writers and node administrators. Reject issuer switching, stale unapproved desired objects and identity ingress-shim requests. |
| Default approver | For the in-tree Vault Issuer path, retain default approval only after confirming installed approveSignerNames behaviour and exact admission/signing boundaries. The exact Vault role plus Console admission is the boundary. Verify pinned behavior; broad approval must not widen signer rights. Global replacement belongs to the server-CA follow-up. CSI may require a signer-specific exclusion as described below. |
| CSI variant | Prove generated namespace/service-account identity equals the exact URI and cannot be caller-overridden. Identity integration maintainer to confirm against the selected pinned driver: whether the driver needs its own approver with this signer excluded from approveSignerNames, and whether the Pod service account needs certificaterequests create. If required, allow exactly that right scoped by exact identity/requester admission; grant no token-minting rights. Driver selection and compatible application integration require proof rather than assuming Certificate/Secret equivalence. |
| Workload template admission | Pin Console and producer Pod templates to approved submitters: image digest, command, service account, identity/trust volumes and paths, OK_OBSERVER_TLS_CLIENT_CA_FILE and OK_OBSERVER_TLS_CLIENT_IDENTITY. Deny any Pod selecting ok-console from another workload, including ReplicaSet-created Pods. Controller exceptions such as VSO may change only the restart annotation; they may not mutate other template fields. |

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
| Producer validates Console client | `ok-console/deploy/kubernetes/overlays/ok-shared-live/producer-deployment.yaml` | Replace the leaf Secret ca.crt projection with the client-trust ConfigMap: existing public CA, bounded old+new, then new-only. |
| Console validates producer server | `ok-console/deploy/kubernetes/overlays/ok-shared-live/kustomization.yaml` | Split the coupled CA/cert/key projection. Keep existing server CA in the server-trust ConfigMap at OK_CONSOLE_OBSERVED_STATE_CA_FILE; change only client cert/key delivery. |
| Producer reload | `openkubes/platform/console/observed-state-producer/app.py` | Trust context is created at startup. Prove reload or automatic guarded rollout with consistent generations. |
| Console reload | `ok-console/bff/adapters/mtlsFetch.mjs` | Trust context is created at source construction. Secret/CSI replacement alone is insufficient; prove consistent cert/key/trust loading. |

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
| 3 — bounded overlap | Producer loads old+new client roots first; switch Console leaf/delivery second. Keep server trust separate and unchanged. | Separately authorized window, named operator role and fixed overlap deadline; every backend authenticates with consistent cert/key/trust generations and readiness/drain budget. Old CA holders retain identity authority during overlap. |
| 4 — new-only | Remove old client root from every producer context and drain old connections. | Old-CA/same-URI fails; new-CA/exact-URI succeeds on every replica, renewal/reload and traffic continue. Rollback re-issues from the new CA; re-trusting old root requires fresh residual review and maintenance authorization. No automatic old-root fallback or silent overlap extension. |

### Single disposable-cluster proof

The numeric outage and alert bounds below are proposed adoption criteria for the
7d/3d hypothesis, subject to the service reliability owner and architecture owner
review; they are not a claim of measured recovery capability.

The proof owner is the identity integration maintainer. Capture pinned versions,
images, flags, Pod securityContexts, quota, logs and hashes. Validate flags and
compatibility before the run; preserve evidence without keys or tokens. This is
one scoped Console proof, not a platform redesign or a second server-CA programme.

| Test | Pass criterion |
|:---|:---|
| Exact identity and signing | New CA/exact URI produces authenticated observed-state traffic. Absent/null/wrong-type/extra/foreign SANs, DNS/IP/email, CA=true, wrong EKU/TTL, issuer switches and direct/stale requests fail admission/signing with no leaf. Valid issuer-auth token cannot sign another identity. |
| Foreign identity and material | Wrong requester/namespace/service account/audience and matching second-cluster token fail. Foreign CSI mounts, issuer-auth Pods, crafted CNPG Pods/Cluster/Pooler and ingress-shim identity requests denied; no API Secret client leaf key on CSI path. Genuine database reconciliation/failover and ingress renewal succeed. |
| Token, template and trust paths | Deny direct/indirect token acquisition, including VSO resources with foreign VaultConnection endpoints; deny unapproved image/command/service-account/volume/trust/env changes and resulting controller-created Pods. Preserve approved deployer updates and restart-annotation-only controller actions. Protect namespace policy and trusted credential homes. |
| Signer custody and endpoint | Pilot security requirements pass, including full policy/mount inventory and rejection of shared-server/transit-CA endpoint impersonation before login; dedicated serving-CA control succeeds. |
| Producer denial | Old CA/same URI fails TLS; new CA/wrong URI and no certificate return HTTP 403. Pair every denial with successful authenticated observed-state traffic so unavailability cannot pass a denial. |
| Renewal at 3 days | Confirm actual 168-hour TTL and 72-hour remaining renewal configuration; two scheduled renewals change serial/generation, load consistent cert/key and sustain traffic without manual restart. Accelerated scheduling alone does not establish the 7d/3d hypothesis. |
| Outage within headroom | From 72 hours remaining, block signing for 47 hours: existing leaf sustains traffic, renewal-error alert fires within 15 minutes, restored signer renews and reloads within one hour, with at least 24 hours before expiry. Record recovery latency; any missed bound fails adoption. |
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

The threat paths listed are the set identified in design review, not an exhaustive analysis; each implementation PR requires its own threat review against the chosen option, signer host and pinned versions.

**Shown in:** this proposed contract, repository-grounded assessment, decision matrix
and future verification gates. Repository paths establish source existence, not
installed ownership or runtime enforcement.

**Follow-ups:** authorized ownership/principal inventory and residual-authority review,
pinned signer/CSI/admission implementation, controller continuity and renewal/traffic
proof, and separate server-CA work. No live PKI, RBAC or cluster change is made or
authorized by this ADR.
