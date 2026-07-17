# Local-only checks for the OK-60 OpenRMF Crossplane scaffold.

PYTHON     ?= python3
HELM       ?= helm
RMF_CHART  ?= ../../../../../rmf_deployment_template/charts/rmf-deployment
YAML_FILES := xrd.yaml composition.yaml examples/ok2-rmf.yaml
PROFILE_ARGS := \
	--set-string hostName=rmf.openkubes.local \
	--set-string baseUrl=https://rmf.openkubes.local \
	--set ENABLE_RMF_SIM=true \
	--set ENABLE_RMF=false \
	--set-string ingress.provider=traefik \
	--set-string ingress.className=ok-ingress \
	--set tls.enabled=true \
	--set tls.useTraefikDefaultCertificate=true \
	--set monitoring.enabled=false \
	--set-string rmf_web.API_SERVER_DB_PASSWD=validation-only \
	--set-string rmf_web.ADMIN_PASSWD=validation-only \
	--set-string keycloak.KEYCLOAK_ADMIN_PASSWD=validation-only \
	--set-string keycloak.KEYCLOAK_DB_PASSWD=validation-only

.PHONY: help validate chart-check ready-check

help: ## Show available local checks
	@awk 'BEGIN {FS = ":.*## "}; /^[a-zA-Z_-]+:.*## / {printf "  %-16s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

validate: ## Parse YAML and verify scaffold safety invariants
	@$(PYTHON) -c 'import pathlib, sys, yaml; [list(yaml.safe_load_all(pathlib.Path(p).read_text())) for p in sys.argv[1:]]' $(YAML_FILES)
	@grep -q 'deletionPolicy: Orphan' composition.yaml
	@grep -q 'charts.openkubes.invalid' composition.yaml
	@! grep -Eq '(PASSWD|Password):[[:space:]]+[^#[:space:]]' examples/ok2-rmf.yaml
	@echo "OK: scaffold YAML parses and local safety guards are present"

chart-check: ## Run local Helm lint/template for the ok2-rmf values profile
	@test -d "$(RMF_CHART)" || (echo "ERROR: RMF chart not found: $(RMF_CHART)"; exit 1)
	@$(HELM) lint "$(RMF_CHART)" $(PROFILE_ARGS)
	@$(HELM) template rmf "$(RMF_CHART)" $(PROFILE_ARGS) | $(PYTHON) -c 'import sys, yaml; docs = [d for d in yaml.safe_load_all(sys.stdin) if isinstance(d, dict)]; forbidden = [d.get("kind") for d in docs if d.get("kind") in {"Certificate", "ServiceMonitor"}]; annotated = [d.get("metadata", {}).get("name") for d in docs if d.get("kind") == "IngressRoute" and "kubernetes.io/ingress.class" in d.get("metadata", {}).get("annotations", {})]; assert not forbidden, f"forbidden resources rendered: {forbidden}"; assert not annotated, f"IngressRoute class annotations rendered: {annotated}"'
	@echo "OK: Helm lint/template and ok2-rmf ingress/CRD guards passed locally"

ready-check: validate ## Fail until the non-deployable chart placeholder is replaced
	@if grep -q 'charts.openkubes.invalid' composition.yaml; then \
		echo "BLOCKED: publish the chart and replace charts.openkubes.invalid"; \
		exit 1; \
	fi
	@echo "OK: scaffold chart-source guard cleared"

.DEFAULT_GOAL := help
