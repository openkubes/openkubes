# KubeVirt Cluster Provisioning via Crossplane

Crossplane-based self-service API for provisioning and deleting
KubeVirt-backed Kubernetes workload clusters on OpenKubes.

---

## Overview

### Deploy flow

```
kubectl apply -f examples/ok1.yaml
       ↓
KubeVirtClusterClaim (platform.openkubes.ai/v1alpha1)
       ↓
Crossplane Composition (function-patch-and-transform)
       ↓
provider-kubernetes creates:
  ├── ConfigMap  (deploy-args-ok1)
  └── Job        (deploy-ok1) ← runs capi-platform-runner
       ↓
crossplane-deploy.sh → deploy-full.sh → CAPI + KubeVirt → Workload Cluster
```

### Cleanup flow

```
kubectl apply -f examples/cleanup-ok1.yaml
       ↓
KubeVirtClusterCleanupClaim (platform.openkubes.ai/v1alpha1)
       ↓
Crossplane Composition (function-patch-and-transform)
       ↓
provider-kubernetes creates:
  ├── ConfigMap  (cleanup-args-cleanup-ok1)
  └── Job        (cleanup-cleanup-ok1) ← runs capi-platform-runner
       ↓
crossplane-cleanup.sh → cleanup.sh → removes CAPI Cluster + VMs + Namespaces
```

---

## Prerequisites

- Crossplane v2.2+ installed on the management cluster
- `provider-kubernetes` v0.17+ with `in-cluster` ProviderConfig
- `function-patch-and-transform` v0.10.1+ (required for Crossplane v2)
- `function-go-templating` v0.11.4+
- `kubernautslabs/capi-platform-runner:v4.2` accessible from the cluster
- CAPI + CAPK installed on the management cluster

---

## Installation

```bash
# 1. Create openkubes-system namespace, ServiceAccount and ClusterRoleBinding
kubectl apply -f namespace.yaml

# 2. Apply RBAC for provider-kubernetes
kubectl apply -f rbac.yaml

# Find the exact provider-kubernetes ServiceAccount name and update rbac.yaml:
kubectl get sa -n crossplane-system | grep provider-kubernetes

# 3. Register XRDs
kubectl apply -f xrd.yaml
kubectl apply -f xrd-cleanup.yaml

# 4. Apply Compositions
kubectl apply -f composition.yaml
kubectl apply -f composition-cleanup.yaml

# 5. Verify
kubectl get xrd
kubectl get composition
kubectl get functions.pkg.crossplane.io
```

---

## Deploy a cluster

```bash
# Edit endpointIP in examples/ok1.yaml to a free MetalLB IP
kubectl apply -f examples/ok1.yaml

# Watch the deploy Job
kubectl get jobs -n openkubes-system -w

# Follow logs
kubectl logs -n openkubes-system job/deploy-ok1-<hash> -f

# Get workload kubeconfig (replace ok1-<hash> with actual XR name)
clusterctl get kubeconfig ok1-<hash> -n ok1-<hash> \
  --kubeconfig ~/.kube/ok-capi-kubevirt-on-kbm.yaml \
  > ~/.kube/ok1.kubeconfig

KUBECONFIG=~/.kube/ok1.kubeconfig kubectl get nodes
```

---

## Delete a cluster

```bash
# 1. Find the actual XR name (with hash suffix)
kubectl get cluster -A

# 2. Edit examples/cleanup-ok1.yaml and set clusterName to the XR name
#    e.g. clusterName: ok1-gh5ms
vim platform/cluster-management/crossplane/examples/cleanup-ok1.yaml

# 3. Apply the cleanup claim
kubectl apply -f examples/cleanup-ok1.yaml

# 4. Watch the cleanup Job
kubectl get jobs -n openkubes-system -w
kubectl logs -n openkubes-system job/cleanup-cleanup-ok1-<hash> -f

# 5. After cleanup is complete, delete both claims
kubectl delete -f examples/ok1.yaml
kubectl delete -f examples/cleanup-ok1.yaml
```

