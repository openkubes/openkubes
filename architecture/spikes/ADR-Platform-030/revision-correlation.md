# OK-141 Revision Correlation

Status: **Read-only interpretation of the recorded snapshot; no component decision**

Source snapshot: [condition-observation.md](condition-observation.md)

## Question

Which observed status belongs to which desired revision? Where is correlation
explicit, where is it inferred, and where is it impossible with the current system?

## Correlation vocabulary

| Classification | Meaning |
|---|---|
| **Explicit** | A stable identity/revision is carried by both records or by an authoritative reference between them |
| **Structural** | Kubernetes ownership or provider labels establish a resource relationship, but not a desired OpenKubes revision |
| **Inferred** | Values/names/timestamps agree, but no shared immutable identity proves the relationship |
| **Impossible now** | A required object, revision field or authoritative record is absent |

Value equality is never upgraded from **Inferred** to **Explicit** merely because the
values look correct.

## Observed relationship graph

```text
Local ok-cluster commit 61f9bd55...
└── ok-ai/cluster-config.yaml
    ├── name ok-ai
    ├── Kubernetes v1.34.1
    ├── Talos v1.9.5
    ├── endpoint 192.168.100.201
    └── topology 1 control plane + 3 workers
          │
          │ value/name match only
          ▼
Current ok-mgmt
├── CAPI Cluster: absent
├── InfraCluster: absent
├── ControlPlane: absent
├── MachineDeployment/Machines: absent
├── Crossplane cluster intent: absent
└── Argo Application API: absent

ok-infra provider inventory
├── Service ok-ai-lb → 192.168.100.201
└── 4 KubeVirt VMs labeled cluster-name=ok-ai
      │ exact machine-name match
      ▼
ok-ai workload
├── 4 Kubernetes Nodes
└── Cilium Helm revision 2 / version 1.19.6
```

The graph has a continuous runtime identity chain between KubeVirt VM names and
workload Node names. It does not have a continuous desired-revision chain from the
local file or an OpenKubes contract through CAPI to those runtime objects.

## Pairwise correlation

| From | To | Evidence | Classification | Limitation |
|---|---|---|---|---|
| Local config `name=ok-ai` | Provider namespace/VM labels | Same cluster name | Inferred | Cluster name is mutable/reusable and is not a revision |
| Local endpoint `192.168.100.201` | `ok-ai-lb` VIP and workload API endpoint | Exact value equality | Inferred | No allocation claim/UID or file hash is recorded on the Service |
| Local topology 1+3 | Four provider VMs and four workload Nodes | Role labels and counts agree | Inferred | No contract generation establishes that this is the requested current count |
| Local Kubernetes/Talos versions | Workload Node versions | Exact `v1.34.1` / `v1.9.5` equality | Inferred | No source commit/config hash is carried by Nodes |
| KubeVirt VM | KubeVirt VMI | VMI owner reference names and UID of VM | Explicit | Links provider objects only |
| KubeVirt VM/VMI | Workload Node | Exact machine name and CAPK labels; corresponding provider ID convention | Structural | Cross-cluster Kubernetes owner references cannot establish it; no CAPI Machine remains |
| Provider VMs | Current `ok-mgmt` CAPI resources | No CAPI objects exist | Impossible now | Lifecycle authority and desired generation cannot be reconstructed from current CAPI state |
| Local config | Crossplane intent | No claim/composite instance exists | Impossible now | No accepted generation or operation identity |
| Cilium Helm release | Cilium workload resources | Helm ownership annotations, version and image identity | Structural | Helm revision 2 is not linked to OpenKubes intent |
| Cilium resources | Local cluster config | No CNI version/config identity exists in the local cluster config | Impossible now | Runtime Cilium config hash cannot be compared to a declared desired hash |
| Platform desired revision | Argo status | Argo API and Applications absent | Impossible now | No platform root, sync revision or health status exists |

## Timeline correlation

