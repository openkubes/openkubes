# OK-141 Contract Inventory

Status: **Read-only inventory; no target API decision**

Recorded: 2026-08-09

OpenKubes baseline: `a6d19b8`

`ok-cluster` baseline: `430b946` (`main`)

`ok-linux` baseline: `49c2445` (`main`)

## Purpose

This inventory records the cluster-lifecycle semantics and state stores that exist
today. It is input to the ADR-030 spike; it is not a proposed OpenKubes API.

The order of work is deliberately:

1. extract existing semantics;
2. identify the current authority and reconciling mechanism;
3. locate gaps or competing authorities;
4. only then decide whether a new contract or component is necessary.

No schema, public API, operator, repository split, or write path is selected by this
document.

## Sources reviewed

| Source | Role in the current implementation | Evidence |
|---|---|---|
| OpenKubes Crossplane API | Self-service claims and Job orchestration | [`xrd.yaml`](../../../platform/cluster-management/crossplane/xrd.yaml), [`xrd-upgrade.yaml`](../../../platform/cluster-management/crossplane/xrd-upgrade.yaml), [`xrd-cleanup.yaml`](../../../platform/cluster-management/crossplane/xrd-cleanup.yaml), [`composition.yaml`](../../../platform/cluster-management/crossplane/composition.yaml) |
| v4.2 runner | Historical rendering, submission, bootstrap, waiting, upgrade and cleanup flow | [`README.md`](../../../platform/cluster-management/capi-platform-v4.2/README.md), [`deploy-full.sh`](../../../platform/cluster-management/capi-platform-v4.2/scripts/deploy-full.sh), [`crossplane-deploy.sh`](../../../platform/cluster-management/capi-platform-v4.2/scripts/crossplane-deploy.sh), [`cleanup.sh`](../../../platform/cluster-management/capi-platform-v4.2/scripts/cleanup.sh) |
| `ok-cluster` | Current cluster configuration, allocation, CAPI rendering and lifecycle commands | [`README.md`](../../../../ok-cluster/README.md), [`render.py`](../../../../ok-cluster/render.py), [`new-cluster.sh`](../../../../ok-cluster/new-cluster.sh), [`Makefile`](../../../../ok-cluster/Makefile) |
| `ok-linux` | OS profiles, image identity and OS build/adoption authority | [`README.md`](../../../../ok-linux/README.md) |
| ADR-030/031 | Proposed execution model and management-plane DR boundary | [ADR-030](../../decisions/ADR-Platform-030-control-plane-execution-model.md), [ADR-031](../../decisions/ADR-Platform-031-ok-mgmt-disaster-recovery.md) |

No `ClusterClass` or Cluster API managed-topology definition was found in the
reviewed OpenKubes or `ok-cluster` sources. Current `ok-cluster` templates render
individual CAPI resources. ClusterClass therefore remains a capability to evaluate,
not an implementation already in use or a preselected target.

## Existing API and configuration surfaces

### Crossplane `KubeVirtClusterClaim`

The v4.2 XRD exposes the following user-visible inputs:

| Field | Expressed meaning | Current use | Observation |
|---|---|---|---|
| `metadata.name` | Cluster identity | Passed into runner environment and CAPI rendering | Stable domain concept |
| `country` | Geographic/configuration selector | Passed to runner | Meaning and authority are not defined by the XRD |
| `provider` | Infrastructure provider | Restricted to `kubevirt` and passed to runner | Domain concept, but API currently binds to one implementation |
| `endpointIP` | Control-plane endpoint | Passed to rendered CAPI objects | Allocation is external to the claim |
| `cni` | CNI choice | Runner installs Calico or Cilium | Desired state is declared, reconciliation is procedural |
| `multus` | Multus enablement | Runner applies Multus | Stored as string `"true"`/`"false"`; implementation-shaped API |
| `controlPlane.replicas` | Control-plane capacity | Rendered to CAPI | CAPI-owned lifecycle input |
| `controlPlane.kubernetesVersion` | Kubernetes target version | Rendered; also changes Job name and triggers upgrade logic | Contract meaning is mixed with Job orchestration |
| `workers.replicas` | Worker capacity | Rendered to CAPI | CAPI-owned lifecycle input |
| `runnerImage` | Executor implementation version | Selects Job image | Implementation detail, not cluster desired state |
| `mgmtKubeconfigSecret` | Management credentials | Mounted into runner Job | Security/wiring detail, not cluster desired state |

