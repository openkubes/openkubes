# OpenKubes Security Baseline v0.2

**Status:** Discovery working draft; **not** an accepted ADR, implementation instruction, production certification, or publication.  
**Date:** 2026-11-23  
**Basis:** Three read-only review rounds with Claude (architecture), Codex (pinned source/Git review), and Gemini (independent platform challenge); source citations in the companion Findings Register.  
**Scope:** OpenKubes lifecycle security, with *concrete current evidence concentrated on CAPI/BYOH*. vCluster, KubeVirt/VNC and HCP remain separate evaluation profiles.

## 1. Security objective and operating constraints

> **Secure by Contract. Verified by Evidence. Designed for Recovery.**

A security boundary must survive installation, reconciliation, upgrades, rollback, deletion, management handover, backup restoration and disaster recovery. Security measures must **reduce material risk without imposing unnecessary operational complexity or blocking authorized recovery**. Approval, successful API admission, controller execution and independently observed outcome are distinct facts.

**Safety**: unauthorized effects do not occur. **Liveness**: authorized work can complete within defined conditions. **Recoverability**: operators can restore safe operation after specified failures. A design that achieves Safety by making tested recovery impossible is not ready for the affected production profile.

This baseline specifies **desired, testable requirements**. Unless the Evidence Matrix identifies a matching result, an invariant is **proposed**, not demonstrated.

## 2. Trust domains and protected assets

| Trust domain / principal | Lower-trust or higher-trust boundary | Key protected assets / effects |
|---|---|---|
| BYOH host agent, often remote/customer-operated | Host is lower-trust than the management plane | Agent client certificate, bootstrap payloads, pending actions, host placement |
| BYOH management controller SA | High-value platform identity; distinct from hosts | Management-cluster Secrets; bootstrap/installer content; CSR approvals; host assignment |
| CAPI/KCP/MHC controllers | Authorized Kubernetes reconcilers, **not independent policy authority** | Machine/ByoMachine mutations, upgrade fallback, replacement and deletion |
| Policy/approval/operation executor | Protected mutation-authority domain | Grants, claims, exact transition and protected human approval |
| Old and new management planes | Must never both hold effective write authority | Host operations, workload API, BMC/Redfish, cloud-provider APIs, SSH paths |
| Recovery and external evidence authority | Must withstand relevant restore/failure domain | Revocations, consumed grants, ownership epochs, historical receipts |
| Hosted/external AI agents and gateways | Untrusted proposals and tools; no operational authority | Read-only diagnostics, bounded tool access; no direct mutation grant |

**Four operational models:** (a) CAPI/BYOH; (b) vCluster; (c) KubeVirt-backed Virtual Nested Clusters; (d) Hosted Control Planes. A common contract does **not** mean equivalent tenant isolation. No production-ready security equivalence is claimed.

## 3. Normative candidate requirements (independent of implementation choice)

The `B-*` IDs below are **working traceability IDs**, not replacements for existing ADR/SEC/INV identifiers. A requirement can be accepted as a security objective while its enforcement and maturity remain open.

### 3.1 Platform baseline

