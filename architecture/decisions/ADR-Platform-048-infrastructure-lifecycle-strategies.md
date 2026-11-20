# ADR-Platform-048: Infrastructure Lifecycle Strategies

**Date:** 2026-11-20  
**Status:** Proposed  
**Scope:** Lifecycle strategy selection for CAPI-managed infrastructure across BYOH, cloud and OpenStack profiles

**Extends:** ADR-Platform-023  
**Constrained by:** ADR-Platform-030, ADR-Platform-034, ADR-Platform-047  
**Related:** ADR-Platform-006, ADR-Platform-007, ADR-Platform-031, ADR-Platform-035

---

## Context

OpenKubes targets infrastructure with materially different replacement and availability characteristics.

Dedicated bare-metal hosts are often scarce, identity-bearing and not quickly replaceable. A cloud or OpenStack environment may offer an API-driven capacity pool in which a replacement Machine can be created, verified and joined before an old Machine is removed. Treating both environments as if they had the same rollout semantics either makes bare-metal upgrades unsafe or unnecessarily constrains elastic environments.

CAPI exposes provider-specific rollout capabilities, but those capabilities do not by themselves define OpenKubes' authorization, capacity, availability, persistent-state migration or recovery contracts.

OpenKubes therefore needs an explicit lifecycle strategy independent of the provider implementation. The provider executes the selected strategy; the strategy constrains which lifecycle transitions are admissible.

## Decision

### 1. Two explicit strategies

The initial supported strategy set is:

- **InPlaceOnly** — update the existing Machine/host in place. Replacement is not an automatic fallback. This is the initial strategy for dedicated BYOH bare-metal clusters.
- **RollingReplacement** — provision and validate a replacement Machine before retiring the old Machine, subject to independent replacement authorization and a proven capacity/readiness contract. This is the candidate strategy for cloud and OpenStack profiles with suitable elastic capacity.

There is no implicit `PreferInPlace` mode. A preference that silently falls back to replacement is unsafe for no-spare bare-metal environments.

### 2. Strategy selection and precedence

The effective strategy is resolved from the most specific applicable declaration:

1. resource/workload override;
2. cluster declaration;
3. provider/profile default.

A more specific declaration may narrow the permitted lifecycle behavior. It must not widen a parent constraint from `InPlaceOnly` to `RollingReplacement` unless an explicit capacity, readiness, authorization and persistent-state contract is independently satisfied and the governing policy permits that widening.

The representation remains open: a versioned Cluster API field, ClusterClass variable or another typed contract is preferred over undocumented annotations. The chosen representation must be validated, observable and included in the canonical desired-state digest.

### 3. Provider execution ownership

The infrastructure provider and relevant CAPI controllers own execution of provider-specific operations. The OpenKubes lifecycle strategy constrains the permitted path and required evidence; it does not duplicate provider reconciliation.

A provider's technical ability to replace a Machine is not authority to do so. Replacement requires a separate authorization and an independently satisfied capacity/readiness contract.

### 4. Identity and authorization consequences

Under `InPlaceOnly`, the Machine UID, infrastructure identity and physical-host identity remain stable across the upgrade.

Under `RollingReplacement`, the replacement Machine has a new UID and normally a new infrastructure identity. An in-place upgrade grant bound to the old Machine UID can never authorize the replacement. Replacement is a separate lifecycle operation governed by its own authorization envelope.

The no-replacement contract and in-place authorization semantics are defined by ADR-Platform-047.

### 5. CAPI rollout mapping and compatibility constraints

The following source-level facts were checked against Cluster API v1.14.4 and must be revalidated when dependencies change:

| CAPI resource | Verified behavior | OpenKubes implication |
|---|---|---|
| KubeadmControlPlane (KCP) | `spec.rollout.strategy` supports `RollingUpdate`; it does not expose an `OnDelete` enum. `maxSurge` is constrained to 0 or 1. | KCP configuration alone does not provide a general OnDelete/no-replacement switch. Exact in-place behavior and fallback must be tested. |
| MachineDeployment (MD) | `RollingUpdate` and `OnDelete` strategies are represented. | The existence of OnDelete does not itself implement a safe in-place Kubernetes upgrade or its authorization. |

For KCP, `maxSurge: 0` is not a universal guarantee of in-place behavior; CAPI validation and replica/topology constraints apply. A one-replica control plane cannot be assumed to support the same rollout semantics as an HA control plane.

The exact MachineDeployment defaults, in-place gating and provider/runtime-extension compatibility are not decided by this ADR and require version-pinned tests.

### 6. Availability contracts differ by role and topology

**Control plane**

- **Singleton control plane:** treat upgrade/recovery as a disaster-recovery operation, not a rolling availability operation. Require a verified etcd backup, a tested restore procedure and an explicitly accepted outage window. A singleton control plane is not eligible for `RollingReplacement` under this initial decision.
- **HA control plane:** any replacement rollout must preserve etcd quorum and API availability. Surge capacity, membership changes, health gates and failure recovery must be demonstrated before old members are removed.

**Workers**

- Replacement must not reduce workload availability below the declared service contract.
- The contract must account for PodDisruptionBudgets, workload replica/anti-affinity constraints, storage attachment and migration, node drain behavior, and readiness of the replacement before retirement of the old Machine.
- A PDB alone is not proof of spare infrastructure capacity or successful state migration.

