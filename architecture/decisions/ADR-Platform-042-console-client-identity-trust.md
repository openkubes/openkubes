# ADR-Platform-042 — Independent Console client identity CA, leaf delivery and trust distribution

- **Status:** Proposed
- **Date:** 2026-10-27
- **Decision scope:** Console client identity to the observed-state producer; design only
- **Tracking:** https://kubernauts.atlassian.net/browse/OK-210

## Context

The observed-state producer authorizes the Console by the exact URI SAN
`spiffe://openkubes.io/ns/openkubes-console/sa/ok-console`.
Read-only observations on 2026-10-22 identified `ok-shared-internal-ca` as a plain
cert-manager v1.17.2 CA ClusterIssuer, with default CertificateRequest approval
enabled and no approver-policy. Its CA key Secret exists in both `cert-manager`
and `vault`, and six service accounts can read it cluster-wide.

Any holder of that key can sign the Console identity outside cert-manager.
CertificateRequest admission or approval cannot constrain that signing path.
The same CA serves Keycloak, zot, Console ingress, producer HTTPS and Vault HTTPS.
Changing an issuer name or namespace while retaining its key does not isolate identity.

## Proposed decision

Create an independent client identity CA whose signing key stays outside ok-shared
Kubernetes Secrets. Ultimately the producer would trust only that CA for clients
and authorize only the exact Console URI above. Keep server trust separate.
This is a proposal for architecture review; the choices below remain open.

### Scope and operational trust

| Work | Boundary |
|:---|:---|
| OK-210 | Console leaf delivery, Pods, service-account tokens, namespaced external Issuer, exact Certificate and CertificateRequest identity constraints, public trust ConfigMaps and independent signer role. |
| Proposed server-CA follow-up | Narrow the six existing CA readers and manual/key-copy readers; safely replace default approval across server/bootstrap consumers; protect and eventually rotate the server CA and its management-plane OIDC dependencies. |
| Trusted operators | Named platform administrators, cert-manager controller, exact approved deployer, external signer administrators and Pod/CSI node administrators. Inventory actual principals and capabilities; existing violations do not become blanket allowlist entries. |
| Runtime identity | The Console runtime service account receives no issuance or token-minting rights. |

External custody protects the CA key, but cannot protect a client leaf key stored
in an API Secret from existing Secret readers. A blanket denial of CNPG Pod,
exec and Secret access or Traefik serving-Secret access cannot pass: CNPG needs
those capabilities for database reconciliation, and Traefik needs TLS renewal.
The selected delivery design must preserve those operations.

### Leaf delivery and namespace boundary

The architecture owner must select between the following alternatives.
Investigate (b) first because it avoids a stateful database move; it is not selected.

| Option | Required change and consequence | Go/no-go proof |
|:---|:---|:---|
| (a) Namespace separation | Move the database to a database namespace, or move the identity workload to an isolated namespace. A database move changes service addresses, credentials, network rules and migration/failover planning. Moving Console requires an explicit SPIFFE identity contract change; this proposal retains the current URI. No destructive move is authorized. | Demonstrate leaf isolation and renewal while CNPG retains required database operations. |
| (a) Ingress boundary | Moving the database alone leaves Traefik namespace-wide Secret list/watch. Narrow access to exact serving Secrets with a compatible cache, or move ingress termination out. | Do not issue a Secret-backed identity leaf while broad readers remain. If enforceable narrowing is unavailable, choose (b). |
| (b) CSI delivery | Deliver the client leaf through a pinned compatible cert-manager csi-driver or csi-driver-spiffe implementation, outside API Secrets. Keep database and ingress placement. Select issuance API, authentication, trust domain and application mount/reload integration explicitly. | Prove exact URI generation and authorization; foreign Pods/service accounts cannot obtain the Console identity. No client leaf key may appear in API Secrets. |
| (b) Pod admission | Fail closed for Pods created by cnpg-manager: reviewed database service accounts, images, volumes and ownership only. Forbid Console and issuer-auth service accounts, identity CSI mounts, leaf paths, privileged Pods and hostPath access. Names and labels alone are insufficient. | Crafted CNPG Pods cannot obtain identity, while genuine reconciliation and failover succeed. CSI alone does not prevent Pod impersonation. |

