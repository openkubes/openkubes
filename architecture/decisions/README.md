# Architecture Decision Records (ADRs)

Accepted ADRs are historical records. They are not silently rewritten when the architecture evolves.

## Governance & Lifecycle

### Editorial changes
Editorial changes may be applied directly when they do not alter the decision or its consequences.
*Examples:*
* Spelling and formatting fixes
* Broken links or incorrect ADR references
* Removal of generation artifacts
* Metadata corrections that do not change architectural meaning

### Extensions and clarifications
Material extensions or clarifications are recorded in a new ADR using one of the following relationships:
* `Extends: ADR-Platform-XXX`
* `Clarifies: ADR-Platform-XXX`

The original ADR remains **Accepted**. A back-reference (`Extended by: ADR-Platform-YYY` / `Clarified by: ADR-Platform-YYY`) may be added to the original ADR's metadata as an editorial change.

### Superseding decisions
When a decision is replaced, the new ADR declares:
* `Supersedes: ADR-Platform-XXX`

The original ADR's status is updated to:
* `Status: Superseded by ADR-Platform-YYY`

The original decision text is preserved as historical context.

### Relationships and the architecture graph
Relationship keywords are part of the platform architecture vocabulary and the architecture graph. They **MUST** be used consistently across all platform ADRs and expressed in ADR metadata using the exact keywords defined above.

---

## Index of Platform ADRs

### 🏗️ Core Architecture & Framework
Fundamental architectural choices, OS capabilities, and the platform execution model.

| ADR | Title | Scope |
|:---|:---|:---|
| **001** | [Contracts not Components](ADR-Platform-001-contracts-not-components.md) | Contract-driven architecture principles |
| **002** | [Distribution Layer](ADR-Platform-002-distribution-layer.md) | Distribution layer abstractions |
| **004** | [Runner is Implementation Detail](ADR-Platform-004-runner-is-implementation-detail.md) | Decoupling runner execution |
| **016** | [OS Capability Contract](ADR-Platform-016-os-capability-contract.md) | Operating system interface boundaries |
| **020** | [Shared Platform Services](ADR-Platform-020-shared-platform-services.md) | Cross-cutting platform services |
| **022** | [Distribution Framework not a Distribution](ADR-Platform-022-distribution-framework-not-a-distribution.md) | Framework positioning |
| **026** | [Vertical Layer](ADR-Platform-026-vertical-layer.md) | Vertical layer architecture |
| **030** | [Control Plane Execution Model](ADR-Platform-030-control-plane-execution-model.md) | Control plane execution engine |
| **034** | [OK UP](ADR-Platform-034-ok-up.md) | Platform bootstrapping & lifecycle (`ok up`) |
| **035** | [Hybrid Intent & Control Plane Execution](ADR-Platform-035-hybrid-intent-and-control-plane-execution.md) | Blending intent-driven and declarative control planes |

### 🌐 CAPI & Fleet Management
Cluster API (CAPI) integrations, management cluster design, and cluster registration.

| ADR | Title | Scope |
|:---|:---|:---|
| **003** | [CAPI Platform v4.2 Prototype](ADR-Platform-003-capi-platform-v4.2-prototype.md) | CAPI prototyping & foundation |
| **006** | [Mgmt Cluster](ADR-Platform-006-mgmt-cluster.md) | Management cluster architecture |
| **007** | [CAPI Responsibility Split](ADR-Platform-007-capi-responsibility-split.md) | Responsibility boundaries in CAPI |
| **008** | [Mgmt Cluster Type](ADR-Platform-008-mgmt-cluster-type.md) | Topology types for management clusters |
| **013** | [Workload Cluster Registration](ADR-Platform-013-workload-cluster-registration.md) | Workload cluster onboarding workflow |
| **023** | [CAPI Infrastructure Providers as Implementation Profiles](ADR-Platform-023-capi-infrastructure-providers-as-implementation-profiles.md) | Infrastructure providers as profiles |
| **031** | [OK Mgmt Disaster Recovery](ADR-Platform-031-ok-mgmt-disaster-recovery.md) | Mgmt cluster backup & DR strategy |
| **033** | [OpenKubes OKP Single](ADR-Platform-033-openkubes-okp-single.md) | Single-node / single-cluster topology profile |

