# ADR-Platform-042: Cross-Cluster Enterprise Workspace Model and Governance

**Date:** 2026-10-28  
**Status:** Proposed  
**Extends:** ADR-Platform-001 (Contracts not Components)  
**Related:** ADR-Platform-006 (Management Cluster), ADR-Platform-011 (GitOps), ADR-Platform-013 (Workload Cluster Registration), ADR-Platform-015 (Agentic AI), ADR-Platform-017 (Constraint Envelopes), ADR-Platform-030 (Control Plane Execution Model), ADR-Platform-034 (Authorized Desired-State Transitions), ADR-Platform-037 (Console Authentication and Identity Federation), ADR-Platform-039 (Developer Workspace Contract)  
**Decision owner:** OpenKubes Architecture  
**Scope:** Architecture contract proposal; no production implementation or authorization to roll out

---

## Context

OpenKubes requires an organizational and governance boundary spanning multiple registered Kubernetes clusters. Kubernetes Namespaces and cluster-local grouping are insufficient as stable, cross-cluster organizational identities. Enterprise teams require consistent membership, constrained access, policy intent, audit trails, and sovereignty requirements across independently operated clusters.

OpenKubes already defines a separate **Developer Workspace Contract** in ADR-Platform-039: a bounded execution environment for a developer and/or coding agent, with source, runtime, storage, credentials, capabilities, and lifecycle semantics. Its first reference implementation maps a DeveloperWorkspace to a dedicated Namespace and uses a Crossplane-based reconciler. This ADR MUST NOT reinterpret or replace that contract.

The proposed Enterprise Workspace is instead a **logical governance scope**, not an execution environment, Namespace, cluster, or implicit Kubernetes security principal.

## Problem statement

How can OpenKubes manage tenant-scoped, cluster-independent team governance and explicit Namespace assignments without (1) introducing a second identity provider, (2) undermining existing GitOps ownership, (3) granting ambient Kubernetes permissions, (4) weakening ADR-039 DeveloperWorkspace isolation, or (5) making healthy workload clusters operationally dependent on management-plane availability?

## Decision drivers

- Cluster-independent tenant and workspace identities
- Explicit, independently verifiable Namespace-to-Workspace ownership
- Strict tenant isolation and server-side authorization
- Reuse of OIDC federation, cluster registration, Kubernetes RBAC, policy enforcement, GitOps, and evidence mechanisms
- Least-privilege target-cluster enforcement and fail-closed new privilege grants
- Declarative source-of-truth clarity; deterministic reconciliation and conflict detection
- Workload continuity during management-plane outages
- Compatibility with existing DeveloperWorkspace instances and ADR-039 invariants
- Sovereignty / data-residency constraints that can be verified, not merely displayed
- Incremental rollout and backwards compatibility

## Considered alternatives

1. **Rancher-style cluster-local Project only.** Simple but cannot express the desired cross-cluster governance identity; not selected as the central domain abstraction.
2. **Reinterpret DeveloperWorkspace as an Enterprise Workspace.** Rejected: conflates long-lived organizational governance with bounded runtime lifecycle and breaks ADR-039 semantics.
3. **Namespace labels alone as the source of Workspace membership.** Rejected: mutable labels are not an authoritative identity or authorization boundary.
4. **External IAM groups only, without a Workspace domain object.** Useful identity input but insufficient for namespace binding, sovereignty constraints, reconciliation state, and evidence.
5. **Independent custom IAM and permissions database.** Rejected as default: duplication and risk of inconsistent authorization.
6. **Management-plane Enterprise Workspace + explicit bindings + cluster-native enforcement.** Proposed; balances a portable contract and verifiable execution boundaries.

## Proposed decision

**D-042-1 — Separate domains.** Introduce an enterprise governance domain named **Enterprise Workspace**. It owns organizational grouping and governance intent, not execution environments. Its future public API kind is **undecided** (`EnterpriseWorkspace` versus `Workspace`); the architecture spike MUST check existing API-group collisions before choosing. A `DeveloperWorkspace` continues to mean only the ADR-039 bounded execution environment.

