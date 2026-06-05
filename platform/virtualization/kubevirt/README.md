# KubeVirt Installation

This guide covers installing KubeVirt on both the **Infra Cluster** (RKE2 bare metal)
and the **Management Cluster** (kubeadm VMs).

---

## Overview

```
RKE2 Bare Metal (Infra Cluster)
├── KubeVirt Operator + CR      ← runs VMs
├── CDI (Containerized Data Importer)
├── KubeVirt Manager UI
└── MetalLB                     ← provides LoadBalancer IPs for VMs

Management Cluster (kubeadm on ok1-vm / ok2-vm / ok3-vm)
└── KubeVirt Operator + CR      ← needed for CAPK to provision workload VMs
```

---

## 1. Install KubeVirt on the Infra Cluster

```bash
# KubeVirt Operator and CR
kubectl apply -f https://github.com/kubevirt/kubevirt/releases/download/v1.8.1/kubevirt-operator.yaml
kubectl apply -f https://github.com/kubevirt/kubevirt/releases/download/v1.8.1/kubevirt-cr.yaml

# Wait for KubeVirt to become ready
kubectl -n kubevirt wait kubevirt kubevirt \
  --for=condition=Available \
  --timeout=300s

kubectl get kubevirt -n kubevirt
kubectl get pods -n kubevirt
```

---

## 2. Install CDI (Containerized Data Importer)

CDI is required for VM disk management (DataVolumes, PVCs).

```bash
kubectl apply -f https://github.com/kubevirt/containerized-data-importer/releases/latest/download/cdi-operator.yaml
kubectl apply -f https://github.com/kubevirt/containerized-data-importer/releases/latest/download/cdi-cr.yaml

kubectl get pods -n cdi
```

---

## 3. Install kubectl virt plugin

```bash
kubectl krew install virt

# Test
kubectl virt version
```

---

## 4. Install KubeVirt Manager UI (optional)

```bash
kubectl apply -f https://github.com/kubevirt-manager/kubevirt-manager/releases/download/v1.5.4/bundled-v1.5.4.yaml

# Access via port-forward
kubectl port-forward -n kubevirt-manager svc/kubevirt-manager 8080:8080
# Open: http://localhost:8080
```

---

## 5. Install KubeVirt on the Management Cluster

The Management Cluster also needs KubeVirt installed so that CAPK
(Cluster API Provider KubeVirt) can provision workload VMs through it.

```bash
# Switch to management cluster kubeconfig
export KUBECONFIG=~/.kube/ok-capi-kubevirt-on-kbm.yaml

kubectl apply -f https://github.com/kubevirt/kubevirt/releases/download/v1.8.1/kubevirt-operator.yaml
kubectl apply -f https://github.com/kubevirt/kubevirt/releases/download/v1.8.1/kubevirt-cr.yaml

kubectl -n kubevirt wait kubevirt kubevirt \
  --for=condition=Available \
  --timeout=300s
```

---

## Verify

```bash
# Infra Cluster
kubectl get kubevirt -n kubevirt
kubectl get pods -n kubevirt
kubectl get pods -n cdi

# Management Cluster
KUBECONFIG=~/.kube/ok-capi-kubevirt-on-kbm.yaml kubectl get kubevirt -n kubevirt
```
