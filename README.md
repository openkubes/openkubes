# OpenKubes

<!-- SHIELDS -->
![Release](https://img.shields.io/github/v/release/openkubes/openkubes)
![License](https://img.shields.io/github/license/openkubes/openkubes)
![Status](https://img.shields.io/badge/status-community--preview-blue)
![Docker](https://img.shields.io/badge/docker-kubernautslabs%2Fcapi--platform--runner%3Av4.2-blue)

<div align="center">

### **Kubernetes Anywhere. Make it.**

*On-Premises · Bare Metal · Edge · EKS · AKS · GKE*

</div>

---

> **The Open Platform for Sovereign Kubernetes Infrastructure — On-Premises, Edge, and Multi-Cloud.**

OpenKubes is a platform engineering toolkit that runs Kubernetes clusters, virtual machines, and workloads **anywhere** — bare metal, KubeVirt, EKS, AKS, GKE — through a unified `make` interface and self-service Crossplane APIs.

| Repository | Purpose | Status |
|---|---|---|
| [`openkubes/openkubes`](https://github.com/openkubes/openkubes) | Core Platform (this repo) | ✅ live |
| `openkubes/openkubes-robotics` | Industrial Fleet & Autonomous Systems | 🚧 coming soon |
| `openkubes/openkubes-ai` | AI Inference & Model Runtime | 🚧 coming soon |
| `openkubes/openkubes-anywhere` | Multi-Cloud & Hybrid Operations | 🚧 coming soon |

> 🚀 **Community Preview v1.0.4** — VMs, Clusters, Ingress, TLS — all via `make`.
> Live demo: [rmf.openkubes.ai](https://rmf.openkubes.ai/dashboard/login) · Docs: [docs.openkubes.ai](https://docs.openkubes.ai) *(coming soon)*

---

## Kubernetes Anywhere. Make it.

OpenKubes is operated entirely via `make` — on bare metal, KubeVirt, EKS, AKS, or GKE. No scripts to remember, no long kubectl commands — just:

```bash
# VMs
cd platform/virtualization/openkubesvm
make vm-create  vm=ok4          # create a VM via Crossplane
make vm-ssh     vm=ok4          # SSH into a VM
make vm-delete  vm=ok4          # delete a VM
make vm-list                    # list all VMs

# Clusters — same command, any provider
cd platform/cluster-management
make deploy     cluster=factory-a                        # KubeVirt on-prem
make deploy     cluster=prod-aws                         # EKS (coming soon)
make deploy     cluster=prod-azure                       # AKS (coming soon)
make recreate   cluster=ok1 kubernetes-version=v1.34.1  # reliable upgrade
make kubeconfig cluster=ok1                              # get kubeconfig
make delete     cluster=ok1                              # clean delete
make status     cluster=ok1                              # show status

# Cluster Manager (Headlamp)
make manager-deploy  cluster=ok1   # install Headlamp UI on workload cluster
make manager-token   cluster=ok1   # generate admin token
make manager-open    cluster=ok1   # port-forward + open browser

# Ingress (Traefik via INFRA LB proxy)
make ingress-setup   cluster=ok1   # deploy Traefik + patch INFRA LB
make ingress-delete  cluster=ok1   # remove Traefik
make ingress-delete  cluster=ok1 cert=true  # remove Traefik + cert-manager

# TLS / cert-manager
make cert-setup      cluster=ok1   # cert-manager + Let's Encrypt
make cert-delete     cluster=ok1   # remove cert-manager
make cert-status     cluster=ok1   # show certificate status
```

> **Kubernetes Anywhere. Make it.**

---

## Quick Start

```sh
# 1. Install KubeVirt + CDI on the Infra Cluster
kubectl apply -f https://github.com/kubevirt/kubevirt/releases/download/v1.8.1/kubevirt-operator.yaml
kubectl apply -f https://github.com/kubevirt/kubevirt/releases/download/v1.8.1/kubevirt-cr.yaml
kubectl apply -f https://github.com/kubevirt/containerized-data-importer/releases/latest/download/cdi-operator.yaml
kubectl apply -f https://github.com/kubevirt/containerized-data-importer/releases/latest/download/cdi-cr.yaml

# 2. Deploy Management VMs
cd platform/virtualization/openkubesvm
make setup
make vm-create vm=ok1
make vm-create vm=ok2
make vm-create vm=ok3

# 3. Bootstrap CAPI + CAPK on Management Cluster
clusterctl init --infrastructure kubevirt:v0.11.2 -v5

# 4. Deploy Workload Clusters
cd platform/cluster-management
make setup
make deploy cluster=ok1
make status cluster=ok1
make kubeconfig cluster=ok1

# 5. Install Cluster Manager (Headlamp)
make manager-deploy cluster=ok1
make manager-token  cluster=ok1   # copy token
make manager-open   cluster=ok1   # opens http://localhost:8080

# 6. Ingress + TLS
make ingress-setup  cluster=ok1   # Traefik + INFRA LB
make cert-setup     cluster=ok1   # cert-manager + Let's Encrypt
# → https://headlamp.openkubes.ai  HTTP/2 200 ✅
```

→ Full walkthrough: [`docs/getting-started/README.md`](./docs/getting-started/README.md)

---

## Why OpenKubes?

Most Kubernetes platforms force a choice: cloud flexibility *or* on-prem control. OpenKubes gives you both — with a unified operational model that runs identically on hyperscale clouds, on-premises datacenters, or completely isolated factory floors.

- **Anywhere deployment** — bare metal, KubeVirt VMs, edge (k3s), or cloud via Cluster API
- **Unified Platform API** — Crossplane compositions expose clusters, VMs, and databases as self-service products
- **No vendor lock-in** — built entirely on open standards: Kubernetes, Flux, Cilium, Crossplane, Cluster API
- **Production-proven** — 50+ clusters in production across automotive, industrial, financial, and healthcare environments
- **Enterprise-grade from day one** — GitOps, Zero Trust, RBAC, compliance-ready (DSGVO, TISAX, ISO 27001)

> **This is a platform architecture — not a demo setup.**

---

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Kubernetes (RKE2) | ≥ 1.29 | Management cluster must be running |
| kubectl | latest | configured with cluster access |
| make | ≥ 3.81 | GNU make |
| jq | ≥ 1.6 | used in all platform scripts |
| clusterctl | latest | for CAPI bootstrap |
| helm | ≥ 3.14 | for Crossplane + addons |
| flux | ≥ 2.x | for GitOps bootstrap |

Management cluster provisioning is out of scope — OpenKubes assumes you bring your own.
→ See [`platform/hardware/README.md`](./platform/hardware/README.md) for guidance.

---

## Platform Components

### `platform/virtualization/openkubesvm/` — OpenKubesVM

Self-service KubeVirt VM management via Crossplane or direct kubectl.

```bash
cd platform/virtualization/openkubesvm
make help
```

| Target | Description |
|---|---|
| `make setup` | One-time: apply XRD + Composition |
| `make vm-create vm=ok4` | Create VM via Crossplane Claim |
| `make vm-delete vm=ok4` | Delete VM via Crossplane Claim |
| `make vm-status vm=ok4` | Show VM claim + infra status |
| `make vm-ssh    vm=ok4` | SSH into VM |
| `make vm-list` | List all OpenKubesVMs |
| `make vm-apply  vm=ok4` | Apply VM directly (no Crossplane) |
| `make vm-remove vm=ok4` | Remove VM directly (no Crossplane) |

→ [`platform/virtualization/openkubesvm/README.md`](./platform/virtualization/openkubesvm/README.md)

---

### `platform/cluster-management/` — OpenKubesCluster

Full Kubernetes cluster lifecycle via Crossplane + Cluster API.

```bash
cd platform/cluster-management
make help
```

| Target | Description |
|---|---|
| `make setup` | One-time: apply XRDs, Compositions, RBAC |
| `make deploy     cluster=ok1` | Deploy a workload cluster |
| `make recreate   cluster=ok1 kubernetes-version=v1.34.1` | Reliable upgrade via recreate |
| `make upgrade    cluster=ok1 kubernetes-version=v1.34.1` | Rolling upgrade (experimental) |
| `make kubeconfig cluster=ok1` | Retrieve workload cluster kubeconfig |
| `make status     cluster=ok1` | Show cluster status |
| `make logs       cluster=ok1` | Follow deploy Job logs |
| `make delete     cluster=ok1` | Clean delete via Cleanup Job |
| `make check      cluster=ok1` | Check for leftover resources |
| `make force-clean cluster=ok1` | Emergency cleanup |
| `make manager-deploy cluster=ok1` | Install Headlamp UI on workload cluster |
| `make manager-token  cluster=ok1` | Generate Headlamp admin token |
| `make manager-open   cluster=ok1` | Port-forward + open browser |
| `make manager-status cluster=ok1` | Show Headlamp status |
| `make manager-delete cluster=ok1` | Remove Headlamp |
| `make ingress-setup  cluster=ok1` | Deploy Traefik + patch INFRA LB |
| `make ingress-delete cluster=ok1` | Remove Traefik |
| `make ingress-delete cluster=ok1 cert=true` | Remove Traefik + cert-manager |
| `make ingress-status cluster=ok1` | Show Traefik + LB status |
| `make cert-setup     cluster=ok1` | Deploy cert-manager + Let's Encrypt |
| `make cert-delete    cluster=ok1` | Remove cert-manager |
| `make cert-status    cluster=ok1` | Show certificate status |

→ [`platform/cluster-management/README.md`](./platform/cluster-management/README.md)

---

## Architecture

```
[ Self-Service API ]
  make vm-create vm=ok4          make deploy cluster=ok1
        │                                │
        ▼                                ▼
[ Crossplane Compositions ]    [ Crossplane + Cluster API ]
  OpenKubesVMClaim               KubeVirtClusterClaim
        │                                │
        ▼                                ▼
[ KubeVirt Infra Cluster ]     [ CAPI + CAPK ]
  DataVolume + VM + Service      Machines + KCP + MachineDeployment
        │                                │
        ▼                                ▼
[ Bare Metal Nodes ]           [ Workload Cluster Nodes ]
```

| Component | Role |
|---|---|
| Kubernetes (RKE2) | Control plane for everything |
| Cluster API + CAPK | Cluster lifecycle management |
| KubeVirt | VM layer on Kubernetes |
| Crossplane v2.2.0 | Platform API & self-service compositions |
| Flux | GitOps engine |

→ Full architecture: [`architecture/`](./architecture/)

---

## Roadmap

### v1.0.4 — Done ✅
- [x] Traefik Ingress via INFRA LB proxy (no MetalLB on workload cluster)
- [x] cert-manager + Let's Encrypt TLS (`make cert-setup`)
- [x] Headlamp auto-deployed on CP node (`make manager-deploy`)
- [x] Ordered ingress cleanup with `cert=true` flag
- [x] Full lifecycle test documented (delete + recreate → 4 min)

### v1.1.0
- [ ] OpenKubes Anywhere — EKS, AKS, GKE via unified OpenKubesCluster API
- [ ] OpenKubesClusterManager — Headlamp multi-cluster via Crossplane
- [ ] OpenKubesStorage — self-service PVC + StorageClass management
- [ ] Rolling upgrade via CAPK v0.12.x evaluation

### v1.2.0
- [ ] OpenKubesMetal — Bare Metal via Metal3
- [ ] Observability stack (Prometheus + Grafana)
- [ ] Multi-cluster dashboard

### v2.0.0
- [ ] OpenKubes Fleet — multi-cluster GitOps
- [ ] OpenKubes Robotics — Open-RMF + ROS2
- [ ] Native Go operator (`openkubes-operator`)
- [ ] OperatorHub publication

---

## Community & Support

| | |
|---|---|
| 🌍 Worldwide Meetup | [meetup.com/kubernauts](https://www.meetup.com/kubernauts/) |
| 📺 YouTube | [youtube.com/c/kubernautsio](https://www.youtube.com/c/kubernautsio) |
| 🤖 Live Demo | [rmf.openkubes.ai](https://rmf.openkubes.ai/dashboard/login) |
| 🌐 Docs | [docs.openkubes.ai](https://docs.openkubes.ai) *(coming soon)* |
| 💬 Enterprise | [kubernauts.de](https://kubernauts.de) |

---

## License

[Apache 2.0](./LICENSE) · Built by [Kubernauts GmbH](https://kubernauts.de) · Cologne, Germany
> 10+ years of Kubernetes expertise · 50+ production clusters
