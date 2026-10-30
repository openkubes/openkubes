# OK-167 — gitless GitOps with Argo CD and zot.
#
# The only entry point for this spike. Nothing here is run by hand: every
# command that reads or changes a cluster goes through a target, and every such
# target depends on `guard` first (BRIEF B4 rule 1, B8).
#
# Targets cover installation, guarded experiments, verification and teardown.

.DEFAULT_GOAL := help
.NOTPARALLEL:
SHELL := /usr/bin/env bash
.SHELLFLAGS := -euo pipefail -c

# ---------------------------------------------------------------------------
# Version pins — maintained in versions.env only
# ---------------------------------------------------------------------------
include versions.env
export

# ---------------------------------------------------------------------------
# Cluster isolation
# ---------------------------------------------------------------------------
# Set here as well as in the session, so a target run from a shell with a wrong
# or missing KUBECONFIG still reaches only the local kind cluster. guard.sh
# verifies it regardless — the export is a seatbelt, not the check.
export KUBECONFIG := $(CURDIR)/.local/kubeconfig

# ---------------------------------------------------------------------------
# Tool configuration kept out of $HOME (BRIEF B4 rule 6)
# ---------------------------------------------------------------------------
# Nothing may be written to ~/.docker, ~/Library/Preferences/helm or ~/.config.
export HELM_CONFIG_HOME   := $(CURDIR)/.local/helm/config
export HELM_CACHE_HOME    := $(CURDIR)/.local/helm/cache
export HELM_DATA_HOME     := $(CURDIR)/.local/helm/data
export HELM_REGISTRY_CONFIG := $(CURDIR)/.local/helm/config/registry/config.json

# DOCKER_CONFIG is deliberately NOT exported globally: kind needs the host's
# Docker context. It is set as a prefix on cosign calls only (Phase 8).
DOCKER_CONFIG_LOCAL := $(CURDIR)/.local/docker

# ---------------------------------------------------------------------------
# Toolchain
# ---------------------------------------------------------------------------
# Tool variables accept executable paths, including executable container wrappers.
# A shell command string is not a portable executable override for every script.
#
# kubectl: the binary first on PATH is Docker Desktop's and trails the pinned
# node image by two minor versions (evidence/00-preflight.md, finding F2).
# Homebrew's is preferred when present; guard.sh enforces the +/-1 rule anyway.
KUBECTL    ?= $(shell for c in /opt/homebrew/bin/kubectl kubectl; do command -v $$c >/dev/null 2>&1 && { command -v $$c; break; }; done)
HELM       ?= helm
KIND       ?= kind
DOCKER     ?= docker
ORAS       ?= oras
COSIGN     ?= cosign
GTAR       ?= gtar
JQ         ?= jq
YQ         ?= yq
YAMLLINT   ?= yamllint
SHELLCHECK ?= shellcheck
ACTIONLINT ?= actionlint
# System openssl on macOS is LibreSSL and differs from OpenSSL in ways that
# matter for certificate generation; openssl@3 is used explicitly.
OPENSSL    ?= $(shell for c in /opt/homebrew/opt/openssl@3/bin/openssl /usr/local/opt/openssl@3/bin/openssl openssl; do command -v $$c >/dev/null 2>&1 && { command -v $$c; break; }; done)

GUARD := scripts/guard.sh
UTC    = $(shell date -u +%Y%m%dT%H%M%SZ)

.PHONY: help guard preflight lint shellcheck-scripts yamllint-manifests \
        scan-secrets debug diff upgrade clean-local \
        up down clean cluster-info \
        namespaces pki identities zot-secrets events-install events-log \
        zot-template zot-install zot-logs zot-verify zot-down zot-up repo-server-restart \
        push push-dry determinism verify \
        argocd-install argocd-repo argocd-project argocd-repo-creds \
        app-tag app-digest app-semver app-kustomize app-helm app-set-revision \
        refresh app-status app-wait probe-version measure drift

# ---------------------------------------------------------------------------

# Two deviations from the CONTRIBUTING.md template, both forced by this host:
#   - $(firstword ...) instead of $(MAKEFILE_LIST): `include versions.env`
#     appends that file to the list, grep would then see two files and prefix
#     every line with a filename, so every target printed as "Makefile".
#   - ":.*## " instead of ":.*?## ": `.*?` is a PCRE lazy quantifier. macOS awk
#     is BSD awk and only speaks POSIX ERE, where it does not mean "lazy".
#     Greedy is correct here anyway — a target line carries one "## ".
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*## .*$$' $(firstword $(MAKEFILE_LIST)) \
		| awk 'BEGIN {FS = ":.*## "}; {printf "\033[36m%-24s\033[0m %s\n", $$1, $$2}'

guard: ## Verify the session can only reach the local kind cluster
	@$(GUARD)

# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------
# Automates the Phase 0 checks so they can be re-run at any time.
#
# Deviation from BRIEF B8, deliberate: B8 says preflight writes
# evidence/00-preflight.md. That document carries hand-written analysis of five
# findings which a script cannot reproduce, and regenerating it would destroy
# them. The target therefore asserts the same facts and appends a machine
# readable record to evidence/raw/, which 00-preflight.md references.
preflight: ## Check tools, versions, architecture, ports and pins (no cluster needed)
	@mkdir -p evidence/raw
	@out="evidence/raw/preflight-$(UTC).txt"; \
	{ \
	  echo "# OK-167 preflight — $$(date -u +%Y-%m-%dT%H:%M:%SZ)"; \
	  echo "host: $$(uname -m) / $$(sw_vers -productName) $$(sw_vers -productVersion)"; \
	  echo ""; \
	  echo "## tools"; \
	  for t in "$(DOCKER)" "$(KIND)" "$(KUBECTL)" "$(HELM)" "$(ORAS)" "$(COSIGN)" \
	           "$(GTAR)" "$(JQ)" "$(YQ)" "$(YAMLLINT)" "$(SHELLCHECK)" "$(OPENSSL)"; do \
	    if command -v "$$t" >/dev/null 2>&1; then \
	      printf '%-12s %s\n' "$$(basename $$t)" "$$(command -v $$t)"; \
	    else \
	      printf '%-12s MISSING\n' "$$(basename $$t)"; \
	    fi; \
	  done; \
	  echo ""; \
	  echo "## docker"; \
	  $(DOCKER) info --format 'cpus={{.NCPU}} memory_bytes={{.MemTotal}} server={{.ServerVersion}}'; \
	  echo ""; \
	  echo "## pins"; \
	  echo "kind_node_image=$(KIND_NODE_IMAGE)"; \
	  echo "zot_chart=$(ZOT_CHART_NAME)-$(ZOT_CHART_VERSION) image=$(ZOT_IMAGE_REPOSITORY):$(ZOT_IMAGE_TAG)"; \
	  echo "argocd_chart=$(ARGOCD_CHART_NAME)-$(ARGOCD_CHART_VERSION) version=$(ARGOCD_VERSION)"; \
	  echo "podinfo_a=$(PODINFO_VERSION_A)@$(PODINFO_DIGEST_A)"; \
	  echo "podinfo_b=$(PODINFO_VERSION_B)@$(PODINFO_DIGEST_B)"; \
	} > "$$out"; \
	echo "wrote $$out"
	@echo "--- assertions ---"
	@command -v $(ORAS)     >/dev/null || { echo "FAIL oras missing";     exit 1; }
	@command -v $(COSIGN)   >/dev/null || { echo "FAIL cosign missing";   exit 1; }
	@command -v $(GTAR)     >/dev/null || { echo "FAIL gtar missing";     exit 1; }
	@command -v $(YAMLLINT) >/dev/null || { echo "FAIL yamllint missing"; exit 1; }
	@command -v $(SHELLCHECK) >/dev/null || { echo "FAIL shellcheck missing"; exit 1; }
	@$(OPENSSL) version | grep -q '^OpenSSL' || { echo "FAIL openssl is not OpenSSL (LibreSSL will not do)"; exit 1; }
	@$(GTAR) --version | head -1 | grep -q 'GNU tar' || { echo "FAIL gtar is not GNU tar"; exit 1; }
	@mem=$$($(DOCKER) info --format '{{.MemTotal}}'); \
	  if [ "$$mem" -lt 4294967296 ]; then echo "FAIL docker memory $$mem bytes < 4 GiB"; exit 1; fi
	@if lsof -nP -iTCP:$(ZOT_NODEPORT) -sTCP:LISTEN >/dev/null 2>&1; then \
	   echo "FAIL port $(ZOT_NODEPORT) already in use"; exit 1; fi
	@echo "preflight OK"

# ---------------------------------------------------------------------------
# Cluster lifecycle
# ---------------------------------------------------------------------------

# `up` is the one target that cannot depend on the guard beforehand: it creates
# the kubeconfig the guard checks. The guard runs immediately afterwards, and
# the target fails if it does not pass.
up: ## Create the local kind cluster (idempotent), then verify isolation
	@mkdir -p .local
	@if $(KIND) get clusters 2>/dev/null | grep -qx '$(CLUSTER_NAME)'; then \
	  echo "cluster '$(CLUSTER_NAME)' already exists — nothing to do"; \
	else \
	  echo "creating kind cluster '$(CLUSTER_NAME)' with $(KIND_NODE_IMAGE)"; \
	  $(KIND) create cluster \
	    --name '$(CLUSTER_NAME)' \
	    --config kind/cluster.yaml \
	    --image '$(KIND_NODE_IMAGE)' \
	    --kubeconfig '$(KUBECONFIG)' \
	    --wait 180s; \
	fi
	@# kind only writes the kubeconfig when it creates the cluster, so an
	@# existing cluster needs it exported explicitly for idempotency.
	@if [ ! -s '$(KUBECONFIG)' ]; then \
	  $(KIND) export kubeconfig --name '$(CLUSTER_NAME)' --kubeconfig '$(KUBECONFIG)'; \
	fi
	@chmod 600 '$(KUBECONFIG)'
	@$(GUARD)
	@$(KUBECTL) wait --for=condition=Ready node --all --timeout=180s
	@echo "cluster '$(CLUSTER_NAME)' ready"

