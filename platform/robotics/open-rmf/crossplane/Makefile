# Local checks for the OpenRMF Crossplane capability, plus the
# approval-gated ok-mgmt bind/deploy lifecycle.

# Required: the lifecycle recipes use `set -Eeuo pipefail`, which dash rejects
# outright ("Illegal option -o pipefail"). Without this every one of them aborts
# at its first line on any system where /bin/sh is not bash.
SHELL := /bin/bash

PYTHON     ?= python3
HELM       ?= helm
CROSSPLANE ?= crossplane
DOCKER     ?= docker
RMF_CHART  ?= ../../../../../rmf_deployment_template/charts/rmf-deployment
CHART_URL  := https://github.com/openkubes/rmf_deployment_template/releases/download/openrmf-deployment-v1.0.1/openrmf-deployment-1.0.1.tgz
CLUSTER    ?= ok-robotics
XR         ?= tests/xr-$(CLUSTER).yaml
YAML_FILES := xrd.yaml composition.yaml claim-admission-policy.yaml examples/ok-robotics.yaml \
	rbac/claim-editor-role.yaml rbac/claim-editor-binding.yaml \
	tests/functions.yaml tests/xr-ok-robotics.yaml

# ok-mgmt lifecycle (bind/deploy/status/undeploy). Every target that mutates
# ok-mgmt goes through require-mgmt-approval.
MGMT_CLUSTER        ?= ok-mgmt
MGMT_KUBECONFIG     ?= $(HOME)/.kube/ok-mgmt.yaml
MGMT_KUBECTL        := kubectl --kubeconfig $(MGMT_KUBECONFIG)
CLAIM_NAMESPACE     := openkubes-system

# Impersonated subject for authz-check. CLAIM_EDITOR_USER deliberately names a
# user that does not exist in the realm: the positive result must come from group
# membership alone, not from anything specific to one person's account.
#
# PEER_GROUPS lists the OTHER groups a real claim editor also carries. It is not
# cosmetic: a negative assertion is only as strong as the subject it runs
# against, so checking the editor group in isolation would report "Secrets are
# denied" while the actual human — who is also a platform admin — could read
# them. The default mirrors the group set observed in a real ID token. Set it to
# empty only when you have confirmed no claim editor holds another group.
CLAIM_EDITOR_USER   ?= oidc:claim-editor-probe
CLAIM_EDITOR_GROUPS ?= oidc:openrmf-claim-editors
PEER_GROUPS         ?= oidc:platform-admins
# Required by deploy as explicit admin-impersonation attribution rather than
# silently reusing the synthetic authz-check identity.
DEPLOY_USER         ?=

# Group lists intentionally expand to several flags. DEPLOY_USER is separately
# restricted to a single safe username token before its quoted use.
POS_ARGS  := --as=$(CLAIM_EDITOR_USER) \
	$(foreach g,$(CLAIM_EDITOR_GROUPS),--as-group=$(g)) \
	--as-group=system:authenticated
FULL_ARGS := --as=$(CLAIM_EDITOR_USER) \
	$(foreach g,$(CLAIM_EDITOR_GROUPS) $(PEER_GROUPS),--as-group=$(g)) \
	--as-group=system:authenticated
DEPLOY_ARGS := --as='$(DEPLOY_USER)' \
	$(foreach g,$(CLAIM_EDITOR_GROUPS),--as-group=$(g)) \
	--as-group=system:authenticated
RENDER_CMD := $(CROSSPLANE) composition render $(XR) \
	composition.yaml tests/functions.yaml --crossplane-version=v2.3.3 \
	--include-full-xr
PROFILE_ARGS := \
	--set-string hostName=robotics.openkubes.local \
	--set-string baseUrl=https://robotics.openkubes.local \
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

.PHONY: help validate claim-policy-check chart-check ready-check render render-check render-prerequisites \
	require-mgmt-context require-mgmt-approval require-explicit-cluster require-deploy-user \
	setup bind authz-check claim-admission-check deploy status undeploy

help: ## Show available local checks
	@awk 'BEGIN {FS = ":.*## "}; /^[a-zA-Z_-]+:.*## / {printf "  %-16s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