| Time | Observation | Correlation strength |
|---|---|---|
| `2026-07-21T13:45:03Z` | `ok-ai` infrastructure namespace created | Runtime timestamp only |
| `2026-07-21T13:45:18Z`–`13:45:19Z` | Four KubeVirt VMs created | Provider object identity |
| `2026-07-21T13:47:00Z`–`13:47:30Z` | VMs became `Ready` | Provider condition transitions |
| `2026-07-21T13:48:27Z`–`13:48:39Z` | Workload Nodes created | Runtime object identity |
| `2026-07-21T13:48:49Z` | Cilium DaemonSet/operator created | Workload add-on identity |
| `2026-07-21T13:49:09Z`–`13:49:31Z` | Nodes became `Ready` | Workload condition transitions |
| `2026-07-22T13:24:58Z` | Current CAPI controller Deployment object created | Management component timestamp, not cluster revision |
| `2026-07-22T15:25:42+02:00` | Cilium Helm release revision 2 recorded | Add-on revision only |
| `2026-07-30T08:18:44+02:00` | Latest local commit touching `ok-ai` inputs | Local Git revision only; later than cluster creation |
| `2026-08-09T09:57:33Z`–`09:58:36Z` | Read-only snapshot | Observation time |

The local commit observed for `ok-ai` is later than the workload's creation. It may
describe a later profile update, but no runtime annotation, CAPI generation or
operation record proves whether or how that commit was applied.

## Desired OpenKubes condition assessment

The classifications below use the requested A/B/C/D condition test, not the overall
operator outcomes A/B/C/D.

| Desired condition | Current evidence path | Condition mode | Result |
|---|---|---|---|
| `InfrastructureReady` | Four KubeVirt VMs have `Ready=True`, matching cluster labels and `observedGeneration=1` | Deterministically derivable from provider inventory for this snapshot | **B**, but not correlated to an accepted OpenKubes revision |
| `ControlPlaneAvailable` | Control-plane VM `Ready=True`; control-plane workload Node `Ready=True`; API responds | Deterministically derivable as an observation | **B**, but weaker than a control-plane provider's authoritative `Available` condition |
| `NetworkReady` | All Nodes have `NetworkUnavailable=False/CiliumIsUp`; Cilium DS is 4/4; operator is available; pinned images/config hash observed | Deterministically derivable for the observed runtime identity | **B/C candidate**, because no durable profile root publishes it and no desired Cilium revision is declared |
| `EnablementReady` | Only network observations were captured | Not derivable until the profile defines all required enablement capabilities | **D not proven**; semantic root is missing before writer choice |
| `PlatformReady` | No Argo API/Application or other platform-profile root | Not derivable | **D not proven**; first define/find an authoritative GitOps root |
| Aggregate `Ready` | Infrastructure, control plane and network appear healthy; enablement/platform revision sources are absent | Must remain unknown for ADR-030 semantics | Derived only after required sources and revisions exist |

### Why these are not current-generation success claims

The provider VM and Cilium objects have internally current generations:

```text
VM metadata.generation=1
VM status.observedGeneration=1

Cilium DaemonSet metadata.generation=1
Cilium DaemonSet status.observedGeneration=1
```

That proves each controller observed its own object generation. It does **not** prove:

```text
OpenKubes desired revision R
    → projected into VM generation 1
    → projected into Cilium generation 1
```

No shared `R` exists in the observed runtime records.

## Explicit gaps exposed by the snapshot

### 1. Current lifecycle authority cannot be demonstrated

The current `ok-mgmt` serves healthy CAPI/CAPK controllers and CRDs but contains no
`ok-ai` lifecycle objects. The provider VMs have CAPK/CAPI labels, but no current
management object chain was observed.

This snapshot cannot determine whether:

- the original management state was removed or replaced;
- another management plane still owns these resources; or
- the running provider objects are intentionally retained outside current CAPI
  authority.

It therefore records **management correlation absent**, not “successfully adopted”
and not a proven orphan-recovery state.

### 2. Allocation identity is absent

The endpoint value agrees across local config, provider Service and workload API.
There is no observed allocation claim, reservation UID or allocation revision. The
same is true for pod/service CIDRs.

### 3. Enablement has runtime identity but no desired identity

Cilium is observable down to Helm revision, image digests, object generations and a
configuration hash. No OpenKubes/profile record declares which of those identities is
desired for `ok-ai`.

### 4. Platform correlation is impossible

No Argo CD Application API was served on management or workload. The documented
future `ok-gitops`/Argo model is not an observed platform status source in this
snapshot.

### 5. Evidence exists after the fact

