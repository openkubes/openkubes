# platform/ai/openclaw/crossplane/Makefile
# Manages OpenClaw deployments via Crossplane from ok-mgmt —
# same pattern as platform/ai/open-webui/crossplane/Makefile.
#
# Order: make token-secret -> make setup -> make deploy CLUSTER=... OLLAMA_ENDPOINT=...

MGMT_KUBECONFIG  ?= $(HOME)/.kube/ok-mgmt.yaml
KUBECTL          := kubectl --kubeconfig $(MGMT_KUBECONFIG)
CLAIM_NAMESPACE  := openkubes-system
CLUSTER          ?= ok1-talos
# Provider Value — no default by convention (real endpoint: private infra repo)
OLLAMA_ENDPOINT  ?=
TOKEN_SECRET     ?= openclaw-gateway-token

.PHONY: help token-secret setup deploy status undeploy list

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

token-secret: ## Create the gateway-token Secret on ok-mgmt (run once; idempotent)
	@$(KUBECTL) -n $(CLAIM_NAMESPACE) get secret $(TOKEN_SECRET) >/dev/null 2>&1 \
		&& echo "OK: Secret $(TOKEN_SECRET) already exists (kept — token is operational state)" \
		|| $(KUBECTL) -n $(CLAIM_NAMESPACE) create secret generic $(TOKEN_SECRET) \
			--from-literal=gateway-token=$$(openssl rand -hex 24)

setup: ## Apply XRD + Composition to ok-mgmt (run once after bootstrap)
	@echo "[openclaw] Applying XRD and Composition to ok-mgmt..."
	$(KUBECTL) apply -f xrd.yaml
	$(KUBECTL) apply -f composition.yaml
	$(KUBECTL) wait xrd/openclawinstances.platform.openkubes.ai \
		--for=condition=Established --timeout=60s
	@echo "✅ OpenClaw Composition ready on ok-mgmt"

deploy: token-secret ## Deploy OpenClaw on a cluster (CLUSTER=... OLLAMA_ENDPOINT=...)
	@echo "[openclaw] Deploying OpenClaw on cluster '$(CLUSTER)'..."
	@if [ -f "examples/$(CLUSTER).yaml" ] && ! grep -q OLLAMA_IP "examples/$(CLUSTER).yaml"; then \
		$(KUBECTL) apply -f examples/$(CLUSTER).yaml; \
	else \
		test -n "$(OLLAMA_ENDPOINT)" || { echo "ERROR: OLLAMA_ENDPOINT required, e.g. make deploy OLLAMA_ENDPOINT=http://<ip>:11434"; exit 1; }; \
		printf '%s\n' \
			'apiVersion: platform.openkubes.ai/v1alpha1' \
			'kind: OpenClawClaim' \
			'metadata:' \
			'  name: $(CLUSTER)' \
			'  namespace: $(CLAIM_NAMESPACE)' \
			'spec:' \
			'  clusterRef: $(CLUSTER)' \
			'  ollamaEndpoint: $(OLLAMA_ENDPOINT)' \
			'  namespace: openclaw' \
			| $(KUBECTL) apply -f -; \
	fi
	@echo "[openclaw] Waiting for Helm release to be ready..."
	@for i in $$(seq 1 24); do \
		STATE=$$($(KUBECTL) get release.helm.crossplane.io openclaw-$(CLUSTER) \
			-o jsonpath='{.status.atProvider.state}' 2>/dev/null || echo ""); \
		if [ "$$STATE" = "deployed" ]; then \
			echo "✅ OpenClaw deployed on $(CLUSTER)"; \
			break; \
		fi; \
		echo "  ⏳ waiting... ($$i/24) state=$$STATE"; \
		sleep 10; \
	done
	@$(MAKE) status CLUSTER=$(CLUSTER)

status: ## Show OpenClaw deployment status (CLUSTER=...)
	@echo "=== Claim ==="
	$(KUBECTL) get openclawclaim $(CLUSTER) -n $(CLAIM_NAMESPACE) 2>/dev/null || \
		echo "  No claim found for '$(CLUSTER)'"
	@echo ""
	@echo "=== Helm Release ==="
	$(KUBECTL) get release.helm.crossplane.io openclaw-$(CLUSTER) 2>/dev/null || \
		echo "  No release found"
	@echo ""
	@echo "=== Pods on $(CLUSTER) ==="
	@if [ -f "$(HOME)/.kube/$(CLUSTER).yaml" ]; then \
		kubectl --kubeconfig $(HOME)/.kube/$(CLUSTER).yaml get pods -n openclaw 2>/dev/null || \
			echo "  No pods found"; \
	else \
		echo "  Kubeconfig not found: ~/.kube/$(CLUSTER).yaml"; \
	fi

undeploy: ## Remove OpenClaw from a cluster (CLUSTER=...)
	@echo "[openclaw] Removing OpenClaw from cluster '$(CLUSTER)'..."
	$(KUBECTL) delete openclawclaim $(CLUSTER) -n $(CLAIM_NAMESPACE) --ignore-not-found
	@echo "✅ OpenClawClaim deleted"

list: ## List all OpenClaw deployments
	@echo "=== OpenClaw Claims ==="
	$(KUBECTL) get openclawclaim -A
	@echo ""
	@echo "=== Helm Releases ==="
	$(KUBECTL) get release.helm.crossplane.io -A | grep openclaw || \
		echo "  No OpenClaw releases found"

.DEFAULT_GOAL := help
