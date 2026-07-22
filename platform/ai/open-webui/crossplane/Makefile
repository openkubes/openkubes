# platform/ai/open-webui/crossplane/Makefile
# Manages OpenWebUI deployments via Crossplane from ok-mgmt

MGMT_KUBECONFIG  ?= $(HOME)/.kube/ok-mgmt.yaml
KUBECTL          := kubectl --kubeconfig $(MGMT_KUBECONFIG)
CLAIM_NAMESPACE  := openkubes-system
CLUSTER          ?= ok-ai
# Provider Value — no default by convention (real endpoint: ok-cluster/open-webui/)
OLLAMA_ENDPOINT  ?=

.PHONY: help setup deploy status undeploy list

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

setup: ## Apply XRD + Composition to ok-mgmt (run once after bootstrap)
	@echo "[open-webui] Applying XRD and Composition to ok-mgmt..."
	$(KUBECTL) apply -f xrd.yaml
	$(KUBECTL) apply -f composition.yaml
	$(KUBECTL) wait xrd/openwebuiinstances.platform.openkubes.ai \
		--for=condition=Established --timeout=60s
	@echo "✅ OpenWebUI Composition ready on ok-mgmt"

deploy: ## Deploy Open WebUI on a cluster (CLUSTER=ok-ai OLLAMA_ENDPOINT=...)
	@echo "[open-webui] Deploying Open WebUI on cluster '$(CLUSTER)'..."
	@if [ -f "examples/$(CLUSTER).yaml" ] && ! grep -q OLLAMA_IP "examples/$(CLUSTER).yaml"; then \
		$(KUBECTL) apply -f examples/$(CLUSTER).yaml; \
	else \
		test -n "$(OLLAMA_ENDPOINT)" || { echo "ERROR: OLLAMA_ENDPOINT required, e.g. make deploy OLLAMA_ENDPOINT=http://<ip>:11434 (or apply ok-cluster/open-webui/claim-$(CLUSTER).yaml directly)"; exit 1; }; \
		echo "  Ollama endpoint: $(OLLAMA_ENDPOINT)"; \
		$(KUBECTL) apply -f - < <(printf '%s\n' \
			'apiVersion: platform.openkubes.ai/v1alpha1' \
			'kind: OpenWebUIClaim' \
			'metadata:' \
			'  name: $(CLUSTER)' \
			'  namespace: $(CLAIM_NAMESPACE)' \
			'spec:' \
			'  clusterRef: $(CLUSTER)' \
			'  ollamaEndpoint: $(OLLAMA_ENDPOINT)' \
			'  namespace: open-webui'); \
	fi
	@echo "[open-webui] Waiting for Helm release to be ready..."
	@for i in $$(seq 1 24); do \
		STATE=$$($(KUBECTL) get release.helm.crossplane.io open-webui-$(CLUSTER) \
			-o jsonpath='{.status.atProvider.state}' 2>/dev/null || echo ""); \
		if [ "$$STATE" = "deployed" ]; then \
			echo "✅ Open WebUI deployed on $(CLUSTER)"; \
			break; \
		fi; \
		echo "  ⏳ waiting... ($$i/24) state=$$STATE"; \
		sleep 10; \
	done
	@$(MAKE) status CLUSTER=$(CLUSTER)

status: ## Show Open WebUI deployment status (CLUSTER=ok-ai)
	@echo "=== Claim ==="
	$(KUBECTL) get openwebuiclaim $(CLUSTER) -n $(CLAIM_NAMESPACE) 2>/dev/null || \
		echo "  No claim found for '$(CLUSTER)'"
	@echo ""
	@echo "=== Helm Release ==="
	$(KUBECTL) get release.helm.crossplane.io open-webui-$(CLUSTER) 2>/dev/null || \
		echo "  No release found"
	@echo ""
	@echo "=== Pods on $(CLUSTER) ==="
	@if [ -f "$(HOME)/.kube/$(CLUSTER).yaml" ]; then \
		kubectl --kubeconfig $(HOME)/.kube/$(CLUSTER).yaml get pods -n open-webui 2>/dev/null || \
			echo "  No pods found"; \
	else \
		echo "  Kubeconfig not found: ~/.kube/$(CLUSTER).yaml"; \
	fi

undeploy: ## Remove Open WebUI from a cluster (CLUSTER=ok-ai)
	@echo "[open-webui] Removing Open WebUI from cluster '$(CLUSTER)'..."
	$(KUBECTL) delete openwebuiclaim $(CLUSTER) -n $(CLAIM_NAMESPACE) --ignore-not-found
	@echo "✅ OpenWebUIClaim deleted"

list: ## List all Open WebUI deployments
	@echo "=== OpenWebUI Claims ==="
	$(KUBECTL) get openwebuiclaim -A
	@echo ""
	@echo "=== Helm Releases ==="
	$(KUBECTL) get release.helm.crossplane.io -A | grep open-webui || \
		echo "  No Open WebUI releases found"

.DEFAULT_GOAL := help