validate: claim-policy-check ## Parse YAML and verify scaffold safety invariants
	@$(PYTHON) -c 'import pathlib, sys, yaml; [list(yaml.safe_load_all(pathlib.Path(p).read_text())) for p in sys.argv[1:]]' $(YAML_FILES)
	@grep -q 'deletionPolicy: Orphan' composition.yaml
	@grep -Fq 'url: $(CHART_URL)' composition.yaml
	@! grep -q '\.invalid' composition.yaml
	@! grep -Eq '(PASSWD|Password):[[:space:]]+[^#[:space:]]' examples/ok-robotics.yaml
	@$(PYTHON) -c 'import pathlib, yaml; role = yaml.safe_load(pathlib.Path("rbac/claim-editor-role.yaml").read_text()); rules = role["rules"]; assert len(rules) == 1, rules; rule = rules[0]; assert rule["apiGroups"] == ["platform.openkubes.ai"], rule; assert rule["resources"] == ["openrmfclaims"], rule; assert "secrets" not in rule["resources"], rule'
	@$(PYTHON) -c 'import pathlib, yaml; b = yaml.safe_load(pathlib.Path("rbac/claim-editor-binding.yaml").read_text()); assert b["kind"] == "RoleBinding", b["kind"]; assert b["metadata"]["namespace"] == "openkubes-system", b["metadata"]; rr = b["roleRef"]; assert rr == {"kind": "Role", "name": "openrmf-claim-editor", "apiGroup": "rbac.authorization.k8s.io"}, rr; subs = b["subjects"]; assert len(subs) == 1, "exactly one subject is intended; widening the binding must be a reviewed edit, not an appended list item: %r" % subs; s = subs[0]; assert s == {"kind": "Group", "name": "oidc:openrmf-claim-editors", "apiGroup": "rbac.authorization.k8s.io"}, "the bound subject is pinned; note the oidc: prefix, without which it silently binds nobody: %r" % s'
	@$(PYTHON) -c 'import pathlib, yaml; c = yaml.safe_load(pathlib.Path("composition.yaml").read_text()); res = c["spec"]["pipeline"][0]["input"]["resources"][0]; fp = res["base"]["spec"]["forProvider"]; chart = fp["chart"]; assert chart == {"name": "openrmf-deployment", "version": "1.0.1", "url": "$(CHART_URL)"}, "pin chart name and version with its URL; stale late-initialized identity makes provider-helm upgrade forever: %r" % chart; kc = fp["values"]["keycloak"]; assert kc["enabled"] is False, "the profile-local Keycloak must stay disabled: RMF uses the one central Keycloak on ok-shared: %r" % kc; assert kc["issuer"] == "https://keycloak.ok-shared.internal/realms/rmf-web", kc["issuer"]; assert kc["externalUrl"].startswith("https://") and not kc["externalUrl"].endswith("/"), kc["externalUrl"]; assert kc["jwtPublicKey"].startswith("-----BEGIN PUBLIC KEY-----") and kc["jwtPublicKey"].rstrip().endswith("-----END PUBLIC KEY-----"), "jwtPublicKey must be a PEM public key or every login 401s with nothing logged"; keys = [s["valueFrom"]["secretKeyRef"]["key"] for s in fp["set"]]; assert not [k for k in keys if "keycloak" in k.lower()], "no keycloak credential belongs in the Secret contract once the bundled Keycloak is gone: %r" % keys'
	@echo "OK: YAML parses and local safety/chart-source/RBAC/central-identity guards are present"

claim-policy-check: ## Reject unauthorized Claim authority and prove local guards can fail
	@$(PYTHON) tests/claim-policy-check.py --negative-controls
	@$(PYTHON) tests/claim-policy-check.py

