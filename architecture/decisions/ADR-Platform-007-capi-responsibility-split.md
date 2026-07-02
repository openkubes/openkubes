# ADR-Platform-007: CAPI Responsibility Split — ok-infra bootstraps, ok-mgmt operates

**Date:** 2026-07-02
**Status:** Accepted

---

## Context

OpenKubes runs CAPI (Cluster API) + CAPK (KubeVirt Provider) on the RKE2 host cluster (ok-infra). This was the correct approach before ok-mgmt existed — it was the only place to run CAPI.

Now that ok-mgmt exists as a dedicated Talos-based management cluster (see ADR-Platform-006), the question arises: should CAPI on ok-infra be removed? And who is responsible for provisioning which clusters?

Two competing concerns:
1. **Separation of concerns** — ok-infra should be a pure infrastructure layer, not a platform operations layer
2. **Idempotency and re-create** — ok-mgmt itself must be re-creatable if it fails or needs upgrading; something must be able to bootstrap it

---

## Decision

> CAPI on ok-infra is kept, but its responsibility is strictly limited to bootstrapping the management plane. CAPI on ok-mgmt is the runtime provider for all workload clusters.

```
ok-infra CAPI:    bootstrap provider  — provisions ok-mgmt and ok-mgmt-shadow only
ok-mgmt CAPI:     runtime provider    — provisions all workload clusters
```

Concretely:

```
ok-infra (RKE2 Host-Cluster)
└── KubeVirt + CDI + MetalLB    ← Infrastructure Layer (VMs, storage, networking)
└── CAPI + CAPK                 ← Bootstrap Layer (ok-mgmt only)
    ├── ✅ ok-mgmt              ← may provision
    ├── ✅ ok-mgmt-shadow       ← may provision (future)
    └── ❌ ok1-talos, ok2-talos ← must NOT provision directly

ok-mgmt (Management Cluster — Talos, on ok-infra VMs)
└── CAPI + CAPK + Crossplane    ← Platform Operations Layer
    ├── ✅ ok1-talos            ← provisions and manages
    ├── ✅ ok2-talos            ← provisions and manages
    └── ❌ ok-mgmt itself       ← cannot manage itself (bootstrap paradox)
```

---

## Rationale

**1. The bootstrap paradox requires ok-infra CAPI.**
ok-mgmt cannot provision itself. If ok-mgmt is torn down, rebuilt, or upgraded, something external must recreate it. ok-infra is the only stable, always-available layer that can fulfil this role — it is the bare-metal host cluster that exists before any Talos cluster is created. Removing CAPI from ok-infra would make ok-mgmt non-re-creatable without manual intervention.

**2. ok-infra CAPI must not manage workload clusters.**
If ok-infra CAPI provisions ok1-talos directly, it bypasses the ok-mgmt Platform Layer entirely. This means no Crossplane self-service, no GitOps-driven provisioning, no unified platform API. The workload cluster would exist outside the management plane — invisible to ok-mgmt's Crossplane and ArgoCD.

**3. Idempotency is preserved.**
`make new CLUSTER=ok-mgmt && make bootstrap CLUSTER=ok-mgmt` on ok-infra is the idempotent re-create path for the management plane. This works regardless of ok-mgmt's state — even if ok-mgmt is completely gone.

**4. Clear layer boundaries.**
Each layer has one job:
- ok-infra: provide infrastructure (VMs, networking, storage) and bootstrap the management plane
- ok-mgmt: operate the platform (provision workload clusters, deploy applications)
- Workload clusters: run developer workloads

This follows ADR-Platform-001: OpenKubes owns the contracts, not the components. The "bootstrap contract" belongs to ok-infra; the "cluster lifecycle contract" belongs to ok-mgmt.

---

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| Remove CAPI from ok-infra entirely | ok-mgmt becomes non-re-creatable without manual Hetzner/KubeVirt intervention; violates idempotency |
| Keep CAPI only on ok-infra, not on ok-mgmt | No self-service provisioning; every workload cluster requires CLI access to ok-infra; does not scale |
| Run CAPI only on ok-mgmt, bootstrap ok-mgmt via a separate bootstrap cluster | Over-engineering for current scale; adds a third cluster just for bootstrapping |

---

## Consequences

**Positive:**
- ok-mgmt is re-creatable at any time via `make bootstrap CLUSTER=ok-mgmt` on ok-infra
- All workload clusters are managed exclusively by ok-mgmt — single source of truth for cluster state
- ok-infra remains minimal: no workload cluster management, no Crossplane, no ArgoCD
- Clean audit trail: if a workload cluster exists, it was created by ok-mgmt

**Negative / trade-offs:**
- Two CAPI installations to maintain (ok-infra and ok-mgmt) — different versions must be kept compatible
- ok-infra CAPI is "mostly idle" — it only activates when ok-mgmt needs to be re-created
- Bootstrap paradox remains: ok-mgmt cannot recover itself if CAPI on ok-infra is also broken

**Neutral:**
- ok-cluster CLI (`make new`, `make bootstrap`) continues to work against ok-infra for management plane operations, and against ok-mgmt for workload cluster operations — same tool, different target kubeconfig

---

## Operational rules

These rules follow directly from this decision and must be respected by all operators:

1. **Never run `make bootstrap CLUSTER=ok1-talos` against ok-infra.** Workload clusters are provisioned from ok-mgmt via Crossplane Claims only.
2. **Always run `make bootstrap CLUSTER=ok-mgmt` against ok-infra.** The management cluster is the only cluster ok-infra CAPI should create.
3. **ok-mgmt kubeconfig is the operational kubeconfig.** Day-to-day platform operations (creating clusters, deploying applications) use `~/.kube/ok-mgmt.yaml`, not `~/.kube/ok-infra.yaml`.

---

## Re-evaluation triggers

- ok-mgmt-shadow implemented → update bootstrap sequence (ok-infra may need to bootstrap both)
- Hetzner bare-metal provider added → ok-infra CAPI may gain a second responsibility (bare-metal node provisioning)
- ok-mgmt reaches HA (3 CP) → re-evaluate whether ok-infra CAPI is still needed for re-create
EOF
echo "ADR-Platform-007 done"