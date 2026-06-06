# KubeVirt Cluster Provisioning via Crossplane

This directory provides a Crossplane-based self-service API for provisioning
KubeVirt-backed Kubernetes workload clusters on OpenKubes.

> 🇩🇪 [Deutsche Version](README_DE.md)

---

## Overview

```
kubectl apply -f examples/ok1.yaml
       ↓
KubeVirtClusterClaim (platform.openkubes.ai/v1alpha1)
       ↓
Crossplane Composition
       ↓
provider-kubernetes creates:
  ├── Namespace (openkubes-system)
  ├── ConfigMap  (deploy-args-ok1)
  ├── ServiceAccount + ClusterRoleBinding
  └── Job  (deploy-ok1)  ← runs capi-platform-runner
       ↓
deploy-full.sh → CAPI + KubeVirt → Workload Cluster
```

---

## Prerequisites

- Crossplane installed on the management cluster
- `provider-kubernetes` v0.17+ with `in-cluster` ProviderConfig
- `function-patch-and-transform` v0.8+
- `kubernautslabs/capi-platform-runner:v4.2` image accessible from the cluster
- CAPI + CAPK installed on the management cluster

---

## Installation

```bash
# 0. Create the openkubes-system namespace (one-time setup)
kubectl apply -f namespace.yaml

# 1. Apply RBAC for provider-kubernetes
kubectl apply -f rbac.yaml

# Find the exact provider-kubernetes ServiceAccount name and update rbac.yaml:
kubectl get sa -n crossplane-system | grep provider-kubernetes

# 2. Register the XRD
kubectl apply -f xrd.yaml

# 3. Apply the Composition
kubectl apply -f composition.yaml

# 4. Verify
kubectl get xrd kubevirtclusters.platform.openkubes.ai
kubectl get composition kubevirtcluster.platform.openkubes.ai
```

---

## Usage

### Deploy a cluster

```bash
# Edit the endpointIP first
kubectl apply -f examples/ok1.yaml

# Watch progress
kubectl get kubevirtclusterclaim ok1 -n openkubes-system -w

# Check the deploy Job
kubectl get jobs -n openkubes-system
kubectl logs -n openkubes-system job/deploy-ok1 -f
```

### Delete a cluster

```bash
kubectl delete -f examples/ok1.yaml
```

Crossplane will delete all composed resources. The cleanup Job is triggered
automatically via the Composition's delete pipeline (see Roadmap below).

---

## File Structure

```
crossplane/
├── xrd.yaml              # CompositeResourceDefinition + schema
├── composition.yaml      # Composition (patch-and-transform pipeline)
├── rbac.yaml             # RBAC for provider-kubernetes ServiceAccount
├── examples/
│   ├── ok1.yaml          # KubeVirtClusterClaim example
│   └── ok2.yaml          # KubeVirtClusterClaim example
└── README.md
```

---

## API Reference

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

---

## Roadmap

### Phase 1 – Current (Crossplane P&T)
- [x] XRD with full cluster spec
- [x] Composition creates Namespace, ConfigMap, SA, Job
- [x] Deploy Job runs `capi-platform-runner`
- [ ] Delete pipeline triggers cleanup Job
- [ ] Status writeback (phase, jobName, kubeconfigSecret)

### Phase 2 – Composition Functions (KCL / Go)
- [ ] Job status observation → XR status.phase
- [ ] Workload kubeconfig stored as Connection Secret
- [ ] Cluster upgrade via spec.controlPlane.kubernetesVersion change

### Phase 3 – Native Operator (controller-runtime)
- [ ] `KubeVirtCluster` controller in Go
- [ ] Full reconcile loop with Events and Conditions
- [ ] No Crossplane dependency
- [ ] Published as `openkubes-operator` to OperatorHub

---

## Notes

- The deploy Job uses the `capi-platform-runner` ServiceAccount with
  `cluster-admin`. Scope this down to a custom ClusterRole in production.
- The runner image must be pre-pulled or available in your registry.
- `compositeDeletePolicy: Foreground` ensures composed resources are deleted
  before the XR is removed.