cluster-info: guard ## Print cluster facts (version, node image, storage classes)
	@echo "--- versions ---"
	@$(KUBECTL) version -o json | $(JQ) -r \
	  '"client=\(.clientVersion.gitVersion) server=\(.serverVersion.gitVersion)"'
	@echo "--- nodes ---"
	@$(KUBECTL) get nodes -o wide
	@echo "--- node container image (from the host's docker) ---"
	@$(DOCKER) inspect '$(CLUSTER_NAME)-control-plane' \
	  --format '{{.Config.Image}}{{"\n"}}{{index .Config.Labels "io.x-k8s.kind.role"}}' 2>/dev/null || true
	@echo "--- storage classes ---"
	@$(KUBECTL) get storageclass
	@echo "--- api server ---"
	@$(KUBECTL) config view -o json | $(JQ) -r '.clusters[].cluster.server'

down: ## Delete the kind cluster; .local/ (credentials, PKI) is kept
	@if $(KIND) get clusters 2>/dev/null | grep -qx '$(CLUSTER_NAME)'; then \
	  $(GUARD); \
	  $(KIND) delete cluster --name '$(CLUSTER_NAME)'; \
	  echo "cluster deleted; .local/ kept"; \
	else \
	  echo "cluster '$(CLUSTER_NAME)' does not exist — nothing to do"; \
	fi
	@rm -f '$(KUBECONFIG)'

clean: down ## Alias for `down` (CONTRIBUTING.md standard target)

# ---------------------------------------------------------------------------
# Namespaces, PKI, identities
# ---------------------------------------------------------------------------

ALL_NAMESPACES := $(ZOT_NAMESPACE) $(ARGOCD_NAMESPACE) $(EVENTS_NAMESPACE) \
                  $(NS_DEMO) $(NS_DIGEST) $(NS_SEMVER) $(NS_KUSTOMIZE) \
                  $(NS_HELM) $(NS_NEG) $(NS_IMPORTED)

namespaces: guard ## Create every namespace the spike uses (idempotent)
	@for ns in $(ALL_NAMESPACES); do \
	  $(KUBECTL) create namespace "$$ns" --dry-run=client -o yaml \
	    | $(KUBECTL) apply -f - >/dev/null; \
	done
	@echo "namespaces present: $(ALL_NAMESPACES)"

pki: ## Create the local CA and zot server certificate in .local/pki/ (idempotent)
	@OPENSSL='$(OPENSSL)' scripts/pki.sh

identities: ## Generate machine identity passwords and htpasswd in .local/ (idempotent)
	@OPENSSL='$(OPENSSL)' scripts/identities.sh

# The two Kubernetes secrets zot mounts. Both are built from .local/ and piped
# straight into kubectl: nothing is ever written to a file under version
# control, and no secret value appears in an argument or in the output.
zot-secrets: guard namespaces pki identities ## Create zot's TLS and htpasswd secrets from .local/
	@$(KUBECTL) create secret generic zot-server-tls \
	  --namespace '$(ZOT_NAMESPACE)' \
	  --from-file=tls.crt=.local/pki/tls.crt \
	  --from-file=tls.key=.local/pki/tls.key \
	  --from-file=ca.crt=.local/pki/ca.crt \
	  --dry-run=client -o yaml | $(KUBECTL) apply -f - >/dev/null
	@$(KUBECTL) create secret generic zot-htpasswd \
	  --namespace '$(ZOT_NAMESPACE)' \
	  --from-file=htpasswd=.local/htpasswd \
	  --dry-run=client -o yaml | $(KUBECTL) apply -f - >/dev/null
	@echo "secrets zot-server-tls and zot-htpasswd applied in namespace $(ZOT_NAMESPACE)"

# ---------------------------------------------------------------------------
# Event receiver
# ---------------------------------------------------------------------------
# Deployed before zot so the sink exists when zot starts and begins posting.

events-install: guard namespaces ## Deploy the CloudEvents receiver used by Q3
	@$(KUBECTL) apply -f events/receiver.yaml >/dev/null
	@$(KUBECTL) -n '$(EVENTS_NAMESPACE)' rollout status deployment/event-receiver --timeout=120s
	@echo "event receiver ready at http://event-receiver.$(EVENTS_NAMESPACE).svc.cluster.local:8080/"

events-log: guard ## Tail what the event receiver has logged
	@$(KUBECTL) -n '$(EVENTS_NAMESPACE)' logs deployment/event-receiver --tail=200

# ---------------------------------------------------------------------------
# zot registry
# ---------------------------------------------------------------------------

ZOT_HELM_ARGS := $(ZOT_CHART_NAME) \
  --repo '$(ZOT_CHART_REPO)' \
  --version '$(ZOT_CHART_VERSION)' \
  --namespace '$(ZOT_NAMESPACE)' \
  --values zot/values-poc.yaml

zot-template: ## Render zot's manifests without installing (proof for B6 3.4)
	@$(HELM) template '$(ZOT_RELEASE)' $(ZOT_HELM_ARGS)

