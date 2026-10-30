# OK-211 — Knative as an optional serverless and event capability.
#
# The only entry point for this spike (BRIEF B0 rule 4, B8). Every command that
# changes the VM or the cluster goes through a target here, and every target
# that reads or changes the cluster depends on `guard` first. Targets that call
# multipass, ssh or scp go through scripts/lib.sh (ok211::vm_*), which refuses
# any instance other than ok-knative-local.
#
# Always run as: make -C architecture/spikes/OK-211-knative-serverless <target>

.DEFAULT_GOAL := help
.NOTPARALLEL:
SHELL := /usr/bin/env bash
.SHELLFLAGS := -euo pipefail -c

# The help target must read this file, not versions.env: `include` appends to
# MAKEFILE_LIST (OK-167 hurdle C6), so the name is captured before it.
SELF := $(lastword $(MAKEFILE_LIST))

# ---------------------------------------------------------------------------
# Version pins — maintained in versions.env only (B6)
# ---------------------------------------------------------------------------
include versions.env
export

# ---------------------------------------------------------------------------
# Isolation (B4 rules 2, 3, 7). The guard verifies all of this regardless;
# these exports are a seatbelt, not the check.
# ---------------------------------------------------------------------------
export KUBECONFIG    := $(CURDIR)/.local/kubeconfig
export KUBECACHEDIR  := $(CURDIR)/.local/kube-cache
export PATH          := $(CURDIR)/.local/bin:$(PATH)
export KUBECTL       := $(CURDIR)/.local/bin/kubectl

export HELM_CONFIG_HOME     := $(CURDIR)/.local/helm/config
export HELM_CACHE_HOME      := $(CURDIR)/.local/helm/cache
export HELM_DATA_HOME       := $(CURDIR)/.local/helm/data
export HELM_REGISTRY_CONFIG := $(CURDIR)/.local/helm/config/registry/config.json
export TUF_ROOT             := $(CURDIR)/.local/sigstore
export PUPPETEER_CACHE_DIR  := $(CURDIR)/.local/puppeteer
# oras: digest lookups only; keeps its cache and (empty) auth config local.
export ORAS_CACHE           := $(CURDIR)/.local/oras-cache
export DOCKER_CONFIG        := $(CURDIR)/.local/docker-config

GUARD      := scripts/guard.sh
GUARD_NODE := scripts/guard.sh --node
UTC         = $(shell date -u +%Y%m%dT%H%M%SZ)

SHELLCHECK ?= shellcheck
YAMLLINT   ?= yamllint
KUBECONFORM ?= kubeconform

.PHONY: help guard guard-node preflight kubectl-pin manifests-fetch \
        lint lint-shell lint-yaml lint-kubeconform test-guard scan-secrets scan-history debug \
        vm-up vm-info vm-stop vm-start vm-snapshot vm-restore vm-delete k3s-install kubeconfig \
        tunnel tunnel-status tunnel-stop baseline down clean \
        knative-install knative-verify knative-post-install probe-up probe apps-serving smoke install vm-ssh

# ---------------------------------------------------------------------------
help: ## Show this help
	@grep -E '^[a-zA-Z0-9_-]+:.*## .*$$' $(SELF) \
		| awk 'BEGIN {FS = ":.*## "}; {printf "\033[36m%-24s\033[0m %s\n", $$1, $$2}'

guard: ## Static guard: kubeconfig, context ok211, server 127.0.0.1:6450, pinned kubectl
	@$(GUARD)

guard-node: ## Full guard including the node check (from Phase 2 on)
	@$(GUARD_NODE)

# ---------------------------------------------------------------------------
# Phase 0/1 — preflight, pins, tooling
# ---------------------------------------------------------------------------
preflight: ## Read-only host, tool, Multipass and pin check; raw output to evidence/raw/
	@scripts/preflight.sh

kubectl-pin: ## Download the pinned kubectl into .local/bin/ and verify SHA-256
	@scripts/kubectl-pin.sh

manifests-fetch: ## Download release manifests for VERSION=1.23|1.24|cert-manager and verify checksums
	@test -n "$(VERSION)" || { echo "usage: make manifests-fetch VERSION=1.23|1.24|cert-manager"; exit 2; }
	@scripts/fetch-manifests.sh "$(VERSION)" > ".local/manifests-$(VERSION).tsv"
	@column -t -s "$$(printf '\t')" ".local/manifests-$(VERSION).tsv"

