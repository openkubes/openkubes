# OK-141 Condition Source Map

Status: **Read-only source and ownership analysis; no aggregator decision**

Recorded: 2026-08-09

OpenKubes baseline: `97cbeeb`

`ok-cluster` baseline: `430b946` (`main`)

## Question

Who writes each condition or readiness signal today, which source is authoritative
for the fact it represents, and which ADR-030 conditions have no durable source?

This analysis distinguishes:

- **source condition** — written by the controller that owns the resource/fact;
- **mirrored or summarized condition** — written by a higher-level controller from
  one or more source conditions;
- **procedural observation** — evaluated by a script/process and not published as a
  durable condition; and
- **proposed normalized condition** — named by ADR-030 but not necessarily implemented.

No new status API or condition writer is selected here.

## Version and evidence boundary

The current evidence combines:

- historical v4.2 scripts that wait for deprecated v1beta1-style Cluster conditions;
- current `ok-cluster` paths using CAPI `v1beta2` resources and CAPI `v1.13.3`;
- CAPK `v0.11.2`, which retains provider-contract compatibility behavior; and
- runtime evidence that records CAPI `Available`, Kubernetes Node `Ready`, Cilium
  health and timestamps, but does not preserve complete live status objects.

No live cluster state is relied upon. Therefore “writer” assignments below come from
controller contracts and source code paths; exact live condition payloads remain a
future read-only evidence capture.

Primary CAPI references:

