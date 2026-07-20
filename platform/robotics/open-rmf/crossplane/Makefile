# Local-only checks for the OK-60 OpenRMF Crossplane scaffold.

PYTHON     ?= python3
HELM       ?= helm
CROSSPLANE ?= crossplane
DOCKER     ?= docker
RMF_CHART  ?= ../../../../../rmf_deployment_template/charts/rmf-deployment
CHART_URL  := https://github.com/openkubes/rmf_deployment_template/releases/download/openrmf-deployment-v1.0.0/openrmf-deployment-1.0.0.tgz
CLUSTER    ?= ok2-rmf
XR         ?= tests/xr-$(CLUSTER).yaml
YAML_FILES := xrd.yaml composition.yaml examples/ok2-rmf.yaml \
	examples/ok-robotics.yaml rbac/claim-editor-role.yaml \
	tests/functions.yaml tests/xr-ok2-rmf.yaml tests/xr-ok-robotics.yaml
RENDER_CMD := $(CROSSPLANE) composition render $(XR) \
	composition.yaml tests/functions.yaml --crossplane-version=v2.3.3 \
	--include-full-xr
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

.PHONY: help validate chart-check ready-check render render-check render-prerequisites

help: ## Show available local checks
	@awk 'BEGIN {FS = ":.*## "}; /^[a-zA-Z_-]+:.*## / {printf "  %-16s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

validate: ## Parse YAML and verify scaffold safety invariants
	@$(PYTHON) -c 'import pathlib, sys, yaml; [list(yaml.safe_load_all(pathlib.Path(p).read_text())) for p in sys.argv[1:]]' $(YAML_FILES)
	@grep -q 'deletionPolicy: Orphan' composition.yaml
	@grep -Fq 'url: $(CHART_URL)' composition.yaml
	@! grep -q '\.invalid' composition.yaml
	@! grep -Eq '(PASSWD|Password):[[:space:]]+[^#[:space:]]' examples/ok2-rmf.yaml
	@$(PYTHON) -c 'import pathlib, yaml; role = yaml.safe_load(pathlib.Path("rbac/claim-editor-role.yaml").read_text()); rules = role["rules"]; assert len(rules) == 1, rules; rule = rules[0]; assert rule["apiGroups"] == ["platform.openkubes.ai"], rule; assert rule["resources"] == ["openrmfclaims"], rule; assert "secrets" not in rule["resources"], rule'
	@echo "OK: YAML parses and local safety/chart-source guards are present"

chart-check: ## Run local Helm lint/template for the ok2-rmf values profile
	@test -d "$(RMF_CHART)" || (echo "ERROR: RMF chart not found: $(RMF_CHART)"; exit 1)
	@$(HELM) lint "$(RMF_CHART)" $(PROFILE_ARGS)
	@$(HELM) template rmf "$(RMF_CHART)" $(PROFILE_ARGS) | $(PYTHON) -c 'import sys, yaml; docs = [d for d in yaml.safe_load_all(sys.stdin) if isinstance(d, dict)]; forbidden = [d.get("kind") for d in docs if d.get("kind") in {"Certificate", "ServiceMonitor"}]; annotated = [d.get("metadata", {}).get("name") for d in docs if d.get("kind") == "IngressRoute" and "kubernetes.io/ingress.class" in d.get("metadata", {}).get("annotations", {})]; assert not forbidden, f"forbidden resources rendered: {forbidden}"; assert not annotated, f"IngressRoute class annotations rendered: {annotated}"'
	@echo "OK: Helm lint/template and ok2-rmf ingress/CRD guards passed locally"

ready-check: validate ## Verify the pinned published chart name and version
	@$(HELM) show chart "$(CHART_URL)" | $(PYTHON) -c 'import sys, yaml; chart = yaml.safe_load(sys.stdin); assert chart.get("name") == "openrmf-deployment", chart; assert chart.get("version") == "1.0.0", chart'
	@echo "OK: published chart is reachable and pinned to openrmf-deployment 1.0.0"

render-prerequisites: ## Verify local Crossplane render dependencies
	@command -v "$(CROSSPLANE)" >/dev/null || (echo "ERROR: Crossplane CLI is required"; exit 1)
	@command -v "$(DOCKER)" >/dev/null || (echo "ERROR: Docker is required by Crossplane render"; exit 1)
	@$(DOCKER) info >/dev/null 2>&1 || (echo "ERROR: Docker daemon is unavailable; enable Docker integration before rendering"; exit 1)

render: render-prerequisites ## Render the representative XR locally (CLUSTER=ok2-rmf|ok-robotics)
	@$(RENDER_CMD)

render-check: render-prerequisites ## Render and verify the composed Helm Release (CLUSTER=ok2-rmf|ok-robotics)
	@$(RENDER_CMD) | $(PYTHON) -c 'import sys, yaml; docs = [d for d in yaml.safe_load_all(sys.stdin) if isinstance(d, dict)]; releases = [d for d in docs if d.get("apiVersion") == "helm.crossplane.io/v1beta1" and d.get("kind") == "Release"]; assert len(releases) == 1, releases; r = releases[0]; spec = r["spec"]; fp = spec["forProvider"]; assert r["metadata"]["name"] == "openrmf-$(CLUSTER)", r["metadata"]; assert r["metadata"]["annotations"]["crossplane.io/external-name"] == "rmf", r["metadata"]; assert spec["deletionPolicy"] == "Orphan", spec; assert spec["providerConfigRef"]["name"] == "$(CLUSTER)", spec; assert fp["chart"]["url"] == "$(CHART_URL)", fp["chart"]; assert fp["namespace"] == "rmf", fp; refs = [v["valueFrom"]["secretKeyRef"] for v in fp["set"]]; assert len(refs) == 4, refs; assert all(v["name"] == "rmf-credentials" and v["namespace"] == "crossplane-system" for v in refs), refs'
	@echo "OK: Composition rendered one safe, secret-referencing Helm Release for $(CLUSTER)"

.DEFAULT_GOAL := help
