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

.PHONY: help setup deploy delete status logs check force-clean kubeconfig upgrade recreate

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
	@echo "  make recreate    cluster=ok1 kubernetes-version=v1.34.1  Recreate cluster on new version (reliable, destructive)"
	@echo "  make upgrade     cluster=ok1 kubernetes-version=v1.34.1  Rolling upgrade (experimental, requires CAPK fix)"
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
	@echo "[deploy] waiting for Crossplane to create Job..."; \
	JOB=""; \
	for i in $$(seq 1 24); do \
	  JOB=$$(kubectl get jobs -n $(namespace) \
	    --sort-by=.metadata.creationTimestamp \
	    -o jsonpath='{.items[*].metadata.name}' 2>/dev/null | \
	    tr ' ' '\n' | grep "^deploy-$(cluster)-" | tail -1 || echo ""); \
	  if [ -n "$$JOB" ]; then break; fi; \
	  echo "[deploy] waiting for Job... ($$i/24)"; \
	  sleep 5; \
	done; \
	if [ -n "$$JOB" ]; then \
	  echo "[deploy] watching Job $$JOB..."; \
	  kubectl wait job/"$$JOB" -n $(namespace) \
	    --for=condition=complete \
	    --timeout=600s 2>/dev/null && \
	  echo "[deploy] cluster '$(cluster)' deployed ✅"; \
	else \
	  echo "[deploy] WARNING: no job found after 120s, check: kubectl get jobs -n $(namespace)"; \
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
# Recreate – reliable cluster upgrade via delete + redeploy
#
# How it works:
#   1. Reads current parameters from live KubeVirtClusterClaim
#   2. Patches claim to target version
#   3. Pauses Crossplane reconciliation (prevents interference)
#   4. Deletes current CAPI cluster resources (cleanup-local)
#   5. Recreates cluster with target version (deploy-full-local)
#   6. Verifies all workload nodes report target kubelet version
#   7. Resumes Crossplane reconciliation
#
# Note: This is destructive — workloads on the cluster will be lost.
#       Use for test/dev clusters or when rolling upgrade is not available.
# ---------------------------------------------------------------
recreate:
	@test -n "$(cluster)" || (echo "ERROR: cluster is required  →  make recreate cluster=ok1 kubernetes-version=v1.34.1"; exit 1)
	@test -n "$(kubernetes-version)" || (echo "ERROR: kubernetes-version is required  →  make recreate cluster=ok1 kubernetes-version=v1.34.1"; exit 1)
	@test -f "$(examples_dir)/$(cluster).yaml" || \
	  (echo "ERROR: $(examples_dir)/$(cluster).yaml not found"; exit 1)
	@CURRENT=$$(kubectl get kubeadmcontrolplane "$(cluster)-control-plane" \
	  -n "$(cluster)" \
	  -o jsonpath='{.spec.version}' 2>/dev/null || echo ""); \
	if [ -z "$$CURRENT" ]; then \
	  echo "ERROR: could not read version from cluster '$(cluster)' — is it running?"; exit 1; \
	fi; \
	echo "[recreate] current version: $$CURRENT"; \
	echo "[recreate] target version:  $(kubernetes-version)"; \
	echo "[recreate] ⚠️  WARNING: this will DELETE and RECREATE the cluster!"; \
	echo "[recreate] All workloads will be lost. Press Ctrl+C within 5s to abort..."; \
	sleep 5; \
	echo "[recreate] patching kubernetesVersion in $(examples_dir)/$(cluster).yaml..."; \
	perl -0pi -e 's|(^[ ]*kubernetesVersion: ).*|$${1}$(kubernetes-version)|m' \
	  "$(examples_dir)/$(cluster).yaml"; \
	echo "[recreate] applying claim for cluster '$(cluster)'..."; \
	kubectl apply -f "$(examples_dir)/$(cluster).yaml"; \
	echo "[recreate] watching Jobs (Ctrl+C to stop watching)..."; \
	for i in $$(seq 1 24); do \
	  JOB=$$(kubectl get jobs -n $(namespace) \
	    --sort-by=.metadata.creationTimestamp \
	    -o jsonpath='{.items[*].metadata.name}' 2>/dev/null | \
	    tr ' ' '\n' | grep "^deploy-$(cluster)-" | tail -1 || echo ""); \
	  if [ -n "$$JOB" ]; then break; fi; \
	  echo "[recreate] waiting for Job... ($$i/24)"; \
	  sleep 5; \
	done; \
	if [ -n "$$JOB" ]; then \
	  echo "[recreate] watching Job $$JOB..."; \
	  kubectl wait job/"$$JOB" -n $(namespace) \
	    --for=condition=complete \
	    --timeout=900s 2>/dev/null && \
	  echo "[recreate] cluster '$(cluster)' recreated on $(kubernetes-version) ✅"; \
	else \
	  echo "[recreate] WARNING: no job found after 120s, check: kubectl get jobs -n $(namespace)"; \
	fi

