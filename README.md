# OpenKubes Platform

<!-- SHIELDS -->
![Release](https://img.shields.io/github/v/release/openkubes/openkubes)
![License](https://img.shields.io/github/license/openkubes/openkubes)
![Status](https://img.shields.io/badge/status-early--alpha-orange)
![Docker](https://img.shields.io/badge/docker-kubernautslabs%2Fcapi--platform--runner%3Av4.2-blue)

> **AI-Native Runtime Infrastructure for Sovereign Edge, Industrial Systems and Next-Generation Compute.**

OpenKubes is the core runtime distribution for sovereign Kubernetes infrastructure — engineered for mission-critical, air-gapped, and intelligent workloads at any scale.

| Repository | Purpose | Status |
|---|---|---|
| [`openkubes/openkubes`](https://github.com/openkubes/openkubes) | Core Runtime Distribution (this repo) | ✅ live |
| `openkubes/openkubes-robotics` | Fleet Orchestration & Industrial Automation | 🚧 coming soon |
| `openkubes/openkubes-ai` | AI Inference & Model Runtime | 🚧 coming soon |
| `openkubes/openkubes-quantum` | Hybrid Quantum-Classical Runtime | 🚧 coming soon |

> ⚠️ **Project Status: Early Alpha** — Core runtime is undergoing structural sanitization and public blueprint extraction.
> Live demo: [rmf.openkubes.ai](https://rmf.openkubes.ai/dashboard/login) · Docs: [docs.openkubes.ai](https://docs.openkubes.ai) *(coming soon)*

---

## The Make Philosophy

OpenKubes is operated entirely via `make`. No scripts to remember, no long kubectl commands — just:

```bash
# VMs
cd platform/virtualization/openkubesvm
make vm-create  vm=ok4          # create a VM via Crossplane
make vm-ssh     vm=ok4          # SSH into a VM
make vm-delete  vm=ok4          # delete a VM
make vm-list                    # list all VMs

# Clusters
cd platform/cluster-management
make deploy     cluster=ok1                              # deploy a workload cluster
make upgrade    cluster=ok1 kubernetes-version=v1.34.1  # rolling upgrade (experimental)
make recreate   cluster=ok1 kubernetes-version=v1.34.1  # reliable upgrade via recreate
make kubeconfig cluster=ok1                             # get workload kubeconfig
make delete     cluster=ok1                             # clean delete
make status     cluster=ok1                             # show status
make logs       cluster=ok1                             # follow job logs
```

> **Run VMs. Run Clusters. Run Anything.**

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

### v1.1.0
- [ ] OpenKubesStorage — self-service PVC + StorageClass management
- [ ] OpenKubesNetworking — Network policies + LoadBalancer management
- [ ] Status writeback for OpenKubesVM (phase, IP)

### v1.2.0
- [ ] Rolling upgrade via CAPK v0.12.x evaluation
- [ ] Observability stack (Prometheus + Grafana)
- [ ] Multi-cluster dashboard

### v2.0.0
- [ ] Native Go operator (`openkubes-operator`)
- [ ] Full reconcile loop with Events and Conditions
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
