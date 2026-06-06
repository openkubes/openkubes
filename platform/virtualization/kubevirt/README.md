# KubeVirt Installation

Installs KubeVirt on the **Infra Cluster** (RKE2 bare metal) and the
**Management Cluster** (kubeadm VMs).

## make Targets

```sh
make kubevirt-install       # install KubeVirt + CDI on the current cluster
make kubevirt-install-mgmt  # install KubeVirt on the management cluster
make kubevirt-verify        # check KubeVirt, CDI and virt plugin
make kubevirt-ui            # deploy KubeVirt Manager UI (optional)
make kubevirt-clean         # remove KubeVirt and CDI
```

---

## Overview

```
RKE2 Bare Metal (Infra Cluster)
├── KubeVirt Operator + CR      ← runs VMs
├── CDI (Containerized Data Importer)
├── KubeVirt Manager UI (optional)
└── MetalLB                     ← provides LoadBalancer IPs for VMs

Management Cluster (kubeadm on ok1/ok2/ok3-vm)
└── KubeVirt Operator + CR      ← needed for CAPK to provision workload VMs
```

---

## Manual Steps

<details>
<summary>Step-by-step without make</summary>

### 1. Install KubeVirt on the Infra Cluster

```sh
kubectl apply -f https://github.com/kubevirt/kubevirt/releases/download/v1.8.1/kubevirt-operator.yaml
kubectl apply -f https://github.com/kubevirt/kubevirt/releases/download/v1.8.1/kubevirt-cr.yaml

kubectl -n kubevirt wait kubevirt kubevirt \
  --for=condition=Available \
  --timeout=300s
```

### 2. Install CDI

```sh
kubectl apply -f https://github.com/kubevirt/containerized-data-importer/releases/latest/download/cdi-operator.yaml
kubectl apply -f https://github.com/kubevirt/containerized-data-importer/releases/latest/download/cdi-cr.yaml

kubectl get pods -n cdi
```

### 3. Install kubectl virt plugin

```sh
kubectl krew install virt
kubectl virt version
```

### 4. Install KubeVirt Manager UI (optional)

```sh
kubectl apply -f https://github.com/kubevirt-manager/kubevirt-manager/releases/download/v1.5.4/bundled-v1.5.4.yaml

# Access via port-forward
kubectl port-forward -n kubevirt-manager svc/kubevirt-manager 8080:8080
# Open: http://localhost:8080
```

### 5. Install KubeVirt on the Management Cluster

```sh
export KUBECONFIG=~/.kube/ok-capi-kubevirt-on-kbm.yaml

kubectl apply -f https://github.com/kubevirt/kubevirt/releases/download/v1.8.1/kubevirt-operator.yaml
kubectl apply -f https://github.com/kubevirt/kubevirt/releases/download/v1.8.1/kubevirt-cr.yaml

kubectl -n kubevirt wait kubevirt kubevirt \
  --for=condition=Available \
  --timeout=300s
```

</details>

---

## Verify

```sh
make kubevirt-verify
```

Expected output:

```
# Infra Cluster
NAME       AGE   PHASE   READY
kubevirt   10m   Deployed  True

# CDI
NAME   AGE   PHASE
cdi    10m   Deployed

# Management Cluster
NAME       AGE   PHASE   READY
kubevirt   5m    Deployed  True
```

---

## Next Step

→ [`../../hardware/README.md`](../../hardware/README.md) — Deploy Management VMs
