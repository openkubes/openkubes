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
              $(CP_DIR)/tests/functions.yaml \
              $(CP_DIR)/singleton-admission.yaml
CHART_VER  ?= 0.30.1
GATE       := gate/vault-health-gate.sh
CONF_SCRIPTS := conformance/singleton-conformance.sh conformance/singleton-negative-test.sh \
                conformance/outage-evidence.sh backup/vault-raft-snapshot.sh \
                tooling/ok115-scoped-seed-test.sh

.PHONY: help validate lint-gate template-check health-gate render-prerequisites render render-check singleton-conformance singleton-negative-test outage-evidence raft-snapshot

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
seed=props["properties"]["seedRoles"]; item=seed["items"]; \
assert set(item["required"])==set(["name","appName","serviceAccountName","serviceAccountNamespace","ttlSeconds"]), "seedRoles shape must be closed over the five safe inputs"; \
assert "path" not in item["properties"] and "capabilities" not in item["properties"], "seedRoles must not expose path/capability"; \
assert item["properties"]["ttlSeconds"]["maximum"]==600, "seeding token TTL ceiling must stay short"; \
assert seed["maxItems"]==32 and props["properties"]["roles"]["maxItems"]==64, "top-level role arrays must retain their reviewed cost bounds"; \
validations=props["x-kubernetes-validations"]; assert len(validations)==4, "all four seed-role CEL guards must remain present"; \
rules=" ".join(v["rule"] for v in validations); \
assert "serviceAccountName in r.serviceAccountNames" in rules, "seed SA must not reuse workload SA"; \
assert "other.appName == s.appName" in rules and "other.name == s.name" in rules, "seed app/role names must be unique"; \
assert "r.name != s.name" in rules, "seed role name must not reuse workload role name"; \
print("OK: vaultconfig-xrd invariants (seedRoles has no path/capability input, unique identities, no workload-SA reuse, TTL <= 600s)")'
	@$(PYTHON) -c 'import yaml; \
x=yaml.safe_load(open("$(CP_DIR)/vaultconfig-xrd.yaml")); \
schema=x["spec"]["versions"][0]["schema"]["openAPIV3Schema"]; nodes=[]; \
walk=lambda node,path: (nodes.append((node,path)),[walk(v,f"{path}.{k}") for k,v in node.get("properties",{}).items()],walk(node["items"],f"{path}[]") if isinstance(node.get("items"),dict) else None); \
walk(schema,"$$"); arrays=[(n,p) for n,p in nodes if n.get("type")=="array"]; strings=[(n,p) for n,p in nodes if n.get("type")=="string"]; \
assert all(isinstance(n.get("maxItems"),int) for n,p in arrays), "arrays lack integer maxItems: "+", ".join(p for n,p in arrays if not isinstance(n.get("maxItems"),int)); \
assert all(isinstance(n.get("maxLength"),int) for n,p in strings), "strings lack integer maxLength: "+", ".join(p for n,p in strings if not isinstance(n.get("maxLength"),int)); \
print(f"OK: vaultconfig CEL cost proxy ({len(arrays)} arrays have maxItems; {len(strings)} strings have maxLength)")'
	@$(PYTHON) -c 'import copy, jsonschema, yaml; \
x=yaml.safe_load(open("$(CP_DIR)/vaultconfig-xrd.yaml")); \
schema=x["spec"]["versions"][0]["schema"]["openAPIV3Schema"]; \
good={"spec":{"clusterName":"ok-obs-verify","kubernetesHost":"https://127.0.0.1:6443","reviewerJwtSecretRef":{"namespace":"crossplane-system","name":"reviewer","key":"token"},"caCert":"public-ca","seedRoles":[{"name":"obs-seed","appName":"obs","serviceAccountName":"vault-seed-obs","serviceAccountNamespace":"ok-observability","ttlSeconds":600}]}}; \
validator=jsonschema.Draft7Validator(schema); assert validator.is_valid(good), list(validator.iter_errors(good)); \
bad_slash=copy.deepcopy(good); bad_slash["spec"]["seedRoles"][0]["appName"]="obs/other"; \
bad_wild=copy.deepcopy(good); bad_wild["spec"]["seedRoles"][0]["appName"]="obs*"; \
assert not validator.is_valid(bad_slash) and not validator.is_valid(bad_wild), "seedRoles appName must reject slash and wildcard"; \
too_many_seed=copy.deepcopy(good); too_many_seed["spec"]["seedRoles"]*=33; \
too_long_host=copy.deepcopy(good); too_long_host["spec"]["kubernetesHost"]="h"*2049; \
assert not validator.is_valid(too_many_seed) and not validator.is_valid(too_long_host), "schema bounds must reject oversized arrays and strings"; \
print("OK: vaultconfig jsonschema accepts safe shape; rejects appName slash/wildcard and over-bound array/string")'
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
	@$(PYTHON) -c 'import yaml; \
docs=[d for d in yaml.safe_load_all(open("$(CP_DIR)/singleton-admission.yaml")) if d]; \
pol=[d for d in docs if d.get("kind")=="ValidatingAdmissionPolicy"][0]; \
bnd=[d for d in docs if d.get("kind")=="ValidatingAdmissionPolicyBinding"][0]; \
assert pol["spec"]["failurePolicy"]=="Fail", "singleton VAP must be fail-closed (failurePolicy: Fail)"; \
rr=pol["spec"]["matchConstraints"]["resourceRules"][0]; \
assert "platform.openkubes.ai" in rr["apiGroups"] and "vaultinstances" in rr["resources"], "VAP must match vaultinstances.platform.openkubes.ai"; \
assert "CREATE" in rr["operations"], "VAP must intercept CREATE"; \
assert any("ok-shared-vault" in v["expression"] for v in pol["spec"]["validations"]), "VAP must pin the singleton name ok-shared-vault"; \
assert bnd["spec"]["policyName"]==pol["metadata"]["name"], "Binding must reference the policy"; \
assert "Deny" in bnd["spec"]["validationActions"], "Binding must Deny (not audit-only)"; \
print("OK: singleton-admission invariants (fail-closed VAP, CREATE on vaultinstances, name-pinned, Deny binding)")'
	@echo "OK: Vault scaffold safety invariants passed locally"

