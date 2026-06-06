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

## Quick Start

```sh
make help                  # all available targets
make kubevirt-install      # install KubeVirt on management cluster
make vms-deploy            # deploy management VMs (ok1/ok2/ok3)
make capi-init             # bootstrap Cluster API + CAPK
make crossplane-install    # install Crossplane v2.2.0
make gitops-bootstrap      # bootstrap Flux GitOps
make verify                # check overall platform status
```

> All targets are idempotent. Run `make help` first.

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

Other supported management cluster options:

| Option | Use Case |
|---|---|
| RKE2 on bare metal | Production (recommended) |
| k3s on Multipass VMs | Local development |
| KubeVirt VMs on existing cluster | Nested / lab environments |
| kind | Minimal local testing |

---

## Installation

### 1. Clone & configure

```sh
git clone https://github.com/openkubes/openkubes.git
cd openkubes
cp .env.example .env    # adjust versions and namespace defaults
```

### 2. Install KubeVirt

```sh
make kubevirt-install
make kubevirt-verify
```

<details>
<summary>What <code>make kubevirt-install</code> does</summary>

```
kubectl apply -f https://github.com/kubevirt/kubevirt/releases/download/v1.8.1/kubevirt-operator.yaml
kubectl apply -f https://github.com/kubevirt/kubevirt/releases/download/v1.8.1/kubevirt-cr.yaml
kubectl apply -f https://github.com/kubevirt/containerized-data-importer/releases/latest/download/cdi-operator.yaml
kubectl apply -f https://github.com/kubevirt/containerized-data-importer/releases/latest/download/cdi-cr.yaml
# Optional: KubeVirt Manager UI
kubectl apply -f https://github.com/kubevirt-manager/kubevirt-manager/releases/download/v1.5.4/bundled-v1.5.4.yaml
```

</details>

### 3. Deploy Management VMs

```sh
make vms-deploy
make vms-verify
```

Expected output:

```
NAME     STATUS    READY
ok1-vm   Running   True
ok2-vm   Running   True
ok3-vm   Running   True
```

### 4. Bootstrap Cluster API + CAPK

```sh
make capi-init
make capi-verify
```

→ See [`platform/cluster-management/cluster-api/README.md`](./platform/cluster-management/cluster-api/README.md)

### 5. Deploy Crossplane & GitOps

```sh
make crossplane-install    # Crossplane v2.2.0
make gitops-bootstrap      # Flux
```

→ See [`platform/gitops/fluxcd/README.md`](./platform/gitops/fluxcd/README.md)

---

## make Targets

```sh
make help
```

| Target | Description |
|---|---|
| `make kubevirt-install` | Install KubeVirt operator + CDI |
| `make kubevirt-verify` | Check KubeVirt and CDI pod status |
| `make vms-deploy` | Deploy ok1/ok2/ok3 management VMs |
| `make vms-verify` | Check VM status via kubectl virt |
| `make capi-init` | Bootstrap CAPI + CAPK provider |
| `make capi-verify` | Check capi-system / capk-system pods |
| `make capi-secret` | Create external-infra-kubeconfig secret |
| `make crossplane-install` | Install Crossplane v2.2.0 |
| `make crossplane-upgrade` | Upgrade Crossplane (uses jq, no Python) |
| `make gitops-bootstrap` | Bootstrap Flux on management cluster |
| `make verify` | Full platform status check |
| `make lint` | Lint all manifests (yamllint) |
| `make diff` | Dry-run diff against current cluster state |
| `make clean` | Teardown all platform components |
| `make debug` | Collect diagnostic info for troubleshooting |

---

## Configuration

All versions and namespace defaults are managed via `.env`:

```sh
# Core versions
KUBEVIRT_VERSION=v1.8.1
CROSSPLANE_VERSION=v2.2.0
CAPK_VERSION=v0.11.2

# Namespaces
CROSSPLANE_NAMESPACE=crossplane-system
CAPI_NAMESPACE=capi-system
CAPK_NAMESPACE=capk-system

# Docker image
RUNNER_IMAGE=kubernautslabs/capi-platform-runner:v4.2
```

Override at runtime without editing `.env`:

```sh
CROSSPLANE_VERSION=v2.3.0 make crossplane-upgrade
```

---

## Architecture

