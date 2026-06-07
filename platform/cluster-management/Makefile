SHELL := /bin/bash
.DEFAULT_GOAL := help

cluster            ?=
kubernetes-version ?=
namespace          ?= openkubes-system
examples_dir   ?= crossplane/examples
scripts_dir    ?= capi-platform-v4.2/scripts
crossplane_dir ?= crossplane
runner_image   ?= kubernautslabs/capi-platform-runner:v4.2
kubeconfig_dir ?= $(HOME)/.kube

.PHONY: help setup deploy delete status logs check force-clean kubeconfig upgrade

help:
	@echo ""
	@echo "OpenKubes Platform – Cluster Operations"
	@echo ""
	@echo "Setup (one-time):"
	@echo "  make setup                              Apply all Crossplane XRDs and Compositions"
	@echo ""
	@echo "Cluster Lifecycle:"
	@echo "  make deploy      cluster=ok1            Deploy a workload cluster"
	@echo "  make delete      cluster=ok1            Clean delete (Cleanup Job + remove claims)"
	@echo "  make kubeconfig  cluster=ok1            Get workload cluster kubeconfig"
	@echo "  make upgrade     cluster=ok1 kubernetes-version=v1.34.1  Upgrade cluster (patches claim + triggers Job)"
	@echo "  make status      cluster=ok1            Show cluster status"
	@echo "  make logs        cluster=ok1            Follow deploy Job logs"
	@echo ""
	@echo "Troubleshooting:"
	@echo "  make check       cluster=ok1            Check for leftover resources"
	@echo "  make force-clean cluster=ok1            Force cleanup all resources (emergency)"
	@echo ""

# ---------------------------------------------------------------
# Setup – apply all Crossplane resources (one-time)
# ---------------------------------------------------------------
setup:
	@echo "[setup] applying Crossplane stack..."
	kubectl apply -f $(crossplane_dir)/namespace.yaml
	kubectl apply -f $(crossplane_dir)/rbac.yaml
	kubectl apply -f $(crossplane_dir)/xrd.yaml
	kubectl apply -f $(crossplane_dir)/xrd-cleanup.yaml
	kubectl apply -f $(crossplane_dir)/xrd-upgrade.yaml
	kubectl apply -f $(crossplane_dir)/composition.yaml
	kubectl apply -f $(crossplane_dir)/composition-cleanup.yaml
	kubectl apply -f $(crossplane_dir)/composition-upgrade.yaml
	@echo "[setup] done ✅"
	@echo ""
	kubectl get xrd
	kubectl get composition
	kubectl get functions.pkg.crossplane.io

# ---------------------------------------------------------------
# Deploy – apply cluster claim and wait for completion
# ---------------------------------------------------------------
deploy:
	@test -n "$(cluster)" || (echo "ERROR: cluster is required  →  make deploy cluster=ok1"; exit 1)
	@test -f "$(examples_dir)/$(cluster).yaml" || \
	  (echo "ERROR: $(examples_dir)/$(cluster).yaml not found"; exit 1)
	@echo "[deploy] applying claim for cluster '$(cluster)'..."
	kubectl apply -f "$(examples_dir)/$(cluster).yaml"
	@echo "[deploy] waiting for Job to complete..."
	@sleep 5
	@JOB=$$(kubectl get jobs -n $(namespace) \
	  --sort-by=.metadata.creationTimestamp \
	  -o jsonpath='{.items[-1:][0].metadata.name}' 2>/dev/null || echo ""); \
	if [ -n "$$JOB" ]; then \
	  echo "[deploy] watching Job $$JOB..."; \
	  kubectl get jobs -n $(namespace) "$$JOB"; \
	  kubectl wait job/"$$JOB" -n $(namespace) \
	    --for=condition=complete \
	    --timeout=600s 2>/dev/null && \
	  echo "[deploy] cluster '$(cluster)' deployed ✅"; \
	else \
	  echo "[deploy] WARNING: no job found, check: kubectl get jobs -n $(namespace)"; \
	fi