zot-install: guard zot-secrets events-install ## Install zot with the pinned chart and image
	@echo "--- checking the rendered image matches the pin ---"
	@rendered=$$($(HELM) template '$(ZOT_RELEASE)' $(ZOT_HELM_ARGS) \
	   | $(YQ) -r 'select(.kind=="StatefulSet") | .spec.template.spec.containers[0].image'); \
	 expected='$(ZOT_IMAGE_REPOSITORY):$(ZOT_IMAGE_TAG)'; \
	 if [ "$$rendered" != "$$expected" ]; then \
	   echo "FAIL rendered image '$$rendered' != pin '$$expected'"; exit 1; \
	 fi; \
	 echo "OK image pinned: $$rendered"
	@echo "--- checking no chart-default htpasswd Secret is rendered ---"
	@if $(HELM) template '$(ZOT_RELEASE)' $(ZOT_HELM_ARGS) \
	   | $(YQ) -r 'select(.kind=="Secret") | .metadata.name' | grep -q .; then \
	   echo "FAIL the chart rendered a Secret; the example htpasswd may be active"; exit 1; \
	 fi
	@echo "OK no Secret rendered by the chart"
	@$(HELM) upgrade --install '$(ZOT_RELEASE)' $(ZOT_HELM_ARGS) --wait --timeout 5m
	@$(KUBECTL) -n '$(ZOT_NAMESPACE)' rollout status statefulset/'$(ZOT_RELEASE)' --timeout=300s
	@echo "zot ready at https://$(ZOT_HOST) (host) and https://$(ZOT_SERVICE_HOST):$(ZOT_SERVICE_PORT) (in cluster)"

zot-logs: guard ## Tail zot's logs
	@$(KUBECTL) -n '$(ZOT_NAMESPACE)' logs statefulset/'$(ZOT_RELEASE)' --tail=200

# ---------------------------------------------------------------------------
# Argo CD
# ---------------------------------------------------------------------------

ARGOCD_HELM_ARGS := $(ARGOCD_CHART_NAME) \
  --repo '$(ARGOCD_CHART_REPO)' \
  --version '$(ARGOCD_CHART_VERSION)' \
  --namespace '$(ARGOCD_NAMESPACE)' \
  --values argocd/values-poc.yaml

# The CA is injected from .local/ at install time, never copied into the values
# file. Dots in the key are escaped because Helm treats them as path separators.
ARGOCD_CA_ARG := --set-file 'configs.tls.certificates.zot\.zot\.svc\.cluster\.local=.local/pki/ca.crt'

argocd-install: guard namespaces pki ## Install Argo CD v3.5.6 and trust the zot CA
	@echo "--- checking every rendered image is pinned by digest ---"
	@$(HELM) template '$(ARGOCD_RELEASE)' $(ARGOCD_HELM_ARGS) \
	  | $(YQ) -r 'select(.kind=="Deployment" or .kind=="StatefulSet") | .spec.template.spec.containers[].image' \
	  | sort -u | while read -r img; do \
	      case "$$img" in \
	        ---) : ;; \
	        *@sha256:*) echo "  OK   $$img" ;; \
	        *) echo "  FAIL unpinned image: $$img"; exit 1 ;; \
	      esac; \
	    done
	@$(HELM) upgrade --install '$(ARGOCD_RELEASE)' $(ARGOCD_HELM_ARGS) $(ARGOCD_CA_ARG) --wait --timeout 8m
	@$(KUBECTL) -n '$(ARGOCD_NAMESPACE)' rollout status statefulset/argocd-application-controller --timeout=300s
	@$(KUBECTL) -n '$(ARGOCD_NAMESPACE)' rollout status deployment/argocd-repo-server --timeout=300s
	@echo "Argo CD $(ARGOCD_VERSION) ready in namespace $(ARGOCD_NAMESPACE)"

# REPO is the last path segment, e.g. podinfo-manifests.
argocd-repo: guard ## Create a repository Secret for one repo (REPO=podinfo-manifests)
	@test -n '$(REPO)' || { echo "REPO= is required, e.g. make argocd-repo REPO=podinfo-manifests"; exit 2; }
	@scripts/repository-secret.sh repository '$(REPO)' | $(KUBECTL) apply -f - >/dev/null
	@echo "repository Secret applied from local credential input"

argocd-repo-creds: guard ## Create the OCI prefix credential template
	@scripts/repository-secret.sh repo-creds | $(KUBECTL) apply -f - >/dev/null

argocd-project: guard namespaces ## Create the ok167 AppProject
	@$(KUBECTL) apply -f argocd/appproject.yaml >/dev/null
	@echo "AppProject ok167 applied"

# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------

app-tag: guard argocd-project ## Create/update the tag-based Application (D2)
	@$(KUBECTL) apply -f argocd/application-tag.yaml >/dev/null
	@echo "Application ok167-podinfo-tag applied"

app-digest: guard argocd-project ## Create/update the digest-pinned Application (DIGEST=sha256:...)
	@test -n '$(DIGEST)' || { echo "DIGEST= is required, e.g. make app-digest DIGEST=sha256:..."; exit 2; }
	@sed 's|DIGEST_PLACEHOLDER|$(DIGEST)|' argocd/application-digest.yaml \
	  | $(KUBECTL) apply -f - >/dev/null
	@echo "Application ok167-podinfo-digest pinned to $(DIGEST)"

