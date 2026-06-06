# OpenKubes Platform v1.0.0

> **The Unified Platform for Kubernetes, Virtual Machines & Specialized Workloads**

We are excited to announce the first stable release of **OpenKubes** — a production-ready, self-service Kubernetes platform built on bare metal using KubeVirt, Cluster API, and Crossplane.

---

## 🚀 What is OpenKubes?

OpenKubes turns bare metal servers into a fully automated Kubernetes platform. It provides a self-service API for provisioning and managing workload clusters — no manual steps, no scripts to run manually. Just `kubectl apply`.

```
kubectl apply -f examples/ok1.yaml
       ↓
3 VMs boot on bare metal
       ↓
Kubernetes v1.34 cluster, fully provisioned
       ↓
kubectl get nodes → Ready
```

---

## ✅ What's included in v1.0.0

### Platform Core
- **Self-service cluster provisioning** via `KubeVirtClusterClaim` — deploy a full Kubernetes cluster with a single `kubectl apply`
- **Self-service cluster deletion** via `KubeVirtClusterCleanupClaim` — clean removal of all resources including VMs, namespaces, and secrets
- **Namespace isolation** — each workload cluster gets its own namespace on both the management and infra cluster
- **Per-cluster infra secret** — isolated KubeVirt access per cluster

### Networking
- **Calico CNI** automatically installed into every workload cluster
- **MetalLB LoadBalancer** for the Kubernetes API server endpoint
- **Multus** support (optional)

### Infrastructure
- **KubeVirt v1.8.1** — virtual machines as Kubernetes workloads on bare metal
- **CDI** (Containerized Data Importer) for VM disk management
- **CAPI v1.12.5** — cluster lifecycle management
- **CAPK v0.11.2** — KubeVirt infrastructure provider for Cluster API

### Platform API (Crossplane)
- **Crossplane v2.2.0** as the platform API layer
- **function-patch-and-transform v0.10.1** (Crossplane v2 compatible)
- **function-go-templating v0.11.4**
- **provider-kubernetes v0.17.0** with in-cluster identity

### Operations
- **capi-platform-runner v4.2** — standalone runner image with all platform tooling embedded
- **Automatic CAPI finalizer cleanup** — no more stuck `Terminating` namespaces
- **Operations CheatSheet** — quick reference for all day-to-day commands

### Documentation
- Reference Architecture v1 (EN + DE)
- Getting Started Guide
- KubeVirt Installation Guide
- Cluster API + CAPK Installation Guide
- Crossplane Setup Guide
- Operations CheatSheet

---

## 📋 Prerequisites

| Component | Version |
|-----------|---------|
| Bare metal servers | 3+ nodes recommended |
| RKE2 / Talos (Infra Cluster) | any recent version |
| KubeVirt | v1.8.1 |
| MetalLB | any recent version |
| Crossplane | v2.2.0 |
| CAPI | v1.12.5 |
| CAPK | v0.11.2 |

---

## 🏁 Quick Start

```bash
# 1. Apply Crossplane stack
kubectl apply -f platform/cluster-management/crossplane/namespace.yaml
kubectl apply -f platform/cluster-management/crossplane/rbac.yaml
kubectl apply -f platform/cluster-management/crossplane/xrd.yaml
kubectl apply -f platform/cluster-management/crossplane/xrd-cleanup.yaml
kubectl apply -f platform/cluster-management/crossplane/composition.yaml
kubectl apply -f platform/cluster-management/crossplane/composition-cleanup.yaml

# 2. Deploy a cluster
kubectl apply -f platform/cluster-management/crossplane/examples/ok1.yaml

# 3. Watch it provision
kubectl get jobs -n openkubes-system -w
kubectl get cluster -A

# 4. Get kubeconfig
clusterctl get kubeconfig ok1-<hash> -n ok1-<hash> > ~/.kube/ok1.kubeconfig
KUBECONFIG=~/.kube/ok1.kubeconfig kubectl get nodes
```

→ Full guide: [`docs/getting-started/README.md`](docs/getting-started/README.md)

---

## 🗺️ Roadmap

### v1.1.0
- [ ] Cluster name without hash suffix
- [ ] Status writeback (phase, endpoint, kubeconfigSecret)
- [ ] GitOps integration (Flux)

### v1.2.0
- [ ] Observability stack (Prometheus + Grafana)
- [ ] Cluster upgrade via spec change
- [ ] Multi-cluster dashboard

### v2.0.0
- [ ] Native Go operator (`openkubes-operator`)
- [ ] Full reconcile loop with Events and Conditions
- [ ] OperatorHub publication

---

## 🙏 Credits

Built with:
- [Cluster API](https://cluster-api.sigs.k8s.io/)
- [Cluster API Provider KubeVirt](https://github.com/kubernetes-sigs/cluster-api-provider-kubevirt)
- [KubeVirt](https://kubevirt.io/)
- [Crossplane](https://crossplane.io/)
- [Calico](https://projectcalico.docs.tigera.io/)
- [MetalLB](https://metallb.universe.tf/)

---

**OpenKubes** — Run Everything. Deliver Anything.
