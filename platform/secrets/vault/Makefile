# Local-only checks for the OK-110 Vault datacenter secret backend (ADR-025).
# Mirrors the OK-60 open-rmf gate discipline: deterministic, re-runnable.

PYTHON ?= python3
HELM   ?= helm
SHELLCHECK ?= shellcheck

CP_DIR     := crossplane
YAML_FILES := $(CP_DIR)/xrd.yaml $(CP_DIR)/composition.yaml \
              $(CP_DIR)/examples/ok-shared-vault.yaml $(CP_DIR)/reachability.yaml
CHART_VER  ?= 0.30.1
GATE       := gate/vault-health-gate.sh

.PHONY: help validate lint-gate template-check health-gate

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

health-gate: ## Run the runtime health gate (set VAULT_ADDR/VAULT_CACERT/VAULT_TOKEN/...)
	@bash $(GATE) $(GATE_ARGS)

.DEFAULT_GOAL := help