app-semver: guard argocd-project ## Create/update the SemVer-range Application
	@$(KUBECTL) apply -f argocd/application-semver.yaml >/dev/null
	@echo "Application ok167-podinfo-semver applied"

app-kustomize: guard argocd-project ## Create/update the Kustomize Application
	@$(KUBECTL) apply -f argocd/application-kustomize.yaml >/dev/null
	@echo "Application ok167-podinfo-kustomize applied"

app-helm: guard argocd-project ## Create/update the Helm-chart Application
	@$(KUBECTL) apply -f argocd/application-helm.yaml >/dev/null
	@echo "Application ok167-podinfo-helm applied"

app-set-revision: guard ## Change an Application's targetRevision (APP=... REV=...)
	@test -n '$(APP)' || { echo "APP= is required"; exit 2; }
	@test -n '$(REV)' || { echo "REV= is required"; exit 2; }
	@$(KUBECTL) -n '$(ARGOCD_NAMESPACE)' patch application '$(APP)' --type=merge \
	  -p '{"spec":{"source":{"targetRevision":"$(REV)"}}}' >/dev/null
	@echo "$(APP) targetRevision -> $(REV)"

refresh: guard ## Request an immediate refresh (APP=ok167-podinfo-tag [HARD=1])
	@test -n '$(APP)' || { echo "APP= is required"; exit 2; }
	@$(KUBECTL) -n '$(ARGOCD_NAMESPACE)' annotate application '$(APP)' \
	  argocd.argoproj.io/refresh=$(if $(HARD),hard,normal) --overwrite >/dev/null
	@echo "refresh=$(if $(HARD),hard,normal) requested for $(APP)"

app-status: guard ## Show sync status, revision and resource count (APP=...)
	@test -n '$(APP)' || { echo "APP= is required"; exit 2; }
	@$(KUBECTL) -n '$(ARGOCD_NAMESPACE)' get application '$(APP)' -o json | $(JQ) -r \
	  '{name:.metadata.name, sync:.status.sync.status, health:.status.health.status, \
	    revision:.status.sync.revision, \
	    resources:[(.status.resources // [])[] | "\(.kind)/\(.name)"], \
	    resource_count:((.status.resources // []) | length), \
	    conditions:[(.status.conditions // [])[] | {type,message}]}'

app-wait: guard ## Block until an Application is Synced and Healthy (APP=... [TIMEOUT=300])
	@test -n '$(APP)' || { echo "APP= is required"; exit 2; }
	@scripts/wait-application.sh '$(APP)' '$(DIGEST)' '$(or $(TIMEOUT),300)'

measure: guard ## Measure sync latency (APP=... DIGEST=... [IMAGE=...] [T0=...] [LABEL=...])
	@KUBECTL='$(KUBECTL)' JQ='$(JQ)' scripts/measure-sync.sh \
	  --app '$(APP)' --digest '$(DIGEST)' \
	  $(if $(IMAGE),--image '$(IMAGE)') $(if $(T0),--t0 '$(T0)') \
	  $(if $(LABEL),--label '$(LABEL)') $(if $(MTIMEOUT),--timeout '$(MTIMEOUT)')

drift: guard ## Scale the deployment by hand to test self-heal (NS=ok167-demo)
	@test -n '$(NS)' || { echo "NS= is required"; exit 2; }
	@$(KUBECTL) -n '$(NS)' scale deployment podinfo --replicas=5
	@echo "scaled podinfo in $(NS) to 5 — Argo CD should revert this"

probe-version: guard ## Curl podinfo's /version from inside the cluster (NS=ok167-demo)
	@test -n '$(NS)' || { echo "NS= is required"; exit 2; }
	@$(KUBECTL) -n '$(NS)' run ok167-probe-$$$$ \
	  --image='$(CURL_IMAGE)' --restart=Never --rm -i --quiet \
	  --command -- curl -sS --max-time 10 http://podinfo:9898/version

# ---------------------------------------------------------------------------
# Packaging pipeline (D1)
# ---------------------------------------------------------------------------
# VARIANT selects the manifest directory; TAG is the tag to push.
#   make push VARIANT=plain        TAG=v1.0.0
#   make push VARIANT=plain-update TAG=v1.0.0
#   make push VARIANT=kustomize    TAG=v1.0.0
VARIANT ?= plain
TAG     ?= v1.0.0

variant_source = $(strip \
  $(if $(filter plain,$(1)),app/podinfo-plain,\
  $(if $(filter plain-update,$(1)),app/podinfo-plain-update,\
  $(if $(filter kustomize,$(1)),app/podinfo-kustomize,))))

variant_repo = $(strip \
  $(if $(filter kustomize,$(1)),$(REPO_KUSTOMIZE),$(REPO_MANIFESTS)))

push: ## Package and push a manifest variant (VARIANT=plain|plain-update|kustomize TAG=...)
	@src='$(call variant_source,$(VARIANT))'; \
	 if [ -z "$$src" ]; then \
	   echo "unknown VARIANT '$(VARIANT)'; expected plain, plain-update or kustomize"; exit 2; \
	 fi; \
	 ORAS='$(ORAS)' GTAR='$(GTAR)' YAMLLINT='$(YAMLLINT)' KUBECTL='$(KUBECTL)' JQ='$(JQ)' \
	   scripts/package-and-push.sh \
	     --source "$$src" \
	     --repository '$(call variant_repo,$(VARIANT))' \
	     --tag '$(TAG)'