# ---------------------------------------------------------------------------
# Phase 2 — VM in the ok-local profile, K3s, kubeconfig, tunnel
# ---------------------------------------------------------------------------
# All of these go through scripts/lib.sh, which refuses any VM_NAME other than
# ok-knative-local before multipass, ssh or scp run.
vm-up: ## Render cloud-init into .local/ and launch ok-knative-local (idempotent)
	@scripts/vm.sh up

vm-info: ## multipass info for ok-knative-local only
	@scripts/vm.sh info

vm-stop: ## Stop ok-knative-local
	@scripts/vm.sh stop

vm-start: ## Start ok-knative-local
	@scripts/vm.sh start

vm-snapshot: ## Snapshot the stopped VM: NAME=<snapshot>
	@test -n "$(NAME)" || { echo "usage: make vm-snapshot NAME=<name>"; exit 2; }
	@scripts/vm.sh snapshot "$(NAME)"

vm-restore: ## Restore the stopped VM to a snapshot: NAME=<snapshot>
	@test -n "$(NAME)" || { echo "usage: make vm-restore NAME=<name>"; exit 2; }
	@scripts/vm.sh restore "$(NAME)"

vm-delete: ## Delete ok-knative-local and its local SSH/kubeconfig state (CONFIRM=yes)
	@CONFIRM="$(CONFIRM)" scripts/vm.sh delete

k3s-install: ## Install K3s (pinned, versioned install script) in the VM and wait for Ready
	@scripts/k3s-install.sh

kubeconfig: ## Fetch the K3s kubeconfig into .local/kubeconfig (context ok211, server 127.0.0.1:6450)
	@scripts/kubeconfig.sh

tunnel: ## Start the SSH tunnel 127.0.0.1:6450 -> VM:6443 (control socket .local/tun.sock)
	@scripts/tunnel.sh start

tunnel-status: ## Show whether the tunnel is running
	@scripts/tunnel.sh status

tunnel-stop: ## Stop the tunnel through its control socket (never pkill)
	@scripts/tunnel.sh stop

baseline: ## Resource snapshot of the empty cluster: 3 samples, 60 s apart
	@$(GUARD_NODE)
	@scripts/snapshot-resources.sh baseline 3 60

# ---------------------------------------------------------------------------
# Phase 3 — Knative install and verification
# ---------------------------------------------------------------------------
# Own manifests are rendered from versions.env and applied server-side with the
# field manager ok211, separate from the release manager knative-release.
APPLY_OWN = scripts/render.sh $(1) | $(KUBECTL) apply --server-side --field-manager=ok211 -f -

knative-install: ## Install Knative VERSION=1.23|1.24 (serving, kourier, eventing, imc, mt-broker) with overrides
	@test -n "$(VERSION)" || { echo "usage: make knative-install VERSION=1.23|1.24"; exit 2; }
	@$(GUARD_NODE)
	@scripts/knative.sh install "$(VERSION)"

knative-verify: ## Check deployments, webhooks, overrides and the gateway digest
	@$(GUARD_NODE)
	@scripts/knative.sh verify

knative-post-install: ## Run the post-install Jobs for VERSION (create, never apply; skip if Complete)
	@test -n "$(VERSION)" || { echo "usage: make knative-post-install VERSION=1.23|1.24"; exit 2; }
	@$(GUARD_NODE)
	@scripts/knative.sh post-install "$(VERSION)"

probe-up: ## Create the probe pod ok211-probe in ok211-load
	@$(GUARD_NODE)
	@$(call APPLY_OWN,load/probe.yaml)
	@$(KUBECTL) -n ok211-load wait --for=condition=Ready pod/ok211-probe --timeout=180s

probe: ## Run CMD='...' inside the probe pod (sh -c)
	@test -n "$$CMD" || { echo "usage: make probe CMD='curl ...'"; exit 2; }
	@$(GUARD_NODE)
	@$(KUBECTL) -n ok211-load exec ok211-probe -- sh -c "$$CMD"

apps-serving: ## Create the serving namespace and the base podinfo Knative Service
	@$(GUARD_NODE)
	@$(call APPLY_OWN,apps/serving/namespace.yaml apps/serving/podinfo.yaml)
	@$(KUBECTL) -n ok211-serving wait --for=condition=Ready ksvc/podinfo --timeout=180s

smoke: ## Smoke test: podinfo through Kourier with Host header, expects 200 and version 6.16.0
	@$(GUARD_NODE)
	@$(KUBECTL) -n ok211-load exec ok211-probe -- curl -sS --max-time 30 \
	  -H "Host: podinfo.ok211-serving.$(KNATIVE_DOMAIN)" \
	  -w '\nhttp_code=%{http_code} time_total=%{time_total}\n' http://kourier.kourier-system.svc.cluster.local/

