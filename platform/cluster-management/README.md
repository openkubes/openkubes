# OpenKubesCluster – Cluster Management

Self-service Kubernetes cluster lifecycle management via Crossplane + Cluster API.

---

## Quick Start

```bash
cd platform/cluster-management

# One-time setup
make setup

# Deploy a cluster
make deploy cluster=ok1

# Get kubeconfig
make kubeconfig cluster=ok1

# Install Headlamp UI
make manager-deploy cluster=ok1
make manager-open   cluster=ok1
```

---

## Prerequisites

| Requirement | Notes |
|---|---|
| kubectl | configured for management cluster |
| helm | ≥ 3.14 |
| clusterctl | for kubeconfig retrieval |
| Crossplane | installed on management cluster |
| CAPI + CAPK | installed on management cluster |

---

## Cluster Lifecycle

### Deploy

```bash
make deploy cluster=ok1
```

Applies `crossplane/examples/ok1.yaml` and waits for the deploy Job to complete.

### Delete

```bash
make delete cluster=ok1
```

Cleanly removes the cluster via a Cleanup Job — VMs, namespaces, secrets.

### Kubeconfig

```bash
make kubeconfig cluster=ok1
# Saved to ~/.kube/ok1.kubeconfig
KUBECONFIG=~/.kube/ok1.kubeconfig kubectl get nodes
```

### Status

```bash
make status cluster=ok1
```

Shows cluster, machines, jobs and claims.

### Logs

```bash
make logs cluster=ok1
```

Follows the most recent deploy/upgrade Job logs.

---

## Cluster Upgrade

### Recreate (reliable, supported)

Deletes and recreates the cluster with the target version. Workloads will be lost.

```bash
make recreate cluster=ok1 kubernetes-version=v1.34.1
```

### Rolling Upgrade (experimental)

⚠️ Requires CAPK v0.12+ for reliable ProviderID registration.
With CAPK v0.11.x this may hang. Use `make recreate` instead.

```bash
make upgrade cluster=ok1 kubernetes-version=v1.34.1
```

See [`capi-platform-v4.2/UPGRADE_MVP.md`](./capi-platform-v4.2/UPGRADE_MVP.md) for details.

---

## Cluster Manager (Headlamp)

[Headlamp](https://headlamp.dev) is the official Kubernetes Dashboard successor —
CNCF Sandbox, part of Kubernetes SIG UI since 2025.

### Install Headlamp on a workload cluster

```bash
make manager-deploy cluster=ok1
```

### Generate access token

```bash
make manager-token cluster=ok1
```

Copy the token and paste it into the Headlamp login screen.

### Open Headlamp in browser

```bash
make manager-open cluster=ok1
# Opens http://localhost:8080 automatically
```

### Show status

```bash
make manager-status cluster=ok1
```

### Remove Headlamp

```bash
make manager-delete cluster=ok1
```

---

## Troubleshooting

### Check for leftover resources

```bash
make check cluster=ok1
```

### Force cleanup (emergency)

```bash
make force-clean cluster=ok1
```

Removes all CAPI/Crossplane resources for the cluster without waiting for graceful deletion.

---

## Cluster Claim Example

```yaml
# crossplane/examples/ok1.yaml
apiVersion: platform.openkubes.ai/v1alpha1
kind: KubeVirtClusterClaim
metadata:
  name: ok1
  namespace: openkubes-system
spec:
  country: de
  provider: kubevirt
  endpointIP: 84.200.100.228
  cni: calico
  multus: "false"
  controlPlane:
    replicas: 1
    kubernetesVersion: v1.34.1
  workers:
    replicas: 1
  runnerImage: kubernautslabs/capi-platform-runner:v4.2
```

---

## All Make Targets

| Target | Description |
|---|---|
| `make setup` | One-time: apply XRDs, Compositions, RBAC |
| `make deploy cluster=ok1` | Deploy a workload cluster |
| `make delete cluster=ok1` | Clean delete via Cleanup Job |
| `make kubeconfig cluster=ok1` | Retrieve workload cluster kubeconfig |
| `make recreate cluster=ok1 kubernetes-version=v1.34.1` | Reliable upgrade via recreate |
| `make upgrade cluster=ok1 kubernetes-version=v1.34.1` | Rolling upgrade (experimental) |
| `make status cluster=ok1` | Show cluster status |
| `make logs cluster=ok1` | Follow deploy Job logs |
| `make check cluster=ok1` | Check for leftover resources |
| `make force-clean cluster=ok1` | Emergency cleanup |
| `make manager-deploy cluster=ok1` | Install Headlamp on workload cluster |
| `make manager-token cluster=ok1` | Generate Headlamp admin token |
| `make manager-open cluster=ok1` | Port-forward + open browser |
| `make manager-status cluster=ok1` | Show Headlamp status |
| `make manager-delete cluster=ok1` | Remove Headlamp |

---

## References

- [Crossplane](https://crossplane.io)
- [Cluster API](https://cluster-api.sigs.k8s.io)
- [CAPK (KubeVirt Provider)](https://github.com/kubernetes-sigs/cluster-api-provider-kubevirt)
- [Headlamp](https://headlamp.dev)
- Related: [`platform/virtualization/openkubesvm/`](../virtualization/openkubesvm/README.md)