push-dry: ## Package a variant and report the layer digest without pushing
	@src='$(call variant_source,$(VARIANT))'; \
	 ORAS='$(ORAS)' GTAR='$(GTAR)' YAMLLINT='$(YAMLLINT)' KUBECTL='$(KUBECTL)' JQ='$(JQ)' \
	   scripts/package-and-push.sh --source "$$src" \
	     --repository '$(call variant_repo,$(VARIANT))' --tag '$(TAG)' --dry-run

determinism: ## P4-DET: package the same input three times and compare digests
	@echo "--- layer digest, three runs ---"; \
	 first=""; ok=1; \
	 for i in 1 2 3; do \
	   d=$$(ORAS='$(ORAS)' GTAR='$(GTAR)' YAMLLINT='$(YAMLLINT)' KUBECTL='$(KUBECTL)' JQ='$(JQ)' \
	        scripts/package-and-push.sh --source '$(call variant_source,$(VARIANT))' \
	          --repository '$(call variant_repo,$(VARIANT))' --tag '$(TAG)' --dry-run 2>/dev/null \
	        | grep '^LAYER_DIGEST=' | cut -d= -f2); \
	   echo "  run $$i: $$d"; \
	   if [ -z "$$first" ]; then first="$$d"; elif [ "$$d" != "$$first" ]; then ok=0; fi; \
	 done; \
	 if [ "$$ok" = "1" ]; then echo "PASS identical across runs"; else echo "FAIL digests differ"; exit 1; fi

zot-down: guard ## Scale zot to 0 replicas (registry outage test T8)
	@$(KUBECTL) -n '$(ZOT_NAMESPACE)' scale statefulset '$(ZOT_RELEASE)' --replicas=0
	@$(KUBECTL) -n '$(ZOT_NAMESPACE)' wait --for=delete pod -l app.kubernetes.io/name=zot --timeout=120s 2>/dev/null || true
	@echo "zot scaled to 0"

zot-up: guard ## Scale zot back to 1 replica
	@$(KUBECTL) -n '$(ZOT_NAMESPACE)' scale statefulset '$(ZOT_RELEASE)' --replicas=1
	@$(KUBECTL) -n '$(ZOT_NAMESPACE)' rollout status statefulset/'$(ZOT_RELEASE)' --timeout=300s
	@echo "zot restored"

.PHONY: zot-status
zot-status: guard ## Read zot pod readiness with the spike kubeconfig
	@$(KUBECTL) -n '$(ZOT_NAMESPACE)' get pods -o wide

repo-server-restart: guard ## Rollout-restart the Argo CD repo-server (T8, Q3.a)
	@$(KUBECTL) -n '$(ARGOCD_NAMESPACE)' rollout restart deployment/argocd-repo-server >/dev/null
	@$(KUBECTL) -n '$(ARGOCD_NAMESPACE)' rollout status deployment/argocd-repo-server --timeout=180s

zot-verify: guard ## Run the V1-V8 registry checks (TLS, auth, authz, referrers)
	@KUBECTL='$(KUBECTL)' ORAS='$(ORAS)' scripts/zot-verify.sh

# ---------------------------------------------------------------------------
# Static analysis
# ---------------------------------------------------------------------------

lint: shellcheck-scripts yamllint-manifests ## Run shellcheck and yamllint over the spike

shellcheck-scripts: ## shellcheck every script
	@set -e; \
	files=$$(find scripts ci -name '*.sh' -type f 2>/dev/null || true); \
	if [ -z "$$files" ]; then echo "no shell scripts yet"; else \
	  echo "$$files" | xargs $(SHELLCHECK) -x -P SCRIPTDIR --severity=style --color=auto \
	    && echo "shellcheck clean"; \
	fi

yamllint-manifests: ## yamllint every YAML file the spike owns
	@set -e; \
	files=$$(git ls-files -- '*.yaml' '*.yml' 2>/dev/null; \
	         git ls-files --others --exclude-standard -- '*.yaml' '*.yml' 2>/dev/null); \
	files=$$(printf '%s\n' $$files | sort -u | grep -v '^evidence/raw/' || true); \
	if [ -z "$$files" ]; then echo "no YAML files yet"; else \
	  printf '%s\n' $$files | xargs $(YAMLLINT) -c .yamllint.yaml && echo "yamllint clean"; \
	fi

scan-secrets: ## Check tracked and staged files for credentials
	@scripts/scan-secrets.sh

# ---------------------------------------------------------------------------
# Overall verification
# ---------------------------------------------------------------------------
# Checks every pass criterion that can be re-checked without pushing anything
# new. Deliberately read-only: it must be safe to run at any time, and it must
# not be able to manufacture the evidence it is checking.

