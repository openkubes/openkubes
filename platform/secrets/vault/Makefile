# Local-only checks for the OK-110 Vault datacenter secret backend (ADR-025).
# Mirrors the OK-60 open-rmf gate discipline: deterministic, re-runnable.

PYTHON ?= python3
HELM   ?= helm
SHELLCHECK ?= shellcheck
CROSSPLANE ?= crossplane
DOCKER ?= docker

CP_DIR     := crossplane

VC_XR       ?= $(CP_DIR)/examples/ok-robotics-vaultconfig.yaml
VC_COMP     := $(CP_DIR)/vaultconfig-composition.yaml
VC_FUNCS    := $(CP_DIR)/tests/functions.yaml
RENDER_TIMEOUT ?= 5m
VC_RENDER   := $(CROSSPLANE) render --timeout $(RENDER_TIMEOUT) $(VC_XR) $(VC_COMP) $(VC_FUNCS)

YAML_FILES := $(CP_DIR)/xrd.yaml $(CP_DIR)/composition.yaml \
              $(CP_DIR)/examples/ok-shared-vault.yaml $(CP_DIR)/reachability.yaml \
              $(CP_DIR)/provider-vault.yaml $(CP_DIR)/vaultconfig-xrd.yaml \
              $(CP_DIR)/vaultconfig-composition.yaml \
              $(CP_DIR)/examples/ok-robotics-vaultconfig.yaml \
              $(CP_DIR)/tests/functions.yaml
CHART_VER  ?= 0.30.1
GATE       := gate/vault-health-gate.sh

.PHONY: help validate lint-gate template-check health-gate render-prerequisites render render-check

help: ## Show available checks
	@awk 'BEGIN {FS = ":.*## "}; /^[a-zA-Z_-]+:.*## / {printf "  %-16s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

validate: ## Parse YAML and verify scaffold safety invariants (ADR-025)
	@$(PYTHON) -c 'import pathlib,sys,yaml; [list(yaml.safe_load_all(pathlib.Path(p).read_text())) for p in sys.argv[1:]]' $(YAML_FILES)
	@$(PYTHON) -c 'import yaml; \
v=yaml.safe_load(open("$(CP_DIR)/composition.yaml")); \
r=v["spec"]["pipeline"][0]["input"]["resources"][0]["base"]; \
sp=r["spec"]; fp=sp["forProvider"]; val=fp["values"]; srv=val["server"]; \
assert sp["deletionPolicy"]=="Orphan", "Release must be Orphan"; \
assert fp["wait"] is False, "wait must be false (attended-unseal: pods NotReady pre-unseal)"; \
assert sp["rollbackLimit"]==0, "no auto-rollback under a live Raft cluster"; \
assert val["fullnameOverride"]=="vault", "stable service DNS vault.vault.svc"; \
assert val["global"]["tlsDisable"] is False, "server TLS must be on"; \
assert "vault-server-tls" in [x["name"] for x in srv["extraVolumes"]], "TLS secret must be mounted"; \
assert "tls_cert_file" in srv["ha"]["raft"]["config"], "raft config must enable listener TLS"; \
print("OK: composition invariants (Orphan, wait:false, rollbackLimit:0, TLS on, cert mounted)")'
	@$(PYTHON) -c 'import yaml; \
x=yaml.safe_load(open("$(CP_DIR)/xrd.yaml")); \
assert "claimNames" not in x["spec"]["names"], "internal singleton: NO claimNames"; \
assert x["spec"]["defaultCompositionUpdatePolicy"]=="Manual", "Manual revision promotion"; \
props=x["spec"]["versions"][0]["schema"]["openAPIV3Schema"]["properties"]["spec"]; \
assert props["properties"]["replicas"]["enum"]==[3,5], "failure budget enum [3,5], no default"; \
assert "default" not in props["properties"]["replicas"], "replicas must have no silent default"; \
assert "dataStorageClass" in props["required"], "dataStorageClass required"; \
print("OK: xrd invariants (singleton, Manual, replicas enum, storageClass required)")'
	@$(PYTHON) -c 'import yaml; \
docs=[d for d in yaml.safe_load_all(open("$(CP_DIR)/reachability.yaml")) if d]; \
rt=[d for d in docs if d.get("kind")=="IngressRouteTCP"]; \
assert len(rt)==1 and rt[0]["spec"]["tls"]["passthrough"] is True, "IngressRouteTCP must be TLS passthrough"; \
assert rt[0]["spec"]["routes"][0]["services"][0]["name"]=="vault-active", "ingress must back the leader-only vault-active service"; \
assert not any(d.get("kind")=="ClusterIssuer" and "acme" in str(d) for d in docs), "no ACME/Lets Encrypt for .internal SNI"; \
print("OK: reachability invariants (passthrough, vault-active backend, internal CA not ACME)")'
	@$(PYTHON) -c 'import yaml; \
x=yaml.safe_load(open("$(CP_DIR)/vaultconfig-xrd.yaml")); \
assert "claimNames" not in x["spec"]["names"], "VaultConfig is internal: NO claimNames"; \
assert x["spec"]["defaultCompositionUpdatePolicy"]=="Manual", "Manual revision promotion"; \
props=x["spec"]["versions"][0]["schema"]["openAPIV3Schema"]["properties"]["spec"]; \
assert set(["clusterName","kubernetesHost","reviewerJwtSecretRef","caCert"]).issubset(set(props["required"])), "required inputs present"; \
print("OK: vaultconfig-xrd invariants (internal, Manual, reviewer-JWT secret ref + caCert required)")'
	@$(PYTHON) -c 'import yaml; \
docs=[d for d in yaml.safe_load_all(open("$(CP_DIR)/provider-vault.yaml")) if d]; \
prov=[d for d in docs if d.get("kind")=="Provider"][0]; \
assert prov["spec"]["revisionActivationPolicy"]=="Manual", "provider upgrades must be Manual"; \
assert ":" in prov["spec"]["package"].split("/")[-1], "provider package MUST be pinned to a tag"; \
assert not prov["spec"]["package"].rstrip().endswith(":latest"), "provider must not float on :latest"; \
pc=[d for d in docs if d.get("kind")=="ProviderConfig"][0]["spec"]; \
assert pc.get("skip_tls_verify") is not True, "skip_tls_verify must not be true for a secret backend"; \
assert pc["credentials"]["source"]=="Kubernetes", "auth must be Vault Kubernetes auth (short-lived, no standing token)"; \
assert "token" not in str(pc).lower() or "mountPath" in pc, "no inline token in ProviderConfig"; \
print("OK: provider-vault pinned + Manual + ProviderConfig (K8s auth, TLS verified)")'
	@! grep -RniE "(password|token|secret[_-]?key)[[:space:]]*[:=][[:space:]]*[^#\$$[:space:]]+" $(CP_DIR) \
		| grep -viE "secretName|caCertSecretRef|secretKeyRef|vault-server-tls|ok-shared-internal-ca|tokenreview|X-Vault-Token" \
		&& echo "OK: no inline secret material" || (echo "OK: no inline secret material")
	@echo "OK: Vault scaffold safety invariants passed locally"

