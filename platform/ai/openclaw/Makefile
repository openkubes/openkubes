# OK-15 Phase 1 — OpenClaw on ok1-talos (Makefile + Helm)
# OWNER: this Makefile is the canonical one; ok-cluster/openclaw/Makefile is a
# deliberate PoC copy carrying private provider values — sync changes here first.
# Run the steps in order:
#   make preflight   -> make install   -> make status   -> make validate
#   -> make connect-info  (then wire up Open WebUI in the Admin UI)
#
# Guardrails (docs/agentic-ai-poc-guideline.md): single replica, token auth,
# read-only RBAC (no Secrets), no PVC. Everything in here is a Provider Value.

.PHONY: help preflight install upgrade uninstall status validate logs \
        token-show connect-info connect-openwebui fix-openwebui-ollama \
        image-build image-push image-release verify-kubectl chart-release
.DEFAULT_GOAL := help

CLUSTER     ?= ok1-talos
KUBECONFIG  ?= $(HOME)/.kube/$(CLUSTER).yaml
KUBECTL     := kubectl --kubeconfig $(KUBECONFIG)
NS          ?= openclaw
RELEASE     ?= openclaw
CHART       := $(dir $(lastword $(MAKEFILE_LIST)))charts/openclaw
TOKEN_FILE  := $(dir $(lastword $(MAKEFILE_LIST))).token
SVC_URL     := http://$(RELEASE).$(NS).svc.cluster.local:18789

# Shared platform Ollama — provider-specific, no default in the platform
# repo (convention: real endpoints live in the private infra repo).
# Required: make install OLLAMA_URL=http://<ip>:11434
OLLAMA_URL      ?=
OPENWEBUI_NS    ?= open-webui
OPENWEBUI_STS   ?= open-webui-$(CLUSTER)

help:
	@echo "OK-15 Phase 1 — OpenClaw deployment ($(CLUSTER))"
	@echo ""
	@echo "  make preflight             # step 1: cluster/ollama/open-webui checks"
	@echo "  make install               # step 2: helm install (generates token on first run)"
	@echo "  make status                # step 3: pod, service, gateway health"
	@echo "  make validate              # step 4: in-cluster contract test (/v1/models + completion)"
	@echo "  make connect-openwebui     # step 5: auto-register OpenClaw in Open WebUI (env-based)"
	@echo "  make connect-info          # step 5 alt: values for manual entry in the Admin UI"
	@echo ""
	@echo "  make upgrade               # roll out chart/config changes"
	@echo "  make logs                  # tail gateway logs"
	@echo "  make token-show            # print gateway token"
	@echo "  make fix-openwebui-ollama  # apply OLLAMA_BASE_URL chart-bug workaround"
	@echo "  make uninstall             # remove release + namespace"
	@echo ""
	@echo "Custom image (OpenClaw + kubectl, Cluster Inspection skill):"
	@echo "  make image-build           # step A: build kubectl derivative locally"
	@echo "  make image-release         # step B: build + push to \$$IMG ($(IMG))"
	@echo "  make upgrade               # step C: roll out (image is the values.yaml default)"
	@echo "  make verify-kubectl        # step D: kubectl + RBAC checks in the pod"

# ── step 1 ────────────────────────────────────────────────────────────────────
preflight:
	@echo "== kubeconfig / nodes =="
	@$(KUBECTL) get nodes
	@echo ""
	@echo "== Ollama reachable from inside the cluster? =="
	@$(KUBECTL) run openclaw-preflight --rm -i --restart=Never \
		--image=curlimages/curl:8.9.1 -- \
		curl -fsS --max-time 5 $(OLLAMA_URL)/api/tags \
		&& echo "OK: Ollama reachable — check that 'mistral' is in the list above" \
		|| echo "FAIL: Ollama not reachable from the cluster ($(OLLAMA_URL))"
	@echo ""
	@echo "== Open WebUI: OLLAMA_BASE_URL set? (known chart bug, guideline Part B) =="
	@$(KUBECTL) -n $(OPENWEBUI_NS) get sts $(OPENWEBUI_STS) \
		-o jsonpath='{.spec.template.spec.containers[0].env}' 2>/dev/null \
		| grep -q OLLAMA_BASE_URL \
		&& echo "OK: OLLAMA_BASE_URL is set" \
		|| echo "WARN: OLLAMA_BASE_URL missing — run 'make fix-openwebui-ollama'"

