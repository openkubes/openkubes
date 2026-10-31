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
        knative-install knative-verify knative-post-install probe-up probe apps-serving smoke install vm-ssh lint-server \
        apps-upgrade apps-upgrade-events knative-upgrade upgrade upgrade-collect knative-dry-run apps-upgrade-down \
        measure-s1 measure-scale-to-zero measure-coldstart measure-latency measure-autoscale measure-overhead node-image exp-s8 exp-s9 apps-serving-fastdown apps-serving-exp apps-serving-down coldstart-eval \
        apps-eventing measure-events exp-E5 exp-N1 exp-N4 \
        ingress-render ingress-install kourier-clusterip ingress-route exp-N2b exp-N2b-restore exp-N2-restore measure-fortio tls-install tls-enable tls-disable \
        exp-X1 exp-X1-plain exp-X2 exp-X3 exp-X3-recheck exp-X3-newpod exp-X3-samepod exp-X6 footprint exp-X5 exp-X4 \
        diff gitops-reapply exp-G2

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

lint-server: ## Server-side dry-run of every own manifest (from Phase 3 on)
	@$(GUARD_NODE)
	@files=$$(find load apps ingress tls security gitops -name '*.yaml' -type f 2>/dev/null | sort); \
	 for f in $$files; do printf '%-50s ' "$$f"; scripts/render.sh "$$f" | $(KUBECTL) apply --server-side --field-manager=ok211 --dry-run=server -f - >/dev/null && echo ok || { echo FAIL; exit 1; }; done

# ---------------------------------------------------------------------------
# Phase 4 — upgrade 1.23 -> 1.24 under load (U1, U2)
# ---------------------------------------------------------------------------
apps-upgrade: ## U1: ksvc podinfo-upgrade (min-scale 1) and the 200 ms HTTP probe pod u1-probe
	@$(GUARD_NODE)
	@$(call APPLY_OWN,apps/upgrade/podinfo-upgrade.yaml)
	@$(KUBECTL) -n ok211-serving wait --for=condition=Ready ksvc/podinfo-upgrade --timeout=180s
	@$(call APPLY_OWN,apps/upgrade/u1-probe.yaml)
	@$(KUBECTL) -n ok211-load wait --for=condition=Ready pod/u1-probe --timeout=180s

apps-upgrade-events: ## U2: broker, event-display Deployment, trigger, PingSource ok211-ping and the 1/s sender
	@$(GUARD_NODE)
	@$(call APPLY_OWN,apps/upgrade/u2-events.yaml)
	@$(KUBECTL) -n ok211-events wait --for=condition=Ready broker/default trigger/u2-all pingsource/ok211-ping --timeout=180s
	@$(KUBECTL) -n ok211-events wait --for=condition=Ready pod/u2-sender --timeout=180s

knative-upgrade: ## Upgrade one minor to TO=1.24 (CRDs, serving, kourier, eventing, post-install); marks in evidence/raw/upgrade-steps.log
	@test -n "$(TO)" || { echo "usage: make knative-upgrade TO=1.24"; exit 2; }
	@$(GUARD_NODE)
	@STEP_LOG="$(CURDIR)/evidence/raw/upgrade-steps.log" scripts/knative.sh upgrade "$(TO)"

knative-dry-run: ## Server-side dry run of all release files of TO=<line> as the upgrade would apply them; lists SSA conflicts
	@test -n "$(TO)" || { echo "usage: make knative-dry-run TO=1.24"; exit 2; }
	@$(GUARD_NODE)
	@scripts/knative.sh dry-run "$(TO)"

upgrade: ## Alias for knative-upgrade (CONTRIBUTING.md standard target)
	@$(MAKE) --no-print-directory knative-upgrade TO="$(TO)"

apps-upgrade-down: ## Remove the U1/U2 load: ksvc podinfo-upgrade, u1-probe and everything from u2-events.yaml (ns ok211-events)
	@$(GUARD_NODE)
	@$(KUBECTL) -n ok211-load delete pod u1-probe --ignore-not-found --wait=true
	@$(KUBECTL) -n ok211-serving delete ksvc podinfo-upgrade --ignore-not-found --wait=true
	@scripts/render.sh apps/upgrade/u2-events.yaml | $(KUBECTL) delete --ignore-not-found --wait=true -f -

