# OK-141 Condition Observation

Status: **Raw read-only observation; no normalization or target status design**

Snapshot window: `2026-08-09T09:57:33Z` – `2026-08-09T09:58:36Z`

Management context: `/Users/arash/.kube/ok-mgmt.yaml` (`ok-mgmt-admin@ok-mgmt`)

Workload context: `/Users/arash/.kube/ok-ai.yaml` (`ok-ai-admin@ok-ai`)

Infrastructure context: `/Users/arash/.kube/ok-infra.yaml`

## Scope and method

The snapshot used only read operations. No resource was applied, patched, deleted,
annotated, restarted, scaled or otherwise mutated. TLS verification remained enabled.

The representative workload is `ok-ai`, selected because:

- it is reachable through the VPN;
- a matching local `ok-cluster/ok-ai/cluster-config.yaml` exists;
- matching KubeVirt provider inventory exists in the `ok-ai` infrastructure
  namespace; and
- the workload exposes current Node and Cilium state.

This document records observed facts only. Correlation and interpretation are in
[revision-correlation.md](revision-correlation.md).

No Secrets, kubeconfig contents, tokens, private keys or bearer credentials were
captured.

## Endpoint and version observations

| Plane | API endpoint | Kubernetes version | Observation |
|---|---|---|---|
| Management | `192.168.100.200:6443` | `v1.34.1` | TLS-verified API request succeeded |
| Workload `ok-ai` | `192.168.100.201:6443` | `v1.34.1` | TLS-verified API request succeeded |
| Infrastructure | configured by `ok-infra` context | not captured | TLS-verified provider inventory queries succeeded |

## Management-plane observations

### Installed APIs

The following APIs were discoverable:

| API | Served version |
|---|---|
| `Cluster`, `MachineDeployment`, `Machine`, `MachineSet`, `MachineHealthCheck`, `ClusterClass` | `cluster.x-k8s.io/v1beta2` |
| `KubevirtCluster`, `KubevirtClusterTemplate`, `KubevirtMachine`, `KubevirtMachineTemplate` | `infrastructure.cluster.x-k8s.io/v1alpha1` |
| `TalosControlPlane` | `controlplane.cluster.x-k8s.io/v1alpha3` |
| `KubeVirtClusterClaim`, upgrade and cleanup XRs/claims | `platform.openkubes.ai/v1alpha1` |

The `argoproj.io` API group and `Application` resource were not served on `ok-mgmt`.

### Current object counts

Captured at `2026-08-09T09:58:36Z`:

| Resource type | Count across all namespaces |
|---|---:|
| CAPI `Cluster` | 0 |
| `KubevirtCluster` | 0 |
| `TalosControlPlane` | 0 |
| `MachineDeployment` | 0 |
| CAPI `Machine` | 0 |
| `KubevirtMachine` | 0 |
| `ClusterClass` | 0 |
| `KubeVirtClusterClaim` | 0 |

No namespace named `ok-ai` existed on the current management cluster.

### CAPI controller deployment

| Field | Observed value |
|---|---|
| Deployment | `capi-system/capi-controller-manager` |
| UID | `5b62a898-92f3-46de-b296-26beb2a4da75` |
| Creation time | `2026-07-22T13:24:58Z` |
| `metadata.generation` | 1 |
| `status.observedGeneration` | 1 |
| Image | `registry.k8s.io/cluster-api/cluster-api-controller:v1.13.4` |
| Feature gate | `ClusterTopology=false` |
| Replicas | desired 1, ready 1, available 1 |

Deployment conditions:

| Type | Status | Reason | Message | Last transition |
|---|---|---|---|---|
| `Progressing` | `True` | `NewReplicaSetAvailable` | ReplicaSet successfully progressed | `2026-07-22T13:24:58Z` |
| `Available` | `True` | `MinimumReplicasAvailable` | Deployment has minimum availability | `2026-08-05T14:55:39Z` |

### CAPK controller deployment

| Field | Observed value |
|---|---|
| Deployment | `capk-system/capk-controller-manager` |
| UID | `0c3bcaf2-4a8a-4f37-9665-a66f04b79ed0` |
| Creation time | `2026-07-22T13:25:12Z` |
| `metadata.generation` | 2 |
| `status.observedGeneration` | 2 |
| Image | `quay.io/capk/capk-manager:v0.11.2` |
| Replicas | desired 1, ready 1, available 1 |

