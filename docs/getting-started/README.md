# Getting Started with OpenKubes

Step-by-step setup from bare metal to running workload clusters.

---

## Prerequisites

- Bare metal servers (3+ nodes recommended), RKE2 installed and running
- MetalLB configured with an IP pool
- `kubectl`, `helm`, `clusterctl`, `jq`, `docker` installed locally

---

## Step 1 — Install KubeVirt on the Infra Cluster

KubeVirt enables running Virtual Machines as Kubernetes workloads.

```sh
kubectl apply -f https://github.com/kubevirt/kubevirt/releases/download/v1.8.1/kubevirt-operator.yaml
kubectl apply -f https://github.com/kubevirt/kubevirt/releases/download/v1.8.1/kubevirt-cr.yaml
kubectl apply -f https://github.com/kubevirt/containerized-data-importer/releases/latest/download/cdi-operator.yaml
kubectl apply -f https://github.com/kubevirt/containerized-data-importer/releases/latest/download/cdi-cr.yaml

kubectl -n kubevirt wait kubevirt kubevirt --for=condition=Available --timeout=300s
kubectl get pods -n kubevirt
kubectl get pods -n cdi
```

→ [`../../platform/virtualization/kubevirt/README.md`](../../platform/virtualization/kubevirt/README.md)

---

## Step 2 — Deploy Management VMs

Deploy the three VMs (`ok1-vm`, `ok2-vm`, `ok3-vm`) that will form the Management Cluster.

```sh
kubectl apply -f ok-vms/
kubectl get dv -n kubevirt -w    # watch disk import
kubectl get vms -n kubevirt -w   # watch VMs come up
```

Expected output:

```
NAME     STATUS    READY
ok1-vm   Running   True
ok2-vm   Running   True
ok3-vm   Running   True
```

→ [`../../platform/hardware/README.md`](../../platform/hardware/README.md)

---

## Step 3 — Install Cluster API + CAPK

Bootstrap CAPI with the KubeVirt Infrastructure Provider on the Management Cluster.

```sh
# Install cert-manager first
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/latest/download/cert-manager.yaml
kubectl -n cert-manager wait deployment cert-manager --for=condition=Available --timeout=120s

# Init CAPI + CAPK
clusterctl init --infrastructure kubevirt:v0.11.2 -v5

# Connect to Infra Cluster
kubectl -n capk-system create secret generic external-infra-kubeconfig \
  --from-file=kubeconfig=$HOME/.kube/knautic-bare-metal.yaml \
  --from-literal=namespace=capi-workload
```

→ [`../../platform/cluster-management/cluster-api/README.md`](../../platform/cluster-management/cluster-api/README.md)

---

## Step 4 — Deploy Crossplane & Provision Workload Clusters

Apply the Crossplane stack (XRDs, Compositions, RBAC):

```sh
cd platform/cluster-management
make setup
```

Provision a workload cluster:

```sh
make deploy cluster=ok1
make status cluster=ok1
make logs   cluster=ok1
```

Get the kubeconfig:

```sh
make kubeconfig cluster=ok1
KUBECONFIG=~/.kube/ok1.kubeconfig kubectl get nodes
```

→ [`../../platform/cluster-management/crossplane/README.md`](../../platform/cluster-management/crossplane/README.md)

---

## Cluster Lifecycle (make Targets)

All cluster operations go through `platform/cluster-management/`:

```sh
cd platform/cluster-management
make help                                          # show all targets
make setup                                         # one-time: apply XRDs + Compositions
make deploy      cluster=ok1                       # deploy a cluster
make status      cluster=ok1                       # show cluster status
make logs        cluster=ok1                       # follow deploy job logs
make kubeconfig  cluster=ok1                       # get workload kubeconfig
make upgrade     cluster=ok1 kubernetes-version=v1.34.1
make delete      cluster=ok1                       # clean delete
make check       cluster=ok1                       # check for leftover resources
make force-clean cluster=ok1                       # emergency cleanup
```

---

## What You Get

After completing all steps:

```sh
kubectl get cluster -A

NAMESPACE    NAME         AVAILABLE   PHASE         VERSION
ok1-xxxxx    ok1-xxxxx    True        Provisioned   v1.34.1
ok2-xxxxx    ok2-xxxxx    True        Provisioned   v1.34.1
```

Each cluster has 1 control plane node, 2 worker nodes, Calico CNI, and a dedicated MetalLB LoadBalancer IP.

---

## Architecture

→ [`../../architecture/README.md`](../../architecture/README.md)
