# Getting Started with OpenKubes

This guide walks you through setting up OpenKubes from scratch on bare metal.

---

## Prerequisites

- Bare metal servers (3+ nodes recommended)
- RKE2 or equivalent Kubernetes distribution installed
- MetalLB configured with an IP pool
- `kubectl`, `helm`, `clusterctl` installed locally

---

## Step-by-Step Setup

### Step 1 — Install KubeVirt on the Infra Cluster

KubeVirt enables running Virtual Machines as Kubernetes workloads.

→ [`../../platform/virtualization/kubevirt/README.md`](../../platform/virtualization/kubevirt/README.md)

```bash
kubectl apply -f https://github.com/kubevirt/kubevirt/releases/download/v1.8.1/kubevirt-operator.yaml
kubectl apply -f https://github.com/kubevirt/kubevirt/releases/download/v1.8.1/kubevirt-cr.yaml
```

---

### Step 2 — Deploy Management VMs

Deploy the three VMs (`ok1-vm`, `ok2-vm`, `ok3-vm`) that will form the Management Cluster.

→ [`../../platform/hardware/README.md`](../../platform/hardware/README.md)

```bash
kubectl apply -f ok-vms/
kubectl get vms -n kubevirt -w
```

---

### Step 3 — Install Cluster API + CAPK

Install CAPI with the KubeVirt Infrastructure Provider on the Management Cluster
and connect it to the Infra Cluster.

→ [`../../platform/cluster-management/cluster-api/README.md`](../../platform/cluster-management/cluster-api/README.md)

```bash
clusterctl init --infrastructure kubevirt:v0.11.2
kubectl -n capk-system create secret generic external-infra-kubeconfig \
  --from-file=kubeconfig=$HOME/.kube/infra.yaml \
  --from-literal=namespace=capi-workload
```

---

### Step 4 — Deploy Workload Clusters via Crossplane

Install Crossplane and use the `KubeVirtClusterClaim` API to provision
fully isolated workload clusters with a single `kubectl apply`.

→ [`../../platform/cluster-management/crossplane/README.md`](../../platform/cluster-management/crossplane/README.md)

```bash
kubectl apply -f platform/cluster-management/crossplane/examples/ok1.yaml
kubectl get jobs -n openkubes-system -w
```

---

## What You Get

After completing all steps:

```
kubectl get cluster -A

NAMESPACE    NAME         AVAILABLE   PHASE         VERSION
ok1-xxxxx    ok1-xxxxx    True        Provisioned   v1.34.1
ok2-xxxxx    ok2-xxxxx    True        Provisioned   v1.34.1
```

Each cluster has:
- 1 Control Plane node
- 2 Worker nodes
- Calico CNI installed
- Dedicated namespace on management and infra cluster
- LoadBalancer service with dedicated MetalLB IP

---

## Architecture

→ See [`../../architecture/README.md`](../../architecture/README.md) for the full reference architecture.