The cleanup Job runs `cleanup.sh` which:
1. Deletes the CAPI Cluster (triggers VM deletion on the infra cluster)
2. Removes CAPI finalizers from stuck resources
3. Deletes the per-cluster infra secret
4. Removes the cluster namespace on both management and infra cluster

---

## File Structure

```
crossplane/
├── namespace.yaml            # openkubes-system NS + SA + CRB (one-time setup)
├── rbac.yaml                 # RBAC for provider-kubernetes ServiceAccount
├── xrd.yaml                  # XRD: KubeVirtCluster / KubeVirtClusterClaim
├── xrd-cleanup.yaml          # XRD: KubeVirtClusterCleanup / KubeVirtClusterCleanupClaim
├── composition.yaml          # Deploy Composition (P&T pipeline)
├── composition-cleanup.yaml  # Cleanup Composition (P&T pipeline)
├── examples/
│   ├── ok1.yaml              # KubeVirtClusterClaim example
│   ├── ok2.yaml              # KubeVirtClusterClaim example
│   └── cleanup-ok1.yaml      # KubeVirtClusterCleanupClaim example
└── README.md
```

---

## API Reference

### KubeVirtClusterClaim

```yaml
apiVersion: platform.openkubes.ai/v1alpha1
kind: KubeVirtClusterClaim
metadata:
  name: my-cluster
  namespace: openkubes-system
spec:
  country: de                          # required
  provider: kubevirt                   # required
  endpointIP: 10.10.10.50             # required – free MetalLB IP
  cni: calico                          # calico | cilium
  multus: "false"                      # "true" | "false"
  controlPlane:
    replicas: 1
    kubernetesVersion: v1.34.1
  workers:
    replicas: 2
  runnerImage: kubernautslabs/capi-platform-runner:v4.2
```

### KubeVirtClusterCleanupClaim

```yaml
apiVersion: platform.openkubes.ai/v1alpha1
kind: KubeVirtClusterCleanupClaim
metadata:
  name: cleanup-my-cluster
  namespace: openkubes-system
spec:
  clusterName: my-cluster-<hash>       # required – actual XR name with hash
  country: de
  provider: kubevirt
  runnerImage: kubernautslabs/capi-platform-runner:v4.2
```

---

## Crossplane Components

| Component | Version | Purpose |
|-----------|---------|---------|
| Crossplane | v2.2.0 | Platform control plane |
| provider-kubernetes | v0.17.0 | Creates K8s objects (Jobs, ConfigMaps) |
| function-patch-and-transform | v0.10.1 | Composition pipeline (P&T) |
| function-go-templating | v0.11.4 | Delete hook (future use) |

> **Note:** `function-patch-and-transform` v0.10.1 is required for Crossplane v2.
> v0.8.x is not compatible and will silently drop Composition resources.

---

## Roadmap

### Phase 1 – Current ✅
- [x] XRD with full cluster spec
- [x] Deploy Job via `crossplane-deploy.sh`
- [x] Cleanup Job via `KubeVirtClusterCleanupClaim`
- [x] Per-cluster namespace isolation
- [x] Per-cluster infra secret

### Phase 2 – Composition Functions
- [ ] Status writeback (phase, jobName, kubeconfigSecret)
- [ ] Workload kubeconfig stored as Connection Secret
- [ ] Cluster name without hash suffix

### Phase 3 – Native Operator (controller-runtime)
- [ ] `KubeVirtCluster` controller in Go
- [ ] Full reconcile loop with Events and Conditions
- [ ] No Crossplane dependency
- [ ] Published as `openkubes-operator` to OperatorHub

---

## Notes

- The deploy Job uses the `capi-platform-runner` ServiceAccount with
  `cluster-admin`. Scope this down to a custom ClusterRole in production.
- `namespace.yaml` creates the SA and CRB permanently — they must exist
  before any Claim is applied.
- `compositeDeletePolicy: Foreground` ensures composed resources are deleted
  before the XR is removed.
