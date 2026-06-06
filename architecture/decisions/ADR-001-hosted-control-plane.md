# Architecture Decision Record (ADR-001): Hosted Control Plane (Pod-based) as Optional Cluster Mode

| Field | Value |
|---|---|
| **Status** | Proposed |
| **Date** | 2026-06-06 |
| **Author** | OpenKubes Team |
| **Component** | platform/cluster-management, openkubes-operator (v2.0) |
| **Ticket** | [JIRA-LINK] (https://kubernauts.atlassian.net/jira/software/c/projects/OK/boards/40?selectedIssue=OK-16) |
| **Issue** | [#1](https://github.com/openkubes/openkubes/issues/1) |

---

## Context

OpenKubes currently provisions Kubernetes workload clusters exclusively via **CAPI + CAPK v0.11.2**: every Control Plane runs as a KubeVirt VM on the Infra Cluster. This provides maximum isolation and is the correct default for production and enterprise workloads.

As cluster counts grow (Dev/Test environments, edge deployments, many small tenants), however, there is significant VM overhead per cluster:
- Each Control Plane requires dedicated VM(s) with reserved RAM/CPU
- VM boot time is 2–3 minutes vs. ~30 seconds for Pods
- etcd backup must be managed separately per cluster

The **Hosted Control Plane** concept (Control Plane as Pods in the Management Cluster, Worker Nodes still as KubeVirt VMs) addresses these constraints.

**Reference project:** Kamaji (CLASTIX) implements this approach as an open-source tool (`TenantControlPlane` CRD). Direct integration was evaluated and rejected (see below).

---

## Decision

OpenKubes will implement an **optional pod-based Control Plane mode** (`mode: pod`) as a standalone, native development within the `openkubes-operator` (v2.0 roadmap).

**Kamaji will NOT be integrated as a dependency.**

The Crossplane Platform API (`KubeVirtClusterClaim`) will be extended with an optional `mode` field:

```yaml
apiVersion: platform.openkubes.io/v1alpha1
kind: KubeVirtClusterClaim
metadata:
  name: my-dev-cluster
spec:
  mode: pod          # NEW: "pod" | "vm" (default)
  kubernetesVersion: "1.31"
  workerNodes:
    count: 2
    flavor: small
```

| `mode` | Control Plane | Worker Nodes | Target Use Case |
|---|---|---|---|
| `vm` *(default)* | KubeVirt VMs via CAPK | KubeVirt VMs | Production, Compliance, Full Isolation |
| `pod` *(new)* | Pods in MGMT Cluster | KubeVirt VMs | Dev/Test, many small clusters, Edge |

---

## Rationale

### Why build natively instead of integrating Kamaji?

**License:** Kamaji is licensed under Apache 2.0 — integration would be legally permissible. The concept (Control Plane as Pods) is not a proprietary pattern and is open for independent implementation.

**Stability problem:** Since July 2024, CLASTIX no longer ships stable release artifacts with semantic versioning. From v0.12.0 onward, only edge releases are available. CLASTIX itself recommends commercial support for production-grade implementations. This is incompatible with OpenKubes' open-source commitment.

**Dependency risk:** A dependency on Kamaji would tie OpenKubes to CLASTIX's roadmap and monetization strategy.

**Identity:** OpenKubes would be reduced to a "Kamaji wrapper" rather than remaining an independent project.

**Conclusion:** Kamaji serves as an architectural reference and source of inspiration. No code will be adopted. OpenKubes retains full control over implementation, roadmap, and operations.

### Why in the `openkubes-operator` (v2.0) and not in Crossplane Compositions?

- Compositions are designed for declarative resource orchestration, not complex control-loop logic
- The native Go operator is already on the v2.0 roadmap — it is the architecturally clean place for this
- Better testability, status management, and error handling compared to inline scripts in Compositions

---

## Consequences

### Positive
- **Resource efficiency:** No VM overhead for the Control Plane in Dev/Test clusters
- **Faster provisioning:** Pod start (~30s) instead of VM boot (~2–3 min)
- **Scalability:** Significantly more tenant clusters on the same hardware
- **Centralized etcd management:** Backup and monitoring simplified
- **Broader target audience:** Dev/Test, Edge, many small tenants

### Negative / Risks

| Risk | Mitigation |
|---|---|
| Blast radius: MGMT Cluster failure takes down all pod-based CPs | Clear documentation; `vm` mode remains the default for production |
| Noisy neighbour between tenants | Resource Quotas + LimitRanges per namespace |
| Weaker hard boundary between tenants | Recommend `vm` mode for compliance requirements |
| Higher development effort (native build) | Absorbed into v2.0 operator development |

---

## Alternatives Rejected

| Alternative | Reason for Rejection |
|---|---|
| Integrate Kamaji directly | No stable releases since July 2024; vendor lock-in |
| Keep `vm` mode only | Missed opportunity; poor resource efficiency for Dev/Test |
| k3s/k0s as lightweight VM-based CP | Different problem; VM overhead remains |

---

## Implementation Plan

### Phase 1 – Research & Design (v1.x)
- [ ] `HostedControlPlane` CRD design for `openkubes-operator`
- [ ] Proof of Concept: kube-apiserver + etcd + controller-manager + scheduler as Pods
- [ ] Networking concept: Service exposure, kubeconfig generation
- [ ] Security concept: Namespace isolation, RBAC, Network Policies

### Phase 2 – Implementation (v2.0)
- [ ] `openkubes-operator`: `HostedControlPlaneReconciler`
- [ ] Crossplane Composition: `mode: pod` branch
- [ ] `KubeVirtClusterClaim` API: `mode` field (backward-compatible, default `vm`)
- [ ] Status writeback: `phase`, `endpoint`, `kubeconfigSecret`

### Phase 3 – Documentation & Release
- [ ] Getting Started Guide: pod mode
- [ ] Networking README (Calico/Cilium for Worker ↔ MGMT connectivity)
- [ ] Architecture Reference update

---

## References

- [Kamaji GitHub](https://github.com/clastix/kamaji) – Apache 2.0
- [Kamaji Versioning Policy](https://kamaji.clastix.io/reference/versioning/) – Edge-only since July 2024
- [CAPI Provider Kamaji](https://github.com/clastix/cluster-api-control-plane-provider-kamaji)
- OpenKubes Architecture Reference v1 (`architecture/`)
- OpenKubes v2.0 Roadmap: `openkubes-operator`
