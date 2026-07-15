# ADR-Platform-020: Shared Platform Services Capability (ok-shared)

**Status:** Accepted
**Date:** 2026-07-14
**Accepted:** 2026-07-15
**Acceptance trigger:** ok2-rmf (Robotics Fleet — Suchit, external cluster owner) requires centrally operated Keycloak. Per-cluster path is demonstrably insufficient: ADR-019 provisioned its own Keycloak as a deliberate choice; a second consumer (ok2-rmf) arriving at the same need confirms the duplication the Acceptance Condition was designed to detect. All four conditions met: committed deployment (ok2-rmf is a registered external cluster), central operation required (Keycloak), per-cluster path insufficient (duplication across ok-robotics-fleet and ok2-rmf), duplication test passed.
**Relates:** ADR-Platform-005 (Shared AI Services), ADR-Platform-008 (Dedicated cluster types), ADR-Platform-011 (Secret Contract), ADR-Platform-013 (Cluster registration), ADR-Platform-017 (Constraint Envelopes), ADR-Platform-018 (Observability Capability), ADR-Platform-019 (Robotics Fleet Orchestration — documented counter-evidence for the acceptance trigger)
**Related work:** OK-81 (parked investigation this ADR consciously supersedes as its carrier)

## Context

ADR-018 established per-cluster observability: every OpenKubes cluster carries its own Prometheus, Grafana, and log backend, autonomous and air-gap capable. This decision stands and is not weakened by this ADR.

At scale, and in enterprise deployments, a complementary need emerges: services that are operated **once** and consumed by **all** clusters — central identity, artifact storage, registry, and a federated observability layer for global views and long-term retention. This pattern has proven itself in prior projects: it avoids maintaining N Grafana and OpenSearch instances operationally while keeping cluster-local autonomy intact.

The platform already has one precedent for exactly this shape: ADR-005 (Shared AI Services — one central GPU-backed Ollama, consumed by all clusters). This ADR generalizes that pattern into a named capability with its own cluster.

**Why this ADR was carried as Draft until 2026-07-15:** no forcing consumer existed at authoring time. ADR-019 (Robotics Fleet Orchestration) explicitly provisioned its own cluster-local Keycloak — documented counter-evidence for the trigger. The ok2-rmf external cluster arriving with the same Keycloak need confirmed the duplication pattern and satisfied the Acceptance Condition.

