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

.PHONY: help setup deploy delete status logs check force-clean kubeconfig upgrade recreate manager-deploy manager-delete manager-status manager-open ingress-setup ingress-delete ingress-status cert-setup cert-delete cert-status

help:
	@echo ""
	@echo "OpenKubes Platform – Cluster Operations"
	@echo ""
	@echo "Setup (one-time):"
	@echo "  make setup                              Apply all Crossplane XRDs and Compositions"
	@echo ""
	@echo "Cluster Lifecycle:"
	@echo "  make deploy      cluster=ok1                              Deploy a workload cluster"
	@echo "  make delete      cluster=ok1                              Clean delete (Cleanup Job + remove claims)"
	@echo "  make kubeconfig  cluster=ok1                              Get workload cluster kubeconfig"
	@echo "  make recreate    cluster=ok1 kubernetes-version=v1.34.1  Recreate cluster on new version (reliable)"
	@echo "  make upgrade     cluster=ok1 kubernetes-version=v1.34.1  Rolling upgrade (experimental, CAPK v0.12+)"
	@echo "  make status      cluster=ok1                              Show cluster status"
	@echo "  make logs        cluster=ok1                              Follow deploy Job logs"
	@echo ""
	@echo "Troubleshooting:"
	@echo "  make check       cluster=ok1            Check for leftover resources"
	@echo "  make force-clean cluster=ok1            Force cleanup all resources (emergency)"
	@echo ""
	@echo "Cluster Manager (Headlamp):"
	@echo "  make manager-deploy  cluster=ok1        Deploy Headlamp on workload cluster"
	@echo "  make manager-token   cluster=ok1        Generate Headlamp admin token"
	@echo "  make manager-delete  cluster=ok1        Remove Headlamp from workload cluster"
	@echo "  make manager-status  cluster=ok1        Show Headlamp status + URL"
	@echo "  make manager-open    cluster=ok1        Port-forward + open browser"
	@echo ""
	@echo "Ingress (Traefik via INFRA LB proxy):"
	@echo "  make ingress-setup   cluster=ok1             Deploy Traefik via Crossplane (no MetalLB)"
	@echo "  make ingress-delete  cluster=ok1             Remove Traefik"
	@echo "  make ingress-delete  cluster=ok1 cert=true   Remove Traefik + cert-manager"
	@echo "  make ingress-status  cluster=ok1             Show Traefik + LB status"
	@echo ""
	@echo "TLS / cert-manager:"
	@echo "  make cert-setup  cluster=ok1            Deploy cert-manager + Let's Encrypt ClusterIssuers"
	@echo "  make cert-delete cluster=ok1            Remove cert-manager"
	@echo "  make cert-status cluster=ok1            Show certificate status"
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

# ---------------------------------------------------------------
# Manager Deploy – install Headlamp on workload cluster
# ---------------------------------------------------------------
manager-deploy:
	@test -n "$(cluster)" || (echo "ERROR: cluster is required  →  make manager-deploy cluster=ok1"; exit 1)
	@test -f "$(kubeconfig_dir)/$(cluster).kubeconfig" || \
	  (echo "ERROR: kubeconfig not found — run: make kubeconfig cluster=$(cluster)"; exit 1)
	@echo "[manager] installing Headlamp on cluster '$(cluster)'..."
	@helm repo add headlamp https://kubernetes-sigs.github.io/headlamp/ 2>/dev/null || true
	@helm repo update headlamp 2>/dev/null || true
	@KUBECONFIG=$(kubeconfig_dir)/$(cluster).kubeconfig \
	  helm upgrade --install headlamp headlamp/headlamp \
	  --namespace headlamp --create-namespace \
	  --set nodeSelector."node-role\.kubernetes\.io/control-plane"="" \
	  --set tolerations[0].key="node-role.kubernetes.io/control-plane" \
	  --set tolerations[0].operator="Exists" \
	  --set tolerations[0].effect="NoSchedule" \
	  --wait --timeout 120s
	@echo "[manager] Headlamp installed on cluster '$(cluster)' ✅"
	@echo ""
	@echo "Generate token:"
	@echo "  make manager-token cluster=$(cluster)"
	@echo ""
	@echo "Open UI:"
	@echo "  make manager-open cluster=$(cluster)"