**D-042-2 — Management-plane ownership.** Tenant, Enterprise Workspace, and Namespace-binding desired state are defined within the OpenKubes management plane, compatible with GitOps. The selected persistence mechanism (CRDs or equivalent) remains subject to spike evidence. The management plane does not replace the Kubernetes API authorization of workload clusters.

**D-042-3 — Independent cluster lifecycle.** Clusters are registered and managed independently of Enterprise Workspaces. A binding references an existing registered cluster and a specific Namespace. Deleting a Workspace MUST NOT silently delete its clusters or unrelated workloads.

**D-042-4 — Explicit binding and exclusive ownership.** For the MVP, one concrete Namespace instance on one registered cluster may be assigned to **at most one Enterprise Workspace**. Bindings include stable cluster identity and Kubernetes Namespace UID; a same-name Namespace recreated with a new UID MUST NOT inherit authorization or ownership automatically. A binding that cannot be verified remains non-effective.

**D-042-5 — Separate membership from authority.** Workspace membership is not equivalent to Kubernetes API access. Every privileged operation requires independently evaluated server-side authorization, tenant and binding checks, applicable policy checks, and enforcement at the target cluster. A Workspace role MUST NOT silently imply `cluster-admin`, wildcard RBAC, or unrestricted credentials.

**D-042-6 — No competing reconciliation authority.** The Workspace controller manages only explicitly owned resources/contracts. Existing GitOps-owned resources, the cluster registration contract, and ADR-039 DeveloperWorkspace resources cannot be silently adopted or overwritten. Conflict or ambiguous ownership MUST produce a visible condition and stop privileged reconciliation.

**D-042-7 — Separate execution authority.** Agentic Operations and DeveloperWorkspace agents may inspect or propose changes inside explicit scopes, but a Workspace association confers no merge, release, deploy, approval, or cluster-administrator authority. Any future execution uses an independently authorized, constrained executor and evidence-backed verification.

**D-042-8 — Outage behavior.** Management-plane loss MUST NOT automatically terminate running workload applications. Newly requested grants and privileged changes fail closed when required authorization or binding freshness cannot be validated. Revocation latency and stale cached permission behavior require an explicit time-bound, risk-reviewed design before GA.

**D-042-9 — Evidence.** Workspace and binding modifications, policy decisions, permission materialization, reconciliation drift/conflicts, and revocation outcomes are attributable and auditable. Evidence must distinguish desired intent, observed enforcement state, and historical outcomes.

**D-042-10 — Compatibility.** Enterprise Workspace integration with DeveloperWorkspace is optional and additive; pre-existing DeveloperWorkspace instances continue to function without an Enterprise Workspace binding.

## Data / resource model (candidate, not an accepted CRD schema)

- **Tenant:** stable tenant ID, members/federated identity references, governance constraints, permitted trust domains, lifecycle/status.
- **Enterprise Workspace:** stable Workspace ID, parent Tenant ID, membership/role references, approved registered-cluster scope, policy/sovereignty constraints, status.
- **WorkspaceNamespaceBinding:** immutable logical binding ID, Tenant/Workspace references, immutable registered-cluster identity, Namespace name and observed UID, verification and enforcement status.
- **Cluster registration:** reused from existing OpenKubes cluster registration contract; the Workspace does not own cluster lifecycle.
- **DeveloperWorkspace:** unchanged ADR-039 resource, with separate developerWorkspace ID and scoped execution lifecycle.
- **DeveloperWorkspaceAssignment (optional future adapter):** an explicit reference linking an independently identified DeveloperWorkspace to an Enterprise Workspace, validated against the actual cluster/Namespace binding. It is NOT a rename or mutation of `DeveloperWorkspace.spec.workspaceID`.

Suggested identity tuple for target verification: `(registeredClusterUID, namespaceUID)`. Human-friendly names are display and lookup attributes, not the sole authorization key. The spike must also define creation-before-UID-observation semantics without accidental permission inheritance.

### Non-normative example (concept only)

```yaml
apiVersion: governance.openkubes.io/v1alpha1
kind: WorkspaceNamespaceBinding
metadata:
  name: payments-prod-binding
spec:
  enterpriseWorkspaceRef:
    name: payments
  clusterRef:
    name: prod
  namespaceRef:
    name: payments-prod
    uid: "<observed-namespace-uid>"
```