chart-check: ## Run local Helm lint/template for the simulation values profile
	@test -d "$(RMF_CHART)" || (echo "ERROR: RMF chart not found: $(RMF_CHART)"; exit 1)
	@$(HELM) lint "$(RMF_CHART)" $(PROFILE_ARGS)
	@set -Eeuo pipefail; output="$$(mktemp)"; trap 'rm -f "$$output"' EXIT; \
		$(HELM) template rmf "$(RMF_CHART)" $(PROFILE_ARGS) >"$$output" || \
			{ echo "ERROR: Helm template failed before local resource assertions" >&2; exit 1; }; \
		$(PYTHON) -c 'import pathlib, sys, yaml; docs = [d for d in yaml.safe_load_all(pathlib.Path(sys.argv[1]).read_text()) if isinstance(d, dict)]; assert docs, "Helm template rendered no Kubernetes resources"; forbidden = [d.get("kind") for d in docs if d.get("kind") in {"Certificate", "ServiceMonitor"}]; annotated = [d.get("metadata", {}).get("name") for d in docs if d.get("kind") == "IngressRoute" and "kubernetes.io/ingress.class" in d.get("metadata", {}).get("annotations", {})]; assert not forbidden, f"forbidden resources rendered: {forbidden}"; assert not annotated, f"IngressRoute class annotations rendered: {annotated}"' "$$output"
	@echo "OK: Helm lint/template and ingress/CRD guards passed locally"

ready-check: validate ## Verify the pinned published chart name and version
	@set -Eeuo pipefail; output="$$(mktemp)"; trap 'rm -f "$$output"' EXIT; \
		$(HELM) show chart "$(CHART_URL)" >"$$output" || \
			{ echo "ERROR: Helm could not fetch the pinned chart metadata" >&2; exit 1; }; \
		$(PYTHON) -c 'import pathlib, sys, yaml; chart = yaml.safe_load(pathlib.Path(sys.argv[1]).read_text()); assert isinstance(chart, dict), "Helm returned no chart metadata"; assert chart.get("name") == "openrmf-deployment", chart; assert chart.get("version") == "1.0.1", chart' "$$output"
	@echo "OK: published chart is reachable and pinned to openrmf-deployment 1.0.1"

render-prerequisites: ## Verify local Crossplane render dependencies
	@test -f "$(XR)" || { echo "ERROR: no XR fixture $(XR) for CLUSTER=$(CLUSTER). Without this the render error is piped into a YAML parser and resurfaces as a confusing parse failure. Add tests/xr-$(CLUSTER).yaml, or use a cluster that has one." >&2; exit 2; }
	@command -v "$(CROSSPLANE)" >/dev/null || (echo "ERROR: Crossplane CLI is required"; exit 1)
	@command -v "$(DOCKER)" >/dev/null || (echo "ERROR: Docker is required by Crossplane render"; exit 1)
	@$(DOCKER) info >/dev/null 2>&1 || (echo "ERROR: Docker daemon is unavailable; enable Docker integration before rendering"; exit 1)

render: render-prerequisites ## Render the representative XR locally (CLUSTER=ok-robotics)
	@$(RENDER_CMD)

render-check: render-prerequisites ## Render and verify the composed Helm Release (CLUSTER=ok-robotics)
	@set -Eeuo pipefail; output="$$(mktemp)"; trap 'rm -f "$$output"' EXIT; \
		$(RENDER_CMD) >"$$output" || \
			{ echo "ERROR: Crossplane render failed before rendered-Release assertions" >&2; exit 1; }; \
		$(PYTHON) -c 'import pathlib, sys, yaml; docs = [d for d in yaml.safe_load_all(pathlib.Path(sys.argv[1]).read_text()) if isinstance(d, dict)]; releases = [d for d in docs if d.get("apiVersion") == "helm.crossplane.io/v1beta1" and d.get("kind") == "Release"]; assert len(releases) == 1, releases; r = releases[0]; spec = r["spec"]; fp = spec["forProvider"]; assert r["metadata"]["name"] == "openrmf-$(CLUSTER)", r["metadata"]; assert r["metadata"]["annotations"]["crossplane.io/external-name"] == "rmf", r["metadata"]; assert spec["deletionPolicy"] == "Orphan", spec; assert spec["providerConfigRef"]["name"] == "$(CLUSTER)", spec; assert fp["chart"]["name"] == "openrmf-deployment" and fp["chart"]["version"] == "1.0.1" and fp["chart"]["url"] == "$(CHART_URL)", fp["chart"]; assert fp["namespace"] == "rmf", fp; refs = [v["valueFrom"]["secretKeyRef"] for v in fp["set"]]; assert len(refs) == 2, refs; assert all(v["name"] == "rmf-credentials" and v["namespace"] == "crossplane-system" for v in refs), refs' "$$output"
	@echo "OK: Composition rendered one safe, secret-referencing Helm Release for $(CLUSTER)"

