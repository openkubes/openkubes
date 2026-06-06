# KubeVirt Cluster Provisioning via Crossplane

Crossplane-based self-service API for provisioning and deleting
KubeVirt-backed Kubernetes workload clusters on OpenKubes.

## make Targets

```sh
make crossplane-install    # install Crossplane v2.2.0 + providers + functions
make crossplane-verify     # check XRDs, Compositions and provider health
make crossplane-upgrade    # upgrade Crossplane (jq-based, no Python)
make crossplane-apply      # apply XRDs, Compositions and RBAC
make crossplane-clean      # remove Crossplane from the management cluster
```

## Prerequisites

- Crossplane v2.2.0+ on the management cluster
- `provider-kubernetes` v0.17+ with `in-cluster` ProviderConfig
- `function-patch-and-transform` v0.10.1+
- `function-go-templating` v0.11.4+
- `kubernautslabs/capi-platform-runner:v4.2` accessible from the cluster
- CAPI + CAPK installed → [`../cluster-api/README.md`](../cluster-api/README.md)

---

## Deploy a Cluster

```sh
# Edit endpointIP in examples/ok1.yaml to a free MetalLB IP
kubectl apply -f examples/ok1.yaml

# Watch the deploy Job
kubectl get jobs -n openkubes-system -w
kubectl logs -n openkubes-system job/deploy-ok1-<hash> -f

# Get workload kubeconfig
clusterctl get kubeconfig ok1-<hash> -n ok1-<hash> \
  --kubeconfig ~/.kube/ok-capi-kubevirt-on-kbm.yaml \
  > ~/.kube/ok1.kubeconfig

KUBECONFIG=~/.kube/ok1.kubeconfig kubectl get nodes
```

## Delete a Cluster

```sh
# Find the actual XR name (with hash suffix)
kubectl get cluster -A

# Apply the cleanup claim (set clusterName to the XR name with hash)
kubectl apply -f examples/cleanup-ok1.yaml

# Watch cleanup Job
kubectl get jobs -n openkubes-system -w

# After cleanup is complete, delete both claims
kubectl delete -f examples/ok1.yaml
kubectl delete -f examples/cleanup-ok1.yaml
```

---

## Flow

### Deploy

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

### Cleanup

```
kubectl apply -f examples/cleanup-ok1.yaml
       ↓
KubeVirtClusterCleanupClaim (platform.openkubes.ai/v1alpha1)
       ↓
Crossplane Composition
       ↓
Job (cleanup-cleanup-ok1) ← runs capi-platform-runner
       ↓
crossplane-cleanup.sh → removes CAPI Cluster + VMs + Namespaces
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
  country: de
  provider: kubevirt
  endpointIP: 10.10.10.50        # free MetalLB IP
  cni: calico                    # calico | cilium
  multus: "false"
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
  clusterName: my-cluster-<hash>  # actual XR name with hash
  country: de
  provider: kubevirt
  runnerImage: kubernautslabs/capi-platform-runner:v4.2
```

---

## Crossplane Components

| Component | Version | Purpose |
|---|---|---|
| Crossplane | v2.2.0 | Platform control plane |
| provider-kubernetes | v0.17.0 | Creates Jobs and ConfigMaps |
| function-patch-and-transform | v0.10.1 | Composition pipeline |
| function-go-templating | v0.11.4 | Templating support |

> `function-patch-and-transform` v0.10.1 is required for Crossplane v2 — v0.8.x silently drops Composition resources.

---

## File Structure

```
crossplane/
├── namespace.yaml            # openkubes-system NS + SA + CRB
├── rbac.yaml                 # RBAC for provider-kubernetes SA
├── xrd.yaml                  # XRD: KubeVirtCluster / KubeVirtClusterClaim
├── xrd-cleanup.yaml          # XRD: KubeVirtClusterCleanup / KubeVirtClusterCleanupClaim
├── composition.yaml          # Deploy Composition
├── composition-cleanup.yaml  # Cleanup Composition
├── examples/
│   ├── ok1.yaml
│   ├── ok2.yaml
│   └── cleanup-ok1.yaml
└── README.md
```

---

## Roadmap

- [x] XRD with full cluster spec
- [x] Deploy + Cleanup Job via `capi-platform-runner`
- [x] Per-cluster namespace isolation
- [ ] Status writeback (phase, jobName, kubeconfigSecret)
- [ ] Workload kubeconfig stored as Connection Secret
- [ ] Native Go operator (`openkubes-operator`) — no Crossplane dependency