upgrade-collect: ## Save U1/U2 probe logs with timestamps to evidence/raw/ and evaluate them
	@$(GUARD_NODE)
	@scripts/measure-upgrade.sh

# ---------------------------------------------------------------------------
# Phase 5 — Serving PoC (S1-S10, B11)
# ---------------------------------------------------------------------------
MEASURE = scripts/measure-serving.sh

measure-s1: ## S1: objects of ksvc podinfo and 200 through Kourier
	@$(GUARD_NODE)
	@$(MEASURE) s1

measure-scale-to-zero: ## S2: scale-to-zero time of podinfo with the default config (RUNS=3)
	@$(GUARD_NODE)
	@$(MEASURE) s2 "$(or $(RUNS),3)"

measure-coldstart: ## S3/S4/S7: cold start series ID=<S3|S4|S7> KSVC=<ksvc> N=<runs> [TARGET=<entry point URL>]
	@test -n "$(ID)" -a -n "$(KSVC)" -a -n "$(N)" || { echo "usage: make measure-coldstart ID=S3 KSVC=podinfo N=10"; exit 2; }
	@$(GUARD_NODE)
	@OK211_TARGET="$(TARGET)" $(MEASURE) coldstart "$(ID)" "$(KSVC)" "$(N)"

measure-latency: ## S5: warm latency of podinfo, fortio 10 qps, 200 requests after 30 s warm-up
	@$(GUARD_NODE)
	@$(MEASURE) fortio S5 podinfo 10 1 200

measure-autoscale: ## S6: podinfo-scale (target 10), fortio 50 connections for 60 s, pods every 2 s until 0
	@$(GUARD_NODE)
	@$(MEASURE) s6

measure-overhead: ## S10: kubectl top 3x 60 s apart per namespace, queue-proxy per pod
	@$(GUARD_NODE)
	@$(MEASURE) s10 3 60

exp-s8: ## S8: podinfo-split revisions 6.16.0/6.17.0, 80/20 split, tag candidate, rollback by traffic
	@$(GUARD_NODE)
	@$(MEASURE) s8

exp-s9: ## S9: podinfo-timeout (timeoutSeconds 20) with /delay/10 and /delay/30
	@$(GUARD_NODE)
	@$(MEASURE) s9

apps-serving-fastdown: ## S3-S5: podinfo with autoscaling.knative.dev/window 6s (after S2, which uses the defaults)
	@$(GUARD_NODE)
	@$(call APPLY_OWN,apps/serving/podinfo-fastdown.yaml)
	@$(KUBECTL) -n ok211-serving wait --for=condition=Ready ksvc/podinfo --timeout=300s

apps-serving-exp: ## S6/S7: podinfo-scale (target 10) and podinfo-min1 (after S4, which removes the 6.16.0 image)
	@$(GUARD_NODE)
	@$(call APPLY_OWN,apps/serving/podinfo-scale.yaml apps/serving/podinfo-min1.yaml)
	@$(KUBECTL) -n ok211-serving wait --for=condition=Ready ksvc/podinfo-scale ksvc/podinfo-min1 --timeout=300s

apps-serving-down: ## Remove the experiment services (podinfo-scale, -min1, -split, -timeout); podinfo stays
	@$(GUARD_NODE)
	@$(KUBECTL) -n ok211-serving delete ksvc podinfo-scale podinfo-min1 podinfo-split podinfo-timeout --ignore-not-found --wait=true

coldstart-eval: ## Re-evaluate a cold start TSV: ID=<S3|S4|S7> TSV=evidence/raw/... REV=<revision> IMG=<image digest>
	@test -n "$(ID)" -a -n "$(TSV)" -a -n "$(REV)" -a -n "$(IMG)" || { echo "usage: make coldstart-eval ID= TSV= REV= IMG="; exit 2; }
	@$(GUARD_NODE)
	@$(MEASURE) coldstart-eval "$(ID)" "$(CURDIR)/$(TSV)" "$(REV)" "$(IMG)"

