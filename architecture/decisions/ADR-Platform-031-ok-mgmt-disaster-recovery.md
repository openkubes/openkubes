# ADR-Platform-031: ok-mgmt Protection and Disaster Recovery

**Date:** 2026-08-09
**Status:** Proposed

**Extends:** ADR-Platform-006, ADR-Platform-007
**Related:** ADR-Platform-004, ADR-Platform-011, ADR-Platform-013, ADR-Platform-017, ADR-Platform-030

---

## Context

ADR-Platform-006 makes `ok-mgmt` the runtime home of the OpenKubes platform
contracts, Crossplane, CAPI providers, and GitOps. ADR-Platform-007 assigns the
workload-cluster lifecycle to CAPI on `ok-mgmt`. ADR-Platform-030 makes Executors
non-authoritative, which correctly leaves the accepted desired state and lifecycle
object graph in the management plane.

That produces an intentional failure-domain split:

```text
ok-mgmt outage
  -> cluster lifecycle reconciliation unavailable
  -> otherwise healthy workload runtime should continue

infrastructure-plane outage
  -> workload compute and control-plane VMs endangered

workload-cluster outage
  -> that cluster's applications endangered
```

`ok-mgmt` is therefore not normally in the workload application data path, but it is a
shared **Lifecycle Management Failure Domain**. A temporary outage pauses create,
scale, upgrade, delete, MachineHealthCheck remediation, normalized lifecycle status,
and any centralized Enablement or GitOps reconciliation. Permanent loss of its etcd
state can leave running workload clusters and KubeVirt resources without their CAPI
object graph, credentials, ownership metadata, and lifecycle authority.

Reapplying desired manifests is not equivalent to restoring that authority. It may
create new object identities, duplicate infrastructure, collide with existing provider
resources, or trigger destructive reconciliation. Git protects declared desired state
but does not by itself preserve all management-cluster runtime state.

The Cluster API documentation recommends production management clusters have suitable
backup and disaster-recovery procedures. It also states that `clusterctl move` is
designed and E2E-tested around bootstrap/pivot, not backup/restore; status subresources
are not restored by a move.

OpenKubes therefore needs a separate decision for protecting and recovering the
authoritative management plane. This responsibility does not belong in ADR-030, whose
scope ends at the execution and reconciliation model.

## Decision

OpenKubes classifies `ok-mgmt` as a **Tier-0 lifecycle control plane** with a stricter
protection, recovery, access, and change-management profile than an ordinary workload
cluster.

The normative availability and recovery invariants are:

> **Loss of the management plane must interrupt lifecycle reconciliation, not the
> runtime availability of otherwise healthy and management-independent workload
> clusters.**

> **Recovery must restore or explicitly reconstruct the authoritative lifecycle state
> before controllers are allowed to reconcile existing infrastructure.**

> **At most one management plane may actively reconcile a given OpenKubes lifecycle
> object graph and its provider resources.**

### 1. Failure classes

The recovery profile must distinguish at least:

| Class | Failure | Expected response |
|---|---|---|
| A | API/controller outage; persisted state intact | Restart the same management plane and resume reconciliation |
| B | Management node or etcd quorum failure; recoverable members/storage remain | Restore quorum or the latest accepted snapshot, then validate before resume |
| C | Complete ok-mgmt cluster/etcd loss; infrastructure plane remains | Build a fenced replacement, restore authoritative state, validate external resources, then activate |
| D | ok-mgmt and its hosting infrastructure failure | Recover the infrastructure plane or activate a predesigned replacement site, then perform Class C recovery |

HA mitigates Classes A and some Class B failures. It does not replace backup/restore for
Classes C and D.

### 2. Protected state

The disaster-recovery profile must inventory and protect all state required to resume
safe lifecycle reconciliation, including:

- the ok-mgmt Kubernetes/etcd state containing CAPI, provider, Crossplane, policy,
  registration, finalizer, and ownership objects;
- the authoritative Git repositories and immutable revisions for desired state;
- management-cluster bootstrap configuration and exact Kubernetes, CAPI, CAPK,
  Crossplane, policy, Enablement, and GitOps component versions;
- provider credentials, workload registration credentials, encryption keys, CA
  material, and the external secret references or custody needed to recover them;
- network endpoints, DNS, certificates, infrastructure identifiers, and provider
  configuration required to reconnect to existing resources;
