# Management VMs (ok-vms)

Deploys the three Management VMs (`ok1-vm`, `ok2-vm`, `ok3-vm`) on the Infra Cluster.
These VMs form the nodes of the OpenKubes Management Cluster.

## make Targets

```sh
make vms-deploy    # deploy ok1-vm, ok2-vm, ok3-vm
make vms-verify    # check VM and DataVolume status
make vms-ssh       # print SSH commands for all three VMs
make vms-clean     # delete VMs, PVCs and LoadBalancer services
```

---

## Overview

```
Infra Cluster (RKE2 or Kubeadm Bare Metal)
├── ok1-vm  →  <MGMT_VM_1_IP>  (Management Cluster Node 1)
├── ok2-vm  →  <MGMT_VM_2_IP>  (Management Cluster Node 2)
└── ok3-vm  →  <MGMT_VM_3_IP>  (Management Cluster Node 3)
```

Each VM: Ubuntu 24.04 · 30Gi disk (DataVolume/PVC) · MetalLB LoadBalancer (SSH port 22, API port 6443)

Set your MetalLB IPs in `ok-vms/` manifests before deploying.

## Prerequisites

- KubeVirt installed on the Infra Cluster → [`../virtualization/kubevirt/README.md`](../virtualization/kubevirt/README.md)
- MetalLB configured with an IP pool
- `local-path` or equivalent StorageClass available

---

## Manual Steps

<details>
<summary>Step-by-step without make</summary>

```sh
# Deploy
kubectl apply -f ok-vms/

# Watch DataVolumes (disk import — takes a few minutes)
kubectl get dv -n kubevirt -w

# Watch VMs
kubectl get vms -n kubevirt -w
```

Expected output:

```
NAME     AGE   STATUS    READY
ok1-vm   5m    Running   True
ok2-vm   5m    Running   True
ok3-vm   5m    Running   True
```

```sh
# VM interfaces and IPs
kubectl get vmi -n kubevirt -o wide

# LoadBalancer services
kubectl get svc -n kubevirt

# PVCs
kubectl get pvc -n kubevirt
```

### Access

```sh
ssh ubuntu@<MGMT_VM_1_IP>
ssh ubuntu@<MGMT_VM_2_IP>
ssh ubuntu@<MGMT_VM_3_IP>

# Console (no SSH needed)
kubectl virt console ok1-vm -n kubevirt
```

</details>

---

## Next Step

Once all three VMs are running, install Kubernetes on them (kubeadm) to form the Management Cluster.

→ [`../cluster-management/cluster-api/README.md`](../cluster-management/cluster-api/README.md)
