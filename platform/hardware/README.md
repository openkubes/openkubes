# Management VMs (ok-vms)

This guide covers deploying the three Management VMs (`ok1-vm`, `ok2-vm`, `ok3-vm`)
on the Infra Cluster. These VMs form the nodes of the OpenKubes Management Cluster.

---

## Overview

```
Infra Cluster (RKE2 or Kubeadm Bare Metal)
├── ok1-vm  →  <MGMT_VM_1_IP>  (Management Cluster Node 1)
├── ok2-vm  →  <MGMT_VM_2_IP>  (Management Cluster Node 2)
└── ok3-vm  →  <MGMT_VM_3_IP>  (Management Cluster Node 3)
```

Each VM:
- Ubuntu 24.04
- 30Gi disk (DataVolume / PVC)
- Exposed via MetalLB LoadBalancer on port 22 (SSH) and 6443 (API)

Set your MetalLB IPs in the VM manifests under `ok-vms/` before deploying.

---

## Prerequisites

- KubeVirt installed on the Infra Cluster (see [`../virtualization/kubevirt/README.md`](../virtualization/kubevirt/README.md))
- MetalLB configured with an IP pool
- `local-path` or equivalent StorageClass available

---

## Deploy the VMs

```bash
# From the repo root
kubectl apply -f ok-vms/

# Watch DataVolumes (disk import)
kubectl get dv -n kubevirt -w

# Watch VMs come up
kubectl get vms -n kubevirt -w
```

Expected output:

```
NAME     AGE     STATUS    READY
ok1-vm   5m      Running   True
ok2-vm   5m      Running   True
ok3-vm   5m      Running   True
```

---

## Verify

```bash
# VM status
kubectl get vmi -n kubevirt -o wide

# LoadBalancer services (SSH access)
kubectl get svc -n kubevirt

# Expected services:
# ok1-svc   LoadBalancer   10.43.x.x   <MGMT_VM_1_IP>   22:xxxxx/TCP
# ok2-svc   LoadBalancer   10.43.x.x   <MGMT_VM_2_IP>   22:xxxxx/TCP
# ok3-svc   LoadBalancer   10.43.x.x   <MGMT_VM_3_IP>   22:xxxxx/TCP

# PVCs
kubectl get pvc -n kubevirt
```

---

## Access the VMs

```bash
# SSH (password set via cloud-init in the VM manifest)
ssh ubuntu@<MGMT_VM_1_IP>
ssh ubuntu@<MGMT_VM_2_IP>
ssh ubuntu@<MGMT_VM_3_IP>

# Console access (no SSH needed)
kubectl virt console ok1-vm -n kubevirt
```

---

## Next Step

Once all three VMs are running and accessible via SSH, install Kubernetes
on them using kubeadm to form the Management Cluster.

→ See [`../cluster-management/cluster-api/README.md`](../cluster-management/cluster-api/README.md)