node-image: ## S4: list or remove an image on the node: OP=<list|rmi> [IMAGE=<ref or digest>]
	@test -n "$(OP)" || { echo "usage: make node-image OP=list|rmi [IMAGE=...]"; exit 2; }
	@$(GUARD_NODE)
	@scripts/node-image.sh "$(OP)" "$(IMAGE)"

# ---------------------------------------------------------------------------
# Phase 6 — Eventing PoC (E1-E8)
# ---------------------------------------------------------------------------
MEASURE_EV = scripts/measure-eventing.sh

apps-eventing: ## E1/E6/E8 base (ns ok211-events, broker, event-display, PingSource, triggers) plus E2-E5 objects
	@$(GUARD_NODE)
	@$(call APPLY_OWN,apps/eventing/base.yaml apps/eventing/e2.yaml apps/eventing/e3.yaml apps/eventing/e4.yaml apps/eventing/e5.yaml)
	@$(KUBECTL) -n ok211-events wait --for=condition=Ready broker/default pingsource/ok211-ping ksvc/event-display-ksvc ksvc/podinfo-fail --timeout=300s
	@$(KUBECTL) -n ok211-events wait --for=condition=Ready trigger --all --timeout=300s
	@$(KUBECTL) -n ok211-events wait --for=condition=Available deploy --all --timeout=300s

measure-events: ## E1-E4, E6, E8: TEST=<e1|e2|e3|e4|e6|e8>
	@test -n "$(TEST)" || { echo "usage: make measure-events TEST=e1"; exit 2; }
	@$(GUARD_NODE)
	@$(MEASURE_EV) "$(TEST)"

exp-E5: ## E5: 100 events while the sink is down; SCENARIO=<dispatcher|ingress|restart|none> (force-delete, rollout restart, control)
	@test -n "$(SCENARIO)" || { echo "usage: make exp-E5 SCENARIO=dispatcher|ingress|restart|none"; exit 2; }
	@$(GUARD_NODE)
	@$(MEASURE_EV) e5 "$(SCENARIO)"

# ---------------------------------------------------------------------------
# Phase 7 — Networking, ingress and TLS (N1-N4)
# ---------------------------------------------------------------------------
exp-N1: ## N1: Kourier LoadBalancer via ServiceLB; a second LoadBalancer on 80/443 (removed again)
	@$(GUARD_NODE)
	@scripts/measure-networking.sh n1

exp-N4: ## N4: ksvc podinfo-private with label visibility=cluster-local
	@$(GUARD_NODE)
	@scripts/measure-networking.sh n4

ingress-render: ## N2: verify the Traefik chart checksum and render it with ingress/traefik-values.yaml (refuses Secrets)
	@scripts/ingress.sh render

ingress-install: ## N2: install Traefik (ADR-010 profile v1) into namespace ingress, server-side
	@$(GUARD_NODE)
	@scripts/ingress.sh install

kourier-clusterip: ## N2: kourier Service to ClusterIP (re-applied after release applies while .local/n2-active exists)
	@$(GUARD_NODE)
	@scripts/ingress.sh kourier-clusterip

ingress-route: ## N2: Ingress *.ok211-serving.ok211.internal (class ok-ingress) -> kourier:80, then test via NodePort 30080
	@$(GUARD_NODE)
	@scripts/ingress.sh route
	@scripts/ingress.sh test

exp-N2b: ## N2b: domain-template {{.Name}}-{{.Namespace}}.{{.Domain}} with a *.ok211.internal Ingress
	@$(GUARD_NODE)
	@scripts/ingress.sh n2b

exp-N2b-restore: ## N2b restore: domain-template back to the release default
	@$(GUARD_NODE)
	@scripts/ingress.sh n2b-restore

exp-N2-restore: ## N2 restore: route removed, kourier back to LoadBalancer (Traefik stays)
	@$(GUARD_NODE)
	@scripts/ingress.sh restore