# ---------------------------------------------------------------
# Delete – sauber löschen via Cleanup Job
# ---------------------------------------------------------------
delete:
	@test -n "$(cluster)" || (echo "ERROR: cluster is required  →  make delete cluster=ok1"; exit 1)
	@echo "[delete] cleaning up any stale claims..."
	@kubectl delete kubevirtclusterupgradeclaim "upgrade-$(cluster)" \
	  -n $(namespace) --ignore-not-found 2>/dev/null || true
	@kubectl delete kubevirtclustercleanupclaim "cleanup-$(cluster)" \
	  -n $(namespace) --ignore-not-found 2>/dev/null || true
	@echo "[delete] step 1: deleting claim '$(cluster)'..."
	@kubectl delete -f "$(examples_dir)/$(cluster).yaml" --ignore-not-found || true
	@echo "[delete] step 2: applying cleanup claim..."
	@printf 'apiVersion: platform.openkubes.ai/v1alpha1\nkind: KubeVirtClusterCleanupClaim\nmetadata:\n  name: cleanup-$(cluster)\n  namespace: $(namespace)\nspec:\n  clusterName: $(cluster)\n  country: de\n  provider: kubevirt\n  runnerImage: $(runner_image)\n' | kubectl apply -f -
	@echo "[delete] waiting for cleanup Job to complete..."
	@sleep 5
	@JOB=$$(kubectl get jobs -n $(namespace) -o name | grep "cleanup-$(cluster)" | head -1); \
	if [ -n "$$JOB" ]; then \
	  kubectl wait $$JOB -n $(namespace) --for=condition=complete --timeout=300s && \
	  echo "[delete] cleanup Job completed ✅"; \
	else \
	  echo "[delete] WARNING: cleanup Job not found, waiting 60s..."; \
	  sleep 60; \
	fi
	@echo "[delete] step 3: deleting cleanup claim..."
	@kubectl delete kubevirtclustercleanupclaim "cleanup-$(cluster)" \
	  -n $(namespace) --ignore-not-found || true
	@echo "[delete] cluster '$(cluster)' deleted ✅"

# ---------------------------------------------------------------
# Kubeconfig – retrieve workload cluster kubeconfig
# ---------------------------------------------------------------
kubeconfig:
	@test -n "$(cluster)" || (echo "ERROR: cluster is required  →  make kubeconfig cluster=ok1"; exit 1)
	@echo "[kubeconfig] retrieving kubeconfig for cluster '$(cluster)'..."
	@clusterctl get kubeconfig $(cluster) \
	  -n $(cluster) \
	  --kubeconfig $(KUBECONFIG) \
	  > $(kubeconfig_dir)/$(cluster).kubeconfig
	@echo "[kubeconfig] saved to $(kubeconfig_dir)/$(cluster).kubeconfig ✅"
	@echo ""
	@echo "Use with:"
	@echo "  KUBECONFIG=$(kubeconfig_dir)/$(cluster).kubeconfig kubectl get nodes"
	@echo ""
	@KUBECONFIG=$(kubeconfig_dir)/$(cluster).kubeconfig kubectl get nodes 2>/dev/null || true

# ---------------------------------------------------------------
# Upgrade – upgrade cluster to a new Kubernetes version
#
# How it works:
#   1. Reads current version from the RUNNING cluster (KubeadmControlPlane)
#   2. If already on target version → nothing to do
#   3. Patches kubernetesVersion in crossplane/examples/<cluster>.yaml
#      (macOS-safe sed, keeps claim yaml in sync)
#   4. kubectl apply → Crossplane sees version drift → new deploy Job
#   5. crossplane-deploy.sh detects cluster is Provisioned + wrong version
#      → delegates to crossplane-upgrade.sh
#      → kubectl patch KCP + MachineDeployment → CAPI rolling upgrade
#      → ghost node cleanup
# ---------------------------------------------------------------
upgrade:
	@test -n "$(cluster)" || (echo "ERROR: cluster is required  →  make upgrade cluster=ok1 kubernetes-version=v1.34.1"; exit 1)
	@test -n "$(kubernetes-version)" || (echo "ERROR: kubernetes-version is required  →  make upgrade cluster=ok1 kubernetes-version=v1.34.1"; exit 1)
	@test -f "$(examples_dir)/$(cluster).yaml" || \
	  (echo "ERROR: $(examples_dir)/$(cluster).yaml not found"; exit 1)
	@CURRENT=$$(kubectl get kubeadmcontrolplane "$(cluster)-control-plane" \
	  -n "$(cluster)" \
	  -o jsonpath='{.spec.version}' 2>/dev/null || echo ""); \
	if [ -z "$$CURRENT" ]; then \
	  echo "ERROR: could not read version from cluster '$(cluster)' — is it running?"; exit 1; \
	fi; \
	echo "[upgrade] current version in cluster: $$CURRENT"; \
	echo "[upgrade] target version:             $(kubernetes-version)"; \
	if [ "$$CURRENT" = "$(kubernetes-version)" ]; then \
	  echo "[upgrade] cluster is already on $(kubernetes-version) — nothing to do ✅"; \
	  exit 0; \
	fi; \
	echo "[upgrade] patching kubernetesVersion in $(examples_dir)/$(cluster).yaml..."; \
	sed -i '' "s|^\([ ]*kubernetesVersion: \).*|\1$(kubernetes-version)|" \
	  "$(examples_dir)/$(cluster).yaml"; \
	echo "[upgrade] applying claim for cluster '$(cluster)'..."; \
	kubectl apply -f "$(examples_dir)/$(cluster).yaml"; \
	echo "[upgrade] watching Jobs (Ctrl+C to stop watching)..."; \
	sleep 3 && kubectl get jobs -n $(namespace) -w