# Read-only, so it gates authz-check too: a green authorization result about the
# wrong API server is worse than none.
require-mgmt-context:
	@test -r "$(MGMT_KUBECONFIG)" || { echo "ERROR: MGMT_KUBECONFIG is not readable: $(MGMT_KUBECONFIG)" >&2; exit 2; }
	@context="$$( $(MGMT_KUBECTL) config current-context )"; \
		cluster="$$( $(MGMT_KUBECTL) config view --minify -o jsonpath='{.clusters[0].name}' )"; \
		test "$$context" = "$(MGMT_CLUSTER)" || test "$$cluster" = "$(MGMT_CLUSTER)" || { \
		echo "ERROR: MGMT_KUBECONFIG identifies context '$$context' / cluster '$$cluster', not $(MGMT_CLUSTER)" >&2; exit 2; }

require-mgmt-approval: require-mgmt-context
	@test "$(APPROVE_MGMT)" = yes || { echo "ERROR: this target mutates $(MGMT_CLUSTER); review the manifests, then rerun with APPROVE_MGMT=yes" >&2; exit 2; }
	@test -t 0 || { echo "ERROR: unattended $(MGMT_CLUSTER) applies are forbidden; run this attended from a terminal" >&2; exit 2; }

# A management-plane mutation must name its target cluster rather than inherit a
# default, however sensible that default looks.
require-explicit-cluster:
	@test "$(origin CLUSTER)" != file || { echo "ERROR: name CLUSTER explicitly for this target, e.g. CLUSTER=ok-robotics; a mutating target must not inherit the default '$(CLUSTER)'" >&2; exit 2; }
	@test -f "examples/$(CLUSTER).yaml" || { echo "ERROR: no example Claim for CLUSTER=$(CLUSTER)" >&2; exit 2; }

require-deploy-user:
	@test -n "$(DEPLOY_USER)" || { echo "ERROR: set DEPLOY_USER to the real authenticated operator username for audit attribution" >&2; exit 2; }
	@test "$(DEPLOY_USER)" != "$(CLAIM_EDITOR_USER)" || { echo "ERROR: DEPLOY_USER must not be the synthetic authz-check identity $(CLAIM_EDITOR_USER)" >&2; exit 2; }
	@case "$(DEPLOY_USER)" in system:*|kubernetes-admin) echo "ERROR: DEPLOY_USER must be a non-privileged human identity, not $(DEPLOY_USER)" >&2; exit 2;; *[!A-Za-z0-9._:@/-]*) echo "ERROR: DEPLOY_USER contains unsupported characters" >&2; exit 2;; esac