measure-fortio: ## fortio series ID=<id> KSVC=<ksvc> QPS= C= N=<n|duration> [TARGET=<entry point URL>]
	@test -n "$(ID)" -a -n "$(KSVC)" -a -n "$(QPS)" -a -n "$(C)" -a -n "$(N)" || { echo "usage: make measure-fortio ID= KSVC= QPS= C= N= [TARGET=]"; exit 2; }
	@$(GUARD_NODE)
	@OK211_TARGET="$(TARGET)" $(MEASURE) fortio "$(ID)" "$(KSVC)" "$(QPS)" "$(C)" "$(N)"

tls-install: ## N3: cert-manager (pinned manifest) and the lab CA ClusterIssuer ok211-ca-issuer
	@$(GUARD_NODE)
	@scripts/tls.sh install

tls-enable: ## N3: external-domain-tls Enabled with issuerRef ok211-ca-issuer; then the HTTPS checks
	@$(GUARD_NODE)
	@scripts/tls.sh enable
	@scripts/tls.sh test

tls-disable: ## N3 restore: external-domain-tls Disabled (cert-manager and issuers stay)
	@$(GUARD_NODE)
	@scripts/tls.sh disable

# ---------------------------------------------------------------------------
# Phase 8 — Security, tenancy, policy, observability (X1-X6)
# ---------------------------------------------------------------------------
exp-X1: ## X1: PSA restricted in ok211-tenant-a; secure-pod-defaults disabled vs Enabled, with restore
	@$(GUARD_NODE)
	@scripts/security.sh x1

exp-X1-plain: ## X1 follow-up: podinfo-plain with secure-pod-defaults Enabled, pod state after 90 s, with restore
	@$(GUARD_NODE)
	@scripts/security.sh x1-plain

exp-X2: ## X2: tenant ServiceAccount with namespace edit; auth can-i matrix, aggregated ClusterRoles, Eventing auth features
	@$(GUARD_NODE)
	@scripts/security.sh x2

exp-X3: ## X3: default-deny NetworkPolicy in ok211-tenant-b, then allows for knative-serving and kourier-system
	@$(GUARD_NODE)
	@scripts/security.sh x3

exp-X6: ## X6 (optional): cosign verify + verify-attestation for two Knative 1.24 images (read-only, TUF_ROOT in .local/)
	@scripts/supply-chain.sh

exp-X3-recheck: ## X3 follow-up: default deny only, settled 60 s; direct, warm and cold requests; allows re-applied
	@$(GUARD_NODE)
	@scripts/security.sh x3-recheck

exp-X3-newpod: ## X3 follow-up: deny only; after a cold start, a request every 5 s until the first non-200 or MAX=360 s
	@$(GUARD_NODE)
	@scripts/security.sh x3-newpod "$(or $(MAX),360)"

exp-X3-samepod: ## X3 follow-up: deny only; tb-warm pod replaced, request every 5 s until the first non-200 or MAX=600 s
	@$(GUARD_NODE)
	@scripts/security.sh x3-samepod "$(or $(MAX),600)"

footprint: ## X4 (read-only): Knative CRDs, ClusterRoles/Bindings, webhooks with failurePolicy and rules
	@$(GUARD_NODE)
	@scripts/footprint.sh

exp-X5: ## X5: config-observability; scrape /metrics before and with metrics-protocol=prometheus (with restore); RESTART=1 restarts the components
	@$(GUARD_NODE)
	@RESTART="$(RESTART)" scripts/observability.sh

exp-X4: ## X4 (optional, last of the phase): Serving webhook scaled to 0; create/delete/config attempts; restore to 1
	@$(GUARD_NODE)
	@scripts/security.sh x4-webhook

# ---------------------------------------------------------------------------
# Phase 9 — GitOps lifecycle (G1-G4)
# ---------------------------------------------------------------------------
diff: ## G1: kubectl diff --server-side for release (knative, cert-manager, traefik) and own manifests (gitops/current-set.txt); LABEL=<name>
	@$(GUARD_NODE)
	@scripts/gitops.sh diff "$(or $(LABEL),now)"

gitops-reapply: ## G1: apply everything a second time (release in order with overrides, cert-manager, traefik, own set)
	@$(GUARD_NODE)
	@scripts/gitops.sh reapply

exp-G2: ## G2: minimal ksvc g2-podinfo; client-side vs server-side diff; fields added by the webhook
	@$(GUARD_NODE)
	@scripts/gitops.sh g2