The API group, resource kind, field names, and binding lifecycle above are illustrative and MUST NOT be treated as implemented.

## Authorization and tenant isolation

1. Authenticate human or workload subjects via existing approved identity mechanisms (including the federated Console identity contract, where applicable).
2. Resolve subject, tenant, Workspace role, and target to stable identities on a trusted server.
3. Verify the Workspace belongs to the tenant, the cluster is permitted, the binding is effective and UID-matched, and sovereignty constraints are satisfied.
4. Evaluate explicit permissions, policies, and (where required) human approval separately from identity and membership.
5. Reconcile or execute using least-privileged credentials on the target cluster. Workspace membership alone never provides cluster API credentials.
6. Deny privilege escalation across tenants, ambiguous ownership, expired approvals, UID mismatches, missing policies, stale binding proofs, and conflicting resource managers.
7. Audit both decisions and observed outcomes, including policy-denied actions.

A CRD, Kubernetes label, Namespace, or Console switcher is **not by itself** a security boundary. Provider/controller service accounts may hold elevated authority internally only under separately reviewed, tightly constrained operator admission and reconciliation rules; such authority is never delegated to Workspace members or agents.

## Reconciliation architecture

```text
OIDC / existing Identity Federation
                |
                v
OpenKubes Management Plane
  Tenant + Enterprise Workspace desired state <--- GitOps source of truth
                |
  Workspace Controller / Authorizer / Evidence
                |
  Cluster Registry + immutable Namespace-binding validation
         +------+------+
         |             |
         v             v
  Workload Cluster A   Workload Cluster B
  Namespace UID A      Namespace UID B
  target RBAC/policy   target RBAC/policy
  observed status      observed status
```

The controller performs validate -> authorize relevant transition -> resolve registered cluster -> verify Namespace identity -> detect ownership conflicts -> reconcile approved owned resources -> independently read back target state -> record status/evidence. Desired state and observed state are separate. The spike must determine how GitOps-owned RBAC/policies are generated or referenced without two writers competing for the same object.

## Failure modes and expected behavior

| Scenario | Required outcome |
| --- | --- |
| Management cluster unavailable | Workloads continue; no unverified new privileged grant |
| Target cluster unreachable | Binding reports Unknown/Degraded; no unverified success |
| Namespace deleted and recreated | Old UID binding becomes invalid; no silent reattachment |
| Two Workspaces claim the same Namespace | Conflict; neither new privileged claim becomes effective |
| Tenant / cluster identity mismatch | Reject and audit |
| GitOps and controller both claim same object | Ownership conflict; do not overwrite |
| Workspace removed | Revoke managed access through a verified, idempotent process; workloads not silently deleted |
| Revocation while target is offline | Record pending revocation and risk; do not claim success until verified |
| Credential or policy materialization fails | Fail closed for new access and surface explicit condition |
| DeveloperWorkspace is unassigned | Existing ADR-039 behavior remains unchanged |
| DeveloperWorkspace assignment removed | No implicit deletion of DeveloperWorkspace; remove optional governance-derived entitlements according to reviewed lifecycle |

## Developer Workspace compatibility — normative invariants

- **INV-042-1:** `DeveloperWorkspace` retains its ADR-039 meaning, API boundary, identity, runtime and lifecycle semantics.
- **INV-042-2:** `DeveloperWorkspace.spec.workspaceID` MUST NOT become an Enterprise Workspace ID.
- **INV-042-3:** Existing DeveloperWorkspaces MUST operate without Enterprise Workspace assignments, without forced migration.
- **INV-042-4:** An Enterprise Workspace assignment MUST NOT automatically expand source, network, MCP/tool, credentials, Kubernetes API, filesystem, or compute capabilities declared for the DeveloperWorkspace.
- **INV-042-5:** ADR-039 default `kubernetes.access = none` and no ambient cluster authority remain effective.
- **INV-042-6:** No Enterprise Workspace controller may take ownership of, mutate, or delete ADR-039-managed Namespace/runtime resources without an explicit, separately reviewed contract.
- **INV-042-7:** DeveloperWorkspace task success never implies merge, release, deployment, or desired-state transition authorization.
- **INV-042-8:** DeveloperWorkspace evidence export and cleanup ordering remain independently enforced by its lifecycle contract.
- **INV-042-9:** Cross-tenant binding or assignment is rejected, even when display names coincide.
- **INV-042-10:** All existing ADR-039 invariants INV-039-1 through INV-039-10 remain in force; conflicts require a new explicit ADR, not an implicit reinterpretation.

