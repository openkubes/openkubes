# ADR-Platform-009: Persistent Storage Contract and Implementation

**Status:** Proposed
**Date:** 2026-07-03

## Context

OpenKubes workload clusters run as KubeVirt VMs on the RKE2 host cluster (two bare-metal hosts). Persistent storage is currently provided by local-path-provisioner: single-node, no redundancy, no snapshots, and it forces node affinity — VM disks are pinned to one host, which blocks KubeVirt live migration and makes every stateful workload (Open WebUI PVCs, future GitOps state) dependent on a single machine.

The platform runs on two bare-metal servers with local NVMe. The bare-metal provider offers no attachable network volumes for dedicated servers, so storage must be built from node-local disks.

Following the platform principle — OpenKubes owns contracts, not components — this ADR defines the storage contract first, then selects an implementation that fulfils it on the current hardware.

## Decision

### 1. The Storage Contract

OpenKubes defines storage as a set of StorageClasses with guaranteed capabilities. Consumers (ok-cluster templates, Crossplane Compositions, ok-apps) reference only these names:

| StorageClass | Access Mode | Guarantees |
|---|---|---|
| `ok-storage-block` (default) | RWO | Replicated (≥2), survives single node failure, snapshot/restore, online expansion |
| `ok-storage-shared` | RWX | Shared access for KubeVirt live migration and multi-pod workloads, same durability as block |
| `ok-storage-local` | RWO | Node-local, non-replicated — scratch, cache, reproducible data only |

No manifest in any ok-* repo may reference an implementation-specific StorageClass (e.g. `longhorn`, `rook-ceph-block`). The contract names are the only stable interface.

### 2. Implementation: Longhorn (v1 data engine) on the RKE2 host cluster

Evaluated against the contract on the actual hardware (2 storage nodes):

- **Rook/Ceph** — fulfils the contract technically, but requires 3 monitors for quorum. A 2-node Ceph cluster is an anti-pattern (split-brain risk, explicitly discouraged by Rook). Highest operational complexity. **Deferred**, not rejected: Ceph becomes the preferred implementation once a third storage node exists.
- **Longhorn** — fulfils the contract with 2 nodes at `numberOfReplicas: 2`. RWX via built-in share-manager (internally NFS, but the backing volume is replicated and HA). Rancher-native, first-class on RKE2. Only host prerequisite is `open-iscsi`, added to the `prereqs.yml` Ansible role. **Selected.**
- **Standalone NFS** — single point of failure, cannot fulfil the replication guarantee. **Rejected.**

`ok-storage-local` remains backed by local-path-provisioner.

### 3. Redundancy lives on exactly one layer: the host cluster

Talos workload clusters do NOT run their own distributed storage. The stacking is:

```
Workload cluster PVC (local-path inside the VM)
  → VM disk (KubeVirt DataVolume)
    → Longhorn volume on RKE2, replica=2   ← redundancy here
```

Rationale: nested distributed storage (Longhorn-in-Longhorn) multiplies write amplification (~4x), doubles operational surface, and would force iscsi system extensions into every ok-linux profile. Workload clusters inherit durability through their VM disks.

Consequence: once VM root/data disks are provisioned on `ok-storage-shared` (RWX), KubeVirt live migration becomes possible — removing today's hard node-affinity constraint.

## Consequences

**Positive**
- Stateful workloads survive single node failure; Open WebUI PVCs become redundant
- KubeVirt live migration unblocked (RWX VM disks)
- Snapshot/restore and volume expansion available platform-wide
- Implementation is swappable (Ceph at 3+ nodes) without touching any consumer

**Negative / accepted**
- 2x storage overhead from replication on already-limited NVMe
- Replication traffic crosses the provider's private L2 network between two datacenters — write latency includes inter-DC RTT; must be validated for KubeVirt disk workloads
- With replica=2 there is no quorum arbiter; simultaneous failure of both nodes or a prolonged network partition requires manual intervention
- Longhorn v2 (SPDK) data engine is not yet production-ready; v1 engine is mandated until re-evaluated

**Prerequisites before implementation**
- Verify free NVMe capacity and create a dedicated filesystem/partition for `/var/lib/longhorn` on both storage nodes (bare-metal provisioning images typically allocate everything to `/`)
- Add `open-iscsi` to `prereqs.yml`
- Benchmark inter-DC replication latency for representative KubeVirt disk I/O

## Migration path

1. Deploy Longhorn on RKE2, dedicated disk path, `numberOfReplicas: 2`
2. Create contract StorageClasses (`ok-storage-block` default, `ok-storage-shared`, `ok-storage-local`)
3. Migrate Open WebUI PVCs and new DataVolumes to `ok-storage-block`
4. Move VM disks to `ok-storage-shared`, enable and test live migration
5. At 3+ storage nodes: re-evaluate Rook/Ceph behind the same contract (new ADR)
