SHELL := /bin/bash
.DEFAULT_GOAL := help

cluster        ?=
namespace      ?= openkubes-system
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
	@echo "  make upgrade     cluster=ok1 kubernetes-version=v1.34.1  Upgrade cluster"
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
# Deploy – apply cluster claim
# ---------------------------------------------------------------
deploy:
	@test -n "$(cluster)" || (echo "ERROR: cluster is required  →  make deploy cluster=ok1"; exit 1)
	@test -f "$(examples_dir)/$(cluster).yaml" || \
	  (echo "ERROR: $(examples_dir)/$(cluster).yaml not found"; exit 1)
	@echo "[deploy] applying claim for cluster '$(cluster)'..."
	kubectl apply -f "$(examples_dir)/$(cluster).yaml"
	@echo "[deploy] watching Job (Ctrl+C to stop watching)..."
	@sleep 3 && kubectl get jobs -n $(namespace) -w

# ---------------------------------------------------------------
# Delete – sauber löschen via Cleanup Job
# ---------------------------------------------------------------
delete:
	@test -n "$(cluster)" || (echo "ERROR: cluster is required  →  make delete cluster=ok1"; exit 1)
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
# Upgrade – upgrade cluster to new Kubernetes version
# ---------------------------------------------------------------
upgrade:
	@test -n "$(cluster)" || (echo "ERROR: cluster is required  →  make upgrade cluster=ok1 kubernetes-version=v1.34.1"; exit 1)
	@test -n "$(kubernetes-version)" || (echo "ERROR: kubernetes-version is required  →  make upgrade cluster=ok1 kubernetes-version=v1.34.1"; exit 1)
	@echo "[upgrade] upgrading cluster '$(cluster)' to $(kubernetes-version)..."
	@printf 'apiVersion: platform.openkubes.ai/v1alpha1\nkind: KubeVirtClusterUpgradeClaim\nmetadata:\n  name: upgrade-$(cluster)\n  namespace: $(namespace)\nspec:\n  clusterName: $(cluster)\n  targetKubernetesVersion: $(kubernetes-version)\n  upgradeStrategy: RollingUpdate\n  country: de\n  provider: kubevirt\n  runnerImage: $(runner_image)\n' | kubectl apply -f -
	@echo "[upgrade] watching Job (Ctrl+C to stop watching)..."
	@sleep 5
	@JOB=$$(kubectl get jobs -n $(namespace) -o name | grep "upgrade-$(cluster)" | head -1); \
	if [ -n "$$JOB" ]; then \
	  kubectl logs -n $(namespace) $$(basename $$JOB) -f 2>/dev/null || true; \
	  kubectl wait $$JOB -n $(namespace) --for=condition=complete --timeout=600s && \
	  echo "[upgrade] cluster '$(cluster)' upgraded to $(kubernetes-version) ✅"; \
	else \
	  echo "[upgrade] Job not found, check: kubectl get jobs -n $(namespace)"; \
	fi
	@kubectl delete kubevirtclusterupgradeclaim "upgrade-$(cluster)" \
	  -n $(namespace) --ignore-not-found || true

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
	@bash "$(scripts_dir)/force-clean-leftovers.sh" "$(cluster)" "$(cluster)" "$(namespace)"