setup: validate require-mgmt-approval ## APPROVAL: install Claim policy before serving the generic XRD
	@set -Eeuo pipefail; \
		for f in claim-admission-policy.yaml xrd.yaml composition.yaml; do \
			$(MGMT_KUBECTL) apply --dry-run=server -f "$$f" >/dev/null; \
			$(MGMT_KUBECTL) diff -f "$$f" && echo "  ($$f: no change)" || \
				{ rc=$$?; test $$rc -eq 1 || { echo "ERROR: kubectl diff failed on $$f (exit $$rc)" >&2; exit $$rc; }; }; \
		done; \
		claim_binding="$$($(MGMT_KUBECTL) get rolebinding/openrmf-claim-editor -n $(CLAIM_NAMESPACE) --ignore-not-found -o name)"; \
		if test -n "$$claim_binding"; then \
			if $(MGMT_KUBECTL) diff -f rbac/claim-editor-binding.yaml; then \
				echo "  (rbac/claim-editor-binding.yaml: no change)"; \
			else \
				rc=$$?; test $$rc -eq 1 || { echo "ERROR: kubectl diff failed on the live Claim RoleBinding (exit $$rc)" >&2; exit $$rc; }; \
				echo "ERROR: live Claim RoleBinding differs from the reviewed manifest; refusing to replace it during setup" >&2; exit 1; \
			fi; \
		fi; \
		read -r -p "Suspend Claim delegation, update and prove admission, then serve the generic XRD on $(MGMT_CLUSTER)? Type yes: " answer; \
		test "$$answer" = yes || { echo "Aborted." >&2; exit 1; }; \
		inventory="$$(mktemp)"; denial="$$(mktemp)"; probe="$$(mktemp)"; restored=false; \
		trap 'rc=$$?; rm -f "$$inventory" "$$denial" "$$probe"; if test $$rc -ne 0 && test -n "$$claim_binding" && test "$$restored" != true; then echo "SAFE FAILURE: Claim delegation remains suspended. After resolving the error, restore only with:" >&2; echo "  $(MGMT_KUBECTL) apply -f rbac/claim-editor-binding.yaml" >&2; fi; exit $$rc' EXIT; \
		if test -n "$$claim_binding"; then \
			$(MGMT_KUBECTL) delete rolebinding/openrmf-claim-editor -n $(CLAIM_NAMESPACE); \
			for verb in create update patch; do \
				test "$$($(MGMT_KUBECTL) auth can-i "$$verb" openrmfclaims.platform.openkubes.ai -n $(CLAIM_NAMESPACE) $(POS_ARGS))" = no || { echo "ERROR: delegated group can still $$verb OpenRMFClaims after RoleBinding suspension" >&2; exit 1; }; \
			done; \
			echo "  suspended and verified delegated Claim writes while changing the authorization map"; \
		fi; \
		claim_crd="$$($(MGMT_KUBECTL) get crd/openrmfclaims.platform.openkubes.ai --ignore-not-found -o name)"; \
		if test -n "$$claim_crd"; then $(MGMT_KUBECTL) get openrmfclaims.platform.openkubes.ai --all-namespaces -o json >"$$inventory"; else printf '%s\n' '{"items":[]}' >"$$inventory"; fi; \
		$(PYTHON) tests/claim-policy-check.py --claims-json "$$inventory"; \
		$(MGMT_KUBECTL) apply -f claim-admission-policy.yaml; \
		check_policy() { \
			for i in $$(seq 1 10); do generation="$$($(MGMT_KUBECTL) get validatingadmissionpolicy/openrmfclaim-authority.platform.openkubes.ai -o jsonpath='{.metadata.generation}')"; observed="$$($(MGMT_KUBECTL) get validatingadmissionpolicy/openrmfclaim-authority.platform.openkubes.ai -o jsonpath='{.status.observedGeneration}')"; test "$$observed" = "$$generation" && break; test "$$i" -lt 10 || { echo "ERROR: admission policy status did not observe generation $$generation" >&2; exit 1; }; sleep 1; done; \
			warnings="$$($(MGMT_KUBECTL) get validatingadmissionpolicy/openrmfclaim-authority.platform.openkubes.ai -o jsonpath='{range .status.typeChecking.expressionWarnings[*]}{.fieldRef}{": "}{.warning}{"\n"}{end}')"; \
			test -z "$$warnings" || { echo "ERROR: admission policy has CEL type-check warnings:" >&2; printf '%s\n' "$$warnings" >&2; exit 1; }; \
			$(MGMT_KUBECTL) get validatingadmissionpolicybinding/openrmfclaim-authority.platform.openkubes.ai >/dev/null; \
		}; \
		prove_admission() { \
			$(PYTHON) -c 'import pathlib, sys, yaml; obj = yaml.safe_load(pathlib.Path(sys.argv[1]).read_text()); obj["metadata"]["name"] = "ok-robotics-policy-setup-probe"; pathlib.Path(sys.argv[2]).write_text(yaml.safe_dump(obj, sort_keys=False))' examples/ok-robotics.yaml "$$probe"; \
			if $(MGMT_KUBECTL) create --dry-run=server -f "$$probe" --as=system:serviceaccount:crossplane-system:crossplane --as-group=system:serviceaccounts --as-group=system:serviceaccounts:crossplane-system --as-group=system:authenticated >/dev/null 2>"$$denial"; then echo "ERROR: admission policy did not deny an unmapped CREATE" >&2; exit 1; fi; \
			grep -Fq 'OpenRMFClaim allocation authorization denied' "$$denial" || { echo "ERROR: admission denial came from an unexpected guard:" >&2; cat "$$denial" >&2; exit 1; }; \
			echo "  admission guard denied an unmapped CREATE"; \
		}; \
		check_policy; \
		if test -n "$$claim_crd"; then prove_admission; fi; \
		$(MGMT_KUBECTL) apply -f xrd.yaml; \
		$(MGMT_KUBECTL) wait xrd/openrmfinstances.platform.openkubes.ai --for=condition=Established --timeout=60s; \
		$(MGMT_KUBECTL) patch validatingadmissionpolicy/openrmfclaim-authority.platform.openkubes.ai --type=json -p='[{"op":"replace","path":"/spec/validations/0/message","value":"OpenRMFClaim allocation authorization denied: post-XRD type-check recheck."}]' >/dev/null; \
		check_policy; \
		$(MGMT_KUBECTL) apply -f claim-admission-policy.yaml; \
		check_policy; \
		MGMT_KUBECTL="$(MGMT_KUBECTL)" $(PYTHON) tests/claim-admission-check.py --schema-only; \
		prove_admission; \
		$(MGMT_KUBECTL) apply -f composition.yaml; \
		if test -n "$$claim_binding"; then $(MGMT_KUBECTL) apply -f rbac/claim-editor-binding.yaml; echo "  restored delegated Claim writes after the authorization map passed"; fi; \
		restored=true
	@echo "OK: OpenRMF admission policy, XRD and Composition are current on $(MGMT_CLUSTER)."
	@echo "    Existing Claims reconcile against the new Composition revision on their own."
	@echo "    Safe rollback: retain this policy. To suspend delegation, remove the claim-editor"
	@echo "    RoleBinding first; policy removal is unsupported while the generic XRD is served."
	@echo "      $(MGMT_KUBECTL) delete rolebinding/openrmf-claim-editor -n $(CLAIM_NAMESPACE)"