### 7. MachineHealthCheck and controller-originated replacement

MachineHealthCheck remediation is a replacement path, not an implicit repair exception.

- Under `InPlaceOnly`, MHC must not automatically delete and replace a protected Machine. Its scope must be disabled or otherwise constrained for those Machines, with an explicit operator recovery procedure.
- Under `RollingReplacement`, MHC remediation is admissible only within a valid replacement authorization and a currently satisfied capacity/readiness contract.
- CAPI fallback after a failed in-place attempt is subject to the same replacement gate. Controller origin does not grant authority.

The mechanism that correlates controller-originated CREATE/DELETE requests to a previously approved replacement envelope remains an implementation decision. Request fields or controller identity alone are not sufficient proof of authorization.

### 8. Mandatory Replacement Authorization Gate

No replacement may proceed under `RollingReplacement` unless both conditions hold:

1. a valid, independently issued replacement authorization is bound to the exact cluster, Machine transition, target and validity window; and
2. a currently satisfied capacity-and-readiness contract proves that replacement can be created, initialized, joined, made Ready and safely adopted before the old Machine is retired.

The gate must fail closed on missing, stale, replayed or mismatched authorization; insufficient capacity; failed readiness; or unverifiable persistent-state migration.

Disabling or removing an enforcement component is not an authorization to replace.

### 9. Guard applicability

ADR-Platform-047 defines the initial no-replacement guard semantics for protected InPlaceOnly BYOH scope. Whether the same enforcement component is reused for cloud/OpenStack RollingReplacement, and how it integrates with provider-specific replacement gates, remains open. The lifecycle authorization contract applies regardless of implementation.

### 10. Why PreferInPlace is not an initial strategy

A `PreferInPlace` strategy is rejected for the initial strategy set. If an in-place attempt can silently fall back to replacement, a no-spare bare-metal environment may lose its only viable path. If it cannot fall back, the behavior is effectively `InPlaceOnly`.

Any future preference mode must define an explicit decision point, independent authorization for both paths, a deterministic path record and a verified capacity/readiness contract before replacement is allowed.

## Invariants

- **INV-048-1 — Explicit strategy:** every managed cluster resolves to exactly one effective lifecycle strategy.
- **INV-048-2 — Replacement gate:** RollingReplacement requires both independent replacement authorization and a currently satisfied capacity/readiness contract.
- **INV-048-3 — No authorization crossover:** in-place authorization never authorizes replacement; replacement authorization never authorizes arbitrary in-place field changes.
- **INV-048-4 — Availability by topology:** singleton control planes use a DR contract; HA control planes require quorum-preserving rollout evidence.
- **INV-048-5 — Worker availability:** worker replacement respects workload availability, disruption, storage and readiness contracts.
- **INV-048-6 — Fail closed:** missing authorization, capacity, readiness or enforcement evidence blocks replacement; disabling enforcement is not permission.
- **INV-048-7 — Provider executes, strategy constrains:** provider implementation does not define or enlarge lifecycle authority.
- **INV-048-8 — No silent preference fallback:** PreferInPlace is not an initial strategy.

## Consequences

Positive consequences:

- Bare-metal and elastic infrastructure are not forced into one rollout model.
- Replacement becomes an explicit, separately authorized operation.
- Availability and recovery requirements are stated per control-plane topology and worker workload.
- Provider-specific controllers remain responsible for execution.

Costs and limitations:

- Multiple strategies increase contract and test surface.
- RollingReplacement requires real capacity, readiness and state-migration evidence.
- InPlaceOnly requires an independently implemented and tested in-place executor.
- CAPI provider capabilities and validation rules must be pinned and rechecked as versions evolve.

## Alternatives considered

| Alternative | Assessment |
|---|---|
| One global rolling strategy | Rejected: unsafe for scarce/no-spare bare metal. |
| One global in-place strategy | Rejected: needlessly constrains elastic cloud/OpenStack capacity. |
| PreferInPlace with automatic fallback | Rejected: makes replacement implicit. |
| Let each provider choose freely | Rejected: provider capability is not lifecycle authorization. |
| Use PDB as the complete replacement contract | Rejected: PDB does not prove infrastructure capacity, node readiness or persistent-state migration. |

## Open decisions

1. Typed strategy declaration and provider → cluster → resource precedence encoding.
2. Formal capacity/readiness/replacement authorization schema and controller-originated operation correlation.
3. Exact KCP/MD version-specific defaults, constraints and in-place behavior.
4. Exact CAPI v1.14.4 BYOH in-place field set and runtime-extension/executor implementation.
5. Formal HA control-plane quorum contract and singleton etcd backup/restore acceptance.
6. Worker SLO/PDB/storage migration contract and readiness measurement.
7. MHC scoping and operator recovery workflow under InPlaceOnly.
8. Applicability and implementation of replacement admission gates for cloud/OpenStack providers.
9. Future PreferInPlace semantics, if ever required.

## Acceptance criteria

This ADR may move to Accepted only after:

- strategy declaration and precedence are represented in a versioned, validated contract;
- InPlaceOnly has a real-host identity-preserving upgrade proof;
- RollingReplacement has an end-to-end proof of independent authorization, capacity, readiness, state handling and safe retirement;
- singleton and HA control-plane contracts are separately tested;
- worker disruption and storage behavior are validated;
- MHC and CAPI fallback paths are covered by negative and positive tests.
