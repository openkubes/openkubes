# DeveloperWorkspace Crossplane capability (OK-175, ADR-Platform-039).
SHELL := /bin/bash
DOCKER ?= docker
GOTEMPLATING_IMAGE := xpkg.upbound.io/crossplane-contrib/function-go-templating:v0.9.2
AUTOREADY_IMAGE := xpkg.upbound.io/crossplane-contrib/function-auto-ready:v0.4.1
SPIKE_IMAGES := ../../../../architecture/spikes/ADR-Platform-039/live/evidence/published-images.env

.PHONY: help live-selftest xrd xrd-check cel-check admission-cel-check functions-up functions-down render-check live-install live-run live-up live-down live-uninstall audit-doc-check

help: ## Show targets
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-15s %s\n", $$1, $$2}'

xrd: ## Regenerate xrd.yaml from the contract schema
	@python3 tests/xrd_schema.py --write

xrd-check: ## Fail if xrd.yaml drifts from the contract schema
	@python3 tests/xrd_schema.py --check
	@python3 tests/xrd-cel-check.py

cel-check: ## Evaluate XRD and admission-policy CEL offline (needs tests/cel-requirements.txt)
	@python3 tests/xrd-cel-check.py
	@$(MAKE) --no-print-directory admission-cel-check

admission-cel-check: ## Evaluate admission-policy CEL offline (needs tests/cel-requirements.txt)
	@python3 tests/admission-cel-check.py

audit-doc-check: ## Check the documented Namespace metadata and platform identity trust boundaries
	@python3 tests/audit-doc-check.py

functions-up: ## Run both functions as Development-runtime containers for render-check
	@$(DOCKER) run -d --rm --name ok175-fn-gotemplating -p 127.0.0.1:9443:9443 $(GOTEMPLATING_IMAGE) --insecure >/dev/null
	@$(DOCKER) run -d --rm --name ok175-fn-autoready -p 127.0.0.1:9444:9443 $(AUTOREADY_IMAGE) --insecure >/dev/null

functions-down: ## Stop the function containers
	@$(DOCKER) rm -f ok175-fn-gotemplating ok175-fn-autoready >/dev/null

render-check: xrd-check admission-cel-check audit-doc-check ## Composition output must equal render() (needs functions-up)
	@python3 tests/render-check.py

live-selftest: ## Offline live harness, ownership mutation controls, and committed profile examples
	@python3 tests/live/hands_on_ownership_selftest.py --prove-mutations
	@python3 tests/live/hands_on_ownership_selftest.py
	@python3 tests/live/reconcile_proof_selftest.py
	@python3 tests/live/profile_examples_selftest.py

live-install: ## Install and observe admission guards before enabling this capability on TARGET_CONTEXT (disposable clusters only)
	@test -n "$${KUBECONFIG:-}" && test -n "$${TARGET_CONTEXT:-}" || { echo 'set KUBECONFIG and TARGET_CONTEXT' >&2; exit 2; }
	@python3 tests/live/reconcile_proof.py install

live-run: ## Admission-gated reconciler live proof; images default to the OK-174 published digests
	@test -n "$${KUBECONFIG:-}" && test -n "$${TARGET_CONTEXT:-}" || { echo 'set KUBECONFIG and TARGET_CONTEXT' >&2; exit 2; }
	@set -a; [[ -n "$${OK175_RUNTIME_IMAGE:-}" ]] || { source $(SPIKE_IMAGES); OK175_RUNTIME_IMAGE=$$OK174_OPENCODE_IMAGE; OK175_FIXTURE_IMAGE=$$OK174_FIXTURE_IMAGE; }; set +a; \
	  python3 tests/live/reconcile_proof.py run $(if $(REQUIRE_CLEAN),--require-clean)

live-up: ## Keep one usable persistent OpenCode workspace on the disposable target
	@test -n "$${KUBECONFIG:-}" && test -n "$${TARGET_CONTEXT:-}" || { echo 'set KUBECONFIG and TARGET_CONTEXT' >&2; exit 2; }
	@set -a; [[ -n "$${OK175_RUNTIME_IMAGE:-}" ]] || { source $(SPIKE_IMAGES); OK175_RUNTIME_IMAGE=$$OK174_OPENCODE_IMAGE; OK175_FIXTURE_IMAGE=$$OK174_FIXTURE_IMAGE; }; set +a; \
	  OK176_PROFILE_FILE="$${OK176_PROFILE_FILE:-$(abspath profiles/namespace-profile-local-quota.yaml)}" python3 tests/live/reconcile_proof.py up

live-down: ## Delete the hands-on workspace and fixture; wait for Namespace/PV removal
	@test -n "$${KUBECONFIG:-}" && test -n "$${TARGET_CONTEXT:-}" || { echo 'set KUBECONFIG and TARGET_CONTEXT' >&2; exit 2; }
	@python3 tests/live/reconcile_proof.py down

live-uninstall: ## Remove this capability and Crossplane (after every DeveloperWorkspace is deleted)
	@test -n "$${KUBECONFIG:-}" && test -n "$${TARGET_CONTEXT:-}" || { echo 'set KUBECONFIG and TARGET_CONTEXT' >&2; exit 2; }
	@python3 tests/live/reconcile_proof.py uninstall