**Existing S3 needs are not a forcing consumer.** Although MinIO would also satisfy existing backup targets (e.g. Longhorn's `VolumeSnapshot`-to-backup path, which requires an external S3/NFS target), this operational convenience alone is intentionally not considered a forcing consumer. Existing backup requirements can be fulfilled by any S3-compatible implementation without establishing a new platform capability; a single bucket does not justify an always-on shared services cluster.

## Decision (target architecture, effective upon acceptance)

### 1. Capability

OpenKubes adopts **Shared Platform Services** as a platform capability: services operated centrally on a dedicated cluster and consumed by all registered clusters through their contracts.

### 2. The shared services cluster: `ok-shared`

A dedicated cluster, named **`ok-shared`**, hosts the capability.

Naming decision (made 2026-07-14, three-way review):

- `ok-shared` continues established ADR vocabulary (ADR-005 "Shared AI Services"); the central Ollama conceptually belongs on this cluster.
- Clear separation from `ok-mgmt`: **ok-mgmt controls clusters** (Crossplane, CAPI, XRDs); **ok-shared serves them** (identity, storage, registry, observability federation). "Hub" was rejected because it blurs this line; ok-mgmt is the hub in the control sense.
- "EE" was rejected in cluster and repository names: edition is a packaging/business concept, not an architecture concept. Using it would send open-core signals toward the community.

### 3. Service scope (v1 candidates)

| Service | Role | Consumed via |
|---|---|---|
| Keycloak | Central OIDC identity | OIDC/OAuth2 endpoints (workloads may still bring profile-local identity, per ADR-019) |
| MinIO | S3 object storage | S3 API — also the natural Thanos store backend and backup target |
| Harbor | Container registry | OCI registry API — complements ADR-012 air-gapped mirroring |
| Secret Backend | Central secrets management | Secret Contract (ADR-011) — implementation may be Vault, Infisical, or a cloud secrets manager; the contract, not the product, is the capability |
| Thanos | Federated metrics: global query + long-term retention over per-cluster Prometheus | Sidecar/Agent on the ADR-018 per-cluster stack |
| Central Grafana | Global dashboards across clusters | Thanos datasource |
| Central OpenSearch (and/or Loki) | Cross-cluster log aggregation | Log forwarding from cluster-local collectors |
| Ollama (existing) | Shared AI inference | OpenAI-compatible API — existing capability per ADR-005; migration to ok-shared is a follow-up candidate, not part of ADR-020 acceptance |

The exact v1 service set is decided at acceptance time, driven by what the first consumer actually needs.

### 4. Relationship to ADR-018 — strictly additive

This capability **extends** per-cluster observability; it does not replace it:

- Every cluster keeps its local stack and all five ADR-018 guarantees, including autonomy (guarantee 5). Air-gapped clusters remain fully functional without ok-shared.
- **Testable additivity guarantee:** absence or unavailability of ok-shared must leave all five ADR-018 guarantees verifiably intact. All ok-shared integration hooks (Thanos sidecar/agent, log forwarding, central OIDC) are opt-in per implementation profile — never default-on modifications of the per-cluster stack.
- Thanos requires per-cluster Prometheus — the ADR-018 stack is the foundation of the federated model, not its alternative.
- ADR-018 v1 explicitly listed "cross-cluster federation / long-term aggregation" as a possible future capability. This ADR is that capability.
- Whether individual per-cluster guarantees (e.g. local Grafana) may become profile-scoped optional where a central instance exists is decided only through an explicit amendment of ADR-018 under ADR-017 envelope rules — envelope-scoped, never silently. **This ADR itself grants no authority to weaken existing guarantees.**

### 5. Cluster type

Upon acceptance, ok-cluster gains a dedicated type for provisioning the shared services cluster (working name `TYPE=shared`), following the ADR-008 precedent (`TYPE=talos-mgmt`). The type is an implementation detail of this ADR, defined at acceptance, not before.

### 6. Repository question (consequence, not core decision)

Whether the capability warrants a sibling repository (`ok-shared`) is decided at acceptance against the established bar (ADR-018 Consequences): independently versioned contracts, multiple implementation profiles, own test suite. It is a consequence of the accepted decision, not its prerequisite.

### 7. Enterprise packaging

An enterprise offering built on this capability is a **bundle of implementation profiles** over unchanged contracts — federated observability, central OIDC, Harbor registry, Thanos retention — not a fork and not withheld features. "OpenKubes owns the contracts, not the components," applied to the commercial question.

## Acceptance Condition

This ADR moves from Draft to Accepted only when **a first real consumer exists**. A consumer, in the sense of this condition, is not an installation, an expression of interest, or a PoC. It is a capability need that satisfies all of the following:

1. **Committed deployment** — a signed enterprise engagement or a binding internal platform commitment, not exploratory demand-sensing;
2. **Central operation required** — at least one service that must be centrally operated to fulfil the consumer's requirement;
3. **Per-cluster path demonstrably insufficient** — the consumer must show that the per-cluster model (ADR-018 stack, profile-local identity per ADR-019, per-cluster S3 targets) does not meet the requirement;
4. **Duplication test** — centralization prevents identical operational responsibility that would otherwise be duplicated across multiple clusters.

The internal path remains open, but only when objectively demonstrable: a concrete internal operational need where identical shared services would otherwise be operated independently across multiple clusters, making the per-cluster model operationally unjustified — evidenced by architecture and operations (e.g. multiple identical registry or identity instances under management, or measurable duplicated operational cost per Revisit Trigger 3), not by preference or estimation.

Upon meeting the condition:

1. the v1 service set is fixed against the consumer's actual requirements;
2. the Shared Platform Services Contract is written (testable guarantees, per the platform method);
3. the cluster type and repository questions are decided;
4. three-way review completes and the ADR is committed as Accepted.

Until then: no repository, no cluster type, no implementation. This ADR is the carrier of the recorded decisions (naming, additivity, boundaries) — nothing more.

## Alternatives Considered

### Centralized observability replacing the per-cluster stack

Rejected. It would break ADR-018's autonomy guarantee, air-gap capability (ADR-012 context), and create a single point of failure. The additive model keeps local guarantees and adds global capabilities.

### Hosting shared services on ok-mgmt

Rejected. ok-mgmt is the control plane (Crossplane, CAPI); loading it with application-facing services (identity, registry, object storage) mixes control and service responsibilities and widens its blast radius. Same reasoning as ADR-019's rejection of running workloads on infrastructure clusters.

### Naming the cluster ok-ee or ok-hub

Rejected — see naming decision above.

### PKI / trust distribution as a v1 candidate

Considered but intentionally deferred. It becomes relevant once central identity, registry, or secret-management capabilities require platform-wide trust management — it is a logical consequence of the trust-bearing services already modelled above (Keycloak, Harbor, Secret Backend), not a distant future vision. Until then, trust remains profile-local. No table row is added before that dependency materializes.

## Consequences (upon acceptance)

- A new always-on cluster with its own lifecycle, upgrade, and backup obligations.
- ok-shared becomes operationally critical for the services it centralizes; its availability model must be defined before any per-cluster guarantee is relaxed in its favor.
- ADR-005's central Ollama gains a natural home; migrating it is a candidate follow-up, not a requirement (see service table).

## Revisit Triggers

- First enterprise/EE engagement requiring central services (primary — this is the acceptance trigger)
- A second workload (after ADR-019) that would otherwise deploy its own Keycloak/MinIO/registry — a forcing consumer for central identity or storage
- Operational cost of per-cluster Grafana/OpenSearch maintenance measurably exceeding federation cost at real cluster counts