The status fields `phase`, `jobName`, and `kubeconfigSecret` primarily expose the
runner/Job implementation. They do not yet provide generation-aware lifecycle,
enablement, and platform conditions.

### Separate operation claims

The current Crossplane surface models upgrade and cleanup as separate desired-state
objects:

| Surface | Inputs | Current execution |
|---|---|---|
| `KubeVirtClusterUpgradeClaim` | cluster name, target version, strategy, provider/country, runner image | Dedicated upgrade composition/Job |
| `KubeVirtClusterCleanupClaim` | cluster name, provider/country, runner image | Dedicated cleanup composition/Job |

This creates multiple workflow records around one cluster. ADR-030 instead requires
operations to be authorized mutations of one authoritative desired state. The spike
must determine how existing mechanisms can satisfy that invariant; this inventory
does not prescribe a replacement CRD.

### `ok-cluster` configuration

The current `ok-cluster` configuration adds semantics that do not exist in the v4.2
XRD:

| Area | Existing semantics |
|---|---|
| Role and topology | cluster type, control-plane/worker replicas and resources |
| Versions | Kubernetes and OS/Talos versions |
| Network | endpoint IP, pod CIDR and service CIDR, with local and live-allocation checks |
| OS | distribution, profile, schematic/image identity |
| Infrastructure | provider profile, identity, node selectors, storage/snapshot/replica constraints |
| Upgrade | blue/green strategy and workload-migration assumptions |
| Platform | imperative targets for CNI, storage, ingress, observability and registration |

`render.py` resolves defaults, allocations, provider profiles and OS information,
then writes resolved configuration and CAPI manifests. Local cluster directories are
therefore both configuration input and part of today's allocation bookkeeping. Live
provider or CAPI checks are used as safeguards, but there is no single server-side
authority for every allocation.

## Lifecycle operation inventory

| Operation | Current entry point | Durable authority after submission | Procedural work still present | ADR-030 question |
|---|---|---|---|---|
| Create | Crossplane claim/runner or `ok-cluster` Make/scripts | CAPI objects in `ok-mgmt` for infrastructure and machines | allocation, rendering, namespace/secret setup, CNI and waits | Can existing APIs submit one authorized transition without a durable executor? |
| Scale | Change rendered CAPI replicas/config and apply | CAPI controllers | local render/apply path | Which surface is authoritative for the requested replica count? |
| Upgrade | Separate upgrade claim/runner or `ok-cluster` blue-green workflow | CAPI reconciles each submitted topology | orchestration, cloned green contract, migration confirmation, old-cluster removal | Can version/strategy be represented as one contract transition without a second workflow truth? |
| Delete | Cleanup claim, scripts or Make target | CAPI finalizers for resources they own | direct fallback deletion, namespace/secret cleanup, local artifact deletion | What is the authoritative deletion transition and how is evidence retained? |
| Enable | Runner/Make installs CNI and sometimes related prerequisites | Helm/workload objects after installation | kubeconfig retrieval, imperative Helm/apply and readiness waits | Which existing mechanism can own minimum-viability reconciliation? |
| Apply platform | Make targets and platform/GitOps mechanisms | Intended authority is GitOps for persistent platform state | bootstrap and platform boundaries are not uniformly enforced | Which settings are enablement versus a platform profile? |
| Register | `ok-cluster` register/unregister targets | Secrets and ProviderConfig resources in `ok-mgmt` | imperative credential wiring | Is registration an OpenKubes semantic or a derived platform action? |
| Observe | `kubectl`, Make targets, runner waits, provider queries | CAPI/workload/provider APIs | aggregation and evidence collection are ad hoc | Can generation-aware outcome be composed without a new controller? |

## State and authority inventory