# ---------------------------------------------------------------
# Manager Token – generate admin token for Headlamp
# ---------------------------------------------------------------
manager-token:
	@test -n "$(cluster)" || (echo "ERROR: cluster is required  →  make manager-token cluster=ok1"; exit 1)
	@test -f "$(kubeconfig_dir)/$(cluster).kubeconfig" || \
	  (echo "ERROR: kubeconfig not found — run: make kubeconfig cluster=$(cluster)"; exit 1)
	@echo "[manager] generating admin token for Headlamp on '$(cluster)'..."
	@KUBECONFIG=$(kubeconfig_dir)/$(cluster).kubeconfig \
	  kubectl create token headlamp -n headlamp --duration 24h

# ---------------------------------------------------------------
# Manager Delete – remove Headlamp from workload cluster
# ---------------------------------------------------------------
manager-delete:
	@test -n "$(cluster)" || (echo "ERROR: cluster is required  →  make manager-delete cluster=ok1"; exit 1)
	@test -f "$(kubeconfig_dir)/$(cluster).kubeconfig" || \
	  (echo "ERROR: kubeconfig not found — run: make kubeconfig cluster=$(cluster)"; exit 1)
	@echo "[manager] removing Headlamp from cluster '$(cluster)'..."
	@KUBECONFIG=$(kubeconfig_dir)/$(cluster).kubeconfig \
	  helm uninstall headlamp --namespace headlamp 2>/dev/null || true
	@KUBECONFIG=$(kubeconfig_dir)/$(cluster).kubeconfig \
	  kubectl delete namespace headlamp --ignore-not-found 2>/dev/null || true
	@echo "[manager] Headlamp removed from cluster '$(cluster)' ✅"

# ---------------------------------------------------------------
# Manager Status – show Headlamp status
# ---------------------------------------------------------------
manager-status:
	@test -n "$(cluster)" || (echo "ERROR: cluster is required  →  make manager-status cluster=ok1"; exit 1)
	@test -f "$(kubeconfig_dir)/$(cluster).kubeconfig" || \
	  (echo "ERROR: kubeconfig not found — run: make kubeconfig cluster=$(cluster)"; exit 1)
	@echo "=== Headlamp on cluster '$(cluster)' ==="
	@KUBECONFIG=$(kubeconfig_dir)/$(cluster).kubeconfig \
	  kubectl get pods -n headlamp 2>/dev/null || echo "Headlamp not installed"
	@echo ""
	@echo "=== Service ==="
	@KUBECONFIG=$(kubeconfig_dir)/$(cluster).kubeconfig \
	  kubectl get svc -n headlamp 2>/dev/null || true
	@echo ""
	@echo "Access via: make manager-open cluster=$(cluster)"