fix-openwebui-ollama:
	$(KUBECTL) -n $(OPENWEBUI_NS) set env sts/$(OPENWEBUI_STS) \
		OLLAMA_BASE_URL=$(OLLAMA_URL)

# ── step 2 ────────────────────────────────────────────────────────────────────
$(TOKEN_FILE):
	@umask 077 && openssl rand -hex 24 > $(TOKEN_FILE)
	@echo "Generated new gateway token -> $(TOKEN_FILE) (gitignored)"

# Optional: override the Ollama model for this rollout without editing
# values.yaml, e.g.  make upgrade MODEL=qwen3.5:9b
# (must be pulled on the Ollama host first — see README "Changing the model")
MODEL ?=

install: $(TOKEN_FILE)
	@test -n "$(OLLAMA_URL)" || (echo "ERROR: OLLAMA_URL is required, e.g. make install OLLAMA_URL=http://<ip>:11434"; exit 1)
	helm upgrade --install $(RELEASE) $(CHART) \
		--kubeconfig $(KUBECONFIG) \
		--namespace $(NS) --create-namespace \
		--set gateway.token=$$(cat $(TOKEN_FILE)) \
		--set ollama.baseUrl=$(OLLAMA_URL) \
		$(if $(MODEL),--set ollama.model=$(MODEL))
	@$(KUBECTL) -n $(NS) rollout status deploy/$(RELEASE) --timeout=180s

upgrade: install

uninstall:
	helm uninstall $(RELEASE) --kubeconfig $(KUBECONFIG) -n $(NS) || true
	$(KUBECTL) delete namespace $(NS) --ignore-not-found

# ── step 3 ────────────────────────────────────────────────────────────────────
status:
	@$(KUBECTL) -n $(NS) get pods,svc
	@echo ""
	@echo "== gateway health (in-pod) =="
	@$(KUBECTL) -n $(NS) exec deploy/$(RELEASE) -- \
		node -e "fetch('http://127.0.0.1:18789/healthz').then(r=>{console.log('healthz:',r.status);return fetch('http://127.0.0.1:18789/readyz')}).then(r=>console.log('readyz: ',r.status)).catch(e=>{console.error(e.message);process.exit(1)})"

logs:
	$(KUBECTL) -n $(NS) logs deploy/$(RELEASE) -f --tail=100

# ── step 4: Agent Interface Contract v1 test (in-cluster) ────────────────────
validate: $(TOKEN_FILE)
	@echo "== GET /v1/models (model discovery — this is what Open WebUI calls) =="
	@$(KUBECTL) run openclaw-validate --rm -i --restart=Never \
		--image=curlimages/curl:8.9.1 -- \
		curl -fsS -H "Authorization: Bearer $$(cat $(TOKEN_FILE))" \
		$(SVC_URL)/v1/models
	@echo ""
	@echo "== POST /v1/chat/completions (end-to-end via Ollama/mistral) =="
	@$(KUBECTL) run openclaw-validate2 --rm -i --restart=Never \
		--image=curlimages/curl:8.9.1 -- \
		curl -fsS --max-time 120 \
		-H "Authorization: Bearer $$(cat $(TOKEN_FILE))" \
		-H "Content-Type: application/json" \
		-d '{"model":"openclaw/default","messages":[{"role":"user","content":"Reply with exactly: pong"}]}' \
		$(SVC_URL)/v1/chat/completions
	@echo ""
	@echo "OK: contract endpoint works — proceed with 'make connect-info'"