### Pod Security and residual authority

Enforce Pod Security Admission with `enforce=restricted` and a pinned
`enforce-version` in namespaces where Pod creators remain, including the selected
Console namespace. Validate CNPG and CSI workloads and resolve incompatibilities
before cutover. Protect namespace labels, exemptions and admission configuration;
review any necessary system-namespace exception explicitly.

Restricted Pod Security prevents privileged and hostPath Pods. It does not stop a
normal Pod choosing another service account, so identity-specific admission is required.
CNPG Cluster resources in protected namespaces are an indirect Pod/Secret path;
ingress-shim is an indirect Certificate path. Inventory and constrain both.

cnpg-manager has cluster-wide Pod create authority in the observed state. In a
namespace without effective Pod Security it can create a privileged hostPath Pod,
compromise a node and reach credentials beyond namespaced gates. Narrowing that
cluster-wide authority belongs to the proposed follow-up. Cutover requires the
owner's explicit residual-authority decision described below.

Node, control-plane and management-plane administrators remain trusted.
Neither external custody nor CSI claims protection from their access.

## Inventory and ownership before implementation

Repository declarations explain intended ownership; they are not installation evidence.
Resolve actual installed release owners and effective principals before implementation.
Paths below are repository-qualified source references, without line-number dependencies.

| Asset or authority | Repository source | Declaration and required action |
|:---|:---|:---|
| Console database | `ok-console/deploy/kubernetes/overlays/ok-shared-live/postgres-cluster.yaml` | CNPG Cluster openkubes-console/ok-console-db; retain required Pod, exec and Secret operations. |
| Console ingress | `ok-console/deploy/kubernetes/overlays/ok-shared-live/certificates.yaml`, `ok-console/deploy/kubernetes/overlays/ok-shared-live/ingress.yaml` | ok-console-ingress-tls is a serving Secret; preserve renewal. |
| Existing CA and manual copy | `openkubes/platform/networking/cert-manager/cluster-issuer-internal-ca.yaml` | Documents copying the entire CA Secret from vault to cert-manager. Count workstation/operator credentials as key holders; reconcile installer ownership. |
| Vault-side CA chain | `openkubes/platform/secrets/vault/crossplane/reachability.yaml` | Ten-year CA Certificate/Secret (87600h), bootstrap Issuer and signing Issuer; reconcile both copies and renewal ownership in the follow-up. |
| Management OIDC trust | `openkubes/platform/networking/cert-manager/cluster-issuer-internal-ca.yaml` | Documents ok-mgmt API-server --oidc-ca-file trust of the server CA. Rotation requires separate management authentication planning and privileged approval. |
| Talos registry trust | `ok-cluster/scripts/talos_registry_trust.py`, `ok-cluster/ok-shared/cluster-config.yaml` | Fetches the whole Secret to extract ca.crt. Inventory caller credentials as key readers; replace with public-only trust in the follow-up. |
| Cross-cluster administration | `openkubes/platform/cluster-management/crossplane/examples/ok1-providerconfigs.yaml` | Workload kubeconfig-backed Helm/Kubernetes ProviderConfigs illustrate a possible path. Inventory actual ok-mgmt ProviderConfigs, provider service accounts, managed objects and credential holders; this example is not a verified ok-shared binding. |
| Candidate signer host | `openkubes/platform/secrets/vault/transit/README.md` | Existing ok-mgmt transit Vault is a candidate for a new PKI mount, not an existing PKI signer. |
| Trusted control-plane paths | Effective-authority inventory required | Include cert-manager, kube-system/generic-garbage-collector wildcard writes, system:masters, deployer, policy/RBAC/admission managers, issuer-auth TokenRequest callers, nodes/proxy, impersonation and trusted service-account home namespaces. |

