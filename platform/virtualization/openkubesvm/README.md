# OpenKubesVM

KubeVirt VM management for OpenKubes — two ways to create VMs.

## Prerequisites

### Crossplane ProviderConfig for Infra Cluster (one-time setup)

Before using the Crossplane path, you need a ProviderConfig that points to the
KubeVirt infra cluster. This reuses the existing infra kubeconfig secret from CAPK:

```bash
# Extract kubeconfig from existing CAPK infra secret
kubectl get secret external-infra-kubeconfig -n capk-system \
  -o jsonpath='{.data.kubeconfig}' | base64 -d > /tmp/infra-kubeconfig.yaml

# Create Crossplane secret
kubectl create secret generic infra-cluster-kubeconfig \
  -n crossplane-system \
  --from-file=kubeconfig=/tmp/infra-kubeconfig.yaml \
  --dry-run=client -o yaml | kubectl apply -f -

# Create ProviderConfig
kubectl apply -f platform/virtualization/openkubesvm/crossplane/providerconfig-infra-cluster.yaml
```

Verify:
```bash
kubectl get providerconfig infra-cluster
```

---

## Option 1: Direct KubeVirt (fast, no Crossplane)

Apply directly on the infra cluster:

```bash
kubectl apply -f platform/virtualization/openkubesvm/kubevirt/ok4-vm.yaml

# or all at once via kustomize
kubectl apply -k platform/virtualization/openkubesvm/examples/direct
```

Check status:
```bash
kubectl get vm -n kubevirt
kubectl get dv -n kubevirt    # DataVolume import takes ~90s
```

SSH access (after VM is ready):
```bash
ssh ubuntu@84.200.100.228   # ok4
ssh ubuntu@84.200.100.229   # ok5
ssh ubuntu@84.200.100.230   # ok6
```

---

## Option 2: Via Crossplane (declarative, GitOps)

### Setup (one-time)
```bash
kubectl apply -k platform/virtualization/openkubesvm/crossplane
```

Verify:
```bash
kubectl get xrd | grep openkubesvm
kubectl get composition | grep openkubesvm
```

### Create VMs
```bash
# Single VM
kubectl apply -f platform/virtualization/openkubesvm/examples/claims/ok4-openkubesvmclaim.yaml

# All at once
kubectl apply -k platform/virtualization/openkubesvm/examples/claims
```

Watch progress (on management cluster):
```bash
kubectl get openkubesvmclaim -A -w
```

Watch VM on infra cluster:
```bash
kubectl get vm -n kubevirt -w
```

### Delete VMs
```bash
kubectl delete -k platform/virtualization/openkubesvm/examples/claims
```

---

## IP / MAC Schema

| VM   | LB IP           | Cluster IP      | MAC               |
|------|-----------------|-----------------|-------------------|
| ok4  | 84.200.100.228  | 192.168.50.14   | 02:50:00:00:00:14 |
| ok5  | 84.200.100.229  | 192.168.50.15   | 02:50:00:00:00:15 |
| ok6  | 84.200.100.230  | 192.168.50.16   | 02:50:00:00:00:16 |

---

## Security Notes

- Crossplane claims use SSH key login by default (`ssh_pwauth: false`).
- Direct Lab YAMLs (`kubevirt/`, `examples/direct/`) contain a `CHANGE_ME`
  password placeholder — change or disable before production use.
- For production use a `secretRef` instead of inline SSH keys in Claims.