# ── custom image: OpenClaw + kubectl (Cluster Inspection skill) ──────────────
# Registry decision (OK-15): GHCR is primary, Harbor is deferred. The Docker
# Hub image (kubernautslabs/openclaw-kubectl) is bootstrap-only until the
# first CI push lands on GHCR. Override: make image-release IMG=...
OPENCLAW_VERSION ?= 2026.7.1
# kubectl: match cluster minor (ok1-talos: v1.34.x)
KUBECTL_VERSION  ?= v1.34.1
IMG              ?= ghcr.io/openkubes/openclaw-kubectl
IMG_TAG          ?= $(OPENCLAW_VERSION)
IMAGE_DIR        := $(dir $(lastword $(MAKEFILE_LIST)))images/openclaw-kubectl

image-build:
	docker build --platform linux/amd64 \
		--build-arg OPENCLAW_VERSION=$(OPENCLAW_VERSION) \
		--build-arg KUBECTL_VERSION=$(KUBECTL_VERSION) \
		-t $(IMG):$(IMG_TAG) $(IMAGE_DIR)

image-push:
	docker push $(IMG):$(IMG_TAG)

image-release: image-build image-push

# Publish the chart as OCI to GHCR — required once before the Crossplane
# Composition (crossplane/composition.yaml) can fetch it.
CHART_OCI ?= oci://ghcr.io/openkubes/charts
chart-release:
	helm package $(CHART) -d /tmp
	helm push /tmp/openclaw-$$(helm show chart $(CHART) | awk '/^version:/{print $$2}').tgz $(CHART_OCI)

verify-kubectl:
	@echo "== kubectl present in the pod =="
	@$(KUBECTL) -n $(NS) exec deploy/$(RELEASE) -- kubectl version --client
	@echo ""
	@echo "== positive: Cluster Inspection Contract (read) =="
	@$(KUBECTL) -n $(NS) exec deploy/$(RELEASE) -- kubectl auth can-i list pods --all-namespaces
	@$(KUBECTL) -n $(NS) exec deploy/$(RELEASE) -- kubectl get pods -n $(NS)
	@echo ""
	@echo "== negative: guardrails (must all be denied) =="
	@$(KUBECTL) -n $(NS) exec deploy/$(RELEASE) -- kubectl auth can-i get secrets --all-namespaces \
		&& (echo "FAIL: secrets readable — RBAC violates the guideline, STOP (Part C)"; exit 1) \
		|| echo "OK: secrets denied"
	@$(KUBECTL) -n $(NS) exec deploy/$(RELEASE) -- kubectl auth can-i delete pods --all-namespaces \
		&& (echo "FAIL: write verb allowed — RBAC violates the guideline, STOP (Part C)"; exit 1) \
		|| echo "OK: writes denied"

# ── step 5 ────────────────────────────────────────────────────────────────────
# Auto-register OpenClaw as an OpenAI connection in Open WebUI — same pattern
# as the platform's OLLAMA_BASE_URL workaround (root Makefile of ok-cluster).
#
# NOTE (PersistentConfig): Open WebUI treats these env vars as *seed* values —
# they populate the config DB on a FRESH instance's first start. On an
# instance where the connection was already added via the Admin UI, the DB
# value wins and this is a no-op. The real value of this target is cluster
# rebuilds (make e2e): freshly claimed Open WebUI + this target = zero manual
# UI steps.
connect-openwebui: $(TOKEN_FILE)
	$(KUBECTL) -n $(OPENWEBUI_NS) set env sts/$(OPENWEBUI_STS) \
		OPENAI_API_BASE_URL=$(SVC_URL)/v1 \
		OPENAI_API_KEY=$$(cat $(TOKEN_FILE))
	@echo "Open WebUI pod restarts; on a fresh instance 'openclaw/default' appears automatically."
	@echo "(Existing instances keep their UI-configured connections — PersistentConfig.)"

token-show: $(TOKEN_FILE)
	@cat $(TOKEN_FILE)

connect-info: $(TOKEN_FILE)
	@echo "Open WebUI -> Admin Settings -> Connections -> OpenAI -> Add Connection"
	@echo ""
	@echo "  URL:     $(SVC_URL)/v1        (the /v1 suffix is REQUIRED)"
	@echo "  API Key: $$(cat $(TOKEN_FILE))"
	@echo ""
	@echo "After Verify+Save, 'openclaw/default' appears in the model dropdown."