### Existing CA-Secret readers

These six identities were observed read-only on 2026-10-22. Repository references
provide source context, not a complete current binding inventory. Their server-CA
remediation is separate from the scoped Console go/no-go gate.

| Reader | Repository source context | Required function and narrowing consequence |
|:---|:---|:---|
| ingress/traefik | `ok-cluster/Makefile` | Secret get/list/watch supports serving TLS and discovery. Preserve renewal; namespace watch filters alone do not revoke authority. |
| kube-system/cilium-operator | `ok-cluster/Makefile` | Cilium 1.19.6 operator Secret sync is conditional. Inventory Gateway/Ingress/BGP consumers; disable unused sync or constrain sources while preserving CNI. |
| cnpg-system/cnpg-manager | `openkubes/platform/identity/keycloak/Makefile` (installs the upstream CloudNativePG v1.30.0 release manifest) | Cluster-bound Secret and Pod authority. Own constrained installation across enrolled database namespaces, including exec/configmaps; retain reconciliation, failover and credential/TLS rotation. Do not edit the upstream release blob. |
| ok-observability/ok-observability-operator | `ok-observability/implementations/prometheus/Chart.yaml`, `ok-observability/implementations/prometheus/values.yaml` | Stack 62.7.0 source context; broad ConfigMap/Secret verbs require narrowing while preserving discovery and config/TLS/auth refresh. Protect trust writes. |
| vault-secrets-operator/vault-secrets-operator-controller-manager | `ok-cluster/Makefile` | Version 1.5.0 context; Secret CRUD/list/watch, serviceaccounts/token create and workload patch require enrolled destinations/auth identities while preserving rotation and rollouts. |
| cert-manager/cert-manager-cainjector | `openkubes/platform/networking/cert-manager/` | Upstream 1.17.2 role includes Secret reads and injection administration. Reconcile installer ownership; use public-only injection sources and supported scoped informers while preserving webhook/CRD/APIService trust renewal. |

## Issuance and trust contract

The following controls are proposed implementation requirements, subject to the
architecture choices and behavior proof below.

| Control | Proposed contract |
|:---|:---|
| External signer | Independent identity root/key, with namespaced external Vault Issuer openkubes-console/console-identity-v1. No identity CA key, static Vault token or AppRole SecretID in ok-shared. |
| Signer host | Choose a new PKI mount on existing ok-mgmt Vault or an independently operated Vault. The former shares management/unseal availability and administrators; the latter adds operational cost for stronger administrative separation. Neither is authorized here. |
| Authentication | Dedicated console-identity-issuer-auth service account; short-lived TokenRequest; exact service account, namespace and audience binding; minimal controller token grant. Deny every Pod selecting the auth account, including controller-created Pods. Deny outside token and token-Secret acquisition in protected and trusted-account home namespaces. Prove cert-manager 1.17.2/Vault audience compatibility. |
| Signing role | Exact Console URI only; client-auth EKU; non-CA; approved algorithm and key size. Reject absent, null, wrong-type, extra or foreign SANs, DNS/IP/email, CA=true, excessive TTL and alternate signing paths. No export, root, sign-verbatim or issuer-override privilege. A stolen auth token must not sign another identity. |
| Lifetime | Propose a 7-day leaf with renewal at 3 days remaining, subject to outage budget. Recovery headroom trades against stolen-leaf exposure. Alert on renewal errors and before headroom is consumed. CSI must provide equivalent rotation/headroom; accelerated TTL is for disposable proof only. |
| Certificate admission | Exact issuerRef/group/kind, identity, usages, duration and approved original submitter for create/spec update and direct CertificateRequests. cert-manager as CSR creator is not the original Certificate submitter. Preserve necessary GC metadata/status behavior without allowing spec bypass. |
| Issuer protection | Protect endpoint/auth fields; reject issuer switching, stale unreviewed desired objects and identity ingress-shim requests. |
| Default approver | Retain default approval in OK-210. It approves internal issuers; the external issuer's exact signing role plus Console admission is the boundary. Verify pinned behavior and any external approver constraints; broad approval must not widen signer rights. Global replacement belongs to the server-CA follow-up. |
| CSI variant | Prove generated namespace/service-account identity equals the exact URI and cannot be caller-overridden. Driver selection and compatible application integration require proof rather than assuming Certificate/Secret equivalence. |

