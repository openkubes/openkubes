# OpenKubes

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
# 1. Install KubeVirt + CDI on the Infra Cluster (manual — no Makefile yet)
kubectl apply -f https://github.com/kubevirt/kubevirt/releases/download/v1.8.1/kubevirt-operator.yaml
kubectl apply -f https://github.com/kubevirt/kubevirt/releases/download/v1.8.1/kubevirt-cr.yaml
kubectl apply -f https://github.com/kubevirt/containerized-data-importer/releases/latest/download/cdi-operator.yaml
kubectl apply -f https://github.com/kubevirt/containerized-data-importer/releases/latest/download/cdi-cr.yaml

# 2. Deploy Management VMs
kubectl apply -f ok-vms/

# 3. Bootstrap CAPI + CAPK (manual — no Makefile yet)
clusterctl init --infrastructure kubevirt:v0.11.2 -v5

# 4. Apply Crossplane stack + manage clusters via make
cd platform/cluster-management
make setup                      # one-time: apply XRDs + Compositions
make deploy cluster=ok1         # deploy a workload cluster
make status cluster=ok1         # check status
make kubeconfig cluster=ok1     # get workload kubeconfig
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

Other supported management cluster options:

| Option | Use Case |
|---|---|
| RKE2 on bare metal | Production (recommended) |
| k3s on Multipass VMs | Local development |
| KubeVirt VMs on existing cluster | Nested / lab environments |
| kind | Minimal local testing |

---

## Installation

### 1. Clone

```sh
git clone https://github.com/openkubes/openkubes.git
cd openkubes
```

### 2. Install KubeVirt

```sh
kubectl apply -f https://github.com/kubevirt/kubevirt/releases/download/v1.8.1/kubevirt-operator.yaml
kubectl apply -f https://github.com/kubevirt/kubevirt/releases/download/v1.8.1/kubevirt-cr.yaml
kubectl apply -f https://github.com/kubevirt/containerized-data-importer/releases/latest/download/cdi-operator.yaml
kubectl apply -f https://github.com/kubevirt/containerized-data-importer/releases/latest/download/cdi-cr.yaml

kubectl -n kubevirt wait kubevirt kubevirt --for=condition=Available --timeout=300s
kubectl get pods -n kubevirt && kubectl get pods -n cdi
```

→ [`platform/virtualization/kubevirt/README.md`](./platform/virtualization/kubevirt/README.md)

### 3. Deploy Management VMs

```sh
kubectl apply -f ok-vms/
kubectl get vms -n kubevirt -w
```

Expected output:

```
NAME     STATUS    READY
ok1-vm   Running   True
ok2-vm   Running   True
ok3-vm   Running   True
```

→ [`platform/hardware/README.md`](./platform/hardware/README.md)

### 4. Bootstrap Cluster API + CAPK

```sh
clusterctl init --infrastructure kubevirt:v0.11.2 -v5

kubectl -n capk-system create secret generic external-infra-kubeconfig \
  --from-file=kubeconfig=$HOME/.kube/knautic-bare-metal.yaml \
  --from-literal=namespace=capi-workload
```

→ [`platform/cluster-management/cluster-api/README.md`](./platform/cluster-management/cluster-api/README.md)

### 5. Apply Crossplane Stack & Deploy Clusters

```sh
cd platform/cluster-management
make setup              # one-time: XRDs, Compositions, RBAC
make deploy cluster=ok1
make status cluster=ok1
```

→ [`platform/cluster-management/crossplane/README.md`](./platform/cluster-management/crossplane/README.md)

---

## make Targets

Cluster operations live in `platform/cluster-management/`:

```sh
cd platform/cluster-management
make help
```

| Target | Description |
|---|---|
| `make setup` | One-time: apply all XRDs, Compositions and RBAC |
| `make deploy cluster=ok1` | Deploy a workload cluster |
| `make status cluster=ok1` | Show cluster status (machines, jobs, claims) |
| `make logs cluster=ok1` | Follow deploy Job logs |
| `make kubeconfig cluster=ok1` | Retrieve workload cluster kubeconfig |
| `make upgrade cluster=ok1 kubernetes-version=v1.34.1` | Upgrade cluster |
| `make delete cluster=ok1` | Clean delete via Cleanup Job |
| `make check cluster=ok1` | Check for leftover resources |
| `make force-clean cluster=ok1` | Emergency cleanup |

Runner image management in `platform/cluster-management/capi-platform-v4.2/runner/`:

```sh
cd platform/cluster-management/capi-platform-v4.2/runner
make help
```

| Target | Description |
|---|---|
| `make build-image` | Build runner image |
| `make release-image` | Build (no-cache) + push to Docker Hub |
| `make clear-image-cache` | Clear image cache on management VMs |
| `make deploy-full ARGS='...'` | Full cluster deploy via runner container |
| `make cleanup ARGS='...'` | Cluster cleanup via runner container |
| `make shell` | Interactive shell inside the runner |

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

Override at runtime:

```sh
kubernetes-version=v1.34.1 make upgrade cluster=ok1
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
make upgrade cluster=ok1
make status cluster=ok1
```

For breaking changes see [`CHANGELOG.md`](./CHANGELOG.md).

---

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---|---|---|
| Pods in `CrashLoopBackOff` | Missing secret or config | `make status cluster=ok1` |
| cert-manager not ready | clusterctl init fails | Wait ~60s and retry |
| `make upgrade cluster=ok1` fails | Legacy python3 dependency | Update to v1.0.3 — uses jq |
| CRDs not registered | Previous install incomplete | `make force-clean cluster=ok1` |

```sh
make check cluster=ok1    # check for leftover resources
```

---

## Contributing

See [`CONTRIBUTING.md`](./CONTRIBUTING.md).

```sh
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