bind: validate require-explicit-cluster require-mgmt-approval ## APPROVAL: apply the claim-only Role and its OIDC RoleBinding to ok-mgmt, then prove both authorization halves
	@set -Eeuo pipefail; \
		for f in rbac/claim-editor-role.yaml rbac/claim-editor-binding.yaml; do \
			$(MGMT_KUBECTL) apply --dry-run=server -f "$$f" >/dev/null; \
			$(MGMT_KUBECTL) diff -f "$$f" && echo "  ($$f: no change)" || \
				{ rc=$$?; test $$rc -eq 1 || { echo "ERROR: kubectl diff failed on $$f (exit $$rc)" >&2; exit $$rc; }; }; \
		done; \
		read -r -p "Apply the Role and RoleBinding diffed above to $(MGMT_CLUSTER)? Type yes: " answer; \
		test "$$answer" = yes || { echo "Aborted." >&2; exit 1; }; \
		$(MGMT_KUBECTL) apply -f rbac/claim-editor-role.yaml; \
		$(MGMT_KUBECTL) apply -f rbac/claim-editor-binding.yaml
	@$(MAKE) --no-print-directory authz-check CLUSTER=$(CLUSTER)

# Impersonation is resolved by the same authorizer a real bearer request reaches,
# so this is authoritative for RBAC and needs nobody's credentials. It does NOT
# exercise the token, the Keycloak mapper, or the client scope — a login whose
# token carries no groups claim would still be refused in practice while this
# passes. Authentication is evidenced separately on OK-99.
authz-check: require-mgmt-context ## Prove the claim-editor subject may create Claims and may not read Secrets
	@set -Eeuo pipefail; \
		for i in $$(seq 1 10); do \
			test "$$($(MGMT_KUBECTL) auth can-i create openrmfclaims.platform.openkubes.ai -n $(CLAIM_NAMESPACE) $(POS_ARGS))" = yes && break; \
			test "$$i" -lt 10 || { echo "ERROR: $(CLAIM_EDITOR_GROUPS) still cannot create openrmfclaims in $(CLAIM_NAMESPACE)" >&2; exit 1; }; \
			sleep 2; \
		done; \
		probe="$$(mktemp)"; \
		trap 'rm -f "$$probe"' EXIT; \
		if $(MGMT_KUBECTL) get openrmfclaim/$(CLUSTER) -n $(CLAIM_NAMESPACE) -o yaml >"$$probe" 2>/dev/null; then \
			$(MGMT_KUBECTL) replace --dry-run=server -f "$$probe" $(POS_ARGS) >/dev/null; \
		else \
			$(MGMT_KUBECTL) create --dry-run=server -f examples/$(CLUSTER).yaml $(POS_ARGS) >/dev/null; \
		fi; \
		for subject in "$(POS_ARGS)" "$(FULL_ARGS)"; do \
			for ns in $(CLAIM_NAMESPACE) crossplane-system kube-system default; do \
				test "$$($(MGMT_KUBECTL) auth can-i get secrets -n "$$ns" $$subject)" = no; \
				test "$$($(MGMT_KUBECTL) auth can-i list secrets -n "$$ns" $$subject)" = no; \
			done; \
			test "$$($(MGMT_KUBECTL) auth can-i create openrmfinstances.platform.openkubes.ai --all-namespaces $$subject)" = no; \
			test "$$($(MGMT_KUBECTL) auth can-i patch openrmfinstances.platform.openkubes.ai --all-namespaces $$subject)" = no; \
			test "$$($(MGMT_KUBECTL) auth can-i '*' '*' --all-namespaces $$subject)" = no; \
		done
	@echo "OK: $(CLAIM_EDITOR_GROUPS) may create OpenRMFClaims in $(CLAIM_NAMESPACE); admission"
	@echo "    dry-runs CREATE on bootstrap or unchanged UPDATE when the Claim already exists."
	@echo "    Secret get/list denied in $(CLAIM_NAMESPACE), crossplane-system, kube-system and"
	@echo "    default, and no blanket ('*' '*') grant — asserted both for the claim-editor group"
	@echo "    alone and with $(PEER_GROUPS) added; composite create/patch are also denied."
	@echo "    Namespaces are enumerated because a single"
	@echo "    --all-namespaces check would not detect a per-namespace RoleBinding."