# ---------------------------------------------------------------
# Upgrade – rolling upgrade (experimental, requires CAPK v0.12+)
#
# ⚠️  EXPERIMENTAL — requires CAPK v0.12+ for reliable ProviderID registration.
#    With CAPK v0.11.x this may hang with "Waiting for a node with matching
#    ProviderID to exist". Use 'make recreate' for a reliable alternative.
#
# How it works:
#   1. Reads current version from the RUNNING cluster (KubeadmControlPlane)
#   2. Patches kubernetesVersion in crossplane/examples/<cluster>.yaml
#   3. kubectl apply → Crossplane sees version drift → new deploy Job
#   4. crossplane-deploy.sh detects cluster is Provisioned + wrong version
#      → delegates to crossplane-upgrade.sh
#      → kubectl patch KCP + MachineDeployment → CAPI rolling upgrade
# ---------------------------------------------------------------
upgrade:
	@test -n "$(cluster)" || (echo "ERROR: cluster is required  →  make upgrade cluster=ok1 kubernetes-version=v1.34.1"; exit 1)
	@test -n "$(kubernetes-version)" || (echo "ERROR: kubernetes-version is required  →  make upgrade cluster=ok1 kubernetes-version=v1.34.1"; exit 1)
	@test -f "$(examples_dir)/$(cluster).yaml" || \
	  (echo "ERROR: $(examples_dir)/$(cluster).yaml not found"; exit 1)
	@CURRENT_CP=$$(kubectl get kubeadmcontrolplane "$(cluster)-control-plane" \
	  -n "$(cluster)" \
	  -o jsonpath='{.spec.version}' 2>/dev/null || echo ""); \
	CURRENT_MD=$$(kubectl get machinedeployment "$(cluster)-md-0" \
	  -n "$(cluster)" \
	  -o jsonpath='{.spec.template.spec.version}' 2>/dev/null || echo ""); \
	if [ -z "$$CURRENT_CP" ]; then \
	  echo "ERROR: could not read control-plane version from cluster '$(cluster)' — is it running?"; exit 1; \
	fi; \
	echo "[upgrade] current control-plane version: $$CURRENT_CP"; \
	echo "[upgrade] current worker spec version:   $$CURRENT_MD"; \
	echo "[upgrade] target version:                $(kubernetes-version)"; \
	if [ "$$CURRENT_CP" = "$(kubernetes-version)" ] && [ "$$CURRENT_MD" = "$(kubernetes-version)" ]; then \
	  echo "[upgrade] CAPI specs already target $(kubernetes-version); still applying claim to let the MVP verifier run"; \
	fi; \
	echo "[upgrade] patching kubernetesVersion in $(examples_dir)/$(cluster).yaml..."; \
	perl -0pi -e 's|(^[ ]*kubernetesVersion: ).*|$${1}$(kubernetes-version)|m' \
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
# Logs – follow the most recent deploy/upgrade Job logs for a cluster
# ---------------------------------------------------------------
logs:
	@test -n "$(cluster)" || (echo "ERROR: cluster is required  →  make logs cluster=ok1"; exit 1)
	@POD=$$(kubectl get pods -n $(namespace) \
	  --sort-by=.metadata.creationTimestamp \
	  -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.status.phase}{"\n"}{end}' 2>/dev/null | \
	  grep "$(cluster)" | grep -E "Running|Pending" | tail -1 | awk '{print $$1}'); \
	if [ -n "$$POD" ]; then \
	  echo "[logs] following pod $$POD..."; \
	  kubectl logs -n $(namespace) $$POD -f; \
	else \
	  POD=$$(kubectl get pods -n $(namespace) \
	    --sort-by=.metadata.creationTimestamp \
	    -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.status.phase}{"\n"}{end}' 2>/dev/null | \
	    grep "$(cluster)" | tail -1 | awk '{print $$1}'); \
	  if [ -n "$$POD" ]; then \
	    echo "[logs] no running pod, showing last pod $$POD..."; \
	    kubectl logs -n $(namespace) $$POD --tail=50; \
	  else \
	    echo "[logs] no pods found for cluster $(cluster)"; \
	  fi; \
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
