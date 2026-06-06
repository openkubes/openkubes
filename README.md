# OpenKubes

> **The Unified Platform for Kubernetes, Virtual Machines & Specialized Workloads**
>
> Run Everything. Deliver Anything.

[![Release](https://img.shields.io/github/v/release/openkubes/openkubes)](https://github.com/openkubes/openkubes/releases)
[![License](https://img.shields.io/github/license/openkubes/openkubes)](LICENSE)

---

## What is OpenKubes?

OpenKubes turns bare metal servers into a fully automated, self-service Kubernetes platform. It provides a clean API for provisioning and managing workload clusters — no manual steps, no scripts to run by hand. Just `kubectl apply`.

```
kubectl apply -f examples/ok1.yaml
       ↓
Crossplane provisions everything
       ↓
3 VMs boot on bare metal
       ↓
Kubernetes v1.34 cluster, fully provisioned
       ↓
kubectl get nodes → Ready
```

---

## Architecture

![OpenKubes Reference Architecture v1](architecture/openkubes-reference-architecture-v1.png)

OpenKubes is built around four clearly separated zones:

| Zone | Purpose |
|------|---------|
| **Management Zone** | Controls, provisions, secures and governs the platform |
| **Infrastructure Zone** | Bare metal nodes, KubeVirt VMs, storage and networking |
| **Tenant / Workload Zone** | Workload clusters, VMs, AI/GPU, HPC, platform services |
| **Operations & Governance** | Observability, security, compliance (cross-cutting) |

→ [Reference Architecture (EN)](architecture/reference-architecture-v1-en.md) | [Referenzarchitektur (DE)](architecture/reference-architecture-v1-de.md) | [Whitepaper](architecture/OpenKubes_BM_Whitepaper_v2.docx)

---

## Core Technology Stack

| Concern | Technology |
|---------|-----------|
| Infra Cluster | RKE2 / Talos on bare metal |
| VM Layer | KubeVirt v1.8.1 |
| Cluster Lifecycle | Cluster API + CAPK v0.11.2 |
| Platform API | Crossplane v2.2.0 |
| GitOps | Flux |
| CNI | Calico (default) / Cilium |
| Load Balancer | MetalLB |

---

## Quick Start

```bash
# 1. Apply Crossplane stack (one-time setup)
kubectl apply -f platform/cluster-management/crossplane/namespace.yaml
kubectl apply -f platform/cluster-management/crossplane/rbac.yaml
kubectl apply -f platform/cluster-management/crossplane/xrd.yaml
kubectl apply -f platform/cluster-management/crossplane/xrd-cleanup.yaml
kubectl apply -f platform/cluster-management/crossplane/composition.yaml
kubectl apply -f platform/cluster-management/crossplane/composition-cleanup.yaml

# 2. Deploy a workload cluster
kubectl apply -f platform/cluster-management/crossplane/examples/ok1.yaml

# 3. Watch it provision
kubectl get jobs -n openkubes-system -w
kubectl get cluster -A

# 4. Get kubeconfig
clusterctl get kubeconfig ok1-<hash> -n ok1-<hash> > ~/.kube/ok1.kubeconfig
KUBECONFIG=~/.kube/ok1.kubeconfig kubectl get nodes

# 5. Clean up
kubectl apply -f platform/cluster-management/crossplane/examples/cleanup-ok1.yaml
```

→ Full guide: [docs/getting-started/README.md](docs/getting-started/README.md)

---

## Repository Structure

```
openkubes/
├── architecture/                        # Reference architecture, diagrams, whitepaper
├── docs/
│   ├── getting-started/                 # Step-by-step setup guide
│   └── Cheat-Sheet.md                   # Operations quick reference
└── platform/
    ├── cluster-management/
    │   ├── capi-platform-v4.2/          # Core platform scripts + runner image
    │   ├── cluster-api/                 # CAPI + CAPK installation guide
    │   └── crossplane/                  # Crossplane XRDs, Compositions, examples
    ├── virtualization/
    │   └── kubevirt/                    # KubeVirt installation guide
    ├── hardware/                        # Management VM deployment
    ├── networking/                      # Calico, Cilium, Multus
    ├── observability/                   # Monitoring (Enterprise)
    └── gitops/                          # Flux / ArgoCD (coming soon)
```

---

## Documentation

| Guide | Description |
|-------|-------------|
| [Getting Started](docs/getting-started/README.md) | Full setup from bare metal to running clusters |
| [KubeVirt Installation](platform/virtualization/kubevirt/README.md) | Install KubeVirt on infra and management cluster |
| [Management VMs](platform/hardware/README.md) | Deploy ok-vms on the infra cluster |
| [Cluster API + CAPK](platform/cluster-management/cluster-api/README.md) | Install CAPI and connect to infra cluster |
| [Crossplane Self-Service](platform/cluster-management/crossplane/README.md) | Deploy clusters via kubectl apply |
| [Operations CheatSheet](docs/Cheat-Sheet.md) | Day-to-day commands quick reference |
| [Reference Architecture](architecture/README.md) | Full platform architecture overview |

---

## Platform APIs

| API | Description |
|-----|-------------|
| `KubeVirtClusterClaim` | Self-service Kubernetes cluster provisioning |
| `KubeVirtClusterCleanupClaim` | Self-service cluster deletion |
| `OpenKubesVM` | VM-as-a-Service _(roadmap)_ |
| `OpenKubesDatabase` | DBaaS _(roadmap)_ |
| `OpenKubesTenant` | Tenant / project isolation _(roadmap)_ |
| `OpenKubesAIWorkspace` | AI / GPU workspaces _(roadmap)_ |

---

## Roadmap

### v1.1.0
- [ ] Cluster name without hash suffix
- [ ] Status writeback (phase, endpoint, kubeconfigSecret)
- [ ] GitOps integration (Flux)

### v1.2.0
- [ ] Observability stack (Prometheus + Grafana)
- [ ] Cluster upgrade via spec change
- [ ] VM-as-a-Service API

### v2.0.0
- [ ] Native Go operator (`openkubes-operator`)
- [ ] OperatorHub publication

---

## License

[Apache 2.0](LICENSE)

---

**OpenKubes** is built with ❤️ by [Kubernauts](https://kubernauts.de) and the community.