claim-schema-check: require-mgmt-context ## Inspect every generated served Claim version and field after Crossplane changes
	@MGMT_KUBECTL="$(MGMT_KUBECTL)" $(PYTHON) tests/claim-admission-check.py --schema-only

claim-admission-check: require-mgmt-context ## Prove the live API rejects unauthorized Claim authority
	@MGMT_KUBECTL="$(MGMT_KUBECTL)" CLAIM_EDITOR_USER="$(CLAIM_EDITOR_USER)" \
		CLAIM_EDITOR_GROUPS="$(CLAIM_EDITOR_GROUPS)" \
		PEER_GROUPS="$(PEER_GROUPS)" \
		$(PYTHON) tests/claim-admission-check.py

deploy: validate require-explicit-cluster require-deploy-user require-mgmt-approval ## APPROVAL: submit the OpenRMFClaim for CLUSTER to ok-mgmt and wait for it to report Ready
	@set -Eeuo pipefail; \
		$(MGMT_KUBECTL) apply --dry-run=server -f examples/$(CLUSTER).yaml $(DEPLOY_ARGS) >/dev/null; \
		$(MGMT_KUBECTL) diff -f examples/$(CLUSTER).yaml $(DEPLOY_ARGS) && echo "  (no change)" || \
			{ rc=$$?; test $$rc -eq 1 || { echo "ERROR: kubectl diff failed (exit $$rc)" >&2; exit $$rc; }; }; \
		read -r -p "Submit the OpenRMFClaim for $(CLUSTER) as $(DEPLOY_USER) with $(CLAIM_EDITOR_GROUPS) to $(MGMT_CLUSTER)? Type yes: " answer; \
		test "$$answer" = yes || { echo "Aborted." >&2; exit 1; }; \
		$(MGMT_KUBECTL) apply -f examples/$(CLUSTER).yaml $(DEPLOY_ARGS)
	@echo "[open-rmf] Waiting for the Claim to report Synced and Ready..."
	@set -Eeuo pipefail; \
		$(MGMT_KUBECTL) wait --for=condition=Synced=True openrmfclaim/$(CLUSTER) -n $(CLAIM_NAMESPACE) --timeout=5m; \
		$(MGMT_KUBECTL) wait --for=condition=Ready=True openrmfclaim/$(CLUSTER) -n $(CLAIM_NAMESPACE) --timeout=5m; \
		ref="$$($(MGMT_KUBECTL) get openrmfclaim $(CLUSTER) -n $(CLAIM_NAMESPACE) -o jsonpath='{.spec.resourceRef.name}')"; \
		test -n "$$ref" || { echo "ERROR: the Claim reports Ready but references no composite" >&2; exit 1; }; \
		owner="$$($(MGMT_KUBECTL) get release.helm.crossplane.io openrmf-$(CLUSTER) -o jsonpath='{.metadata.ownerReferences[0].name}')"; \
		test "$$owner" = "$$ref" || { echo "ERROR: Release openrmf-$(CLUSTER) is owned by '$$owner', not by this Claim's composite '$$ref'. Because deletionPolicy is Orphan, that is a leftover Release from an earlier run, not the resource this one created." >&2; exit 1; }; \
		echo "  composite $$ref owns Release openrmf-$(CLUSTER)"
	@$(MAKE) --no-print-directory status CLUSTER=$(CLUSTER)
	@$(MAKE) --no-print-directory claim-admission-check