| ID | Requirement / falsifiable condition | Related working SEC IDs |
|---|---|---|
| **B-01** | Every principal has an identifiable scope; a host credential grants no unrelated host, namespace, cluster or management-plane authority. | SEC-01, SEC-11 |
| **B-02** | Upstream RBAC and installers are reviewed under OpenKubes' threat model. Default, fresh, reinstall, upgrade, rollback and restore paths converge to **the same restricted authorization**; no transient broadening is silently tolerated. | SEC-12, SEC-13 |
| **B-03** | Host enrollment binds independent inventory ownership, one approved host identity, the expected CSR/key and placement eligibility. A self-asserted hostname, selector label or status does not create privilege. | SEC-01, SEC-11 |
| **B-04** | Privileged host assignment is operator-controlled. A host may report operational state, but cannot self-select a control-plane or other elevated Machine assignment. | SEC-02, SEC-11 |
| **B-05** | Credential delivery, authentication, authorization and **effective revocation** are separate controls; suspension survives reconciliation and same-name reenrollment. Previously delivered payloads, workload bootstrap tokens and queued host actions have distinct fencing rules. | SEC-01, SEC-04, SEC-11 |
| **B-06** | An agent's self-reported reset does not alone prove host sanitization. (a) A host with independently verified reset or trusted reprovisioning MAY be eligible for reassignment after old authority and material are fenced; (b) if reset cannot be independently verified (including unreachable/customer-operated hosts), the existing assignment remains untrusted and the host MUST NOT return to the assignable pool on agent testimony. Any later enrollment requires a new authorized identity generation and an explicit decision about residual material and host eligibility. | SEC-04, SEC-09, SEC-13 |
| **B-07** | A compromised authorized controller remains bounded by structural admission and its own least-privilege identity. Controller credentials, CSR issuance rights and Secret writes are independently audited and scoped. | SEC-02, SEC-03, SEC-12 |
| **B-08** | A protected Machine's creation/deletion/replacement, identity change and unauthorized spec/status transition are denied at the relevant enforcement points, including CAPI fallback and alternate API routes. Upgrade authorization never implicitly authorizes replacement. | SEC-02, SEC-04, SEC-05, SEC-09 |
| **B-09** | Safety constraints and authorization of an operation are distinct. High-consequence transitions require independently issued, target/transition-bound authority; grants are scoped, revocable, replay-resistant and side-effect-free to inspect in admission. An in-place version change is **not automatically safe, authorized or reversible**. | SEC-02, SEC-03, SEC-04, SEC-14 |
| **B-10** | Emergency repair is explicitly authorized, scoped and auditable. Fail-closed enforcement must have a tested recovery path reachable under the documented failure. Neither a privileged RBAC identity nor a mutable bypass label suffices alone. | SEC-05, SEC-09, SEC-13 |
| **B-11** | Recovery does not revive old authority: post-snapshot revocations, consumed grants, revoked host generations and superseded management ownership must be reconciled against the authoritative monotonic facts required by B-17 **before non-recovery traffic and reconcilers are enabled**; alternatively affected credentials/grants must be invalidated and recreated. | SEC-04, SEC-07, SEC-10, SEC-13 |
| **B-12** | Handover admits **one effective writer** at all actual write boundaries (workload API, host/agent execution, BMC, provider, SSH). An offline/partitioned target remains quarantined until its old authority is demonstrably fenced; cooperative pause alone is insufficient. | SEC-07, SEC-13 |
| **B-13** | Artifact, admission-policy and enforcement-administrator integrity are protected. Routine controllers/installers cannot remove their own constraints or silently expand permissions. | SEC-08, SEC-12 |
| **B-14** | Security assurance is tied to exact implementation versions, manifests, environment and negative tests; material dependency changes trigger targeted evidence revalidation. Historical evidence and runtime health are separately represented. | SEC-08, SEC-10 |
| **B-15** | Model-specific profiles may strengthen or substantiate common controls, never silently waive them. Controls for models without proof remain explicitly unvalidated. | SEC-06, SEC-10 |
| **B-16** | Agentic operations cannot mint their own authority. HITL/HOTL changes oversight, not independent enforcement; sensitive agentic write enablement requires separately proven identity, revocation and evidence integrity. | SEC-03, SEC-14 |
| **B-17** | **Monotonic Security Authority:** Security facts including revoked host identities and grants, consumed single-use approvals, retired enrollment generations and superseded management ownership MUST be durably established outside the protected cluster's backup/restore domain (or in an independently verified rollback-resistant authority) no later than the corresponding in-cluster security transition is committed. A restored management plane MUST obtain and enforce current facts before enabling non-recovery API exposure and reconcilers. If freshness/completeness cannot be demonstrated, affected authority MUST remain quarantined or be independently invalidated and reissued. Exact storage and consistency mechanism remain open. | SEC-04, SEC-07, SEC-10, SEC-13 |
| **B-18** | **Secret-equivalent Backup Protection:** etcd, Velero and other state backups containing Secrets, bootstrap material or authorization records MUST be protected as high-sensitivity assets: encryption of relevant API resources at rest, independently protected backup-artifact encryption, restricted readers and restoration credentials, key recovery, transport protection and documented retention/destruction. Encryption at rest of selected Kubernetes API resources alone does not imply an entire etcd snapshot is encrypted. | SEC-08, SEC-10, SEC-13 |
| **B-19** | **Security-Control Detection:** Production profiles MUST detect and alert on disabled, missing, degraded or unexpectedly changed enforcement components and on selected cross-boundary denied access attempts, without relying solely on the compromised control to report its own health. Alert routing and evidence retention MUST be tested under the relevant failure modes. | SEC-05, SEC-10, SEC-13 |