- operation, policy, audit, and terminal lifecycle evidence that must survive loss of
  ok-mgmt; and
- a baseline inventory joining each workload Cluster, CAPI object UID, Machine, Node,
  and external provider resource.

Git is necessary but insufficient. Rendered manifests, Executor-local files, workload
kubeconfigs, or provider inventories are not substitutes for the authoritative etcd
state.

### 3. Backup operating model

The first production profile must define and enforce:

- numeric RPO and RTO objectives derived from the accepted lifecycle failure budget;
- backup cadence and event-driven backups before management-plane upgrades or high-risk
  lifecycle migrations;
- a named owner and escalation path;
- encrypted storage outside the ok-mgmt and hosting-infrastructure failure domains;
- access control, key custody, retention, expiry, and secure deletion;
- integrity verification and an immutable backup register;
- compatibility metadata for Kubernetes and every lifecycle provider version; and
- a periodic restore rehearsal, not merely successful snapshot creation.

A snapshot stored only on ok-mgmt, its VMs, or the same unprotected infrastructure
plane is not a conforming disaster-recovery backup.

### 4. Recovery and fencing

Recovery is fail-closed. Before a replacement management plane can reach provider APIs
with mutating credentials, the old plane must be demonstrably stopped, isolated, or
credential-fenced. A future `ok-mgmt-shadow` is active-passive unless another ADR proves
a safe multi-writer ownership model; installing the same CAPI providers on two active
clusters does not create safe HA.

The recovery sequence must:

1. classify and declare the incident;
2. fence the old management plane and suspend new lifecycle operations;
3. establish a known-compatible base management cluster;
4. restore the authoritative state and required secret/key custody;
5. keep reconcilers paused or provider credentials fenced while validating API health,
   object identities, versions, finalizers, credentials, and external infrastructure;
6. compare the restored object graph with the independently captured provider and
   workload inventory;
7. identify pending deletes, upgrades, remediations, and generation changes that would
   execute when reconciliation resumes;
8. resume in a controlled order or canary scope, then expand only after evidence shows
   no duplicate or unintended destructive action;
9. verify Conditions can be rebuilt from observed state and lifecycle remediation works
   without the original Executor; and
10. record the recovery outcome, achieved RPO/RTO, residual resources, and operator
    decisions in the external evidence store.

Recovery success is not "the API server answers." It requires safe lifecycle
reconciliation of existing workload clusters and proof that exactly one authoritative
management plane is active.

### 5. `clusterctl move` is not the DR mechanism

> **`clusterctl move` is not the disaster-recovery strategy for ok-mgmt.**

It may be used for a planned, healthy bootstrap/pivot or as one step in a separately
validated migration profile. It must not be presented as backup/restore. OpenKubes must
not depend on it to recover an already lost or unstable source management plane.

### 6. No-snapshot and orphan recovery

If no valid authoritative backup exists, OpenKubes enters an explicit **orphan recovery
mode**. It must not blindly reapply cluster manifests or permit controllers to create,
adopt, update, or delete external provider resources.

Orphan recovery requires:

- provider-side and workload-side inventory independent of the lost management plane;
- stable mapping between Cluster/Machine intent and existing external resources;
- per-cluster disposition: adopt, leave unmanaged, migrate, or recreate;
- explicit human authorization and a dry-run/diff for each disposition;
- provider-specific proof that adoption preserves identity and ownership; and
- an auditable residual-resource and credential-revocation record.

Until a provider profile proves adoption semantics, `leave unmanaged` or controlled
recreation are safer than claiming automatic adoption. Force-finalization and manual
provider cleanup remain separate break-glass operations.

### 7. Runtime dependency declaration

Every workload and platform profile must declare whether it has runtime dependencies on
ok-mgmt. In-cluster Kubernetes controllers and GitOps may continue during a management
outage; centralized GitOps and management-hosted services do not. OpenKubes must not
claim workload runtime independence when an undeclared identity, secret, network,
storage, ingress, or application dependency still requires ok-mgmt.

The ADR-030 management-plane-outage scenario validates the declared dependency for the
first KubeVirt forcing profile.

## Rationale

1. **Protects the real authority.** Non-authoritative Executors are recoverable only if
   the authoritative management state is recoverable.