Deployment conditions:

| Type | Status | Reason | Message | Last transition |
|---|---|---|---|---|
| `Progressing` | `True` | `NewReplicaSetAvailable` | ReplicaSet successfully progressed | `2026-07-22T13:25:12Z` |
| `Available` | `True` | `MinimumReplicasAvailable` | Deployment has minimum availability | `2026-08-05T15:08:42Z` |

These are controller Deployment conditions, not workload-cluster lifecycle
conditions.

## Workload `ok-ai` observations

### Nodes

The workload contained four Nodes:

| Node | UID | Role | OS image | Kubelet | `Ready` | `NetworkUnavailable` |
|---|---|---|---|---|---|---|
| `ok-ai-cp-v45mv` | `cffd5264-e0bf-4efc-a982-f2189883a04a` | control plane | `Talos (v1.9.5)` | `v1.34.1` | `True` / `KubeletReady` | `False` / `CiliumIsUp` |
| `ok-ai-workers-qb4gh-4hr4g` | `0a80c3f0-8c12-489a-9c6a-a5d3dbc3c706` | worker | `Talos (v1.9.5)` | `v1.34.1` | `True` / `KubeletReady` | `False` / `CiliumIsUp` |
| `ok-ai-workers-qb4gh-ptvm7` | `1f0692bb-6b77-4642-a747-a7566c2307db` | worker | `Talos (v1.9.5)` | `v1.34.1` | `True` / `KubeletReady` | `False` / `CiliumIsUp` |
| `ok-ai-workers-qb4gh-vpfdm` | `d5c82b1e-2444-41ef-851a-ba9fc6733bff` | worker | `Talos (v1.9.5)` | `v1.34.1` | `True` / `KubeletReady` | `False` / `CiliumIsUp` |

All Nodes also reported `MemoryPressure=False`, `DiskPressure=False` and
`PIDPressure=False`. Kubernetes Nodes do not expose `metadata.generation` or
`status.observedGeneration` in this snapshot.

### Cilium DaemonSet

| Field | Observed value |
|---|---|
| Object | `kube-system/DaemonSet/cilium` |
| UID | `9b7d04b4-d54f-4c89-b7d5-f13f2e252c6f` |
| Creation time | `2026-07-21T13:48:49Z` |
| `metadata.generation` | 1 |
| `status.observedGeneration` | 1 |
| Desired/current/ready/available | 4 / 4 / 4 / 4 |
| Image | `quay.io/cilium/cilium:v1.19.6@sha256:0df5b2750b64c49843aba1d649e9eaf61467cb0645ad3171db6f6962c095ac92` |
| Helm release | `cilium`, namespace `kube-system` |
| `status.conditions` | absent |
| Pod-template SHA-256 | `8f1dd73182612f1739088d105bd5c45cca5440a3f317f9d32278a1dbd0a33130` |

### Cilium operator Deployment

| Field | Observed value |
|---|---|
| Object | `kube-system/Deployment/cilium-operator` |
| UID | `c8cc095f-7deb-49c1-8d83-4cb15d755d81` |
| Creation time | `2026-07-21T13:48:49Z` |
| `metadata.generation` | 1 |
| `status.observedGeneration` | 1 |
| Desired/updated/ready/available | 1 / 1 / 1 / 1 |
| Image | `quay.io/cilium/operator-generic:v1.19.6@sha256:0db4ca4e06969d8904ee036617795d0e9c3228cf7b8d902ba74fc2bb98d2d665` |
| Pod-template SHA-256 | `4d59adac61fe3ad388dc2b1ab99d5bebc9ca0ece8b4f8a77f2bac4bcbc7521e8` |

Conditions:

| Type | Status | Reason | Message | Last transition |
|---|---|---|---|---|
| `Available` | `True` | `MinimumReplicasAvailable` | Deployment has minimum availability | `2026-07-21T13:48:49Z` |
| `Progressing` | `True` | `NewReplicaSetAvailable` | ReplicaSet successfully progressed | `2026-07-21T13:48:49Z` |

### Cilium release/config identity

| Field | Observed value |
|---|---|
| Helm release | `cilium` |
| Helm revision | 2 |
| Chart | `cilium-1.19.6` |
| App version | `1.19.6` |
| Status | `deployed` |
| Last Helm update | `2026-07-22T15:25:42+02:00` |
| `cilium-config` UID | `b46bf77e-eedd-40f0-bcde-b509685d0b14` |
| Config data SHA-256 | `3e88edd80478c0fb4cedb0c8d37b54f70505ec3409fb0d81b6837820f244a0e0` |