### 3.2 BYOH provisional security contract

**BYOH-01 Host Secret scope:** no effective `byoh:hosts` cluster-wide `secrets:get` or equivalent alternate binding. Every host-specific Secret grant uses a **specific authenticated username** and `get` on exactly named required Secrets through `resourceNames` in the appropriate namespace; host `list` and `watch` on Secrets are **denied entirely**. Kubernetes RBAC may constrain `list`/`watch` with `resourceNames` only when clients supply a matching `metadata.name` field selector; OpenKubes does not rely on that pattern for host Secret access. Check **both own-access positive cases and peer/cluster/management negative cases**.

**BYOH-02 Safe installer:** remove the permissive host bindings from the published provider bundle; check all installation modes before admission is available. Admission can reject *new* writes but cannot remove previously created RBAC; owning reconciliation/drift repair and pre-activation audit must address existing objects. Avoid an installer repeatedly fighting a deny policy.

**BYOH-03 Enrollment:** keep manual, inventory-bound CSR approval while the in-cluster automatic approver checks CSR shape but not approved host ownership. Prove exact CSR UID/key, requester/token binding and race safety before enabling unattended admission.

**BYOH-04 Controller trust:** explicitly account for management-wide Secret reads/writes, `kube-system` token-handling needs, CSR signer/approval rights, and wildcard infrastructure access. Reduce by demonstrated reconciliation requirements; **do not assume** controller-managed RoleBinding creation is privilege-free under Kubernetes RBAC escalation rules.

**BYOH-05 Identity generation:** host/node names are operational identifiers; authenticated enrollment username must be non-reused or previous certificate identity must remain unauthorized until that certificate expires. Current agent username is based on namespace+hostname; **object UID metadata alone does not change X.509 CN**. Document the no-agent-change quarantine alternative and its recovery impact.

**BYOH-06 Revocation/assignment:** a durable suspension/assignment record must drive every grant writer. Revocation must remain effective across controller restart, new ByoMachine object, same Secret name and etcd restore. A `Ready` condition alone cannot stand in for an independently verified reset.

### 3.3 Operation and recovery profiles — do not conflate

| Profile/gate | Must demonstrate | Current characterization |
|---|---|---|
| **G-BYOH-ENROLL** | Two real host identities: own named reads, peer/cross-namespace/management/list/watch denials; inventory-bound CSR; safe placement; false-reset denial; durable revocation after reinstall/reconcile/restore | **OPEN**; default bundle exposed in reviewed source, lab hardening partial |
| **G-UPGRADE** | Actual protected BYOH host/CP upgrade with unchanged required resource UIDs, declined/failed fallback denial, exact operation authority, observed kubelet convergence and backup/recovery | **OPEN**; CAPD no-op host update is not protected real-BYOH proof |
| **G-DR** | Cold restore with old-plane effective-write denial, B-17 facts verified reachable/current (or all affected authority independently invalidated), no revoked authority resurrected, offline target quarantine, provider/host-side fencing, protected backup artifacts, accepted restore drill | **OPEN**; accepted CAPI ADRs and partial CLI/Lab enforcement are not integrated proof |
| **G-AGENTIC-WRITE** | Agent cannot directly mutate; approved exact transition, binding/replay checks, point-of-use revocation, independent tamper-evident outcome evidence | **OPEN**; proposals/partial foundations only |
| **G-MODEL-{VCLUSTER,VNC,HCP}** | Distinct isolation, blast-radius, lifecycle/recovery and negative E2E evidence per model | **OPEN**; no blanket production endorsement |

