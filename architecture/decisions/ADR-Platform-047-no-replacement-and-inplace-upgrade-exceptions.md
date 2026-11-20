# ADR-Platform-047: No-Replacement Protection and In-Place Upgrade Authorization

**Date:** 2026-11-20  
**Status:** Proposed  
**Scope:** CAPI-managed infrastructure lifecycle, initially BYOH clusters declared `InPlaceOnly`  
**CAPI reference:** v1.14.x (exact provider/runtime compatibility remains subject to validation)

**Extends:** ADR-Platform-030  
**Constrained by:** ADR-Platform-034  
**Related:** ADR-Platform-017, ADR-Platform-023, ADR-Platform-035, ADR-Platform-048

---

## Context

Cluster API (CAPI) reconciles Machines and control planes declaratively. Depending on the infrastructure provider, control-plane implementation, rollout strategy, capacity and failure path, an upgrade or remediation may result in Machine replacement.

For dedicated bare-metal BYOH environments, replacement is not a safe implicit fallback. A physical host may be a scarce, identity-bearing resource with local state, attached devices, manually managed networking, or workload responsibilities that cannot be transparently recreated elsewhere. In a no-spare topology, a replacement request can be impossible to satisfy or can cause destructive lifecycle behavior.

OpenKubes therefore needs a policy boundary that distinguishes an in-place change to an existing Machine from provisioning, replacement, remediation, and decommissioning. The authorization to upgrade an existing Machine must never be interpreted as authorization to replace it.

This ADR defines the safety and authorization contract. It does not claim that CAPI v1.14.x or the current BYOH provider already implements the complete in-place execution path.

## Decision

### 1. Permanent no-replacement baseline

For a cluster whose effective lifecycle strategy is `InPlaceOnly`:

- The existing Machine and its infrastructure/host identity are preserved throughout an authorized in-place upgrade.
- Machine CREATE and DELETE are denied unless a separate, explicit lifecycle/replacement authorization is defined and accepted by the applicable policy.
- An in-place upgrade authorization does not authorize provisioning, replacement, remediation by replacement, or decommissioning.
- Unsupported, ambiguous, timed-out, or failed in-place operations stop without silently falling back to replacement.
- Disabling, removing, or bypassing an enforcement component is not an authorization to replace a Machine.

The baseline is deny-by-default for protected lifecycle operations. A safety mechanism must not infer protection or authorization solely from request-supplied Machine labels, annotations, owner references, status, or controller progress fields.

### 2. Independent authorization for an in-place transition

An in-place version change is a separately authorized transition over an existing Machine. The policy enforcement point verifies authorization; it does not mint authorization.

The authorization must be issued through a trusted Policy Authority / approval path and bind at least:

- cluster namespace, name and immutable Cluster UID;
- Machine namespace, name and immutable Machine UID;
- the exact allowed transition and field set (initially Kubernetes version and only explicitly enumerated correlated fields);
- the approved starting state (resourceVersion or a canonical digest of the relevant spec subset);
- target version and request digest;
- audience, validity window, permitted-use count and durable transition identity.

A replacement Machine has a different UID and cannot inherit an authorization bound to the original Machine. A recreated Cluster has a different UID and invalidates the old authorization.

The precise grant transport, signature/verification mechanism and canonical digest schema remain open implementation decisions constrained by ADR-034.

### 3. Lifecycle paths are disjoint

The authorization model has separate paths:

- **Machine CREATE:** no in-place grant is accepted as input; replacement/provisioning requires its own authorization.
- **Machine DELETE:** no in-place grant is accepted as input; deletion requires its own authorization.
- **Main-resource UPDATE:** only the exact, enumerated in-place transition may be considered, after independent authorization and starting-state verification.
- **Status-subresource UPDATE:** separately authorized for the narrowly scoped controller identity and explicitly permitted status fields. Status permission never implies spec permission, and an in-place grant never implies arbitrary status permission.

All unrecognized operations, resources, subresources and fields fail closed for protected scope.

### 4. Atomic single-use claim; read-only admission

A Kubernetes ValidatingWebhook is read-only, idempotent, retry-safe and dry-run-safe. It must not consume a grant or mutate a claim ledger during admission.

Single-use authorization is claimed out of band by the trusted Policy Authority / Contract Executor using an atomic compare-and-set operation consistent with ADR-034. Admission verifies the resulting claim and exact transition binding without writing state.

Retries of the same request must produce the same decision. A different transition, changed starting state, expired grant, mismatched audience, or replay must fail closed. Recovery after claim succeeds but the desired-state write or execution outcome is uncertain must use the same transition identity and bounded idempotent recovery; it must never repurpose the grant for a different operation.

### 5. Trusted scope and namespace isolation

Protection authority comes from a trusted registry/policy source bound to the live CAPI Cluster UID, not from Machine metadata.

Namespace selectors are routing mechanisms, not protection authority. If selector labels are used, their mutation and removal must themselves be protected by an independently enforced policy. Newly created or unlabeled namespaces must not silently escape protection.

The initial design assumes dedicated namespaces for protected BYOH clusters. A cluster-wide Machine webhook combined with a registry that treats unknown namespaces as unverified can deny unrelated Machine operations; therefore webhook matching and namespace-selection semantics must be designed and tested together before enablement.