status: require-mgmt-context ## Show Claim, composite, and composed Release state for CLUSTER
	@echo "=== OpenRMFClaim ($(CLAIM_NAMESPACE)) ==="
	@$(MGMT_KUBECTL) get openrmfclaim $(CLUSTER) -n $(CLAIM_NAMESPACE) || echo "  no Claim for '$(CLUSTER)'"
	@echo "=== OpenRMFInstance (composite) ==="
	@$(MGMT_KUBECTL) get openrmfinstance -l crossplane.io/claim-name=$(CLUSTER) || echo "  no composite"
	@echo "=== Helm Release (on $(MGMT_CLUSTER)) ==="
	@$(MGMT_KUBECTL) get release.helm.crossplane.io openrmf-$(CLUSTER) || echo "  no Release"

undeploy: require-explicit-cluster require-mgmt-approval ## APPROVAL: delete the OpenRMFClaim for CLUSTER; the Orphan Release is reported, never deleted
	@set -Eeuo pipefail; \
		read -r -p "Delete OpenRMFClaim $(CLUSTER) from $(MGMT_CLUSTER)? Type yes: " answer; \
		test "$$answer" = yes || { echo "Aborted." >&2; exit 1; }; \
		$(MGMT_KUBECTL) delete openrmfclaim $(CLUSTER) -n $(CLAIM_NAMESPACE) --ignore-not-found
	@echo "NOTE: deletionPolicy is Orphan. The composed Release object on $(MGMT_CLUSTER), and the"
	@echo "      rmf namespace it installed on $(CLUSTER), both SURVIVE this deletion. Removing"
	@echo "      them destroys data and is deliberately not automated. Name the kubeconfig"
	@echo "      explicitly so it cannot act on whichever context happens to be current:"
	@echo "        kubectl --kubeconfig $(MGMT_KUBECONFIG) delete release.helm.crossplane.io openrmf-$(CLUSTER)"
	@$(MGMT_KUBECTL) get release.helm.crossplane.io openrmf-$(CLUSTER) || echo "  (no Release object present)"

.DEFAULT_GOAL := help