verify: guard ## Check current runtime state and provenance; timing is assessed separately
	@fail=0; \
	 chk() { if [ "$$2" = "$$3" ]; then printf '  PASS %s (%s)\n' "$$1" "$$2"; \
	         else printf '  FAIL %s: got "%s", expected "%s"\n' "$$1" "$$2" "$$3"; fail=1; fi; }; \
	 echo "--- cluster ---"; \
	 chk "node Ready" \
	   "$$($(KUBECTL) get nodes -o jsonpath='{.items[0].status.conditions[?(@.type=="Ready")].status}')" "True"; \
	 chk "kubernetes version" \
	   "$$($(KUBECTL) version -o json | $(JQ) -r .serverVersion.gitVersion)" "$(KUBERNETES_VERSION)"; \
	 echo "--- zot ---"; \
	 chk "zot image pin" \
	   "$$($(KUBECTL) -n $(ZOT_NAMESPACE) get statefulset $(ZOT_RELEASE) -o jsonpath='{.spec.template.spec.containers[0].image}')" \
	   "$(ZOT_IMAGE_REPOSITORY):$(ZOT_IMAGE_TAG)"; \
	 chk "anonymous /v2/ refused" \
	   "$$(curl -s -o /dev/null -w '%{http_code}' --cacert .local/pki/ca.crt https://$(ZOT_HOST)/v2/)" "401"; \
	 chk "health endpoint open" \
	   "$$(curl -s -o /dev/null -w '%{http_code}' --cacert .local/pki/ca.crt https://$(ZOT_HOST)/readyz)" "200"; \
	 echo "--- argo cd ---"; \
	 chk "Argo CD API TLS enabled" \
	   "$$($(KUBECTL) -n $(ARGOCD_NAMESPACE) get cm argocd-cmd-params-cm -o jsonpath='{.data.server\.insecure}')" "false"; \
	 chk "argocd image pin" \
	   "$$($(KUBECTL) -n $(ARGOCD_NAMESPACE) get statefulset argocd-application-controller -o jsonpath='{.spec.template.spec.containers[0].image}')" \
	   "$(ARGOCD_IMAGE_REPOSITORY):$(ARGOCD_IMAGE_TAG)"; \
	 chk "zot CA trusted" \
	   "$$($(KUBECTL) -n $(ARGOCD_NAMESPACE) get cm argocd-tls-certs-cm -o json | $(JQ) -r '(.data // {}) | has("$(ZOT_SERVICE_HOST)")')" "true"; \
	 chk "repo secret uses the read-only identity" \
	   "$$($(KUBECTL) -n $(ARGOCD_NAMESPACE) get secret ok167-zot-podinfo-manifests -o jsonpath='{.data.username}' | base64 -d)" \
	   "$(IDENTITY_PULLER)"; \
	 chk "AppProject forbids cluster-scoped resources" \
	   "$$($(KUBECTL) -n $(ARGOCD_NAMESPACE) get appproject $(ARGOCD_PROJECT) -o json | $(JQ) -r '.spec.clusterResourceWhitelist | length')" "0"; \
	 echo "--- applications ---"; \
	 for app in ok167-podinfo-tag ok167-podinfo-digest ok167-podinfo-kustomize; do \
	   chk "$$app synced" \
	     "$$($(KUBECTL) -n $(ARGOCD_NAMESPACE) get application $$app -o jsonpath='{.status.sync.status}/{.status.health.status}' 2>/dev/null)" \
	     "Synced/Healthy"; \
	   chk "$$app resource count" \
	     "$$($(KUBECTL) -n $(ARGOCD_NAMESPACE) get application $$app -o json 2>/dev/null | $(JQ) -r '(.status.resources // []) | length')" "2"; \
	 done; \
	 echo "--- provenance (M3) ---"; \
	 if scripts/verify-provenance.sh; then :; else fail=1; fi; \
	 echo; \
	 if [ "$$fail" = "0" ]; then echo "verify: all checks passed"; else echo "verify: FAILURES above"; exit 1; fi

# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------

debug: guard ## Collect a redacted diagnostic snapshot under evidence/raw/
	@dir="evidence/raw/debug-$(UTC)"; mkdir -p "$$dir"; \
	$(KUBECTL) get nodes -o wide                  > "$$dir/nodes.txt"      2>&1 || true; \
	$(KUBECTL) get pods -A -o wide                > "$$dir/pods.txt"       2>&1 || true; \
	$(KUBECTL) get events -A --sort-by=.lastTimestamp > "$$dir/events.txt" 2>&1 || true; \
	$(KUBECTL) get application -n $(ARGOCD_NAMESPACE) -o yaml > "$$dir/applications.yaml" 2>&1 || true; \
	echo "wrote $$dir (secrets are never collected)"

# ---------------------------------------------------------------------------
# Standard targets that do not apply here
# ---------------------------------------------------------------------------
# CONTRIBUTING.md expects every component to carry these. Printing why they do
# not apply is more useful than a target that silently does nothing.

diff: ## Not applicable for this spike — explains why
	@echo "not applicable for this spike."
	@echo "  'diff' compares desired Git state against a cluster. Here the"
	@echo "  desired state is delivered through OCI artifacts in zot and"
	@echo "  reconciled by Argo CD, so the authoritative comparison is Argo CD's"
	@echo "  own sync status. Use:  make guard && $(KUBECTL) get application -n $(ARGOCD_NAMESPACE)"