install: ## From zero: preflight kubectl-pin vm-up k3s-install kubeconfig tunnel baseline manifests knative 1.23 verify
	@$(MAKE) --no-print-directory preflight || true
	@$(MAKE) --no-print-directory kubectl-pin vm-up k3s-install kubeconfig tunnel baseline
	@$(MAKE) --no-print-directory manifests-fetch VERSION=1.23
	@$(MAKE) --no-print-directory manifests-fetch VERSION=1.24
	@$(MAKE) --no-print-directory knative-install VERSION=1.23
	@$(MAKE) --no-print-directory knative-verify

down: tunnel-stop vm-stop ## Stop the tunnel and the VM (the VM is kept)

clean: ## Delete the VM (requires CONFIRM=yes)
	@$(MAKE) --no-print-directory vm-delete CONFIRM="$(CONFIRM)"

# ---------------------------------------------------------------------------
# Quality gates (no cluster)
# ---------------------------------------------------------------------------
lint: lint-shell lint-yaml lint-kubeconform ## shellcheck, yamllint, kubeconform (if installed)

lint-shell: ## shellcheck every script
	@$(SHELLCHECK) -x -P SCRIPTDIR --severity=style scripts/*.sh && echo "shellcheck clean ($$(ls scripts/*.sh | wc -l | tr -d ' ') files)"

lint-yaml: ## yamllint every YAML file the spike owns
	@files=$$(find . -path ./.local -prune -o \( -name '*.yaml' -o -name '*.yml' \) -type f -print | sort); \
	if [ -z "$$files" ]; then echo "no YAML files yet"; else \
	  $(YAMLLINT) -c .yamllint.yaml $$files && echo "yamllint clean ($$(echo "$$files" | wc -l | tr -d ' ') files)"; fi

lint-kubeconform: ## Schema-check Kubernetes manifests with kubeconform if it is installed
	@if command -v $(KUBECONFORM) >/dev/null 2>&1; then \
	  files=$$(find knative apps load ingress tls security gitops -name '*.yaml' -type f 2>/dev/null | grep -v '^knative/patch-' | sort); \
	  if [ -z "$$files" ]; then echo "kubeconform: no manifests yet"; else \
	    $(KUBECONFORM) -strict -ignore-missing-schemas -summary $$files; fi; \
	else echo "kubeconform not installed (optional, reported at CP1) — skipped"; fi

test-guard: ## Run the guard negative tests against synthetic kubeconfigs in .local/test/
	@scripts/test-guard.sh

scan-secrets: ## Check tracked, staged and untracked spike files for credentials
	@scripts/scan-secrets.sh

scan-history: ## Secret scan including every added line on the branch (B15)
	@scripts/scan-secrets.sh --history origin/main..HEAD

# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------
debug: ## Diagnostic snapshot to .local/debug/<timestamp>/ (never Secrets)
	@$(GUARD_NODE)
	@dir=".local/debug/$(UTC)"; mkdir -p "$$dir"; \
	$(KUBECTL) get nodes -o wide                      > "$$dir/nodes.txt"   2>&1 || true; \
	$(KUBECTL) get pods -A -o wide                    > "$$dir/pods.txt"    2>&1 || true; \
	$(KUBECTL) get events -A --sort-by=.lastTimestamp > "$$dir/events.txt"  2>&1 || true; \
	$(KUBECTL) get ksvc,revision,route,podautoscaler,sks -A -o wide > "$$dir/knative.txt" 2>&1 || true; \
	$(KUBECTL) get broker,trigger,channel,subscription -A -o wide   > "$$dir/eventing.txt" 2>&1 || true; \
	$(KUBECTL) top pods -A                            > "$$dir/top.txt"     2>&1 || true; \
	echo "wrote $$dir (Secrets are never collected; copy redacted excerpts to evidence/raw/ by hand)"

# ---------------------------------------------------------------------------
# Read-only inspection inside the VM (B4 rule 5: only through ok211::vm_ssh)
# ---------------------------------------------------------------------------
vm-ssh: ## Run CMD='...' in ok-knative-local through ok211::vm_ssh
	@test -n "$$CMD" || { echo "usage: make vm-ssh CMD='...'"; exit 2; }
	@bash -c '. scripts/lib.sh; ok211::vm_ssh "$$CMD"'