## Security, sovereignty, and compliance

Tenant boundaries are explicit logical and authorization boundaries, **not automatically hardened hostile-multitenancy isolation**. Network, storage, node, CNI, secret, and runtime isolation claims require separate profile-specific evidence. Sovereignty claims must be based on authoritative cluster properties, allowed locations/regions, identity/secret storage, and data movement paths. An Enterprise Workspace label alone does not establish data residency or regulatory compliance.

Approval and evidence are not substitutes for target-cluster enforcement. Audit records should avoid leaking tenant secrets or sensitive payloads.

## Migration / rollout strategy

1. Inventory relevant ADRs and current implementations (especially 013, 017, 037, 039); validate naming/API-group collisions and controller ownership.
2. Specify immutable IDs, binding state machine, conflicts, source-of-truth, target RBAC enforcement, and revocation semantics.
3. Demonstrate a minimal non-production proof with one Tenant, two Enterprise Workspaces, and two registered disposable clusters; prove cross-cluster visibility without broad authorization.
4. Add explicit, least-privileged target enforcement and negative tests for UID reuse, cross-tenant links, duplicate claims, offline cluster, revocation, and GitOps conflict.
5. Introduce Console switcher/overview only after server-side authorization is independently verifiable.
6. Evaluate optional DeveloperWorkspace assignment in a separate compatibility gate; never require conversion of existing instances.
7. Evaluate Workspace-scoped Agentic Operations only after enforcement/approval/evidence gates pass.

No work for this ADR is required in the W-JAX demonstration on **2026-11-03**. No production rollout is authorized by Proposed status.

## Consequences

**Benefits:** stable cross-cluster enterprise organization; explicit governance and policy contracts; auditable permissions; clearer sovereignty constraints; reusable basis for future Workspace-scoped Agentic Operations without coupling to a particular agent implementation.

**Costs and tradeoffs:** new domain/controller and reconciliation complexity; stale membership/revocation risks; identity and cluster mapping; conflict management with GitOps and existing controllers; increased security-testing burden; careful naming and UX differentiation from DeveloperWorkspace.

## Open questions / blocking spike tasks

1. Which API kind and group avoids ambiguity with `DeveloperWorkspace` and its existing API group?
2. Is the central persisted source a management-cluster CRD, a GitOps-defined contract with a CRD projection, or another existing OpenKubes domain mechanism?
3. Which components currently implement cluster registration, OIDC roles, policy enforcement and evidence, and what can be reused without dual ownership?
4. What is the authoritative tenant membership / role mapping, including group revocation and IdP outages?
5. What is the exact Namespace binding admission and UID-rebinding lifecycle?
6. How are RBAC and policy objects owned and reconciled when GitOps also manages target clusters?
7. What bounded revocation/authorization freshness guarantees are required under network partitions?
8. How are workspace-scoped resource quotas and budgets aggregated across clusters without misrepresenting enforcement?
9. How do Console Workspace switching and backend authorization remain explicitly separated?
10. Which explicit compatibility tests prove no ADR-039 regression?
11. What runtime and platform evidence supports sovereignty constraints?

## Acceptance gates for this ADR

The decision stays **Proposed** until an architecture spike provides: inventory of existing components and ADR conflicts; candidate API and state machine; threat model; source-of-truth/ownership matrix; authorization and revocation design; compatibility test plan and results; negative isolation/failure tests; and reviewed incremental MVP estimate. Acceptance requires architecture review and explicit approval; a passing prototype alone is insufficient.

## Non-goals

- Replacing ADR-039 DeveloperWorkspace or its Crossplane reference implementation
- Introducing a custom password store or parallel identity provider
- Automatic Namespace/workload migration or deletion
- Fully autonomous production agent remediation
- Granting cluster-admin rights to AI agents
- Production-grade cost accounting or global quotas in the first MVP
- Altering the November 2026 W-JAX demo scope