### Public trust distribution and mount split

Declare public PEM in Git with reviewed fingerprint, generation and expiry metadata.
Render separate observed-state-client-trust and observed-state-server-trust ConfigMaps.
No privileged publisher or CA-Secret read is required. CI/render checks must reject
private-key PEM. An owner and runbook must alert on expiry and submit the next reviewed
PEM before expiry. Root changes require review, not automatic acceptance by label.

Protect ConfigMap writes, including broad Prometheus/CNPG authority, namespace
selection and Git/release authority. Public data is still security-sensitive trust.

| Direction | Source declaration | Required change |
|:---|:---|:---|
| Producer validates Console client | `ok-console/deploy/kubernetes/overlays/ok-shared-live/producer-deployment.yaml` | Replace the leaf Secret ca.crt projection with the client-trust ConfigMap: existing public CA, bounded old+new, then new-only. |
| Console validates producer server | `ok-console/deploy/kubernetes/overlays/ok-shared-live/kustomization.yaml` | Split the coupled CA/cert/key projection. Keep existing server CA in the server-trust ConfigMap at OK_CONSOLE_OBSERVED_STATE_CA_FILE; change only client cert/key delivery. |
| Producer reload | `openkubes/platform/console/observed-state-producer/app.py` | Trust context is created at startup. Prove reload or automatic guarded rollout with consistent generations. |
| Console reload | `ok-console/bff/adapters/mtlsFetch.mjs` | Trust context is created at source construction. Secret/CSI replacement alone is insufficient; prove consistent cert/key/trust loading. |

## Decisions requested

Each numbered item requires an architecture-owner answer before the affected
implementation or cutover. References elsewhere describe requirements, not approvals.

1. **Delivery and placement:** (a) namespace separation with isolated Secret delivery,
   requiring database migration or an explicit Console URI change and enforceable
   Traefik serving-Secret isolation; or (b) pinned CSI delivery, retaining placement
   but requiring exact identity and Pod admission proof. Investigate (b) first.
2. **Signer hosting:** a new PKI mount on existing ok-mgmt Vault, sharing its
   administrators, availability and unseal infrastructure; or independent Vault,
   requiring another operated service but separating administration more strongly.
3. **Lifetime and recovery budget:** accept the proposed 7-day leaf/3-day remaining
   renewal headroom, with its exposure window; or select another bounded lifetime
   and headroom, requiring revised outage, alerting and stolen-leaf trade-offs.
4. **Residual authority and trusted principals:** identify the exact deployer and
   administrators, then explicitly accept cnpg-manager's cluster-wide privileged/
   hostPath node-compromise residual for this cutover; or require effective Pod
   Security coverage wherever it can create Pods before proceeding. The latter
   expands prerequisite enforcement and compatibility work. Neither choice removes
   node, control-plane or management-administrator trust.

## Recommended PR sequence and cutover gates

These are future repository changes. No live operation is authorized by this record.
Each live step needs separate approval naming exact revisions, target, window,
rollback and any privileged signer actions.