- [CAPI v1beta2 API reference](https://cluster-api.sigs.k8s.io/reference/api/crd-api-reference)
- [InfraCluster provider contract](https://cluster-api.sigs.k8s.io/developer/providers/contracts/infra-cluster)
- [ControlPlane provider contract](https://cluster-api.sigs.k8s.io/developer/providers/contracts/control-plane)

## CAPI condition propagation in v1beta2

CAPI `v1beta2` already supplies a substantial condition hierarchy:

```text
InfraCluster Ready
    └── mirrored by CAPI Cluster controller
        as Cluster InfrastructureReady

ControlPlane Available
    └── mirrored by CAPI Cluster controller
        as Cluster ControlPlaneAvailable

Machine / MachineDeployment / MachinePool conditions
    └── summarized by CAPI Cluster controller
        as WorkersAvailable, MachinesReady, MachinesUpToDate, ...

Managed Topology reconciliation
    └── ClusterTopology controller
        writes Cluster TopologyReconciled

Cluster conditions + optional availability gates
    └── CAPI Cluster controller
        derives Cluster Available
```

The CAPI `Cluster` controller is therefore the authoritative writer of the CAPI
Cluster-level summaries, but not the originating authority for provider or
control-plane facts. The originating resource and its owning controller remain the
source of truth.

The v1beta2 API lists known Cluster conditions including `Available`,
`InfrastructureReady`, `ControlPlaneInitialized`, `ControlPlaneAvailable`,
`WorkersAvailable`, `MachinesReady`, `MachinesUpToDate` and, for managed topology,
`TopologyReconciled`. `Cluster.status.observedGeneration` records the latest
generation observed by the Cluster controller.

## Current source map

| Fact / signal | Originating source | Current writer | Higher-level projection | Authority classification |
|---|---|---|---|---|
| Infrastructure cluster provisioned/operational | `KubevirtCluster` or other InfraCluster | CAPK/CAPO infrastructure controller | CAPI Cluster controller mirrors InfraCluster `Ready` as `InfrastructureReady` | Provider is source; CAPI Cluster condition is authoritative summary |
| Control plane initialized/API first reachable | `KubeadmControlPlane`/`TalosControlPlane` or Machines | Control-plane provider | CAPI Cluster controller exposes `ControlPlaneInitialized` | Control-plane provider is source; initialization is not ongoing availability |
| Control plane currently available | ControlPlane `Available` | KCP or other control-plane provider | CAPI Cluster controller mirrors as `ControlPlaneAvailable` | Control-plane provider is source; CAPI Cluster condition is authoritative summary |
| Worker deployment available | MachineDeployment/MachineSet/Machines | CAPI MD/MS/Machine controllers | CAPI Cluster controller summarizes as `WorkersAvailable` | CAPI-owned at both source and summary layers |
| Machines ready/up to date | Machine conditions and owning scalable resources | CAPI Machine/KCP/MD/MS controllers | Cluster `MachinesReady`/`MachinesUpToDate` | CAPI-owned lifecycle fact |
| Machine health/remediation | MachineHealthCheck and Machine owner | CAPI MHC and owner controller | Machine/Cluster remediation conditions/events | CAPI-owned lifecycle fact; not OpenKubes `Ready` |
| Topology projection applied | Managed topology graph | ClusterTopology controller | Cluster `TopologyReconciled` | Authoritative only when managed topology is enabled |
| Workload node healthy | Kubernetes `Node.status.conditions[Ready]` | kubelet/node lifecycle controller | Scripts currently wait/read Node `Ready` | Workload API is source; script result is not a durable management condition |
| Cilium agents/operator healthy | DaemonSet/Deployment status and `cilium status` | Kubernetes workload controllers/Cilium | `ok-cluster` runtime evidence records PASS/timestamp | Workload/Cilium is source; no durable OpenKubes `NetworkReady` exists |
| Crossplane composition/job completed | Job and Crossplane composite conditions | Job controller/Crossplane | v4.2 XRD status exposes phase/job | Authoritative for execution/composition only, not cluster lifecycle outcome |
| Helm-installed add-on ready | Crossplane Helm Release or workload resources | Helm provider/workload controller | Make targets poll `Ready` | Add-on-specific source; not a platform aggregate |
| GitOps application reconciled | Argo CD `Application` (the architecture-documented target) | Argo CD application controller | Sync status, health status, operation phase and Git revision | Authoritative for that Application/revision only |
| Platform profile converged | Set of profile-required GitOps objects | No single current source identified | None in reviewed OpenKubes contract | **Missing durable aggregate semantic** |
| Requested OpenKubes generation reconciled | Cross-layer correlation of intent and source observations | No current writer | None | **Missing correlation semantic** |
| Durable operation evidence complete | Policy/audit/status/Git/evidence records | Spike tooling and individual systems | Evidence files | **No single product mechanism selected** |

OpenKubes architecture references `ok-gitops` with Argo CD, although no `ok-gitops`
repository or implemented platform-profile root was present in the reviewed
workspace. Argo CD exposes separate sync and health status plus the targeted Git
revision. Those signals can source a platform outcome, but one Application being
`Synced` and `Healthy` does not establish an entire OpenKubes platform profile unless
that Application is deliberately defined as the authoritative profile root.

- [`ok-cluster` repository map](../../../../ok-cluster/README.md)
- [Argo CD automated sync semantics](https://argo-cd.readthedocs.io/en/stable/user-guide/auto_sync/)
- [Argo CD health and sync status](https://argo-cd.readthedocs.io/en/stable/user-guide/status-badge/)
- [Argo CD revision-aware notification example](https://argo-cd.readthedocs.io/en/stable/operator-manual/notifications/triggers/)

## ADR-030 normalized-name assessment

| ADR-030 name | Closest current durable source | Can be used directly? | Missing semantics / risk |
|---|---|---|---|
| `InfrastructureReady` | CAPI Cluster `InfrastructureReady`, mirrored from InfraCluster `Ready` | **Mostly yes** for CAPI infrastructure | Must preserve source reason/message and verify current generation/provider contract behavior |
| `ControlPlaneReady` | In v1beta2, CAPI uses `ControlPlaneAvailable`; historical scripts wait for deprecated `ControlPlaneReady` | **Rename/semantic alignment required** | “Ready” and “Available” are not automatically identical; ongoing availability is the stronger v1beta2 source |
| `NetworkReady` | Node `Ready`, Cilium DaemonSet/Deployment availability and `cilium status` | **No single current condition** | API reachability or Nodes alone cannot prove the selected network implementation/version is reconciled |
| `EnablementReady` | No durable aggregate source | **No** | Must define profile-required minimum capabilities and correlate each to its owning source |
| `PlatformReady` | Argo CD Application sync/health plus targeted revision, or add-on-specific status | **No single current condition** | Need an explicit profile root or deterministic set of required Applications/resources/revisions |
| `Ready` | CAPI Cluster `Available` covers CAPI availability, not full OpenKubes readiness | **No, not for current ADR meaning** | Must not relabel CAPI `Available` as enablement+platform success |

### Important naming correction

The historical v4.2 waiter uses:

```text
Cluster InfrastructureReady
Cluster ControlPlaneReady
```

The CAPI `v1beta2` contract uses:

```text
Cluster InfrastructureReady
Cluster ControlPlaneAvailable
Cluster Available
```

Current `ok-cluster` evidence code already checks `Available` with a legacy `Ready`
fallback. The spike should not freeze the historical `ControlPlaneReady` label into a
new contract without first choosing its intended semantics.

Evidence:

- [v4.2 `wait-cluster.sh`](../../../platform/cluster-management/capi-platform-v4.2/scripts/wait-cluster.sh)
- [`ok-cluster` runtime validation](../../../../ok-cluster/scripts/adoption/OK-125/runtime.py)
- [recorded node/Cilium evidence](../../../../ok-cluster/docs/adoption/OK-125/.evidence/node-ready.json)

## Authoritative versus observed

The following rule emerges from the current system:

```text
Provider/controller-owned Condition
    = authoritative for its own resource fact

Higher-level CAPI mirrored/summary Condition
    = authoritative projection for the CAPI Cluster lifecycle

Script wait, process exit or evidence collector assertion
    = observation, never lifecycle authority
```

Examples:

- CAPK writes the InfraCluster fact; CAPI writes the Cluster-level
  `InfrastructureReady` projection.
- KCP writes ControlPlane `Available`; CAPI writes `ControlPlaneAvailable`.
- Kubelet and Cilium/workload controllers write their own status; the current Make
  process only observes it.
- Argo CD writes sync/health/revision status for its Application; a CLI cannot promote
  that observation into `PlatformReady` without a defined platform-profile root and
  revision correlation.

## Can CAPI `Available` become the OpenKubes aggregate?

CAPI `v1beta2` supports `Cluster.spec.availabilityGates` and ClusterClass-level
availability gates. They add named Cluster conditions to the evaluation of CAPI
`Available`. This is a relevant existing capability because it may reduce custom
aggregation logic.

It is not yet sufficient evidence for ADR-030 because the spike has not established:

- which durable controller would write `NetworkReady`, `EnablementReady`, or
  `PlatformReady` onto the CAPI Cluster;
- how those writers correlate their observations with an OpenKubes requested
  generation or Git revision;
- whether mixing multiple field owners on CAPI Cluster status is supported by the
  chosen implementations and governance model; or
- whether CAPI `Available` has exactly the desired OpenKubes product semantics.

Therefore availability gates are a capability to test before creating a status
aggregator, not proof that no adapter is needed and not permission to extend CAPI
status ad hoc.

## Gap classification

| Gap | Reconciliation gap? | Current assessment |
|---|---|---|
| CAPI infrastructure/control-plane/machine conditions | No | Existing controllers already own and summarize these facts |
| Network status source | Possibly | Low-level sources exist; durable intent/version correlation and one published condition do not |
| Enablement aggregation | Possibly | Depends on whether an existing add-on mechanism can own a profile root and condition |
| Platform aggregation | Not necessarily | A GitOps profile root may supply sufficient revision-aware readiness |
| Cross-layer normalization | Not necessarily | Could be a read-only derived view, CAPI availability gates, composition status, or thin adapter |
| Requested-generation correlation | Semantic/evidence gap | Must be proven; does not automatically require lifecycle reconciliation |
| Evidence persistence | No by itself | Audit/event/Git/evidence mechanisms may be composed without owning lifecycle |

## Findings

1. **CAPI already owns authoritative lifecycle conditions through a source-and-summary
   hierarchy.** OpenKubes should consume it rather than rewrite it.
2. **`NetworkReady`, `EnablementReady` and profile-level `PlatformReady` have no
   durable current writers in the reviewed implementation.** Current scripts observe
   lower-level facts and record process-local or file evidence.
3. **The largest missing semantic is correlation.** A true source condition must be
   tied to the intended network/platform profile and requested revision, not merely
   be `True` at observation time.
4. **CAPI availability gates and GitOps root-object readiness are existing mechanisms
   that must be evaluated before selecting an OpenKubes status aggregator.**
5. **ADR-030's aggregate writer is still a hypothesis.** The frozen ADR describes the
   target invariant, while this spike must determine whether a new component is
   actually required to satisfy it.

## Required next evidence

The next condition experiment can remain read-only:

1. capture complete status/conditions plus `metadata.generation` and
   `status.observedGeneration` for one current CAPI Cluster, InfraCluster,
   ControlPlane, MachineDeployment and Machines;
2. capture the selected Cilium and GitOps root objects with revisions;
3. trace reason/message propagation from source to CAPI Cluster summaries;
4. test a pure derived view against stale-generation and partial-failure fixtures;
5. compare that result with CAPI availability gates and existing composition status.

Only after this evidence should the spike decide whether the gap is presentation,
normalization, a thin adapter, or genuine reconciliation.

## Decision impact

The result remains **A/B/C/D unclassified**.

The map currently leans away from a broad lifecycle operator: most infrastructure
conditions already have authoritative writers. The unresolved area is narrower—
enablement/platform source definition, revision correlation, normalization and
evidence persistence—but still requires evidence before choosing A or B.

Infrastructure mutation remains **NO-GO**.