The snapshot can persist facts with timestamps and hashes, but no accepted operation
ID or contract generation links them to an authorization decision.

## Gap type after correlation

| Gap | Evidence from snapshot | Current type |
|---|---|---|
| Allocation authority | Values agree; no reservation identity | Potential desired-state authority |
| Enablement/profile root | Cilium runtime is healthy; desired profile/revision absent | Contract-root/ownership gap before reconciliation decision |
| Revision correlation | No shared immutable revision across local, CAPI, provider, Cilium and platform | Correlation/status gap |
| Condition normalization | Provider/workload signals are deterministically readable | Primarily derivation/presentation candidate |
| Evidence persistence | Facts can be captured but are not linked to authorization/intent | Evidence/audit gap |

Only the first two could plausibly force durable OpenKubes reconciliation, and neither
does so based on this snapshot alone.

## Authority and revision evidence matrix

The disposable-cluster test must prove two different chains. A healthy revision chain
does not prove that the correct management plane has lifecycle authority, and an active
lifecycle writer does not prove that it is reconciling the requested OpenKubes revision.

```text
Authority chain
  intent owner
    -> management-plane identity
    -> authorized active writer set
    -> CAPI ownership
    -> provider resources

Revision chain
  OpenKubes intent R
    -> CAPI projection
    -> infrastructure identities and observed generations
    -> enablement revision E
    -> platform revision P
    -> generation-correct derived Conditions
```

The matrix below defines the missing proof without selecting an OpenKubes Operator or
a new public API. A **candidate carrier** is metadata or an existing durable record to
test first, not an accepted schema decision.

| Unknown to resolve | Required evidence | Candidate carrier or relationship to test | Authoritative observer | Acceptance rule |
|---|---|---|---|---|
| Originating intent | Immutable normalized intent revision `R`, contract identity, and accepted generation | Git commit plus normalized contract digest; or contract UID/generation plus digest | Declared authoritative persistence path | One accepted `R` is recoverable independently of the Executor and cannot be confused with a later edit |
| Authorization and operation | Policy decision bound to actor, operation, target, before/after revisions, and correlation ID | Admission/audit record or durable operation evidence keyed by `R` | Policy/audit system outside Executor-local state | The mutation from the prior revision to `R` and the authorizing identity are independently auditable |
| Allocation authority | Allocation UID/revision for endpoint, Pod CIDR, Service CIDR, and any other scarce value | Existing allocation record referenced from the contract and projected objects | Declared allocation authority | Observed values match one current allocation record; value equality alone does not pass |
| Owning management plane | Stable management-plane identity recorded with the lifecycle projection | Management-plane ID plus authority epoch/reference on the top-level lifecycle object and evidence record | Independent management/DR inventory | The CAPI object graph names the expected management authority; API address or reachability alone does not pass |
| Current lifecycle writer | Complete set of components allowed to mutate lifecycle state and proof that no competing authority is active | Controller inventory, leader-election records, scoped credentials, authority epoch, and fencing evidence where another plane exists | Independent authority observer defined by ADR-031 | All declared writers belong to one authority; an old API being unreachable is not fencing evidence |
| Intent-to-CAPI projection | Exact `R` associated with the projected CAPI object identity and desired spec | Revision/digest metadata on `Cluster` or topology root plus a projection record | CAPI API and the declared projection mechanism | The current top-level CAPI UID/spec is explicitly linked to `R`; matching names or values do not pass |
| Object-local reconciliation | Desired spec identity, object UID, `metadata.generation`, and current `status.observedGeneration` for every required CAPI/provider object | OwnerReferences plus per-object spec digest/revision metadata | Each owning controller's API status | Every required object has observed its own current generation and its desired spec is traceable to `R` |
| Machine-to-VM identity | CAPI `Machine` and infrastructure-machine UID chain to the exact KubeVirt VM/VMI | OwnerReferences, provider resource reference, CAPK labels, and provider ID | CAPI/CAPK and KubeVirt APIs | Exactly one current VM/VMI is attributable to each current Machine; names alone do not pass |
| Machine-to-Node identity | Exact current Machine to workload Node relationship | `Machine.status.nodeRef`, Node UID, and `spec.providerID` matched to the provider object | CAPI API plus workload API | Each expected Machine resolves to exactly one current Node and provider identity |
| Intended enablement revision | Profile identity and immutable enablement revision `E`, including CNI chart/image/config identity | Profile digest and controller-owned enablement root projected to Cilium/Helm resources | Declared Enablement owner | `E` is explicit, durable, linked to `R`, and the observed CNI resources resolve to `E` |
| `NetworkReady` outcome | Desired `E` present; required agents available; Node networking established; required control components available; declared functional probe passes | Enablement Conditions plus Cilium DaemonSet/operator status, Node Conditions, image/config identities, and profile-defined probe evidence | Declared Enablement owner; OpenKubes only normalizes | All profile-required signals are current for `E`; DaemonSet availability alone does not pass |
| Intended platform revision | Platform profile identity and immutable GitOps revision `P` | Git commit/chart/profile digest on the authoritative GitOps root | Selected GitOps controller/API | `P` is explicit, linked to `R`, and is the revision reported as applied rather than merely requested |
| `PlatformReady` outcome | Sync, health, and required platform capability results for `P` | GitOps status and profile-defined contract checks | Selected GitOps/platform owner; OpenKubes only normalizes | Every required platform result is healthy for the exact applied `P` |
| Aggregate lifecycle result | Required source Conditions for `R`, including their source revisions, Reasons, and observation times | Durable status/evidence record derived from the authoritative sources | Single declared status aggregator or read-only evidence evaluator | `Ready=True` only when every profile-required source is current and explicitly correlated to `R`; Executor exit never counts |
| Evidence persistence | Tamper-evident bundle linking authorization, `R`, CAPI identities, `E`, `P`, Conditions, timestamps, and outcome | Evidence manifest with content hashes stored outside ephemeral Executor and disposable cluster state | Evidence store and independent reviewer | The full proof survives Executor loss and later cluster deletion and can be re-verified from recorded hashes |