```
[ Self-Service / API / GitOps / CI/CD / Service Catalog ]
                        │
                        ▼
         [ Management Zone ]
  Crossplane v2.2.0 • Cluster API • Flux • Kyverno
  External Secrets • OIDC/Keycloak • Observability
                        │
                        ▼
        [ Infrastructure Zone ]
  Bare Metal • KubeVirt VMs • GPU Nodes
  Storage (Longhorn / Ceph) • Networking (Cilium)
                        │
                        ▼
       [ Tenant / Workload Zone ]
  Workload Clusters • VMs • AI/GPU
  Robotics • HPC • Platform Services
```

| Component | Role |
|---|---|
| Kubernetes (RKE2) | Control plane for everything |
| Cluster API + CAPK | Cluster lifecycle management |
| KubeVirt | VM layer on Kubernetes |
| Crossplane v2.2.0 | Platform API & self-service compositions |
| Flux | GitOps engine |

→ Full architecture deep dives: [`architecture/`](./architecture/)

---

## Platform Components

### Cluster Management
- [`platform/cluster-management/cluster-api/`](./platform/cluster-management/cluster-api) — CAPI + CAPK providers, cluster templates

### GitOps
- [`platform/gitops/fluxcd/`](./platform/gitops/fluxcd) — Flux (recommended)
- [`platform/gitops/argocd/`](./platform/gitops/argocd) — ArgoCD

### Networking
- [`platform/networking/cilium/`](./platform/networking/cilium) — Cilium CNI (default)
- [`platform/networking/calico/`](./platform/networking/calico) — Calico CNI
- [`platform/networking/multus/`](./platform/networking/multus) — Multi-network for Robotics / industrial

### Robotics
- [`platform/robotics/ros2/`](./platform/robotics/ros2) — ROS 2 on Kubernetes
- [`platform/robotics/open-rmf/`](./platform/robotics/open-rmf) — Open-RMF fleet management
- [`platform/robotics/dds/`](./platform/robotics/dds) — DDS networking

### Observability
- [`platform/observability/`](./platform/observability) — Metrics, logging, tracing, alerting

### Virtualization
- [`platform/virtualization/kubevirt/`](./platform/virtualization/kubevirt) — KubeVirt configuration and VM blueprints

---

## Blueprints

| Blueprint | Description |
|---|---|
| [`bare-metal`](./blueprints/bare-metal) | Production bare metal cluster |
| [`capi-kubevirt`](./blueprints/capi-kubevirt) | CAPI + KubeVirt workload cluster |
| [`sovereign-edge`](./blueprints/sovereign-edge) | Air-gapped sovereign edge deployment |
| [`robotops-edge-site`](./blueprints/robotops-edge-site) | Edge site for robotics operations |
| [`ros2-dds-industrial-networking`](./blueprints/ros2-dds-industrial-networking) | ROS 2 with industrial DDS networking |
| [`open-rmf-fleet-management`](./blueprints/open-rmf-fleet-management) | Open-RMF autonomous fleet management |

---

## Architecture Deep Dives

- [`AIRGAPPED-OPERATIONS.md`](./architecture/AIRGAPPED-OPERATIONS.md)
- [`CLUSTERAPI-EDGE-SCALING.md`](./architecture/CLUSTERAPI-EDGE-SCALING.md)
- [`DDS-NETWORKING.md`](./architecture/DDS-NETWORKING.md)
- [`GITOPS-EDGE-LIFECYCLE.md`](./architecture/GITOPS-EDGE-LIFECYCLE.md)
- [`GPU-ISOLATION.md`](./architecture/GPU-ISOLATION.md)
- [`KUBEVIRT-LEGACY-INTEGRATION.md`](./architecture/KUBEVIRT-LEGACY-INTEGRATION.md)
- [`SOVEREIGN-EDGE-RUNTIME.md`](./architecture/SOVEREIGN-EDGE-RUNTIME.md)

---

## Upgrading

```sh
# Edit version in .env, then:
make crossplane-upgrade
make verify
```

For breaking changes see [`CHANGELOG.md`](./CHANGELOG.md).

---

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---|---|---|
| Pods in `CrashLoopBackOff` | Missing secret or config | Check `make verify` output |
| `make capi-init` fails | cert-manager not ready | Wait and retry — cert-manager needs ~60s |
| `make crossplane-upgrade` fails | Legacy python3 dependency | Update to v1.0.3 — uses jq |
| CRDs not registered | Previous install incomplete | `make clean && make install` |

```sh
make debug    # collect full diagnostic snapshot
```

---

## Contributing

See [`CONTRIBUTING.md`](./CONTRIBUTING.md). In short:

```sh
make lint     # before committing
make diff     # review cluster impact
```

Branches: `main` (stable) · `dev` (active development) · `release/vX.Y.Z` (release prep)

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