| Step | Repository change | Required gate |
|:---|:---|:---|
| 0 — proposal | openkubes ADR | Architecture owner resolves the numbered choices, exact URI, custody, trusted principals, admission and residual scope. |
| 1 — trust split | ok-console overlay | Public client/server ConfigMaps initially contain the same existing public CA; no issuer or live trust transition. Render and parse mounts/PEM and unchanged server/leaf references. Rendering is preflight, not runtime proof. |
| 2 — delivery and admission | ok-console and owned platform integration | Implement approved namespace/CSI choice, exact submitter/issuer/token rules, CNPG Pod admission, Pod Security and protected trust writes. Preserve database and ingress behavior without blanket denial. |
| 3 — independent signer | Authorized signer operator and integration | Provision independent CA, exact role/auth and isolated proof. No management or Vault policy/auth/role action is inferred from workload approval. |
| 4 — Console go/no-go | Scoped authority and behavior evidence | All Console gates below pass, including trusted credential homes and verified controller exceptions. Option (a) isolates leaf and equivalent Pod/token takeover; option (b) has no API Secret leaf or foreign CSI identity. Database and ingress renewals pass; record residual-authority decision. |
| 5 — bounded overlap | Separately approved rollout window | Load old+new client trust on producer first, switch Console leaf/delivery second. Verify authenticated requests on every backend, readiness, surge and drain budget. Console server trust remains old-server-only; retain old leaf only within bounded rollback controls. |
| 6 — new-only | Producer trust and client artifacts | Remove old client root from every loaded context and drain old connections. Old-CA/same-URI fails; new-CA/exact-URI succeeds. Observe two scheduled renewals with reload and traffic. Retire old client artifacts only after retention approval; no automatic old-root fallback. |

Keycloak, zot, Console ingress and producer server certificates continue using the
existing ClusterIssuer. Vault keeps its existing namespaced Issuer. Server CA rotation
and key re-copy are outside OK-210, including the ok-mgmt OIDC trust dependency.

## Required authority checks

These are required gate families for implementation, not a claim that a repository
checker exists or has passed. Prefer authenticated complete offline exports for RBAC
analysis; static authority findings need admission and runtime interpretation.

| Gate family | Required coverage and interpretation |
|:---|:---|
| Input integrity | Four complete RBAC Lists for the identified target cluster, UTC timestamp within 24 hours, nonempty resourceVersions, no pagination, duplicates or unresolved references. Authenticate export provenance; labels/timestamps alone do not establish it. Invalid input fails closed. |
| Effective RBAC | Join Roles, ClusterRoles, RoleBindings and ClusterRoleBindings, including RoleBindings referencing ClusterRoles; account for aggregates/stale rules, Users/Groups/service accounts, wildcards, subresources and namespace-less grants. Include a cert-manager writer positive control. |
| Console credentials and workloads | Leaf Secret access, every Secret credential verb in protected namespaces and all trusted-account homes, including kube-system; Pods/controllers, exec/attach/ephemeralcontainers, TokenRequest, external Issuer and named trust ConfigMap mutations. |
| Authority dependencies | Impersonation including userextras subresources, nodes/proxy, protected RBAC writes/bind/escalate, Kubernetes CSR create/approval and signer approve/sign, cert-manager signer/status, admission policies/bindings/webhooks, approver-policy policy writes and protected namespace label changes. Identify administrators of Console controls. |
| Indirect paths | Review CNPG Cluster/Pooler and Ingress controller effects, Pod specs, Pod Security exemptions, trusted-account homes and controller reconciliation. Required controllers remain visible until constrained admission and capability exceptions are proved. |
| Broader retained audit | Record all-namespace Certificate writers and both existing CA Secret targets as server-CA follow-up diagnostics. Their unrelated findings are not global prerequisites for OK-210. |

Distinguish invalid input, authority violations and approved scoped positives.
Prove every gate rejects a corresponding invalid case, then remove each guard in
isolation and observe its assertion fail before restoring it and the positive control.
Do not add cnpg-manager to a blanket trusted set merely to obtain a green result.

An offline RBAC result is not privilege closure. It cannot establish external group
membership, historic credentials, signer-role enforcement, controller effects,
node compromise or loaded TLS contexts. The go/no-go combines scoped findings,
verified exceptions/admission and disposable behavior proof.

## Disposable behavior proof required