2. **Separates HA from DR.** Replicas reduce outage probability; externally stored,
   tested recovery handles total state loss.
3. **Prevents dual reconciliation.** Fencing avoids two CAPI/CAPK installations acting
   on the same external resources.
4. **Avoids false Git recovery claims.** Git preserves desired declarations but not the
   entire CAPI object graph, identity, secret, and finalizer state.
5. **Makes recovery evidence-based.** A restore rehearsal proves controller behavior,
   not just snapshot readability.

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| Recreate ok-mgmt and reapply Git/manifests | Does not preserve all object identity, status, ownership, finalizer, secret, and provider state; may duplicate or delete infrastructure |
| Use `clusterctl move --to-directory/--from-directory` as backup/restore | CAPI documents move as bootstrap/pivot-oriented and not designed for backup/restore; status is not restored |
| Rely only on ok-mgmt HA | HA does not protect against corruption, operator error, credential loss, site loss, or total etcd loss |
| Run ok-mgmt and ok-mgmt-shadow active-active | Two active reconcilers against the same resources create split-brain and destructive-action risk without a proven ownership protocol |
| Keep backups on ok-mgmt or the same host | The backup shares the failure domain it is supposed to recover |
| Automatically adopt orphaned provider resources | Provider adoption is not a generic CAPI guarantee and must be proved per profile |

## Consequences

**Positive:**

- Temporary management outages are separated from permanent lifecycle-state loss.
- Recovery has a safe resume gate before controllers can mutate existing resources.
- Backup scope includes credentials, versions, inventory, and evidence rather than etcd
  snapshots alone.
- A future shadow management plane has an explicit fencing and single-writer contract.

**Negative / trade-offs:**

- Tier-0 backup, external custody, restore drills, and inventory increase operational
  cost.
- Fenced restore is slower than immediately applying manifests to a fresh cluster.
- Numeric RPO/RTO and retention commitments create capacity and on-call obligations.
- Provider-specific orphan adoption may be unavailable, leaving manual recovery or
  controlled recreation as the only honest fallback.

**Neutral:**

- This ADR does not select a backup product, object store, policy engine, or shadow
  replication technology.
- It does not make ok-mgmt part of the workload data path.
- It does not define infrastructure-plane or workload-application disaster recovery.
- It does not modify ADR-Platform-030 or authorize acceptance of that ADR.

## Acceptance conditions

Before this ADR moves to `Accepted`, the first production profile must provide:

1. numeric RPO/RTO, failure budget, owner, cadence, retention, encryption/key custody,
   and external backup location;
2. an automated or operator-run backup procedure with integrity and compatibility
   metadata;
3. a successful restore into a fenced, isolated target using the documented procedure;
4. proof that restored CAPI/CAPK/Crossplane objects retain the identities and
   relationships needed to observe existing KubeVirt workload clusters;
5. an external-resource diff and a controlled reconciliation resume with no duplicate
   VM, unintended delete, or second active management plane;
6. a post-restore MachineHealthCheck/remediation and current-generation Condition
   convergence without the original Executor;
7. successful execution of the ADR-030 management-plane-outage scenario;
8. an independently stored audit/evidence record with achieved RPO/RTO;
9. a tested credential-fencing and old-plane reappearance procedure; and
10. a no-valid-snapshot/orphan-recovery runbook with explicit non-claims about automatic
    adoption.

Design review, HA deployment, or snapshot creation without a restore rehearsal is
insufficient for acceptance.

## Re-evaluation triggers

- A second infrastructure provider proves different snapshot, identity, or adoption
  semantics.
- `ok-mgmt-shadow` implementation begins.
- A disconnected Constraint Envelope cannot reach the selected external backup or key
  custody profile.
- CAPI introduces and validates a purpose-built management backup/restore contract.
- A platform service becomes a hard runtime dependency for workload clusters during
  management-plane outage.

## References

- [Cluster API concepts — management clusters and Machines](https://cluster-api.sigs.k8s.io/user/concepts)
- [Cluster API MachineHealthCheck](https://main.cluster-api.sigs.k8s.io/tasks/automated-machine-management/healthchecking)
- [Cluster API `clusterctl move` warnings](https://cluster-api.sigs.k8s.io/clusterctl/commands/move)
- [Cluster API production management-cluster guidance](https://main.cluster-api.sigs.k8s.io/user/quick-start)