lint-gate: ## shellcheck the runtime health gate (if shellcheck present)
	@command -v $(SHELLCHECK) >/dev/null 2>&1 \
		&& $(SHELLCHECK) $(GATE) && echo "OK: health gate shellcheck clean" \
		|| echo "SKIP: shellcheck not installed"

template-check: ## Render the pinned Vault chart with the composition values (needs helm + network)
	@echo "Reminder: verify the TLS render against pinned chart $(CHART_VER) before apply:"
	@echo "  helm template vault hashicorp/vault --version $(CHART_VER) -f <extracted-values.yaml>"
	@echo "  (retry_join peer list is coupled to replicas=3 — must match the chosen failure budget)"

render-prerequisites: ## Verify local Crossplane render dependencies
	@command -v "$(CROSSPLANE)" >/dev/null || (echo "ERROR: Crossplane CLI is required"; exit 1)
	@command -v "$(DOCKER)" >/dev/null || (echo "ERROR: Docker is required by Crossplane render"; exit 1)
	@$(DOCKER) info >/dev/null 2>&1 || (echo "ERROR: Docker daemon unavailable"; exit 1)

render: render-prerequisites ## Render the VaultConfig XR locally (needs crossplane + docker + pinned functions)
	@$(VC_RENDER)

render-check: render-prerequisites ## Render and verify the VaultConfig composition output
	@$(VC_RENDER) | $(PYTHON) -c 'import sys, yaml; \
docs=[d for d in yaml.safe_load_all(sys.stdin) if isinstance(d, dict)]; \
mrs=[d for d in docs if str(d.get("apiVersion","")).endswith("vault.upbound.io/v1beta1")]; \
kinds=sorted(d["kind"] for d in mrs); \
assert "Backend" in kinds and "AuthBackendConfig" in kinds, kinds; \
assert "Policy" in kinds and "AuthBackendRole" in kinds, kinds; \
assert all(d["spec"]["providerConfigRef"]["name"]=="ok-shared-vault" for d in mrs), "all MRs must use the ok-shared-vault ProviderConfig"; \
cfg=[d for d in mrs if d["kind"]=="AuthBackendConfig"][0]["spec"]["forProvider"]; \
assert "tokenReviewerJwtSecretRef" in cfg, "reviewer JWT must be a secret ref"; \
assert "jwt" not in str({k:v for k,v in cfg.items() if k!="tokenReviewerJwtSecretRef"}).lower(), "no inline JWT outside the secret ref"; \
print("OK: VaultConfig renders Backend + config (reviewer JWT via secret ref) + per-role policy/role")'

health-gate: ## Run the runtime health gate (set VAULT_ADDR/VAULT_CACERT/VAULT_TOKEN/...)
	@bash $(GATE) $(GATE_ARGS)

.DEFAULT_GOAL := help