The workload did not serve the `argoproj.io` API group or Argo CD `Application`
resources.

## Infrastructure-plane observations

The `ok-ai` namespace existed on `ok-infra` with UID
`6384e80c-8817-4f78-9294-5b9e163d8e20` and creation time
`2026-07-21T13:45:03Z`.

### KubeVirt VirtualMachines

Four VMs were present. Each had:

- `metadata.generation=1`;
- `status.observedGeneration=1`;
- `status.ready=true`;
- `status.printableStatus=Running`;
- a `Ready=True` condition;
- a `DataVolumesReady=True` condition with reason `AllDVsReady`; and
- labels `cluster.x-k8s.io/cluster-name=ok-ai` plus the matching CAPK machine name.

| VM | UID | Role | Ready transition | Owner references |
|---|---|---|---|---|
| `ok-ai-cp-v45mv` | `f32e493f-6ba0-498b-9b5f-1ff058704e0f` | control plane | `2026-07-21T13:47:00Z` | absent |
| `ok-ai-workers-qb4gh-4hr4g` | `eee629e8-f9e3-4499-a735-d6e9670c304f` | worker | `2026-07-21T13:47:05Z` | absent |
| `ok-ai-workers-qb4gh-ptvm7` | `557fae3a-b72c-40e1-9082-0c721599f9c7` | worker | `2026-07-21T13:47:30Z` | absent |
| `ok-ai-workers-qb4gh-vpfdm` | `9f1462e6-0994-4259-980f-73582ad4a082` | worker | `2026-07-21T13:47:08Z` | absent |

Each VM also reported `LiveMigratable=False` and `StorageLiveMigratable=False` with
the observed reason that its network interface is not live-migratable. Those
conditions do not negate KubeVirt `Ready=True`.

Matching VMIs were `Running` and `Ready=True`. Their names matched both the
infrastructure VM names and the Kubernetes Node names.

### Control-plane endpoint

`ok-infra/ok-ai/Service/ok-ai-lb` had:

- label `cluster.x-k8s.io/cluster-name=ok-ai`;
- type `LoadBalancer`;
- port `6443`; and
- assigned VIP `192.168.100.201`.

## Local desired-file observations

The local file [`ok-ai/cluster-config.yaml`](../../../../ok-cluster/ok-ai/cluster-config.yaml)
had SHA-256:

```text
ebd258de28fc337f6f76f4be82f540085c8913f6c2b8a99d2807e71c568fd74b
```

Observed values in that file:

| Field | Value |
|---|---|
| name | `ok-ai` |
| type | `talos` |
| Kubernetes version | `v1.34.1` |
| Talos version | `v1.9.5` |
| endpoint | `192.168.100.201` |
| pod CIDR | `10.33.0.0/16` |
| service CIDR | `10.96.16.0/20` |
| control-plane replicas | 1 |
| worker replicas | 3 |
| upgrade strategy | `blue-green` |

The local rendered [`ok-ai/cluster-base.yaml`](../../../../ok-cluster/ok-ai/cluster-base.yaml)
had SHA-256:

```text
8406a94a8bc354b69f3ba4753e540b5cbcdab7ca4b4569baa32669c85cbd0030
```

The latest commit touching the observed local inputs was:

```text
61f9bd55a0f259da09f6a451eb560888027f355a
2026-07-30T08:18:44+02:00
feat(ai): Profile A provider values for ok-ai (OK-92)
```

No live object observed in this snapshot carried that Git commit or either file hash.

## Observation completeness

| Requested source | Snapshot result |
|---|---|
| CAPI Cluster | absent on current `ok-mgmt` |
| InfraCluster | absent on current `ok-mgmt` |
| ControlPlane | absent on current `ok-mgmt` |
| MachineDeployment | absent on current `ok-mgmt` |
| Machines | absent on current `ok-mgmt` |
| KubeVirt provider inventory | present and captured |
| Workload Nodes | present and captured |
| Cilium | present and captured |
| Argo CD Application | API absent on management and workload clusters |
| Crossplane cluster intent | API present; instances absent |

This concludes the raw observation. It does not assign lifecycle authority or infer a
single OpenKubes revision.
