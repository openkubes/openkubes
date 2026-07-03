# OpenKubes Release Notes

---

## v0.2.0 — Private AI Platform + Management Cluster Architecture

> **OpenKubes owns the contracts, not the components.**

### Zero to Private AI in minutes

```bash
make new CLUSTER=ok-mgmt TYPE=talos NODE_SELECTOR=ok-infra WORKERS=2
make bootstrap CLUSTER=ok-mgmt
bash bootstrap-mgmt.sh          # Crossplane + CAPI + 4 XRDs in ~2 min

make new CLUSTER=ok1-talos TYPE=talos WORKERS=1
make bootstrap CLUSTER=ok1-talos
make install-storage CLUSTER=ok1-talos

make deploy CLUSTER=ok1-talos   # Open WebUI deployed in ~90 seconds
# → http://localhost:8080 — mistral:latest, 7.2B, RTX 4000 Ada
```

### What's New

**OpenKubes AI Platform**
- Central Ollama with GPU (RTX 4000 Ada, 20GB VRAM) on RKE2 host cluster
- `OpenWebUIClaim` XRD + Composition — deploy Open WebUI on any cluster via `make deploy`
- mistral:latest, 7.2B, running fully on your own infrastructure
- MCP Connectors for Jira + Confluence planned as next step

**ok-mgmt — Management Cluster**
- Dedicated Talos-based management cluster on ok-infra (separate from workload clusters)
- `bootstrap-mgmt.sh.tpl` — 8-step automated bootstrap: Crossplane, Providers, Functions, CAPI+CAPK+Talos, infra secret, XRDs, RBAC, OpenWebUI XRD
- `make install-storage CLUSTER=<name>` — local-path-provisioner for Talos clusters
- Workload clusters deployed from ok-mgmt via Crossplane Claims — not from your laptop

**8 Platform ADRs**
- ADR-Platform-001: OpenKubes owns the contracts, not the components
- ADR-Platform-002: openkubes/openkubes is the Distribution and Integration Layer
- ADR-Platform-003: capi-platform-v4.2 as Platform Orchestrator prototype
- ADR-Platform-004: Runner is implementation detail — ok-cluster as shared backend
- ADR-Platform-005: Shared AI Services Layer
- ADR-Platform-006: ok-mgmt as Management Cluster
- ADR-Platform-007: CAPI responsibility split (ok-infra bootstraps, ok-mgmt operates)
- ADR-Platform-008: TYPE=talos-mgmt as dedicated cluster type

**Three repositories — three releases**
- openkubes/openkubes v0.2.0
- ok-cluster v0.7.0
- ok-linux v0.1.1

---

# (Previous release notes below)

---

## v1.0.4 — Ingress + TLS + 5-Command Stack

> See git history for full v1.0.4 release notes (capi-platform-v4.2 era)

---

## v1.0.4 — Ingress + TLS + 5-Command Stack

> **Kubernetes Anywhere. Make it.**

### Zero to Production in 5 Commands

```bash
make deploy         cluster=ok1   # ~2 min  → Kubernetes cluster
make kubeconfig     cluster=ok1   # ~5 sec  → kubeconfig saved
make manager-deploy cluster=ok1   # ~30 sec → Headlamp UI on CP node
make ingress-setup  cluster=ok1   # ~30 sec → Traefik + INFRA LB
make cert-setup     cluster=ok1   # ~90 sec → cert-manager + Let's Encrypt
# → https://headlamp.openkubes.ai  HTTP/2 200 ✅
```

**Total time: ~4 minutes from zero to production HTTPS.** 🚀

### What's New

#### Ingress Stack (`make ingress-setup`)

Traefik deployed as NodePort on control-plane node — no MetalLB needed on workload clusters.
INFRA MetalLB acts as proxy via `ok1-lb` Service.

```bash
make ingress-setup   cluster=ok1             # deploy Traefik + patch INFRA LB
make ingress-delete  cluster=ok1             # remove Traefik
make ingress-delete  cluster=ok1 cert=true   # remove Traefik + cert-manager
make ingress-status  cluster=ok1             # show status
```

- Auto-reads INFRA kubeconfig from `external-infra-kubeconfig` secret in `capk-system`
- Auto-detects Traefik NodePorts (with fallback for fresh clusters without named ports)
- Auto-patches `ok1-lb` INFRA Service to expose 80/443
- ProviderConfigs (`ok1-helm`, `ok1-kubernetes`) created automatically

#### TLS / cert-manager (`make cert-setup`)

cert-manager v1.17.2 with Let's Encrypt HTTP-01 challenge — fully automated.

```bash
make cert-setup   cluster=ok1   # deploy cert-manager + ClusterIssuers + Ingress + wait
make cert-delete  cluster=ok1   # remove cert-manager
make cert-status  cluster=ok1   # show certificate status
```

- cert-manager + webhook + cainjector on control-plane node (nodeSelector)
- `letsencrypt-staging` + `letsencrypt-prod` ClusterIssuers
- ACME solver pod runs on control-plane node via `podTemplate` (required for INFRA LB routing)
- Waits for cert-manager `Ready` then waits for certificate `Ready=True`

#### Cluster Manager: Headlamp auto-CP-node (`make manager-deploy`)

Headlamp now automatically deploys on the control-plane node — no manual `kubectl patch` needed.