upgrade: ## Not applicable for this spike — explains why
	@echo "not applicable for this spike."
	@echo "  Every version is pinned in versions.env and the spike is torn down"
	@echo "  with 'make down' rather than upgraded in place. Changing a pin means"
	@echo "  editing versions.env and re-running 'make install' on a fresh cluster,"
	@echo "  which is what makes the evidence reproducible."

clean-local: ## Remove generated Helm/chart caches from .local/ (keeps credentials and PKI)
	@rm -rf .local/helm .local/charts
	@echo "removed .local/helm and .local/charts; credentials, PKI and kubeconfig untouched"

.PHONY: test-review
# This target does not contact a cluster or registry.
test-review: ## Run adversarial review regressions in an isolated Git fixture
	@scripts/test-review-regressions.sh

.PHONY: install argocd-without-ca exp-q1c exp-q1d exp-structure sign verify-signature offline-transfer app-negative app-imported reconcile reconcile-reset
install: ## Create and install the isolated spike in dependency order
	@$(MAKE) up
	@$(MAKE) namespaces pki identities events-install zot-install argocd-install argocd-repo REPO=podinfo-manifests argocd-repo-creds argocd-project

argocd-without-ca: guard ## Q1.d only: temporarily remove zot CA trust
	@$(HELM) upgrade --install '$(ARGOCD_RELEASE)' $(ARGOCD_HELM_ARGS) --wait --timeout 8m

exp-q1c: guard ## Reject an incorrect password and verify restoration
	@scripts/experiments.sh q1c

exp-q1d: guard ## Remove CA trust, observe x509 failure, then restore trust
	@scripts/experiments.sh q1d

exp-structure: guard ## Reproduce two-content-layer and non-archive rejection
	@scripts/experiments.sh structure

sign: guard ## Sign a digest without public services (DIGEST=... MODE=bundle|legacy)
	@scripts/signing.sh sign

verify-signature: guard ## Verify a digest signature offline (DIGEST=...)
	@scripts/signing.sh verify

offline-transfer: guard ## Export/import artifact and referrers, verify and synchronize (DIGEST=...)
	@scripts/experiments.sh offline

app-negative: guard ## Apply an isolated negative artifact case (CASE_ID=...)
	@test -n '$(CASE_ID)'
	@sed 's|CASE_PLACEHOLDER|$(CASE_ID)|g' argocd/application-negative.yaml | $(KUBECTL) apply -f - >/dev/null

app-imported: guard ## Apply the imported artifact by digest (DIGEST=...)
	@test -n '$(DIGEST)'
	@sed 's|DIGEST_PLACEHOLDER|$(DIGEST)|g' argocd/application-imported.yaml | $(KUBECTL) apply -f - >/dev/null

reconcile: guard ## Set reconciliation interval and jitter (REC=... JITTER=...)
	@test -n '$(REC)' -a -n '$(JITTER)'
	@$(HELM) upgrade --install '$(ARGOCD_RELEASE)' $(ARGOCD_HELM_ARGS) $(ARGOCD_CA_ARG) --set-string 'configs.cm.timeout\.reconciliation=$(REC)' --set-string 'configs.cm.timeout\.reconciliation\.jitter=$(JITTER)' --wait --timeout 8m
	@$(KUBECTL) -n argocd rollout restart statefulset/argocd-application-controller deployment/argocd-repo-server >/dev/null
	@$(KUBECTL) -n argocd rollout status statefulset/argocd-application-controller --timeout=300s
	@$(KUBECTL) -n argocd rollout status deployment/argocd-repo-server --timeout=300s

reconcile-reset: guard ## Restore the default 120s reconciliation and 60s jitter
	@$(MAKE) reconcile REC=120s JITTER=60s

.PHONY: probe-argocd-tls exp-webhook
probe-argocd-tls: guard ## Verify API TLS and reject an untrusted certificate
	@scripts/probe-argocd-tls.sh

exp-webhook: guard ## Replay the zot CloudEvent to the TLS-protected Argo CD API
	@scripts/probe-argocd-tls.sh webhook

.PHONY: app-exact exp-latency exp-signing exp-recovery
app-exact: guard ## Apply the retained exact-tag Application for T3
	@$(KUBECTL) create namespace ok167-exact --dry-run=client -o yaml | $(KUBECTL) apply -f - >/dev/null
	@$(KUBECTL) apply -f argocd/application-exact.yaml >/dev/null

exp-latency: guard ## Repeat T1/T2 three times and observe T3/T4 for at least 360 seconds
	@scripts/experiments.sh latency

exp-signing: guard ## Verify signing and prove that an unsigned digest still synchronizes
	@scripts/experiments.sh signing

exp-recovery: guard ## Observe cache-cold registry outage and unattended recovery
	@scripts/experiments.sh recovery

.PHONY: verify-artifact exp-q1b exp-self-heal
verify-artifact: guard ## Compare a fetched artifact with its annotated Git tree
	@scripts/verify-provenance.sh

exp-q1b: guard ## Test prefix credentials without an exact Kustomize repository Secret
	@scripts/experiments.sh q1b

exp-self-heal: guard ## Measure restoration of the Kustomize replica count
	@scripts/experiments.sh self-heal