### 💾 Storage, Networking & Services
Plattform infrastructure capabilities including storage, ingress, and artifact hosting.

| ADR | Title | Scope |
|:---|:---|:---|
| **009** | [Storage Contract](ADR-Platform-009-storage-contract.md) | Storage capability abstraction |
| **010** | [Ingress Contract](ADR-Platform-010-ingress-contract.md) | Ingress capability abstraction |
| **012** | [Air-Gapped Image Mirroring](ADR-Platform-012-air-gapped-image-mirroring.md) | Image mirroring for disconnected environments |
| **028** | [Artifact Registry Capability](ADR-Platform-028-artifact-registry-capability.md) | Internal artifact registry capability |
| **029** | [OK Messaging Capability](ADR-Platform-029-ok-messaging-capability.md) | Platform messaging interface |

### 🔒 Security, Compliance & GitOps
Governance, policy management, secret handling, and continuous delivery.

| ADR | Title | Scope |
|:---|:---|:---|
| **011** | [GitOps](ADR-Platform-011-gitops.md) | GitOps-driven platform reconciliation |
| **017** | [Constraint Envelopes](ADR-Platform-017-constraint-envelopes.md) | Policy & constraint enforcement |
| **025** | [Datacenter Secret Sync Profile](ADR-Platform-025-datacenter-secret-sync-profile.md) | Multi-datacenter secret synchronization |
| **037** | [Console Authentication, Identity Federation, and Break-glass Access](ADR-Platform-037-console-authentication-and-identity-federation.md) | Federated Console identity, server-side sessions, and exceptional local access |
| _n/a_ | Acceptance Records (025-*) | Acceptance records for Fresh Install, Outage Recovery, Singleton Enforcement, etc. |

### 🖥️ Console & Product Experience
Contract-aligned product surfaces and their evolution.

| ADR | Title | Scope |
|:---|:---|:---|
| **036** | [Native OpenKubes Console](ADR-Platform-036-openkubes-console-architecture.md) | Curated-first Console and evolution toward contract-adaptive UI |
| **037** | [Console Authentication, Identity Federation, and Break-glass Access](ADR-Platform-037-console-authentication-and-identity-federation.md) | Federated-first authentication and controlled recovery access |

### 📊 Observability & Diagnostics
Telemetry, health checks, diagnostic contracts, and gating.

| ADR | Title | Scope |
|:---|:---|:---|
| **018** | [Observability Capability](ADR-Platform-018-observability-capability.md) | Core observability capabilities |
| **021** | [Read-Only Platform Diagnostics Contract](ADR-Platform-021-read-only-platform-diagnostics-contract.md) | Diagnostics & telemetry contracts |
| **024** | [Observability Install as Opt-In Gated Command](ADR-Platform-024-observability-install-as-opt-in-gated-command.md) | Opt-in installation workflow for O11y |
| **027** | [Observability Gate Assurance Scope](ADR-Platform-027-observability-gate-assurance-scope.md) | Verification and gating scope for O11y |

### 🚀 Workloads & Specialized Profiles
Edge Computing, AI/ML Infrastructure, Robotics, and DBaaS profiles.

| ADR | Title | Scope |
|:---|:---|:---|
| **005** | [Shared AI Services](ADR-Platform-005-shared-ai-services.md) | Infrastructure for shared AI/ML workloads |
| **014** | [Constrained Edge Profile](ADR-Platform-014-constrained-edge-profile.md) | Edge node resource-constrained profile |
| **015** | [Agentic AI](ADR-Platform-015-agentic-ai.md) | Integration contracts for AI agents |
| **019** | [Robotics Fleet Orchestration](ADR-Platform-019-robotics-fleet-orchestration.md) | Robotics fleet management capabilities |
| **032** | [OpenKubes DBaaS](ADR-Platform-032-openkubes-dbaas.md) | Database-as-a-Service integration profile |
