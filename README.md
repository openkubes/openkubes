# OpenKubes

> **AI-Native Runtime Infrastructure for Sovereign Edge, Industrial Systems and Next-Generation Compute.**

OpenKubes is the core runtime distribution for sovereign Kubernetes infrastructure — engineered for mission-critical, air-gapped, and intelligent workloads at any scale.

Domain-specific runtimes are built on top of this foundation:

| Repository | Purpose |
|---|---|
| `openkubes/openkubes` | Core Runtime Distribution (this repo) |
| `openkubes/openkubes-robotics` | Fleet Orchestration & Industrial Automation |
| `openkubes/openkubes-ai` | AI Inference & Model Runtime |
| `openkubes/openkubes-quantum` | Hybrid Quantum-Classical Runtime |

> ⚠️ **Project Status: Early Alpha** — Core runtime is undergoing structural sanitization and public blueprint extraction.  
> Live demo: [rmf.openkubes.ai](https://rmf.openkubes.ai/dashboard/login) · Docs & Architecture: [openkubes.ai](https://openkubes.ai) *(coming soon)*

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

## Core Architectural Pillars

| Pillar | Description |
|---|---|
| **Deterministic Reliability** | Automated HA and microsecond self-healing loops at the local edge |
| **True GitOps for OT** | Declarative infrastructure via version-controlled code — secure, auditable OTA updates |
| **Sovereign Edge Autonomy** | 100% offline and air-gapped execution — KRITIS, Automotive, Zero Trust ready |
| **AI & GPU Edge Native** | Advanced hardware scheduling (NVIDIA MIG) isolating telemetry from inference pipelines |
| **Hybrid Edge Sovereignty** | One unified model across public cloud, on-prem datacenter, or isolated factory floor |

---

## The Four-Layer Runtime Model

```
+--------------------------------------------------------------------------------------------------+
|                                   1. AI & INTELLIGENCE LAYER                                     |
|--------------------------------------------------------------------------------------------------|
| Autonomous Agents | Vision Inference | AI Pipelines | Vector Databases | Fleet Optimization      |
| Edge AI Models    | LLM Runtime      | Predictive Analytics | Digital Twin Workloads             |
+--------------------------------------------------------------------------------------------------+
                                              │
                                              │ Secure APIs / gRPC / Event Streams
                                              ▼
+--------------------------------------------------------------------------------------------------+
|                              2. OPENKUBES OPERATIONAL RUNTIME                                    |
|--------------------------------------------------------------------------------------------------|
| GitOps Engine | HA/DR Automation | Sovereign Edge Control  | Unified Telemetry                   |
| ClusterAPI    | KubeVirt         | GPU Scheduling          | Identity & Access Management        |
| ArgoCD / Flux | Observability    | Policy Enforcement      | Runtime Orchestration               |
+--------------------------------------------------------------------------------------------------+
                                              │
                                              │ Runtime Scheduling / Service Mesh / CNI
                                              ▼
+--------------------------------------------------------------------------------------------------+
|                          3. ORCHESTRATION & FLEET AUTOMATION LAYER                               |
|--------------------------------------------------------------------------------------------------|
| Enterprise Fleet Control Planes | Industrial Messaging | ROS2 Protocols | Eventing               |
| Open-RMF Ecosystems             | Synaos IMP           | MQTT / NATS    | Fleet Adapters         |
| Workflow Coordination           | Telemetry Routing    | OT Integration | Edge Synchronization   |
+--------------------------------------------------------------------------------------------------+
                                              │
                                              │ Industrial Protocols / Edge Connectivity
                                              ▼
+--------------------------------------------------------------------------------------------------+
|                            4. PHYSICAL INDUSTRIAL INFRASTRUCTURE                                 |
|--------------------------------------------------------------------------------------------------|
| AMRs & AGVs | PLCs / SCADA | Industrial IoT | Smart Elevators | Automated Doors                  |
| Edge Nodes  | GPU Servers  | Factory Sensors | Warehouse Systems | Legacy OT Systems             |
+--------------------------------------------------------------------------------------------------+
```

---

## Architecture Overview

```
[ Self-Service / API / GitOps / CI/CD / Service Catalog ]
                        │
                        ▼
         [ Management Zone ]
  Crossplane • Cluster API • Flux • Kyverno
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
| Kubernetes (RKE2 / Talos) | Control plane for everything |
| Cluster API | Cluster lifecycle management |
| KubeVirt | VM layer on Kubernetes |
| Crossplane | Platform API & self-service compositions |
| Flux / ArgoCD | GitOps engine |

---

## Getting Started

### Prerequisites

A running management cluster is required. Supported options:

| Option | Use Case |
|---|---|
| RKE2 on bare metal | Production (recommended) |
| k3s on Multipass VMs | Local development |
| KubeVirt VMs on existing cluster | Nested / lab environments |
| kind | Minimal local testing |

> Management cluster provisioning is out of scope — OpenKubes assumes you bring your own.  
> See [`platform/hardware/README.md`](platform/hardware/README.md) for guidance.

---

### Step 1 — Install KubeVirt

```bash
# KubeVirt operator and CR
kubectl apply -f https://github.com/kubevirt/kubevirt/releases/download/v1.8.1/kubevirt-operator.yaml
kubectl apply -f https://github.com/kubevirt/kubevirt/releases/download/v1.8.1/kubevirt-cr.yaml

# CDI for VM disk management
kubectl apply -f https://github.com/kubevirt/containerized-data-importer/releases/latest/download/cdi-operator.yaml
kubectl apply -f https://github.com/kubevirt/containerized-data-importer/releases/latest/download/cdi-cr.yaml

# Verify
kubectl get kubevirt -n kubevirt
kubectl get pods -n cdi

# Optional: KubeVirt Manager UI
kubectl apply -f https://github.com/kubevirt-manager/kubevirt-manager/releases/download/v1.5.4/bundled-v1.5.4.yaml

# kubectl virt plugin
kubectl krew install virt
```

### Step 2 — Deploy Management VMs

```bash
kubectl apply -f ok-vms/
```

```
NAME     STATUS    READY
ok1-vm   Running   True
ok2-vm   Running   True
ok3-vm   Running   True
```

VMs are exposed via LoadBalancer services and accessible over SSH.

### Step 3 — Bootstrap Cluster API

Install CAPI with the KubeVirt infrastructure provider (CAPKV).  
→ See [`platform/cluster-management/cluster-api/README.md`](platform/cluster-management/cluster-api/README.md)

### Step 4 — Deploy Crossplane & GitOps

Crossplane turns your platform into a self-service product catalog.  
→ See [`platform/gitops/fluxcd/README.md`](platform/gitops/fluxcd/README.md)

---

## Platform Components

### Cluster Management
- [`platform/cluster-management/cluster-api/`](platform/cluster-management/cluster-api/) — CAPI providers, cluster templates

### GitOps
- [`platform/gitops/fluxcd/`](platform/gitops/fluxcd/) — Flux (recommended)
- [`platform/gitops/argocd/`](platform/gitops/argocd/) — ArgoCD

### Networking
- [`platform/networking/cilium/`](platform/networking/cilium/) — Cilium CNI (default)
- [`platform/networking/calico/`](platform/networking/calico/) — Calico CNI
- [`platform/networking/multus/`](platform/networking/multus/) — Multi-network for Robotics / industrial

### Robotics
- [`platform/robotics/ros2/`](platform/robotics/ros2/) — ROS 2 on Kubernetes
- [`platform/robotics/open-rmf/`](platform/robotics/open-rmf/) — Open-RMF fleet management
- [`platform/robotics/dds/`](platform/robotics/dds/) — DDS networking

### Observability
- [`platform/observability/`](platform/observability/) — Metrics, logging, tracing, alerting

### Virtualization
- [`platform/virtualization/kubevirt/`](platform/virtualization/kubevirt/) — KubeVirt configuration and VM blueprints

---

## Blueprints

| Blueprint | Description |
|---|---|
| [`bare-metal`](blueprints/bare-metal/) | Production bare metal cluster |
| [`capi-kubevirt`](blueprints/capi-kubevirt/) | CAPI + KubeVirt workload cluster |
| [`sovereign-edge`](blueprints/sovereign-edge/) | Air-gapped sovereign edge deployment |
| [`robotops-edge-site`](blueprints/robotops-edge-site/) | Edge site for robotics operations |
| [`ros2-dds-industrial-networking`](blueprints/ros2-dds-industrial-networking/) | ROS 2 with industrial DDS networking |
| [`open-rmf-fleet-management`](blueprints/open-rmf-fleet-management/) | Open-RMF autonomous fleet management |

---

## Architecture Deep Dives

- [`AIRGAPPED-OPERATIONS.md`](architecture/AIRGAPPED-OPERATIONS.md)
- [`CLUSTERAPI-EDGE-SCALING.md`](architecture/CLUSTERAPI-EDGE-SCALING.md)
- [`DDS-NETWORKING.md`](architecture/DDS-NETWORKING.md)
- [`GITOPS-EDGE-LIFECYCLE.md`](architecture/GITOPS-EDGE-LIFECYCLE.md)
- [`GPU-ISOLATION.md`](architecture/GPU-ISOLATION.md)
- [`KUBEVIRT-LEGACY-INTEGRATION.md`](architecture/KUBEVIRT-LEGACY-INTEGRATION.md)
- [`SOVEREIGN-EDGE-RUNTIME.md`](architecture/SOVEREIGN-EDGE-RUNTIME.md)

---

## Product Model

```
1. Foundation         Compute • Network • Storage
2. Runtime            Clusters • VMs • Tenants
3. Platform Services  DBaaS • Messaging • Observability
4. Specialized        AI / GPU • Robotics • HPC • CAD
5. Governance         Security • Compliance • Backup / DR
```

---

## Community & Support

| | |
|---|---|
| 🌍 Worldwide Meetup | [meetup.com/kubernauts](https://www.meetup.com/kubernauts/) — live demos & community sessions |
| 📺 YouTube | [youtube.com/c/kubernautsio](https://www.youtube.com/c/kubernautsio) — tutorials & platform walkthroughs |
| 🤖 Live Demo | [rmf.openkubes.ai](https://rmf.openkubes.ai/dashboard/login) — Open-RMF fleet management live |
| 🌐 Docs | [openkubes.ai](https://openkubes.ai) *(coming soon)* |
| 💬 Enterprise | [kubernauts.de](https://kubernauts.de) — managed operations, support & pilots |

---

## License

See [LICENSE](LICENSE).

---

> Built by [Kubernauts GmbH](https://kubernauts.de) · Cologne, Germany  
> 10+ years of Kubernetes expertise · 50+ production clusters