| State store | What it currently records | Authority assessment | Risk to test |
|---|---|---|---|
| CAPI objects in `ok-mgmt` | cluster, control plane, machines, provider objects and conditions | Authoritative for long-lived infrastructure/machine lifecycle | Management-state loss or competing writers; ADR-031 boundary |
| Workload API | nodes, CNI and installed add-ons | Authoritative for workload-observed runtime state | Bootstrap cannot depend on GitOps being viable before networking |
| Provider/infra API | VMs, volumes, endpoint/load-balancer inventory | Authoritative for provider actuality | Must be independently observed during management outage |
| Crossplane claims | requested cluster/upgrade/cleanup inputs | Competing/fragmented intent surfaces today | Operation claims can become a second workflow truth |
| Crossplane Job status | Job name and procedural phase | Non-authoritative execution state | Job success must never equal lifecycle success |
| `ok-cluster` config directories | requested values, resolved allocations and rendered artifacts | Current user-side source and bookkeeping, but not reconciled server-side | Local state can drift from management/provider reality |
| Git repository/GitOps resources | persistent platform configuration | Intended authority for platform convergence | Boundary with enablement and cluster contract must be explicit |
| Runner filesystem | rendered YAML, kubeconfig and transient progress | Non-authoritative and disposable by design | Restart must not orphan an accepted transition |
| Evidence directory | observations and test outcome | Durable audit artifact, not desired state | Must be generation- and timestamp-aware |

## Existing mechanism capability map

| Mechanism | Capabilities already available | Boundary / missing evidence |
|---|---|---|
| CAPI/CAPK and bootstrap/control-plane providers | Declarative cluster, machine, control-plane and infrastructure reconciliation; conditions and finalizers | Does not define OpenKubes policy, platform profile, evidence, or every enablement action |
| ClusterClass / managed topology | Standard CAPI composition of topology, variables, version, replicas and rollout | Not used in reviewed sources; fit and provider/bootstrap compatibility require evidence |
| Crossplane | Schema validation, compositions, RBAC-integrated Kubernetes API and composition status | Current composition delegates authority to imperative Jobs and exposes implementation fields |
| `ok-cluster` | Mature config resolution, provider profiles, allocation checks, rendering, preflight and explicit apply gates | Local/procedural execution; durable authority and generation-aware outcome are unresolved |
| v4.2 runner | Reproducible toolchain and deterministic orchestration | Directly performs bootstrap and cleanup; process state is not lifecycle authority |
| Enablement mechanism | CNI and prerequisites can be installed after API availability | No reviewed durable owner currently proves `NetworkReady`/`EnablementReady` |
| GitOps | Persistent platform convergence and drift correction | Requires minimum cluster viability; should not be assumed to solve the CNI bootstrap boundary |
| Policy/RBAC | Can authorize semantic Kubernetes mutations | The allowed operation set and approval/evidence flow are not yet demonstrated |
| CLI/Make | Validation, explanation, preflight, rendering and user interaction | Must not become an independent Contract-to-CAPI compiler or lifecycle authority |

## Findings to carry into capability mapping

1. **The durable machine lifecycle already belongs to CAPI.** A runner or future CLI
   must not duplicate it.
2. **Current intent is fragmented.** Cluster, upgrade and cleanup claims plus local
   `ok-cluster` configuration can describe overlapping lifecycle facts.
3. **The public v4.2 XRD leaks implementation details.** `runnerImage`, credential
   secret wiring, Job status and string booleans should not be mistaken for durable
   cluster semantics.
4. **Enablement has declared inputs but procedural ownership.** CNI is the clearest
   forcing case; CSI/cloud-controller prerequisites require case-by-case boundary
   decisions. Metrics, ingress and observability are not automatically enablement.
5. **OS and infrastructure profiles already have external owners.** OpenKubes may
   select or reference them, but should not duplicate `ok-linux` or provider truth.
6. **Allocation is a material unresolved authority.** Endpoint and CIDR selection
   currently combines local inventory with live checks.
7. **Normalized readiness and durable evidence are missing capabilities.** Their
   absence does not by itself prove that an OpenKubes operator is necessary.
8. **ClusterClass is a candidate capability, not a conclusion.** It must be compared
   with the current manually rendered CAPI resources before choosing a translation
   owner.

## Open questions for the spike

- Which single record is authoritative for the requested generation of a cluster?
- Can CAPI topology/ClusterClass express version, replicas, rollout and provider
  profiles without an OpenKubes Contract-to-CAPI controller?
- What mechanism allocates and reserves endpoint IPs and network CIDRs without local
  split-brain?
- Which minimal components must be ready before GitOps can reconcile reliably?
- Can existing condition and policy mechanisms provide current-generation aggregate
  readiness and evidence?
- Is registration derived from cluster readiness, part of enablement, or an explicit
  platform operation?
- Which deletion facts and evidence must outlive the cluster resources?

Answers require read-only mapping and, later, explicitly gated execution evidence.
They must not be inferred from the presence of an architectural box.
