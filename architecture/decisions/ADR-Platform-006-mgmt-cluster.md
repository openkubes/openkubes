# ADR-Platform-006: ok-mgmt as the OpenKubes Management Cluster

**Date:** 2026-07-02
**Status:** Accepted

---

## Context

OpenKubes needs a dedicated cluster that owns the platform contracts at runtime — a place where Crossplane XRDs, CAPI providers, and GitOps tooling run, and from which workload clusters are provisioned and managed.

Previously, a k3s-based `ok-mgmt` cluster was used for this purpose. It was torn down because k3s is not aligned with the OpenKubes principle of using Talos Linux as the standard OS layer for all Kubernetes nodes (ok-linux ADR-001). Running a management cluster on a different OS than the workload clusters creates an inconsistency in the platform: different update paths, different security posture, different operational model.

The question is: where should the platform's runtime contracts live, and how should the management cluster be positioned relative to workload clusters and the host infrastructure?

---

## Decision

> ok-mgmt is a dedicated Talos-based Kubernetes cluster, provisioned by ok-cluster, running on the ok-infra host node. It is the runtime home of the OpenKubes Platform Contracts: Crossplane, CAPI providers, and ArgoCD. All workload clusters (ok1-talos, ok2-talos, ...) are provisioned from ok-mgmt via Crossplane Claims.

Concretely:

```
ok-infra (AX42-U, 188.40.110.28)
└── KubeVirt VMs
    ├── ok-mgmt-cp        (Control Plane)
    └── ok-mgmt-worker-*  (2 Workers)

ok-gpu (GEX44, 5.9.116.80)
└── KubeVirt VMs
    ├── ok1-talos   (Workload Cluster — provisioned by ok-mgmt)
    ├── ok2-talos   (Workload Cluster — provisioned by ok-mgmt)
    └── ...

ok-mgmt owns:
├── Crossplane          — Platform API / XRDs / Compositions
├── CAPI + CAPK         — Cluster Lifecycle Engine
└── ArgoCD              — GitOps bootstrap (Phase 2)
```

**ok-mgmt runs on ok-infra, workload clusters run on ok-gpu.** This ensures the management plane and workload plane are on separate physical hosts — no single hardware failure takes down both.

---

## Rationale

**1. Consistency with ok-linux.**
ok-mgmt is provisioned with `make new CLUSTER=ok-mgmt TYPE=talos` — the same tool, the same OS profile, the same schematic ID as any other OpenKubes cluster. The management cluster is not a special snowflake; it is just another cluster that happens to run platform tooling.

**2. Physical separation of management and workload planes.**
ok-mgmt runs on ok-infra (AX42-U). Workload clusters run on ok-gpu (GEX44). A hardware failure on ok-gpu does not affect ok-mgmt, and vice versa. This is the minimum viable resilience for a platform that manages other clusters.

**3. ok-mgmt-shadow for future redundancy.**
A shadow management cluster (`ok-mgmt-shadow`) on ok-gpu is planned for a future phase — giving ok-mgmt active-passive redundancy across hosts. This is deferred until the primary ok-mgmt is stable in production.

**4. Crossplane as the Self-Service API layer.**
Crossplane on ok-mgmt replaces the local `make new` / `make bootstrap` workflow for provisioning workload clusters. Instead of running CLI commands, a developer submits a `KubeVirtClusterClaim` to ok-mgmt and Crossplane handles the rest. This is the realisation of the Self-Service path described in ADR-Platform-003 (capi-platform-v4.2 as the first Platform Orchestrator prototype).

**5. This is the seam between capi-platform-v4.2 and ok-cluster.**
`capi-platform-v4.2`'s Crossplane XRD (`KubeVirtClusterClaim`) was designed exactly for this topology — a management cluster running Crossplane that provisions workload clusters via CAPI. ok-mgmt is the runtime environment that makes this design real. ok-cluster provides the underlying CAPI templates; Crossplane on ok-mgmt orchestrates them via the XRD.

---

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| k3s-based ok-mgmt | Inconsistent with ok-linux (different OS, different update path, different security posture) |
| Run Crossplane on the RKE2 host cluster (ok-infra) | ok-infra is the bare-metal host cluster — mixing platform tooling with infrastructure management creates tight coupling; ok-infra should remain minimal |
| No dedicated management cluster — use CLI only | Does not scale to self-service; requires operator intervention for every cluster creation; cannot support GitOps-driven provisioning |
| Run ok-mgmt on ok-gpu | ok-gpu also runs workload cluster VMs — a hardware failure would take down both management and workload planes |

---

## Consequences

**Positive:**
- ok-mgmt is provisioned and upgraded with the same tools as workload clusters — no special operational knowledge required
- Physical separation: ok-infra hosts ok-mgmt, ok-gpu hosts workload clusters
- Crossplane on ok-mgmt enables self-service cluster provisioning via `KubeVirtClusterClaim`
- Closes the loop between capi-platform-v4.2's design and the current ok-cluster implementation

**Negative / trade-offs:**
- ok-mgmt is a single point of failure for platform operations (mitigated in the future by ok-mgmt-shadow)
- Bootstrapping paradox: ok-mgmt itself must be provisioned manually via ok-cluster CLI — it cannot provision itself
- Additional cluster to maintain, upgrade, and monitor

**Neutral:**
- ok-mgmt consumes resources on ok-infra (1 CP + 2 Workers) — this is an acceptable trade-off for a dedicated management plane

---

## Bootstrap sequence

```
1. ok-cluster CLI (local)
        ↓  make new CLUSTER=ok-mgmt TYPE=talos NODE_SELECTOR=ok-infra WORKERS=2
        ↓  make bootstrap CLUSTER=ok-mgmt
2. ok-mgmt cluster (Talos, on ok-infra)  ← you are here
        ↓  install Crossplane
        ↓  install CAPI + CAPK providers
        ↓  apply KubeVirtClusterClaim XRD + Composition
3. ok-mgmt provisions workload clusters
        ↓  kubectl apply -f ok1-talos-claim.yaml
        ↓  Crossplane → CAPI → CAPK → KubeVirt VMs on ok-gpu
4. ok-mgmt deploys applications to workload clusters (ArgoCD, Phase 2)
```

---

## Re-evaluation triggers

- ok-mgmt-shadow implemented → update this ADR with active-passive topology
- ArgoCD installed on ok-mgmt → add GitOps bootstrap to the responsibility list
- Crossplane provider for non-KubeVirt infrastructure (Hetzner, AWS) → update the cluster topology diagram
EOF
echo "ADR-Platform-006 done"