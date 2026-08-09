# OK-141 ClusterClass Capability Map

Status: **Read-only capability analysis; no adoption decision**

Recorded: 2026-08-09

OpenKubes baseline: `97cbeeb`

`ok-cluster` baseline: `430b946` (`main`)

## Question

How much of the cluster intent that OpenKubes currently renders as separate CAPI,
bootstrap, control-plane and infrastructure resources could CAPI Managed Topology
carry itself?

This document does not propose a `ClusterClass`, enable `ClusterTopology`, or select
Managed Topology. It maps capabilities and compatibility constraints only.

## Observed implementation baseline

The reviewed `ok-cluster` paths render standalone resources:

```text
Cluster
├── infrastructureRef
│   └── KubevirtCluster or OpenStackCluster
├── controlPlaneRef
│   └── KubeadmControlPlane or TalosControlPlane
└── workers
    └── MachineDeployment
        ├── KubeadmConfigTemplate or TalosConfigTemplate
        └── KubevirtMachineTemplate or OpenStackMachineTemplate
```

There is no `ClusterClass`, `Cluster.spec.topology`, or `TopologyReconciled`
configuration in the reviewed repositories. The strongest recorded runtime baseline
uses CAPI/CABPK/KCP `v1.13.3`, CAPK `v0.11.2`, and CAPI core API `v1beta2`.

The recorded KCP deployment explicitly has `ClusterTopology=false`. The saved
evidence does not include the core CAPI controller deployment, so it does not prove
the complete management-plane feature-gate state. No live query was used for this
analysis.

Evidence:

- [`ok-cluster` README](../../../../ok-cluster/README.md)
- [recorded KCP deployment](../../../../ok-cluster/docs/adoption/OK-125/.evidence/control-plane-deployment.yaml)
- [KubeVirt/Talos template](../../../../ok-cluster/templates/talos/providers/kubevirt/cluster-base.yaml.tpl)
- [KubeVirt/Flatcar template](../../../../ok-cluster/templates/flatcar/cluster-v2.yaml.tpl)
- [KubeVirt/Ubuntu template](../../../../ok-cluster/templates/ubuntu/cluster-v2.yaml.tpl)
- [OpenStack/Talos proof template](../../../../ok-cluster/templates/talos/providers/openstack/cluster.yaml.tpl)

Upstream CAPI describes ClusterClass as an alpha feature behind the
`ClusterTopology` gate. The topology controller continuously creates, updates and
deletes the managed topology resources. A basic topology natively exposes Kubernetes
version, control-plane replicas/metadata and worker classes/replicas/metadata/failure
domains. Variables and patches can customize fields under the referenced templates.

Primary references:

- [CAPI ClusterClass overview](https://cluster-api.sigs.k8s.io/tasks/experimental-features/cluster-class/)
- [Writing a ClusterClass](https://cluster-api.sigs.k8s.io/tasks/experimental-features/cluster-class/write-clusterclass)
- [Operating a managed Cluster](https://cluster-api.sigs.k8s.io/tasks/experimental-features/cluster-class/operate-cluster)
- [ClusterTopology controller](https://cluster-api.sigs.k8s.io/developer/core/controllers/cluster-topology)
- [CAPI v1beta2 API reference](https://cluster-api.sigs.k8s.io/reference/api/crd-api-reference)

## Resource-shape mapping

| Current rendered resource | Managed Topology capability | Mapping assessment | Constraint / evidence needed |
|---|---|---|---|
| `Cluster` with explicit refs | `Cluster.spec.topology.classRef` becomes the single CAPI topology entry point | Native CAPI capability | It changes ownership of generated refs; migration/adoption is not assessed here |
| `KubevirtCluster` | `ClusterClass.spec.infrastructure.templateRef` to a `KubevirtClusterTemplate` | Provider capability appears available in CAPK release line | Confirm exact installed CRD/version and dry-run behavior before any experiment |
| `OpenStackCluster` | Infrastructure template reference | Standard ClusterClass shape | Current CAPO path is only a static proof; no runtime evidence in scope |
| `KubeadmControlPlane` | Control-plane template plus topology version/replicas | Native and documented | Flatcar/Ubuntu bootstrap fields still require template variables/patches |
| `TalosControlPlane` | Requires a ClusterClass-compatible control-plane template kind | **Compatibility unproved** | No `TalosControlPlaneTemplate` was found in reviewed sources; standalone `TalosControlPlane` cannot simply be inserted into a ClusterClass |
| `KubevirtMachineTemplate` | Control-plane machine-infrastructure and worker infrastructure template refs | Native provider-template shape | Image, storage, placement, resource and network variability require patches or class variants |
| `OpenStackMachineTemplate` | Control-plane and worker infrastructure template refs | Native provider-template shape | Flavor/image/SSH and identity semantics require capability validation |
| `KubeadmConfigTemplate` | Worker bootstrap template ref | Native bootstrap-template shape | Flatcar Ignition payload and immutable-template rollout need a dry-run mapping |
| `TalosConfigTemplate` | Worker bootstrap template ref | Template shape exists | Control-plane provider compatibility still blocks an end-to-end Talos topology conclusion |
| `MachineDeployment` | Worker `machineDeployments` topology | Native: class, name, replicas, metadata and failure domain | Rollout settings and provider-specific template changes require class policy/patch mapping |
| Namespace, Role and RoleBinding | Not part of the managed CAPI topology graph | Not covered | Golden-image clone authorization needs another existing authority or prerequisite mechanism |

CAPK `v0.11.2` release artifacts and the earlier `v0.10.0` release notes show
`KubevirtClusterTemplate` support and topology-related dry-run work. This is evidence
of provider capability, not proof that the exact installed management plane is ready
for ClusterClass.

- [CAPK releases](https://github.com/kubernetes-sigs/cluster-api-provider-kubevirt/releases)
- [CAPI InfraCluster provider contract](https://cluster-api.sigs.k8s.io/developer/providers/contracts/infra-cluster)

## Intent-semantic mapping

| Existing OpenKubes/`ok-cluster` semantic | CAPI/ClusterClass can carry | CAPI/ClusterClass does not supply | Assessment |
|---|---|---|---|
| Kubernetes version | `Cluster.spec.topology.version`, propagated to control plane and workers | OpenKubes authorization and supported-version policy | **Strong native fit** |
| Control-plane replicas | Topology control-plane replicas | Product limits/approval | **Strong native fit** |
| Worker groups and replicas | MachineDeployment classes and topology replicas | Product profile vocabulary | **Strong native fit** |
| Rollout mechanics | CAPI/KCP/MD rollout and topology upgrade orchestration | Blue/green workload migration policy | **Partial fit** |
| Cluster network pod/service CIDRs | Remain native fields on the CAPI `Cluster` | Collision-free allocation/reservation | **Carries values, does not allocate** |
| Endpoint/load-balancer IP | Can be patched into infrastructure template fields/annotations | IP allocation authority and reservation | **Carries value, does not allocate** |
| CPU, memory and disk | Variables/patches can customize machine templates | Profile ownership and admissible combinations | **Technically mappable** |
| Placement/node selector | Variables/patches can customize infra templates | Capacity validation and scheduling authority | **Technically mappable** |
| Provider selection | Separate ClusterClasses or compatible class/template variants | A universal cross-provider class is not guaranteed | **Class-boundary decision required** |
| Infrastructure profile | Variables or versioned class selection | OpenKubes profile meaning and external profile identity | **Partial fit** |
| OS image/profile identity | Variables/patches and propagated metadata | `ok-linux` image/profile truth, promotion policy and compatibility | **Reference can be carried; truth remains external** |
| Talos version/config patches | Potential bootstrap/control-plane template variables | Compatible Talos control-plane template support is unproved | **Blocked from full mapping** |
| Flatcar Ignition details | KCP and KubeadmConfig templates with variables/patches | `ok-linux` profile governance and promotion evidence | **Technically plausible; dry-run evidence needed** |
| CNI selection and version | Could be a variable, but topology does not reconcile arbitrary add-ons by itself | Network installation and `NetworkReady` owner | **Not an enablement solution** |
| Multus/CSI/cloud-controller | Could only pass configuration to some other mechanism | Durable add-on reconciliation and readiness | **Outside core topology** |
| Platform profile | Could be metadata/variable for a consumer | GitOps reconciliation and platform status | **Outside core topology** |
| Registration | No native lifecycle semantic identified | Trust-boundary resources and policy | **Outside core topology** |
| Evidence/audit | `TopologyReconciled` and CAPI conditions provide observations | Authorization record and durable cross-layer outcome evidence | **Partial evidence source only** |
| Delete | Deleting a topology-managed Cluster drives deletion of managed CAPI objects | Evidence retention and exceptional cleanup policy | **Lifecycle fit, governance gap remains** |

## What CAPI can remove from an OpenKubes implementation

If compatibility is proven for a profile, Managed Topology can plausibly remove the
need for OpenKubes to independently translate and keep synchronized:

- Kubernetes version across control plane and workers;
- replica counts and worker topology;
- references to bootstrap and infrastructure templates;
- supported rollout mechanics;
- many provider/bootstrap customizations that fit class variables and patches; and
- the creation/update/deletion loop for the generated CAPI resources.

That is materially more than the current runner/renderer delegates to CAPI through a
one-time apply. It is also exactly the lifecycle logic an OpenKubes operator must not
duplicate.

## What remains after maximal CAPI ownership

Even under the most favorable ClusterClass result, CAPI does not by itself establish:

- endpoint/CIDR allocation authority;
- OS and infrastructure profile truth;
- bounded OpenKubes operations and policy authorization;
- CNI/cluster enablement reconciliation;
- GitOps platform convergence;
- cross-layer condition correlation to an OpenKubes requested revision; or
- durable audit/evidence persistence.

These are separate capability questions. Their presence does not imply that a
long-running OpenKubes lifecycle operator is required.

## Findings

1. **For kubeadm-based Flatcar/Ubuntu profiles, much of the current renderer-owned
   CAPI composition is a plausible ClusterClass responsibility.** The mapping is
   strong enough to justify a later dry-run experiment, but not adoption.
2. **The Talos path is not currently proven ClusterClass-compatible.** The reviewed
   resources lack the required control-plane template type. This is a provider
   compatibility gap, not automatically OpenKubes-owned reconciliation semantics.
3. **ClusterClass carries allocated values but is not their allocation authority.**
4. **ClusterClass does not solve enablement or platform convergence.** A CNI variable
   without a durable consumer merely relocates the same gap.
5. **Topology conditions can improve lifecycle observation.** They do not prove
   authorization, network readiness, platform readiness or evidence persistence.

## Decision impact

The result remains **A/B/C/D unclassified**.

This map weakens the case for a broad OpenKubes lifecycle operator because CAPI can
potentially own more of the existing translation/reconciliation than the current
implementation uses. It simultaneously identifies narrow unresolved capabilities
and a Talos compatibility constraint. Neither observation selects a component.

No write-path experiment is authorized by this document.