# ---------------------------------------------------------------
# Manager Open – port-forward and open browser
# ---------------------------------------------------------------
manager-open:
	@test -n "$(cluster)" || (echo "ERROR: cluster is required  →  make manager-open cluster=ok1"; exit 1)
	@test -f "$(kubeconfig_dir)/$(cluster).kubeconfig" || \
	  (echo "ERROR: kubeconfig not found — run: make kubeconfig cluster=$(cluster)"; exit 1)
	@echo "[manager] starting port-forward for Headlamp on '$(cluster)'..."
	@echo "[manager] opening http://localhost:8080"
	@echo "[manager] press Ctrl+C to stop"
	@echo ""
	@echo "Get token with: make manager-token cluster=$(cluster)"
	@echo ""
	@(sleep 2 && open http://localhost:8080 2>/dev/null || \
	  xdg-open http://localhost:8080 2>/dev/null || true) &
	@KUBECONFIG=$(kubeconfig_dir)/$(cluster).kubeconfig \
	  kubectl port-forward svc/headlamp -n headlamp 8080:80

# ---------------------------------------------------------------
# Ingress Setup – deploy Traefik via Crossplane (no MetalLB needed)
#
# How it works:
#   1. Creates Crossplane ProviderConfigs for workload cluster
#   2. Deploys Traefik as NodePort on control-plane node
#   3. Auto-detects Traefik NodePorts
#   4. Patches INFRA LoadBalancer (cluster-lb) to expose 80/443
#
# Note: No MetalLB needed — INFRA MetalLB acts as proxy via cluster-lb.
#       Traefik runs on control-plane node (required for INFRA LB routing).
# ---------------------------------------------------------------
ingress-setup:
	@test -n "$(cluster)" || (echo "ERROR: cluster is required  →  make ingress-setup cluster=ok1"; exit 1)
	@test -f "$(kubeconfig_dir)/$(cluster).kubeconfig" || \
	  (echo "ERROR: kubeconfig not found — run: make kubeconfig cluster=$(cluster)"; exit 1)
	@echo "[ingress] setting up Traefik on cluster '$(cluster)'..."
	@echo ""
	@echo "[ingress] step 1: creating Crossplane ProviderConfigs..."
	@kubectl create secret generic $(cluster)-kubeconfig \
	  -n crossplane-system \
	  --from-file=kubeconfig=$(kubeconfig_dir)/$(cluster).kubeconfig \
	  --dry-run=client -o yaml | kubectl apply -f -
	@kubectl apply -f "$(examples_dir)/$(cluster)-providerconfigs.yaml"
	@kubectl apply -f "$(examples_dir)/$(cluster)-traefik.yaml"
	@echo "[ingress] step 2: waiting for Traefik to be ready (up to 5min)..."
	@for i in $$(seq 1 30); do \
	  READY=$$(KUBECONFIG=$(kubeconfig_dir)/$(cluster).kubeconfig \
	    kubectl get pods -n traefik \
	    -o jsonpath='{.items[0].status.conditions[?(@.type=="Ready")].status}' 2>/dev/null || echo ""); \
	  echo "[ingress] Traefik READY=$$READY ($$i/30)"; \
	  if [ "$$READY" = "True" ]; then break; fi; \
	  [ "$$i" = "30" ] && echo "[ingress] WARNING: Traefik timeout — check: kubectl get release traefik-$(cluster)"; \
	  /bin/sleep 10; \
	done
	@echo "[ingress] step 3: patching INFRA LoadBalancer to expose 80/443..."
	@echo "[ingress] reading INFRA kubeconfig from CAPK secret..."
	@kubectl get secret external-infra-kubeconfig -n capk-system \
	  -o jsonpath='{.data.kubeconfig}' | base64 -d > /tmp/infra-$(cluster).kubeconfig
	@HTTP_NP=$$(KUBECONFIG=$(kubeconfig_dir)/$(cluster).kubeconfig \
	  kubectl get svc traefik-$(cluster) -n traefik \
	  -o jsonpath='{.spec.ports[?(@.name=="web")].nodePort}' 2>/dev/null); \
	HTTPS_NP=$$(KUBECONFIG=$(kubeconfig_dir)/$(cluster).kubeconfig \
	  kubectl get svc traefik-$(cluster) -n traefik \
	  -o jsonpath='{.spec.ports[?(@.name=="websecure")].nodePort}' 2>/dev/null); \
	API_NP=$$(KUBECONFIG=/tmp/infra-$(cluster).kubeconfig \
	  kubectl get svc $(cluster)-lb -n $(cluster) \
	  -o jsonpath='{.spec.ports[?(@.name=="k8s-api")].nodePort}' 2>/dev/null); \
	if [ -z "$$API_NP" ]; then \
	  API_NP=$$(KUBECONFIG=/tmp/infra-$(cluster).kubeconfig \
	    kubectl get svc $(cluster)-lb -n $(cluster) \
	    -o jsonpath='{.spec.ports[0].nodePort}' 2>/dev/null); \
	fi; \
	echo "[ingress] NodePorts: http=$$HTTP_NP https=$$HTTPS_NP api=$$API_NP"; \
	KUBECONFIG=/tmp/infra-$(cluster).kubeconfig \
	  kubectl patch svc $(cluster)-lb -n $(cluster) --type merge -p \
	  "{\"spec\":{\"ports\":[{\"name\":\"k8s-api\",\"nodePort\":$$API_NP,\"port\":6443,\"protocol\":\"TCP\",\"targetPort\":6443},{\"name\":\"http\",\"nodePort\":$$HTTP_NP,\"port\":80,\"protocol\":\"TCP\",\"targetPort\":$$HTTP_NP},{\"name\":\"https\",\"nodePort\":$$HTTPS_NP,\"port\":443,\"protocol\":\"TCP\",\"targetPort\":$$HTTPS_NP}]}}"; \
	LB_IP=$$(KUBECONFIG=/tmp/infra-$(cluster).kubeconfig \
	  kubectl get svc $(cluster)-lb -n $(cluster) \
	  -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null); \
	rm -f /tmp/infra-$(cluster).kubeconfig; \
	echo ""; \
	echo "[ingress] ✅ Traefik is ready!"; \
	echo "[ingress] HTTP:  http://$$LB_IP"; \
	echo "[ingress] HTTPS: https://$$LB_IP"; \
	echo "[ingress] Example: curl -I http://myapp.$$LB_IP.nip.io"

# ---------------------------------------------------------------
# Ingress Delete – remove Traefik (and optionally cert-manager)
#
# Usage:
#   make ingress-delete cluster=ok1           # Traefik only
#   make ingress-delete cluster=ok1 cert=true # Traefik + cert-manager
# ---------------------------------------------------------------
cert ?=
ingress-delete:
	@test -n "$(cluster)" || (echo "ERROR: cluster is required  →  make ingress-delete cluster=ok1"; exit 1)
	@echo "[ingress] removing ingress stack from cluster '$(cluster)'..."
	@echo ""
	@# Step 1: delete cert-manager if requested
	@if [ "$(cert)" = "true" ]; then \
	  echo "[ingress] removing cert-manager..."; \
	  kubectl delete release.helm.crossplane.io certmanager-$(cluster) --ignore-not-found 2>/dev/null || true; \
	  kubectl delete object.kubernetes.crossplane.io \
	    $(cluster)-ns-certmanager \
	    $(cluster)-clusterissuer-staging \
	    $(cluster)-clusterissuer-prod \
	    $(cluster)-ingress-headlamp \
	    --ignore-not-found 2>/dev/null || true; \
	  echo "[ingress] waiting for cert-manager removal..."; \
	  for i in $$(seq 1 20); do \
	    COUNT=$$(KUBECONFIG=$(kubeconfig_dir)/$(cluster).kubeconfig \
	      kubectl get pods -n cert-manager --no-headers 2>/dev/null | wc -l | tr -d ' '); \
	    echo "[ingress] cert-manager pods remaining: $$COUNT ($$i/20)"; \
	    [ "$$COUNT" = "0" ] && break; \
	    /bin/sleep 5; \
	  done; \
	fi
	@echo "[ingress] step 1: removing Traefik release + objects..."
	@kubectl delete release.helm.crossplane.io traefik-$(cluster) \
	  --ignore-not-found 2>/dev/null || true
	@kubectl delete object.kubernetes.crossplane.io \
	  $(cluster)-ns-traefik --ignore-not-found 2>/dev/null || true
	@echo "[ingress] step 2: waiting for Traefik to be removed from workload cluster..."
	@for i in $$(seq 1 20); do \
	  COUNT=$$(KUBECONFIG=$(kubeconfig_dir)/$(cluster).kubeconfig \
	    kubectl get pods -n traefik --no-headers 2>/dev/null | wc -l | tr -d ' '); \
	  echo "[ingress] Traefik pods remaining: $$COUNT ($$i/20)"; \
	  [ "$$COUNT" = "0" ] && break; \
	  /bin/sleep 5; \
	done
	@echo "[ingress] step 3: removing ProviderConfigs..."
	@kubectl patch providerconfig.kubernetes.crossplane.io $(cluster)-kubernetes \
	  --type merge -p '{"metadata":{"finalizers":[]}}' 2>/dev/null || true
	@kubectl delete providerconfig.helm.crossplane.io \
	  $(cluster)-helm --ignore-not-found 2>/dev/null || true
	@kubectl delete providerconfig.kubernetes.crossplane.io \
	  $(cluster)-kubernetes --ignore-not-found 2>/dev/null || true
	@echo "[ingress] step 4: removing 80/443 from INFRA LoadBalancer..."
	@kubectl get secret external-infra-kubeconfig -n capk-system \
	  -o jsonpath='{.data.kubeconfig}' | base64 -d > /tmp/infra-$(cluster).kubeconfig
	@API_NP=$$(KUBECONFIG=/tmp/infra-$(cluster).kubeconfig \
	  kubectl get svc $(cluster)-lb -n $(cluster) \
	  -o jsonpath='{.spec.ports[?(@.name=="k8s-api")].nodePort}' 2>/dev/null); \
	if [ -z "$$API_NP" ]; then \
	  API_NP=$$(KUBECONFIG=/tmp/infra-$(cluster).kubeconfig \
	    kubectl get svc $(cluster)-lb -n $(cluster) \
	    -o jsonpath='{.spec.ports[0].nodePort}' 2>/dev/null); \
	fi; \
	KUBECONFIG=/tmp/infra-$(cluster).kubeconfig \
	  kubectl patch svc $(cluster)-lb -n $(cluster) --type merge -p \
	  "{\"spec\":{\"ports\":[{\"name\":\"k8s-api\",\"nodePort\":$$API_NP,\"port\":6443,\"protocol\":\"TCP\",\"targetPort\":6443}]}}"; \
	rm -f /tmp/infra-$(cluster).kubeconfig
	@echo ""
	@echo "[ingress] ✅ ingress stack removed!"

# ---------------------------------------------------------------
# Ingress Status – show Traefik + LoadBalancer status
# ---------------------------------------------------------------
ingress-status:
	@test -n "$(cluster)" || (echo "ERROR: cluster is required  →  make ingress-status cluster=ok1"; exit 1)
	@echo "=== Crossplane Releases ==="
	@kubectl get release.helm.crossplane.io 2>/dev/null | grep -E "metallb|traefik" || echo "No releases found"
	@echo ""
	@echo "=== Traefik Pod on $(cluster) ==="
	@KUBECONFIG=$(kubeconfig_dir)/$(cluster).kubeconfig \
	  kubectl get pods -n traefik 2>/dev/null || echo "Traefik not found"
	@echo ""
	@echo "=== Traefik Service on $(cluster) ==="
	@KUBECONFIG=$(kubeconfig_dir)/$(cluster).kubeconfig \
	  kubectl get svc -n traefik 2>/dev/null || echo "No service found"
	@echo ""
	@echo "=== INFRA LoadBalancer ==="
	@kubectl get svc $(cluster)-lb -n $(cluster) 2>/dev/null || echo "No LB found"
	@LB_IP=$$(kubectl get svc $(cluster)-lb -n $(cluster) \
	  -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null); \
	echo ""; \
	echo "Access: http://$$LB_IP  https://$$LB_IP"

# ---------------------------------------------------------------
# Cert Setup – deploy cert-manager + Let's Encrypt ClusterIssuers
# ---------------------------------------------------------------
cert-setup:
	@test -n "$(cluster)" || (echo "ERROR: cluster is required  →  make cert-setup cluster=ok1"; exit 1)
	@test -f "$(examples_dir)/$(cluster)-certmanager.yaml" || \
	  (echo "ERROR: $(examples_dir)/$(cluster)-certmanager.yaml not found"; exit 1)
	@echo "[cert] deploying cert-manager on cluster '$(cluster)'..."
	@kubectl apply -f "$(examples_dir)/$(cluster)-certmanager.yaml"
	@echo "[cert] waiting for cert-manager to be ready (up to 5min)..."
	@for i in $$(seq 1 30); do \
	  READY=$$(kubectl get release.helm.crossplane.io certmanager-$(cluster) \
	    -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null || echo ""); \
	  echo "[cert] cert-manager READY=$$READY ($$i/30)"; \
	  if [ "$$READY" = "True" ]; then break; fi; \
	  [ "$$i" = "30" ] && echo "[cert] WARNING: cert-manager timeout"; \
	  /bin/sleep 10; \
	done
	@echo "[cert] waiting for certificate to be issued..."
	@for i in $$(seq 1 30); do \
	  READY=$$(KUBECONFIG=$(kubeconfig_dir)/$(cluster).kubeconfig \
	    kubectl get certificate -A \
	    -o jsonpath='{.items[0].status.conditions[?(@.type=="Ready")].status}' 2>/dev/null || echo ""); \
	  echo "[cert] certificate READY=$$READY ($$i/30)"; \
	  if [ "$$READY" = "True" ]; then \
	    echo "[cert] ✅ Certificate issued!"; \
	    break; \
	  fi; \
	  [ "$$i" = "30" ] && echo "[cert] WARNING: certificate timeout — check: make cert-status cluster=$(cluster)"; \
	  /bin/sleep 10; \
	done

# ---------------------------------------------------------------
# Cert Delete – remove cert-manager
# ---------------------------------------------------------------
cert-delete:
	@test -n "$(cluster)" || (echo "ERROR: cluster is required  →  make cert-delete cluster=ok1"; exit 1)
	@echo "[cert] removing cert-manager from cluster '$(cluster)'..."
	@kubectl delete release.helm.crossplane.io certmanager-$(cluster) --ignore-not-found 2>/dev/null || true
	@kubectl delete object.kubernetes.crossplane.io \
	  $(cluster)-ns-certmanager \
	  $(cluster)-clusterissuer-staging \
	  $(cluster)-clusterissuer-prod \
	  $(cluster)-ingress-headlamp \
	  --ignore-not-found 2>/dev/null || true
	@echo "[cert] cert-manager removed ✅"

# ---------------------------------------------------------------
# Cert Status – show certificate status
# ---------------------------------------------------------------
cert-status:
	@test -n "$(cluster)" || (echo "ERROR: cluster is required  →  make cert-status cluster=ok1"; exit 1)
	@echo "=== cert-manager Release ==="
	@kubectl get release.helm.crossplane.io certmanager-$(cluster) 2>/dev/null || echo "cert-manager not installed"
	@echo ""
	@echo "=== ClusterIssuers ==="
	@KUBECONFIG=$(kubeconfig_dir)/$(cluster).kubeconfig \
	  kubectl get clusterissuer 2>/dev/null || echo "No ClusterIssuers found"
	@echo ""
	@echo "=== Certificates ==="
	@KUBECONFIG=$(kubeconfig_dir)/$(cluster).kubeconfig \
	  kubectl get certificate -A 2>/dev/null || echo "No certificates found"
	@echo ""
	@echo "=== Ingresses ==="
	@KUBECONFIG=$(kubeconfig_dir)/$(cluster).kubeconfig \
	  kubectl get ingress -A 2>/dev/null || echo "No ingresses found"