# ---------------------------------------------------------------
# Status – show cluster status
# ---------------------------------------------------------------
status:
	@test -n "$(cluster)" || (echo "ERROR: cluster is required  →  make status cluster=ok1"; exit 1)
	@echo "=== Cluster ==="
	@kubectl get cluster -A | grep "$(cluster)" || echo "No cluster found"
	@echo ""
	@echo "=== Machines ==="
	@kubectl get machines -n "$(cluster)" 2>/dev/null || echo "No machines found"
	@echo ""
	@echo "=== Jobs ==="
	@kubectl get jobs -n $(namespace) | grep "$(cluster)" || echo "No jobs found"
	@echo ""
	@echo "=== Claims ==="
	@kubectl get kubevirtclusterclaim -n $(namespace) 2>/dev/null | grep "$(cluster)" || echo "No claims found"

# ---------------------------------------------------------------
# Logs – follow deploy Job logs
# ---------------------------------------------------------------
logs:
	@test -n "$(cluster)" || (echo "ERROR: cluster is required  →  make logs cluster=ok1"; exit 1)
	@POD=$$(kubectl get pods -n $(namespace) \
	  --field-selector=status.phase=Running \
	  -o jsonpath='{.items[*].metadata.name}' | \
	  tr ' ' '\n' | grep "$(cluster)" | head -1); \
	if [ -n "$$POD" ]; then \
	  kubectl logs -n $(namespace) $$POD -f; \
	else \
	  echo "No running pod found for cluster $(cluster)"; \
	  kubectl get pods -n $(namespace) | grep "$(cluster)" || true; \
	fi

# ---------------------------------------------------------------
# Check – check for leftover resources
# ---------------------------------------------------------------
check:
	@test -n "$(cluster)" || (echo "ERROR: cluster is required  →  make check cluster=ok1"; exit 1)
	@bash "$(scripts_dir)/check-leftovers.sh" "$(cluster)" "$(cluster)"

# ---------------------------------------------------------------
# Force-clean – emergency cleanup
# ---------------------------------------------------------------
force-clean:
	@test -n "$(cluster)" || (echo "ERROR: cluster is required  →  make force-clean cluster=ok1"; exit 1)
	@echo "⚠️  Force cleaning cluster '$(cluster)'..."
	@echo "[force-clean] removing stale claims..."
	@kubectl delete kubevirtclusterupgradeclaim "upgrade-$(cluster)" \
	  -n $(namespace) --ignore-not-found 2>/dev/null || true
	@kubectl delete kubevirtclustercleanupclaim "cleanup-$(cluster)" \
	  -n $(namespace) --ignore-not-found 2>/dev/null || true
	@kubectl delete kubevirtclusterclaim "$(cluster)" \
	  -n $(namespace) --ignore-not-found 2>/dev/null || true
	@bash "$(scripts_dir)/force-clean-leftovers.sh" "$(cluster)" "$(cluster)" "$(namespace)"
