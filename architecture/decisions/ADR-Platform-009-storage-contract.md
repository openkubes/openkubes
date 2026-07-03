# ADR-Platform-009: Persistent Storage Contract and Implementation

**Status:** Accepted
**Date:** 2026-07-03

## Context

OpenKubes workload clusters run as KubeVirt VMs on the RKE2 host cluster (two bare-metal hosts). Persistent storage is currently provided by local-path-provisioner: single-node, no redundancy, no snapshots, and it forces node affinity — VM disks are pinned to one host, which blocks KubeVirt live migration and makes every stateful workload dependent on a single machine.

The platform runs on two bare-metal servers with local NVMe. The bare-metal provider offers no attachable network volumes for dedicated servers, so storage must be built from node-local disks.

Following the platform principle — OpenKubes owns contracts, not components — this ADR defines the storage contract first, then selects an implementation that fulfils it on the current hardware.

**Storage implementations are replaceable. Storage capabilities are not.**

## Decision

### 1. The Storage Contract

OpenKubes defines storage as a set of StorageClasses with guaranteed capabilities. Consumers (ok-cluster templates, Crossplane Compositions, ok-apps) reference only these names:

| StorageClass | Access Mode | Guarantees |
|---|---|---|
| `ok-storage-block` (default) | RWO | Replicated (≥2), survives single node failure, snapshot/restore, online expansion |
| `ok-storage-shared` | RWX | Shared access for KubeVirt live migration and multi-pod workloads, same durability as block |
| `ok-storage-local` | RWO | Node-local, non-replicated — scratch, cache, reproducible data only |

**Capability Matrix**

| Capability | `ok-storage-block` | `ok-storage-shared` | `ok-storage-local` |
|---|---|---|---|
| Replicated | ✅ | ✅ | ❌ |
| Snapshot | ✅ | ✅ | ❌ |
| Online expansion | ✅ | ✅ | ❌ |
| Live migration (storage prerequisite) | ❌ | ✅ | ❌ |
| Scratch / cache | ❌ | ❌ | ✅ |

No manifest in any ok-* repo may reference an implementation-specific StorageClass (e.g. `longhorn`, `rook-ceph-block`). The contract names are the only stable interface.

The contract describes capabilities, not hardware. Performance tiers (e.g. `ok-storage-archive`, `ok-storage-performance`) are deliberately not part of this contract; they will be introduced as additional classes only if and when heterogeneous storage hardware exists. Capability before performance.

### 2. Implementation: Longhorn (v1 data engine) on the RKE2 host cluster

Evaluated against the contract on the actual hardware (2 storage nodes):

- **Rook/Ceph** — fulfils the contract technically, but requires 3 monitors for quorum. A 2-node Ceph cluster is an anti-pattern (split-brain risk, explicitly discouraged by Rook). Highest operational complexity. **Deferred**, not rejected: Ceph becomes the preferred implementation once a third storage node exists.
- **Longhorn** — fulfils the contract with 2 nodes at `numberOfReplicas: 2`. RWX via built-in share-manager (an NFS export backed by a replicated, HA Longhorn volume). Rancher-native, first-class on RKE2. Only host prerequisite is `open-iscsi`, added to the `prereqs.yml` Ansible role. **Selected.**
- **Standalone NFS** — single point of failure, cannot fulfil the replication guarantee. **Rejected.**

`ok-storage-local` remains backed by local-path-provisioner.

With only two storage nodes, the realistic choices are replica=1 or replica=2; replica=2 is strictly better. Longhorn's HA parameters (Node Down Pod Deletion Policy, Replica Auto Balance, Replica Replenishment Wait Interval, Stale Replica Timeout, storage reservation) are part of the implementation profile and **must be version controlled** in the `ok-storage` repository — they are configuration, not folklore.

### 3. Redundancy lives on exactly one layer: the host cluster

Talos workload clusters do NOT run their own distributed storage. The stacking is:

```
Workload cluster PVC (local-path inside the VM)
  → VM disk (KubeVirt DataVolume)
    → Longhorn volume on RKE2, replica=2   ← redundancy here
```

Rationale: nested distributed storage (Longhorn-in-Longhorn) multiplies write amplification, doubles replication, snapshots, CSI stacks, and failure modes, and would force iscsi system extensions into every ok-linux profile. Workload clusters inherit durability through their VM disks.

Consequence: provisioning VM disks on `ok-storage-shared` (RWX) satisfies the **storage prerequisite** for KubeVirt live migration. Storage alone does not guarantee successful live migration — CPU compatibility, eviction strategy, migration network, and workload behaviour also apply. Live migration support must be validated by integration testing.

### 4. Snapshot semantics

Platform snapshots (Longhorn volume snapshots) provide **crash-consistent** recovery: the snapshot captures the block device as if the node had lost power. Application-consistent backups (databases, message queues) remain the responsibility of workload-level backup solutions. This boundary is part of the contract.

### 5. Repository: `ok-storage`

Storage is a platform capability, not cluster lifecycle logic. The implementation lives in a dedicated repository `github.com/openkubes/ok-storage` (provider-agnostic), alongside ok-linux, ok-cluster, ok-gitops. Structure:

```
ok-storage/
  longhorn/           # implementation profile (Helm values, HA parameters)
  storageclasses/     # the contract classes
  backup/             # future: workload-level backup tooling
  rook/               # future: Ceph implementation profile at 3+ nodes
```

Provider-specific values remain in the private infrastructure repository.

## Consequences

**Positive**
- Stateful workloads survive single node failure; application PVCs become redundant
- Storage prerequisite for KubeVirt live migration fulfilled (RWX VM disks)
- Snapshot/restore and volume expansion available platform-wide
- Implementation is swappable (Ceph at 3+ nodes) without touching any consumer

**Design note: RAID1 × replica=2**
Each volume exists as four physical copies (local RAID1 mirror × Longhorn replica=2). This is intentional, not waste: RAID protects against **disk failure** within a node, Longhorn replication protects against **node failure**. These are different failure domains operating at different layers. RAID stays.

**Negative / accepted**
- 2x logical storage overhead from replication on already-limited NVMe
- Replication traffic crosses the provider's private L2 network between two datacenters — write latency includes inter-DC RTT (validated: sub-millisecond)
- With replica=2 there is no quorum arbiter; simultaneous failure of both nodes or a prolonged network partition requires manual intervention — mitigated by version-controlled HA parameters (see Decision 2)
- Longhorn v2 (SPDK) data engine is not yet production-ready; v1 engine is mandated until re-evaluated

## Migration path

1. Deploy Longhorn on RKE2 from the `ok-storage` implementation profile, `numberOfReplicas: 2`
2. Create contract StorageClasses (`ok-storage-block` default, `ok-storage-shared`, `ok-storage-local`)
3. Migrate application PVCs and new DataVolumes to `ok-storage-block`
4. Move VM disks to `ok-storage-shared`; validate live migration by integration testing
5. At 3+ storage nodes: re-evaluate Rook/Ceph behind the same contract (new ADR)

## Outlook

This ADR instantiates a recurring platform pattern: **Capability → Contract → Implementation Profile → Provider-specific Values**. For storage: Persistent Storage → `ok-storage-*` classes → Longhorn → provider values. The same schema applies to future capabilities (networking, ingress) and will be generalized in a dedicated ADR.