### 6. CAPI integration and fallback behavior

The guard is an independent safety backstop, not an in-place executor. CAPI controller behavior, runtime-extension behavior, provider behavior and MachineHealthCheck remediation must be assessed separately.

For `InPlaceOnly`, a CAPI fallback from an unsuccessful in-place attempt to scale-down/replacement must be denied. MachineHealthCheck remediation that would delete and recreate a protected Machine is likewise not implicitly permitted; its operational policy must be explicit.

The exact fields mutated by the selected CAPI/Kubeadm/BYOH in-place path, status writes, runtime-extension behavior and fallback sequence must be confirmed against the exact dependency versions and an executable compatibility test before a grant schema is finalized.

### 7. Enforcement and deployment requirements

Before operational enablement, the implementation must provide and test:

- Machine ValidatingWebhookConfiguration rules with safe namespace matching;
- explicit `failurePolicy: Fail`, supported review versions, correct side-effect declaration and dry-run behavior;
- Service, Deployment, TLS certificate/CA wiring and registry configuration mount;
- least-privilege RBAC for live Cluster identity lookup;
- protection against selector-label mutation and namespace escape;
- availability, rollout, recovery and controlled-disable procedures;
- end-to-end evidence that unauthorized CREATE/DELETE/UPDATE paths are denied and permitted in-place transitions preserve identities.

A standalone image or registered in-process handler without the corresponding API-server webhook configuration is not an operationally enforced guard.

## Invariants

- **INV-047-1 — No implicit replacement:** an InPlaceOnly upgrade never authorizes Machine replacement.
- **INV-047-2 — Independent authority:** the guard verifies but never creates an in-place authorization.
- **INV-047-3 — Dual identity binding:** authorization is bound to the exact Cluster UID and Machine UID.
- **INV-047-4 — Lifecycle separation:** CREATE and DELETE never consume an in-place grant.
- **INV-047-5 — Exact transition:** only explicitly enumerated fields and the approved starting state may change.
- **INV-047-6 — Read-only admission:** admission is idempotent, side-effect-free and dry-run-safe; claim is atomic and out of band.
- **INV-047-7 — Disjoint status authority:** status-subresource permission and spec-transition permission are separate.
- **INV-047-8 — Fail closed:** unknown scope, stale identity, malformed request, unavailable trust source or uncertain authorization denies protected operations.
- **INV-047-9 — Non-bypassable scope:** selector labels are not protection authority and cannot be removed to escape protection.
- **INV-047-10 — No fallback escape:** CAPI fallback and MHC replacement paths remain denied under InPlaceOnly.
- **INV-047-11 — Enforcement is explicit:** disabling or bypassing the guard is never a replacement authorization.

## Consequences

Positive consequences:

- Bare-metal identity preservation becomes an explicit lifecycle contract.
- Upgrade authority cannot be confused with replacement authority.
- Admission retries and dry-runs do not consume authorizations.
- The policy boundary remains independent of the component that performs the upgrade.

Costs and limitations:

- A trusted authorization/claim service and durable evidence are required.
- CAPI/provider compatibility must be demonstrated rather than assumed.
- Namespace isolation and webhook deployment require careful operational design.
- InPlaceOnly reduces automated remediation options; recovery may require operator-led repair or a separately authorized procedure.

## Alternatives considered

| Alternative | Assessment |
|---|---|
| Trust CAPI rollout settings alone | Rejected: rollout configuration does not independently prove no replacement across every fallback/remediation path. |
| Infer authorization from Machine annotations or status | Rejected: request/controller-writable metadata is not an independent authority. |
| Consume a grant inside admission | Rejected: retries and dry-runs make admission-time mutation unsafe. |
| Allow automatic replacement when in-place fails | Rejected for InPlaceOnly: violates the no-replacement contract. |
| Use one grant for upgrade and status writes | Rejected: different identities and field permissions require separate authorization paths. |

## Open decisions

1. Grant transport, signature format and non-forgeability proof.
2. Atomic claim ledger location, CAS semantics and indeterminate-outcome recovery.
3. Starting-state binding: resourceVersion versus canonical spec-subset digest.
4. Exact in-place mutation field set and status conditions for the selected CAPI/Kubeadm/BYOH versions.
5. Status-subresource authorization mechanism and exact controller identity/field allow-list.
6. Trusted namespace-selection authority and protection against namespace/selector mutation.
7. In-place execution mechanism: CAPI runtime extension, BYOH executor, or another bounded implementation.
8. MachineHealthCheck policy and operator recovery procedure under InPlaceOnly.
9. End-to-end test proving CAPI fallback is denied without corrupting the existing Machine.

## Acceptance criteria

This ADR may move to Accepted only after:

- the grant and claim contracts are specified and reviewed;
- exact CAPI/provider mutation and fallback behavior is tested;
- the webhook and deployment path is implemented with non-bypassable namespace scope;
- negative tests cover CREATE, DELETE, spec mutation, status mutation, replay, stale UIDs, dry-run and webhook outage;
- a real-host in-place upgrade preserves Machine UID, infrastructure identity and physical-host identity;
- failure and recovery behavior is demonstrated without replacement.

A denied replacement attempt is evidence that the safety boundary worked; it is not evidence that an upgrade succeeded.
