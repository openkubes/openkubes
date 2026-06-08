# OpenKubes Release Notes

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
