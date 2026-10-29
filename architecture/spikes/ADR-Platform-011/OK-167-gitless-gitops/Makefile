# OK-167 — gitless GitOps with Argo CD and zot.
#
# The only entry point for this spike. Nothing here is run by hand: every
# command that reads or changes a cluster goes through a target, and every such
# target depends on `guard` first (BRIEF B4 rule 1, B8).
#
# Targets are added phase by phase. Cluster, registry and Argo CD targets arrive
# with their phases; this file currently covers the Phase 1 scaffold.

.DEFAULT_GOAL := help
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
# Every external tool resolves through its own variable, so any one of them can
# be swapped for a pinned container wrapper without touching a single target.
# Override on the command line, e.g.  make lint YAMLLINT='docker run --rm ...'
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
        up down clean cluster-info

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
	  $(KIND) delete cluster --name '$(CLUSTER_NAME)'; \
	  echo "cluster deleted; .local/ kept"; \
	else \
	  echo "cluster '$(CLUSTER_NAME)' does not exist — nothing to do"; \
	fi
	@rm -f '$(KUBECONFIG)'

clean: down ## Alias for `down` (CONTRIBUTING.md standard target)

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