```bash
make manager-deploy cluster=ok1   # auto nodeSelector: control-plane ✅
```

#### Ingress Delete: Ordered Cleanup + cert flag

```bash
make ingress-delete cluster=ok1             # Traefik only
make ingress-delete cluster=ok1 cert=true   # Traefik + cert-manager
```

- Deletes releases and objects first, waits for pod removal
- Auto-removes finalizer from `ok1-kubernetes` ProviderConfig (no more manual intervention)
- Resets INFRA LB to 6443-only

#### Full Lifecycle Test

Validated end-to-end: complete delete + recreate cycle tested and documented.

```bash
make ingress-delete cluster=ok1 cert=true
make delete         cluster=ok1
make deploy         cluster=ok1
make kubeconfig     cluster=ok1
make manager-deploy cluster=ok1
make ingress-setup  cluster=ok1
make cert-setup     cluster=ok1
curl -I https://headlamp.openkubes.ai
# → HTTP/2 200 ✅
```

#### Architecture: Why No MetalLB on Workload Cluster

MetalLB L2 does not work on nested KubeVirt VMs — ARP broadcasts cannot reach
the physical network. The INFRA MetalLB acts as proxy instead:

```
Internet → 84.200.100.228 (INFRA MetalLB)
         → ok1-lb (NodePort → CP node)
         → Traefik → Headlamp / other services
```

### New Files

| File | Description |
|---|---|
| `crossplane/examples/ok1-providerconfigs.yaml` | Helm + Kubernetes ProviderConfigs for ok1 |
| `crossplane/examples/ok1-traefik.yaml` | Traefik NodePort, CP node, ingressClass traefik |
| `crossplane/examples/ok1-certmanager.yaml` | cert-manager + ClusterIssuers + Headlamp Ingress |

---

## v1.0.3 — OpenKubesVM + Make Everything

> **Run VMs. Run Clusters. Run Anything.**

### What's New

#### OpenKubesVM (`platform/virtualization/openkubesvm/`)

A new self-service abstraction for KubeVirt VMs — the foundation of the OpenKubes platform.

```bash
cd platform/virtualization/openkubesvm
make vm-create  vm=ok4    # create VM via Crossplane
make vm-ssh     vm=ok4    # SSH into VM
make vm-delete  vm=ok4    # delete VM
make vm-list              # list all VMs
```

- **`OpenKubesVMClaim`** XRD — declare a VM with IP, MAC, SSH key, CPU, memory, storage
- **Go-Template Composition** — creates DataVolume + Service + VirtualMachine on infra cluster
- **Cross-cluster ProviderConfig** — reuses existing CAPK infra kubeconfig secret
- **Direct KubeVirt YAMLs** — for lab use without Crossplane (`kubevirt/ok4-vm.yaml`)
- **GitOps-ready** — Kustomize for both Crossplane and direct paths
- **Tested end-to-end** — VM ready via SSH in under 90 seconds

#### Cluster Upgrade: `make recreate`

A reliable alternative to rolling upgrade for CAPK v0.11.x environments:

```bash
make recreate cluster=ok1 kubernetes-version=v1.34.1
```

- Reads live cluster parameters from `KubeVirtClusterClaim`
- Pauses Crossplane reconciliation during recreate (prevents interference)
- Deletes and recreates cluster with target version
- Verifies real kubelet versions on workload nodes
- `trap` ensures Crossplane is always resumed, even on failure

Rolling upgrade (`make upgrade`) is now clearly marked as **experimental** pending CAPK v0.12.x evaluation.

#### Make Philosophy

All platform operations now follow a consistent `make` interface:

```bash
# VMs
make vm-create  vm=ok4
make vm-delete  vm=ok4
make vm-ssh     vm=ok4
make vm-list

# Clusters
make deploy     cluster=ok1
make recreate   cluster=ok1 kubernetes-version=v1.34.1
make upgrade    cluster=ok1 kubernetes-version=v1.34.1
make delete     cluster=ok1
make kubeconfig cluster=ok1
make status     cluster=ok1
make logs       cluster=ok1
```

#### Cluster Management Fixes

- `make deploy` now waits for Job completion with `✅` — no more `Ctrl+C`
- `make logs` shows only the most recent pod — no more flood of old pods
- Early-exit in upgrade checks both CP and worker version
- Step 9b verifies real kubelet versions on workload nodes
- Auto-restart stuck VMs after 5 min in worker rollout
- Ghost node cleanup handles `SchedulingDisabled` and `Ready=False`

---

## v1.0.2

- `make upgrade` reads current version from running cluster
- Bootstrap token race condition fix (`ensure_bootstrap_tokens`)
- `checkStrategy: none` fix for CAPK SSH bootstrap check
- macOS-safe `perl` instead of `sed` in Makefile

---

## v1.0.1

- Crossplane Cleanup Claim for clean cluster deletion
- Ghost node cleanup after CP and worker upgrade
- `make force-clean` for emergency cleanup

---

## v1.0.0 — Initial Release

- Self-service cluster provisioning via `KubeVirtClusterClaim`
- Full cluster lifecycle: deploy, status, kubeconfig, delete
- Calico CNI + MetalLB automatically installed
- capi-platform-runner v4.2 with all tooling embedded
- Crossplane v2.2.0 + function-go-templating v0.11.4

---

**OpenKubes** — Run Everything. Deliver Anything.