## 4. Explicit engineering choices NOT yet accepted

1. **CEL vs compiled webhook.** VAP is preferred for request-local rules; identity/ownership joins, live cross-object correlations, checksum-to-version checks, and grant-state validation may require a protected webhook or other gate. CEL alone cannot read arbitrary objects or atomically consume a grant. `ValidatingAdmissionPolicy` cannot protect administration of its own VAP/Binding objects: segregate policy administration via RBAC and test it.
2. **Stateful grants.** Choose when an independently authorized durable operation is required based on action impact and threat model. Do **not** classify a forward in-place upgrade as harmless. A single CAS claim does not render multiple controller/host effects atomic.
3. **Upgrade reversal.** Unapproved downgrade is denied. A recovery/downgrade needs a separately specified and verified compatibility/safety procedure, not a categorical promise that every downgraded cluster will work.
4. **Credentials.** Unique per-enrollment X.509 usernames, bounded ServiceAccount tokens or quarantine until old cert expiry are options. Agent protocol changes and token/certificate renewal availability require a spike; standard Kubernetes client X.509 authentication does not provide general CRL/OCSP revocation.
5. **Grant/revocation store.** B-17 requires an independently rollback-resistant source of monotonic security facts, or verified invalidation prior to activation. Current authoritative security facts must survive or be safely reconstructed after restore. Reuse of an existing independent authority vs a new minimal store remains open; no automatic assumption that an etcd-resident grant plus CEL expiry can solve outage/restore semantics.
6. **Handover.** Start with **cold, operator-authorized**, independently verifiable fencing. External CAS epochs are an option only when enforced at effective write boundaries; an epoch checked solely by cooperating controllers is not a fence.
7. **Break-glass.** Offline signer, short-lived break-glass identity, explicit repair grant and independently managed policy are candidate mechanisms, not presently verified approvals. Avoid treating a group claim or an annotation alone as single-use operation authorization.

## 5. Security evidence and maturity rules

**Evidence tuple (minimum):** `{repository, Git SHA, rendered manifest digest, dependency versions (CAPI/Kubernetes/BYOH), cluster/profile, test ID, identity, operation, expected result, observed result, timestamp, run artifact, reviewer}`. Distinguish **design**, **committed implementation**, **unit/envtest**, **isolated E2E/CAPD**, **real BYOH E2E**, **production-approved named profile**. A passing test is not a universal security property.

Maturity is **scoped**: one passing RBAC denial in a management cluster does not prove host reset, workload token revocation, protected upgrade, or DR. Changes to controller code, default bundle, Kubernetes/CAPI version or policy routing must trigger impact-based revalidation for **every affected gate**; evidence remains historical and is not rewritten. See T-32 and the global gate-invalidation policy in the Evidence Matrix.

## 6. Requirements before accepting the eventual normative security ADR

- Reconcile this draft against **accepted** ADR-CAPI-001–007 and existing Platform ADRs; document references and overlaps, no duplicate authorization system by default. The accompanying `04-capi-adr-crosswalk.md` records the completed read-only CAPI ADR comparison and the remaining implementation questions.
- Classify all findings in the companion register as **source-confirmed / independently reproduced / design risk / unverified**, with attack preconditions and scoped impact. No invented disclosure or complete production proof.
- Maintain an explicit requirement-to-control-to-negative-test map; an unimplemented requirement remains an accepted *goal at most*, not an enforced guarantee.
- Preserve all open trade-offs (credential model, controller trust-domain size, external authority design, upgrade grants, edge quorum/fencing) until specific experiments or acceptance evidence are available.

**No implementation or release authorized by this document.**