lint-gate: ## shellcheck the runtime health gate + conformance scripts (if shellcheck present)
	@command -v $(SHELLCHECK) >/dev/null 2>&1 \
		&& $(SHELLCHECK) $(GATE) $(CONF_SCRIPTS) && echo "OK: gate + conformance scripts shellcheck clean" \
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
mrs=[d for d in docs if str(d.get("apiVersion","")).endswith("vault.upbound.io/v1alpha1")]; \
kinds=sorted(d["kind"] for d in mrs); \
assert "Backend" in kinds and "AuthBackendConfig" in kinds, kinds; \
assert "Policy" in kinds and "AuthBackendRole" in kinds, kinds; \
assert all(d["spec"]["providerConfigRef"]["name"]=="ok-shared-vault" for d in mrs), "all MRs must use the ok-shared-vault ProviderConfig"; \
cfg=[d for d in mrs if d["kind"]=="AuthBackendConfig"][0]["spec"]["forProvider"]; \
assert "tokenReviewerJwtSecretRef" in cfg, "reviewer JWT must be a secret ref"; \
assert "jwt" not in str({k:v for k,v in cfg.items() if k!="tokenReviewerJwtSecretRef"}).lower(), "no inline JWT outside the secret ref"; \
seed_policy=[d for d in mrs if d["kind"]=="Policy" and d["spec"]["forProvider"]["name"]=="okvc-ok-robotics-obs-seed"]; \
assert len(seed_policy)==1 and seed_policy[0]["spec"]["forProvider"]["policy"].strip()=="path \"secret/data/ok-robotics/obs/*\" {\n  capabilities = [\"create\", \"update\"]\n}", "seed policy must be derived create/update-only HCL"; \
seed_role=[d for d in mrs if d["kind"]=="AuthBackendRole" and d["spec"]["forProvider"]["roleName"]=="obs-seed"]; \
assert len(seed_role)==1; sr=seed_role[0]["spec"]["forProvider"]; \
assert sr["boundServiceAccountNames"]==["vault-seed-obs"] and sr["boundServiceAccountNamespaces"]==["ok-observability"], "seed role must bind exactly one dedicated SA"; \
assert sr["tokenPolicies"]==["okvc-ok-robotics-obs-seed"] and sr["tokenNoDefaultPolicy"] is True, "seed role must carry only its derived policy and suppress default"; \
assert sr["tokenTtl"]==sr["tokenMaxTtl"]==sr["tokenExplicitMaxTtl"]==600, "seed TTL must be capped at 600s"; \
print("OK: VaultConfig renders read workload + derived write-only seed policy/role (single SA, no default, capped TTL)")'

health-gate: ## Run the runtime health gate (set VAULT_ADDR/VAULT_CACERT/VAULT_TOKEN/...)
	@bash $(GATE) $(GATE_ARGS)

singleton-conformance: ## crit.14 read-only: verify the singleton is enforced on ok-mgmt (needs kubectl+jq)
	@bash conformance/singleton-conformance.sh $(SINGLETON_ARGS)

singleton-negative-test: ## crit.14: prove a 2nd VaultInstance is rejected (server dry-run, non-mutating)
	@bash conformance/singleton-negative-test.sh $(SINGLETON_ARGS)

outage-evidence: ## crit.8 read-only: capture a phase snapshot (set --phase via EV_ARGS, see runbooks/)
	@bash conformance/outage-evidence.sh $(EV_ARGS)

raft-snapshot: ## crit.11/A10: take + encrypt + register a Raft snapshot (set VAULT_TOKEN/GPG_RECIPIENT/OFFHOST_DIR)
	@bash backup/vault-raft-snapshot.sh

.DEFAULT_GOAL := help
