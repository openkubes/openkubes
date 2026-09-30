.DEFAULT_GOAL := help
SHELL := /usr/bin/env bash

# Shared-cluster proof defaults.
TARGET_CONTEXT ?= ok-obs-verify-admin@ok-obs-verify
TARGET_CLUSTER ?= ok-obs-verify
IMAGE_REGISTRY ?= ok174-build.invalid
PUBLISH_REGISTRY ?= registry.ok-shared.internal
PUBLISH_REPOSITORY ?= openkubes/machine/staging/adr039-live
PUBLISH_MODE ?= render
PUBLISH_OUTPUT ?= ./evidence/published-images.env
OPENCODE_IMAGE := $(IMAGE_REGISTRY)/developer-workspace-opencode:1.18.33
CODEX_IMAGE := $(IMAGE_REGISTRY)/developer-workspace-codex:0.158.0
FIXTURE_IMAGE := $(IMAGE_REGISTRY)/developer-workspace-fixture:1
NODE_IMAGE := node@sha256:36ae19f59c91f3303c7a648f07493fe14c4bd91320ac8d898416327bacf1bbfa
OLLAMA_MODEL ?= ok174-gpt-oss:20b

# Parse, validate, and export only the three digest-pinned proof images. Do not
# source the generated file as shell code: it is an untrusted publication output.
define LOAD_PROOF_ENV
set -Eeuo pipefail; test -f '$(PUBLISH_OUTPUT)' || { echo 'missing published image env; run image-publish first' >&2; exit 2; }; declare -A seen=(); while IFS= read -r line; do [[ -z "$$line" || "$$line" == \#* ]] && continue; [[ "$$line" =~ ^(OK174_(OPENCODE|CODEX|FIXTURE)_IMAGE)=(.+)$$ ]] || { echo 'invalid published image env line' >&2; exit 2; }; key="$${BASH_REMATCH[1]}"; value="$${BASH_REMATCH[3]}"; [[ -z "$${seen[$$key]+x}" ]] || { echo "duplicate published image key: $$key" >&2; exit 2; }; case "$$key" in OK174_OPENCODE_IMAGE) [[ "$$value" =~ ^registry\.ok-shared\.internal/openkubes/machine/staging/adr039-live/opencode:ok174-proof@sha256:[0-9a-f]{64}$$ ]] ;; OK174_CODEX_IMAGE) [[ "$$value" =~ ^registry\.ok-shared\.internal/openkubes/machine/staging/adr039-live/codex:ok174-proof@sha256:[0-9a-f]{64}$$ ]] ;; OK174_FIXTURE_IMAGE) [[ "$$value" =~ ^registry\.ok-shared\.internal/openkubes/machine/staging/adr039-live/fixture:ok174-proof@sha256:[0-9a-f]{64}$$ ]] ;; esac || { echo "invalid digest ref for $$key" >&2; exit 2; }; seen[$$key]=1; export "$$key=$$value"; done < '$(PUBLISH_OUTPUT)'; for key in OK174_OPENCODE_IMAGE OK174_CODEX_IMAGE OK174_FIXTURE_IMAGE; do [[ -n "$${seen[$$key]+x}" ]] || { echo "missing published image key: $$key" >&2; exit 2; }; done;
endef

.PHONY: help live-build image-publish-render image-publish live-render live-apply live-probe live-negative live-evidence live-clean clean-workspaces
help: ## Show OK-174 live-proof and image-publication targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS=":.*?## "}; {printf "  %-24s %s\n", $$1, $$2}'
	@printf '\nTarget cluster: %s (context %s)\n' '$(TARGET_CLUSTER)' '$(TARGET_CONTEXT)'
	@printf 'Image publication: %s/%s\n' '$(PUBLISH_REGISTRY)' '$(PUBLISH_REPOSITORY)'

live-build: ## Build pinned runtime and fixture images
	@NODE_IMAGE='$(NODE_IMAGE)' IMAGE_REGISTRY='$(IMAGE_REGISTRY)' ./scripts/build-images.sh

image-publish-render: ## Render registry publication plan without login or push
	@PUBLISH_MODE=render IMAGE_REGISTRY='$(IMAGE_REGISTRY)' PUBLISH_REGISTRY='$(PUBLISH_REGISTRY)' PUBLISH_REPOSITORY='$(PUBLISH_REPOSITORY)' PUBLISH_OUTPUT='$(PUBLISH_OUTPUT)' ./scripts/load-images.sh

image-publish: ## Publish images and discover immutable digests (approval and credential required)
	@test -n "$${KUBECONFIG:-}" || { echo 'KUBECONFIG must be set explicitly for shared-target actions' >&2; exit 2; }
	@test "$$(kubectl config current-context 2>/dev/null)" = '$(TARGET_CONTEXT)' || { echo 'current kubectl context does not match TARGET_CONTEXT' >&2; exit 2; }
	@PUBLISH_MODE=publish IMAGE_REGISTRY='$(IMAGE_REGISTRY)' PUBLISH_REGISTRY='$(PUBLISH_REGISTRY)' PUBLISH_REPOSITORY='$(PUBLISH_REPOSITORY)' PUBLISH_OUTPUT='$(PUBLISH_OUTPUT)' REGISTRY_USERNAME="$${REGISTRY_USERNAME:-}" REGISTRY_PASSWORD_FD="$${REGISTRY_PASSWORD_FD:-}" PUBLISH_APPROVED="$${PUBLISH_APPROVED:-no}" ./scripts/load-images.sh

live-render: ## Render proof manifests without cluster access
	@[[ "$${OK174_REVISION:-}" =~ ^[0-9a-f]{40}$$ ]] || { echo 'OK174_REVISION must be a 40-hex revision' >&2; exit 2; }
	@set -Eeuo pipefail; OK174_MODEL='$(OLLAMA_MODEL)' python3 ./probes/live_proof.py render --revision "$${OK174_REVISION}" --output ./rendered-live.yaml; python3 -c 'import yaml; from pathlib import Path; docs=list(yaml.safe_load_all(Path("rendered-live.yaml").read_text())); seen=set(); [print("{} {}/{}".format(d["ki"+"nd"], d.get("metadata", {}).get("namespace", "<cluster>"), d.get("metadata", {}).get("name", "<unnamed>"))) for d in docs if d and not (tuple([d["ki"+"nd"], d.get("metadata", {}).get("namespace", "<cluster>"), d.get("metadata", {}).get("name", "<unnamed>")]) in seen or seen.add(tuple([d["ki"+"nd"], d.get("metadata", {}).get("namespace", "<cluster>"), d.get("metadata", {}).get("name", "<unnamed>")]))) ]'

live-apply: ## Apply proof workload (coordinator approval required)
	@test "$${APPROVE_LIVE:-no}" = yes || { echo 'set APPROVE_LIVE=yes for live mutation' >&2; exit 2; }
	@test -n "$${KUBECONFIG:-}" && test "$$(kubectl config current-context 2>/dev/null)" = '$(TARGET_CONTEXT)' || { echo 'explicit KUBECONFIG/current-context guard failed' >&2; exit 2; }
	@test "$${OK174_STORAGE_CLASS:-}" = local-path || { echo 'OK174_STORAGE_CLASS must be local-path' >&2; exit 2; }
	@[[ "$${OK174_REVISION:-}" =~ ^[0-9a-f]{40}$$ ]] || { echo 'OK174_REVISION must be a 40-hex revision' >&2; exit 2; }

	@test "$${OK174_REGISTRY_USERNAME:-}" != '' && [[ "$${OK174_REGISTRY_USERNAME}" =~ ^[A-Za-z0-9._-]+$$ ]] || { echo 'OK174_REGISTRY_USERNAME is required and must be non-secret-safe text' >&2; exit 2; }
	@[[ "$${OK174_REGISTRY_PASSWORD_FD:-}" =~ ^[0-9]+$$ ]] || { echo 'OK174_REGISTRY_PASSWORD_FD must be an inherited numeric descriptor' >&2; exit 2; }
	@$(LOAD_PROOF_ENV) OK174_STORAGE_CLASS=local-path OK174_MODEL='$(OLLAMA_MODEL)' OK174_REVISION="$${OK174_REVISION}" OK174_REGISTRY_USERNAME="$${OK174_REGISTRY_USERNAME}" OK174_REGISTRY_PASSWORD_FD="$${OK174_REGISTRY_PASSWORD_FD}" python3 ./probes/live_proof.py apply --revision "$${OK174_REVISION}"

live-probe: ## Run live checks once
	@test "$${APPROVE_LIVE:-no}" = yes || { echo 'set APPROVE_LIVE=yes for live mutation' >&2; exit 2; }
	@test "$${APPROVE_LIVE_CLEANUP:-no}" = yes || { echo 'set APPROVE_LIVE_CLEANUP=yes because the probe records UID-bound cleanup' >&2; exit 2; }
	@test "$${OK174_STORAGE_CLASS:-}" = local-path || { echo 'OK174_STORAGE_CLASS must be local-path' >&2; exit 2; }
	@[[ "$${OK174_REVISION:-}" =~ ^[0-9a-f]{40}$$ ]] || { echo 'OK174_REVISION must be a 40-hex revision' >&2; exit 2; }
	@[[ "$${OK174_RUN_ID:-}" =~ ^[0-9a-f]{24}$$ ]] || { echo 'OK174_RUN_ID must be the 24-hex apply run ID' >&2; exit 2; }
	@test -n "$${KUBECONFIG:-}" && test "$$(kubectl config current-context 2>/dev/null)" = '$(TARGET_CONTEXT)' || { echo 'explicit KUBECONFIG/current-context guard failed' >&2; exit 2; }
	@$(LOAD_PROOF_ENV) OK174_STORAGE_CLASS=local-path OK174_MODEL='$(OLLAMA_MODEL)' OK174_REVISION="$${OK174_REVISION}" python3 ./probes/live_proof.py probe --run-id "$${OK174_RUN_ID}"

live-negative: ## Break each probe's precondition live; each must go red, then green after revert
	@test "$${APPROVE_LIVE:-no}" = yes && test "$${APPROVE_LIVE_CLEANUP:-no}" = yes || { echo 'set APPROVE_LIVE=yes and APPROVE_LIVE_CLEANUP=yes' >&2; exit 2; }
	@[[ "$${OK174_RUN_ID:-}" =~ ^[0-9a-f]{24}$$ ]] || { echo 'OK174_RUN_ID must be the 24-hex apply run ID' >&2; exit 2; }
	@test -n "$${KUBECONFIG:-}" && test "$$(kubectl config current-context 2>/dev/null)" = '$(TARGET_CONTEXT)' || { echo 'explicit KUBECONFIG/current-context guard failed' >&2; exit 2; }
	@$(LOAD_PROOF_ENV) OK174_STORAGE_CLASS=local-path OK174_MODEL='$(OLLAMA_MODEL)' python3 ./probes/live_proof.py negative --run-id "$${OK174_RUN_ID}"

live-evidence: ## Serialize the last collected probe results; never rerun probes
	@[[ "$${OK174_RUN_ID:-}" =~ ^[0-9a-f]{24}$$ ]] || { echo 'OK174_RUN_ID must be the 24-hex apply run ID' >&2; exit 2; }
	@test -n "$${KUBECONFIG:-}" && test "$$(kubectl config current-context 2>/dev/null)" = '$(TARGET_CONTEXT)' || { echo 'explicit KUBECONFIG/current-context guard failed' >&2; exit 2; }
	@$(LOAD_PROOF_ENV) OK174_MODEL='$(OLLAMA_MODEL)' python3 ./probes/live_proof.py evidence --run-id "$${OK174_RUN_ID}"

clean-workspaces: ## Cleanup proof resources (coordinator approval required)
	@test "$${APPROVE_LIVE_CLEANUP:-no}" = yes || { echo 'set APPROVE_LIVE_CLEANUP=yes for cleanup' >&2; exit 2; }
	@[[ "$${OK174_RUN_ID:-}" =~ ^[0-9a-f]{24}$$ ]] || { echo 'OK174_RUN_ID must be the 24-hex apply run ID' >&2; exit 2; }
	@test -n "$${KUBECONFIG:-}" && test "$$(kubectl config current-context 2>/dev/null)" = '$(TARGET_CONTEXT)' || { echo 'explicit KUBECONFIG/current-context guard failed' >&2; exit 2; }
	@python3 ./probes/live_proof.py clean-workspaces --run-id "$${OK174_RUN_ID}"

live-clean: ## Shared-cluster cleanup (coordinator approval required)
	@$(MAKE) clean-workspaces APPROVE_LIVE_CLEANUP="$${APPROVE_LIVE_CLEANUP:-no}" OK174_RUN_ID="$${OK174_RUN_ID:-}"