After separate authorization, use a uniquely named isolated cluster/context with
synthetic independent CAs and no live key import. Record pinned Kubernetes,
cert-manager 1.17.2, driver, approver and Vault compatibility, flags, images,
securityContexts and quota. Check command flags and security compatibility cheaply
before running. Preserve logs and hashes immediately; guarded cleanup may delete
only resources created by that run.

| Invalid case before positive | Required effect |
|:---|:---|
| Wrong requester, namespace, service account, audience or issuer; absent/null/wrong-type/extra/foreign SANs; wrong EKU, CA or TTL; direct CSR, issuer switch, stale Certificate/CSR | Explicit admission/signing denial with no identity leaf. Show original submitter enforcement and exact-role denial even with valid issuer-auth token. Remove each guard independently, observe assertion failure, then restore. |
| Token Secret/TokenRequest in trusted homes; crafted CNPG Pod/Cluster; foreign CSI mount; issuer-auth service-account Pod; ingress-shim identity request; admission/namespace-label change | Denied authority or execution, plus successful genuine CNPG/ingress reconciliation and Pod Security controls. Static rejection alone is not API enforcement. |
| Old CA with same URI; new CA with wrong URI; no certificate | Authenticated observed-state access denied. New CA with exact URI succeeds. Distinguish authorization denial from transport outage; healthz alone is insufficient. |
| Rotation, outage and rollback | Two scheduled renewals with serial/generation changes, consistent cert/key and traffic without manual restarts. Signer outage alerts and recovery precede expiry. Verify bounded overlap and new-only trust on every replica, without automatic old-root fallback. |

## Proposed follow-up

**Protect shared server CA custody and approval across cluster and management consumers.**

The existing key copies, broad readers and management OIDC dependency need a separate
multi-consumer change. Preserve Console ingress, Keycloak/OIDC, zot/Talos, producer
HTTPS, Vault HTTPS and webhook injection. This work must not restore server-root
trust for Console client authentication.

| Work item | Evidence required |
|:---|:---|
| Inventory ownership and holders | Installed release owners, exact six-reader grants, manual workstation copies, Talos caller, GC/admin/node and ok-mgmt ProviderConfig credential paths. Reconcile both copies and the Vault-side ten-year chain without logging keys. |
| Narrow readers and indirect paths | Own constrained installs removing unnecessary key access for all six accounts and workstation/public-trust consumers. Limit CNPG cluster-wide Pod create/exec/hostPath and token/workload routes. Prove denial alongside reconciliation, failover and rotation; explain remaining administrators. |
| Public-only trust | Move Talos registry and injection consumers to public-only sources. Reviewed PEM updates and expiry alerts need no CA-key read. Prove registry hydration, webhook injection and CA renewal. |
| Approval cutover | Pin compatible approver; disable default approval only after disjoint server-leaf/bootstrap policies and retained-object reconciliation. Reject wrong/extra identities, direct CSR and overlapping-policy bypass; preserve legitimate renewals. |
| Server-CA lifecycle | Exposure response, custody/rotation, backups, expiry alerts, copy consistency and staged public-root overlap. Separately approve management OIDC trust, Keycloak and serving/registry/Vault coordination; workload approval grants no management action. |
| Proof and rollback | Offline gates with guard-removal controls, isolated behavior proof and separately approved live denial/renewal/continuity evidence. Record revisions, rollback, retained credentials/roots and residual authority. |

## Scope of this record

**Applies to:** design and repository declarations only. Live state is as observed
read-only on 2026-10-22, not a current observation.

**Shown in:** this proposed contract, repository-qualified inventory, decision options
and future verification gates. Repository paths establish source existence, not
installed ownership or runtime enforcement.

**Follow-ups:** architecture-owner decisions, authorized ownership/principal inventory,
pinned signer/CSI/admission implementation, controller continuity and renewal/traffic
proof, and separate server-CA work. No live PKI, RBAC or cluster change is made or
authorized by this ADR.