### Correlation rules for the test

The disposable test must enforce these rules before any result is called correlated:

1. Kubernetes `metadata.generation` is object-local. Equal or adjacent generation
   numbers on different objects do not establish a revision relationship.
2. Names, IP addresses, replica counts, versions, and timestamps are supporting facts,
   not immutable identity anchors.
3. Runtime health does not prove lifecycle authority, and lifecycle authority does not
   prove revision provenance.
4. A controller's leader-election record proves leadership only inside its configured
   election domain; it does not by itself exclude an undeclared management plane.
5. `PreviousAPIUnreachable` is not equivalent to `PreviousAuthorityFenced`.
6. Normalized Conditions may preserve or derive source status, but they may not invent
   a correlation that the source evidence cannot prove.

### Read-only gate before disposable creation

Before the mutation gate can be evaluated, every row above must identify:

- an exact sensor or query;
- the failure domain from which that observation is collected;
- the raw artifact and fields to retain;
- the correlation assertion and its negative control; and
- the reviewer responsible for accepting that evidence.

This planning gate can pass without deciding that a new Operator, CRD, or status
aggregator is required. A missing carrier remains a test-design gap until existing
mechanisms have been evaluated. Completing this matrix does not change the outage
preflight: infrastructure mutation remains `NO-GO`.

## Next evidence gate

A complete current-generation correlation test now requires a deliberately created,
disposable cluster whose lifecycle objects remain in `ok-mgmt`. Before creation, the
test must define immutable identities for:

1. accepted input/contract revision;
2. allocated endpoint/CIDRs;
3. CAPI projection generation;
4. enablement profile and Cilium config/version;
5. GitOps platform root and Git revision; and
6. authorization/evidence correlation ID.

The first follow-up can still be non-destructive to existing clusters: prepare a
fixture or disposable-cluster observation plan and define which existing object
metadata can carry correlation. Actual creation remains behind the existing GO/NO-GO
gate.

## Decision impact

Overall operator outcome **A/B/C/D remains unclassified**.

The snapshot strengthens two conclusions:

- existing runtime health can largely be observed and deterministically derived
  without an OpenKubes lifecycle operator; and
- the current environment cannot prove end-to-end revision correlation because the
  management lifecycle objects and platform root are absent.

This is evidence for a narrower problem, not evidence for building a broad operator.
Infrastructure mutation remains **NO-GO**.
