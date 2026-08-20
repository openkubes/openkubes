SHELL := /bin/bash
export PYTHONDONTWRITEBYTECODE := 1

PYTHON ?= python3
CROSSPLANE ?= crossplane
DOCKER ?= docker
KUBECTL ?= kubectl
MGMT_CLUSTER ?= ok-mgmt
MGMT_KUBECONFIG ?=
APPROVE_MGMT ?= no
ACCEPT_PROTOTYPE_LIMITS ?= no
CLUSTER ?= ok-robotics
PROBE_NAMESPACE ?=
PROBE_CNPG_CLUSTER ?=
PROBE_CAPABILITY ?= pgvector
CLAIM_NAMESPACE ?= openkubes-system
DEPLOY_USER ?=
CLAIM_EDITOR_GROUP ?= oidc:database-claim-editors

XR_DEVELOPMENT := crossplane/tests/xr-ok-robotics.yaml
XR_PRODUCTION := crossplane/tests/xr-ok-robotics-production.yaml
COMPOSITION := crossplane/composition.yaml
FUNCTIONS := crossplane/tests/functions.yaml
RENDER_BASE := $(CROSSPLANE) composition render
RENDER_FLAGS := --crossplane-version=v2.3.3
YAML_FILES := crossplane/xrd.yaml crossplane/composition.yaml \
	crossplane/restoreverified-crd.yaml \
	crossplane/claim-admission-policy.yaml \
	crossplane/rbac/claim-editor-role.yaml crossplane/rbac/claim-editor-binding.yaml \
	crossplane/rbac/restoreverified-writer-clusterrole.yaml \
	crossplane/rbac/restoreverified-writer-clusterrolebinding.yaml \
	crossplane/rbac/restoreverified-reader-clusterrole.yaml \
	crossplane/rbac/restoreverified-reader-clusterrolebinding.yaml \
	crossplane/examples/ok-robotics.yaml crossplane/tests/functions.yaml \
	crossplane/tests/xr-ok-robotics.yaml crossplane/tests/xr-ok-robotics-production.yaml \
	crossplane/tests/observed-ok-robotics-valid.yaml \
	crossplane/tests/restoreverified-ok-robotics.yaml \
	drill/recovery-cluster.template.yaml
JSON_FILES := drill/minio-policy-backups-readonly.json \
	drill/minio-policy-backups-ok-robotics-writer.json \
	drill/minio-policy-drill-write.json

.PHONY: help validate render-prerequisites render render-check claim-policy-check \
	claim-authority-model-check claim-admission-check evidence-status-check \
	restoreverified-api-check api-acceptance-check drill-validate drill-policy-check minio-provisioning-check \
	restore-evidence-check \
	require-mgmt-context require-mgmt-approval require-explicit-cluster require-deploy-user \
	setup bind deploy status undeploy

help: ## Show available targets
	@awk 'BEGIN {FS = ":.*##"; printf "Targets:\n"} /^[a-zA-Z0-9_.-]+:.*##/ {printf "  %-24s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

validate: ## Parse all local artifacts and run static contract guards
	@$(PYTHON) -c 'import pathlib, yaml; files="$(YAML_FILES)".split(); [list(yaml.safe_load_all(pathlib.Path(f).read_text())) for f in files]; print("OK: parsed %d YAML files" % len(files))'
	@$(PYTHON) -c 'import json, pathlib; files="$(JSON_FILES)".split(); [json.loads(pathlib.Path(f).read_text()) for f in files]; print("OK: parsed %d JSON policies" % len(files))'
	@$(PYTHON) -c 'import ast, pathlib; files=list(pathlib.Path("crossplane/tests").glob("*.py"))+list(pathlib.Path("drill/tests").glob("*.py")); [ast.parse(f.read_text(), filename=str(f)) for f in files]; print("OK: parsed %d Python files" % len(files))'
	@$(PYTHON) -c 'import pathlib; roots=(pathlib.Path("crossplane"), pathlib.Path("drill")); bad=sorted(str(p) for root in roots for p in root.rglob("*") if p.name in {"__pycache__", ".pytest_cache", "build", "dist"} or p.suffix in {".pyc", ".pyo", ".class", ".o", ".so"}); assert not bad, "generated/build artifacts present: " + ", ".join(bad); print("OK: no Python caches or build artifacts in the capability tree")'
	@bash -n drill/run-restore-drill.sh
	@bash -n probe/pgvector-probe.sh
	@$(MAKE) --no-print-directory claim-policy-check claim-authority-model-check \
		claim-admission-check restoreverified-api-check evidence-status-check drill-validate \
		drill-policy-check minio-provisioning-check restore-evidence-check
	@echo "OK: all offline validation targets are wired and completed or explicitly skipped"

render-prerequisites: ## Verify the local Crossplane render toolchain
	@command -v "$(CROSSPLANE)" >/dev/null || { echo "ERROR: Crossplane CLI is required" >&2; exit 1; }
	@command -v "$(DOCKER)" >/dev/null || { echo "ERROR: Docker is required by Crossplane render" >&2; exit 1; }
	@$(DOCKER) info >/dev/null 2>&1 || { echo "ERROR: Docker daemon is unavailable" >&2; exit 1; }
	@test -f "$(XR_DEVELOPMENT)" -a -f "$(XR_PRODUCTION)" -a -f "$(COMPOSITION)" -a -f "$(FUNCTIONS)"

render: render-prerequisites ## Render both development and production fixtures locally
	@set -Eeuo pipefail; \
		for fixture in "$(XR_DEVELOPMENT)" "$(XR_PRODUCTION)"; do \
			echo "=== $$fixture ==="; \
			$(RENDER_BASE) "$$fixture" "$(COMPOSITION)" "$(FUNCTIONS)" $(RENDER_FLAGS); \
		done

render-check: render-prerequisites ## Render both fixtures and assert Objects and t=0 evidence
	@set -Eeuo pipefail; work="$$(mktemp -d)"; trap 'rm -rf -- "$$work"' EXIT; \
		$(RENDER_BASE) "$(XR_DEVELOPMENT)" "$(COMPOSITION)" "$(FUNCTIONS)" $(RENDER_FLAGS) >"$$work/development.yaml"; \
		$(PYTHON) crossplane/tests/render-check.py "$$work/development.yaml" --policy development; \
		$(RENDER_BASE) "$(XR_PRODUCTION)" "$(COMPOSITION)" "$(FUNCTIONS)" $(RENDER_FLAGS) >"$$work/production.yaml"; \
		$(PYTHON) crossplane/tests/render-check.py "$$work/production.yaml" --policy production; \
		$(RENDER_BASE) "$(XR_DEVELOPMENT)" "$(COMPOSITION)" "$(FUNCTIONS)" $(RENDER_FLAGS) \
			--include-full-xr --observed-resources=crossplane/tests/observed-ok-robotics-valid.yaml >"$$work/observed.yaml"; \
		$(PYTHON) crossplane/tests/render-check.py "$$work/observed.yaml" --policy development \
			--expected-protection-state Unknown --expected-protection-reason BackupAvailabilityUnproven; \
		$(PYTHON) crossplane/tests/evidence-status-check.py "$$work/observed.yaml"

claim-policy-check: ## Prove authority guards fail, then validate the reviewed tuple
	@$(PYTHON) crossplane/tests/claim-policy-check.py --negative-controls
	@$(PYTHON) crossplane/tests/claim-policy-check.py

claim-authority-model-check: ## Exercise the local authority model (not Kubernetes admission)
	@$(PYTHON) crossplane/tests/claim-authority-model-check.py --negative-controls
	@$(PYTHON) crossplane/tests/claim-authority-model-check.py

# Real admission: installs the generated DatabaseClaim CRD, the policy, its binding and the
# claim-editor RBAC on a DISPOSABLE API server, then submits claims under impersonated identities
# and asserts the SERVER's verdict. claim-authority-model-check only compares a tuple to the tuple
# it parsed from the same file — it would pass with the policy deleted. This target would not.
# Skips loudly when no API server is reachable; it never prints OK on the strength of nothing.
claim-admission-check: ## Prove real API-server admission for the authority tuple
	@API_CONTEXT=$(API_CONTEXT) bash crossplane/tests/claim-admission-live.sh

restoreverified-api-check: ## Validate immutable evidence schema and least-privilege RBAC
	@$(PYTHON) -c 'import pathlib,yaml; load=lambda p: yaml.safe_load(pathlib.Path(p).read_text()); c=load("crossplane/restoreverified-crd.yaml"); root=c["spec"]["versions"][0]["schema"]["openAPIV3Schema"]; s=root["properties"]["spec"]; checks=s["properties"]["checks"]; item=checks["items"]; observed=item["properties"]["observed"]; writer=load("crossplane/rbac/restoreverified-writer-clusterrole.yaml"); wb=load("crossplane/rbac/restoreverified-writer-clusterrolebinding.yaml"); reader=load("crossplane/rbac/restoreverified-reader-clusterrole.yaml"); rb=load("crossplane/rbac/restoreverified-reader-clusterrolebinding.yaml"); expected={"outside-recovery","known-row-readable","restore-probe-heap-readable","primary-key-index-readable","selected-backup-object-readable"}; observed_fields={"pgIsInRecovery","matchingRows","marker","rowCount","minimumId","maximumId","indexName","indexValid","indexReady","object","sha256"}; assert c["spec"]["scope"]=="Cluster"; assert not root.get("x-kubernetes-validations"), "no ROOT-level CEL: the root sees only metadata.name/generateName, so a labels rule makes the API server reject the whole CRD"; assert "self == oldSelf" in [v["rule"] for v in s["x-kubernetes-validations"]]; assert {"backupRef","sourceClusterRef","databaseRef"} <= set(s["required"]); assert checks["minItems"]==checks["maxItems"]==5 and checks["x-kubernetes-list-map-keys"]==["name"] and set(item["properties"]["name"]["enum"])==expected; assert "observed" in item["required"] and observed["minProperties"]==1 and set(observed["properties"])==observed_fields; assert "additionalProperties" not in observed, "additionalProperties beside properties is forbidden in a structural schema; pruning already closes the object"; assert writer["rules"]==[{"apiGroups":["evidence.platform.openkubes.ai"],"resources":["restoreverifieds"],"verbs":["create","get","list","watch"]}]; assert wb["subjects"]==[{"kind":"Group","name":"oidc:database-restore-verifiers","apiGroup":"rbac.authorization.k8s.io"}]; assert reader["rules"]==[{"apiGroups":["evidence.platform.openkubes.ai"],"resources":["restoreverifieds"],"verbs":["get","list","watch"]}]; assert rb["subjects"]==[{"kind":"ServiceAccount","name":"crossplane","namespace":"crossplane-system"}]; print("OK: RestoreVerified schema SHAPE is immutable, UID-bound, exact-check and observed-value closed; RBAC least-privilege. NOTE: this reads the file only — run api-acceptance-check for the API server verdict")'

# The only honest verdict on a CRD/policy is an API server's. The file-reading check above once
# certified a CRD that every API server rejects (illegal `additionalProperties` beside `properties`,
# and a root CEL rule reading metadata.labels, which the root cannot see). This target asks a server.
# It SKIPS LOUDLY when none is reachable — it never prints OK on the strength of nothing.
API_CONTEXT ?= docker-desktop
api-acceptance-check: ## Dry-run generated XRD CRDs, evidence CRD, policy and RBAC against a real API server
	@set -Eeuo pipefail; \
		if ! kubectl --context $(API_CONTEXT) get --raw /readyz >/dev/null 2>&1; then \
			printf 'SKIPPED: no API server on context %s — schema acceptance is UNVERIFIED, not OK.\n' '$(API_CONTEXT)' >&2; \
			printf '         Start one (Docker Desktop Kubernetes, kind, minikube) and rerun, or pass API_CONTEXT=<ctx>.\n' >&2; \
			exit 0; \
		fi; \
		printf '  generated Database/DatabaseClaim CRDs: '; \
		$(CROSSPLANE) xrd convert crossplane/xrd.yaml | \
			$(PYTHON) -c 'import sys,yaml; docs=list(yaml.safe_load_all(sys.stdin)); [d.get("metadata", {}).pop("ownerReferences", None) for d in docs]; yaml.safe_dump_all(docs, sys.stdout, sort_keys=False)' | \
			kubectl --context $(API_CONTEXT) apply --dry-run=server -f - >/dev/null; \
		printf 'accepted\n'; \
		for f in crossplane/restoreverified-crd.yaml crossplane/claim-admission-policy.yaml \
		         crossplane/rbac/restoreverified-writer-clusterrole.yaml \
		         crossplane/rbac/restoreverified-reader-clusterrole.yaml; do \
			printf '  %s: ' "$$f"; \
			kubectl --context $(API_CONTEXT) apply --dry-run=server -f "$$f" >/dev/null; \
			printf 'accepted\n'; \
		done; \
		echo "OK: the API server accepted generated XRD CRDs, the evidence CRD, the admission policy and the RBAC"

evidence-status-check: ## Prove rendered state reachability and the production policy boundary
	@set -Eeuo pipefail; \
		$(PYTHON) crossplane/tests/evidence-status-check.py --self-test & core_pid=$$!; \
		$(PYTHON) crossplane/tests/evidence-status-check.py --self-test --self-test-group edges & edge_pid=$$!; \
		wait $$core_pid; wait $$edge_pid

drill-validate: ## Parse and render the unexecuted recovery-drill scaffold
	@bash -n drill/run-restore-drill.sh
	@$(PYTHON) -c 'import ast, pathlib; files=list(pathlib.Path("drill/tests").glob("*.py")); [ast.parse(f.read_text(), filename=str(f)) for f in files]'
	@$(PYTHON) drill/tests/render-recovery-cluster-check.py --negative-controls
	@$(PYTHON) drill/tests/render-recovery-cluster-check.py
	@echo "OK: drill shell/Python syntax and recovery template guards passed"

drill-policy-check: ## Prove the isolation checker rejects mutation and overlap
	@$(PYTHON) drill/tests/isolation-policy-check.py --negative-controls
	@$(PYTHON) drill/tests/isolation-policy-check.py

minio-provisioning-check: ## Prove the pinned MinIO scaffold and credential boundary
	@$(PYTHON) drill/tests/minio-provisioning-check.py --negative-controls
	@$(PYTHON) drill/tests/minio-provisioning-check.py

restore-evidence-check: ## Generate and reject malformed RestoreVerified evidence locally
	@$(PYTHON) drill/tests/restore-evidence-check.py --negative-controls
	@$(PYTHON) drill/tests/restore-evidence-check.py

# Runs against a LIVE cluster, so it is not part of the offline validate list; validate only
# syntax-checks it. Emits a CapabilityVerified artifact on stdout — the CRD that admits that
# artifact lands with OK-150, so on this branch the probe's verdict and exit code are the usable
# output and the artifact is a forward reference.
capability-probe: ## Run the functional capability probe against a live CNPG cluster (PROBE_NAMESPACE, PROBE_CNPG_CLUSTER)
	@test -n "$(PROBE_NAMESPACE)" || { echo "ERROR: name PROBE_NAMESPACE explicitly" >&2; exit 2; }
	@test -n "$(PROBE_CNPG_CLUSTER)" || { echo "ERROR: name PROBE_CNPG_CLUSTER explicitly" >&2; exit 2; }
	@bash probe/pgvector-probe.sh "$(PROBE_NAMESPACE)" "$(PROBE_CNPG_CLUSTER)" "$(PROBE_CAPABILITY)"

require-mgmt-context:
	@test -n "$(MGMT_KUBECONFIG)" -a -r "$(MGMT_KUBECONFIG)" || { echo "ERROR: set MGMT_KUBECONFIG to a readable ok-mgmt kubeconfig" >&2; exit 2; }
	@context="$$( $(KUBECTL) --kubeconfig "$(MGMT_KUBECONFIG)" config current-context )"; \
		cluster="$$( $(KUBECTL) --kubeconfig "$(MGMT_KUBECONFIG)" config view --minify -o jsonpath='{.clusters[0].name}' )"; \
		test "$$context" = "$(MGMT_CLUSTER)" || test "$$cluster" = "$(MGMT_CLUSTER)" || { \
			echo "ERROR: kubeconfig identifies '$$context'/'$$cluster', not $(MGMT_CLUSTER)" >&2; exit 2; }

require-mgmt-approval: require-mgmt-context
	@test "$(APPROVE_MGMT)" = yes || { echo "ERROR: this target mutates $(MGMT_CLUSTER); rerun with APPROVE_MGMT=yes after review" >&2; exit 2; }
	@test -t 0 || { echo "ERROR: unattended $(MGMT_CLUSTER) applies are forbidden" >&2; exit 2; }

require-explicit-cluster:
	@test "$(origin CLUSTER)" != file || { echo "ERROR: name CLUSTER explicitly, for example CLUSTER=ok-robotics" >&2; exit 2; }
	@test -f "crossplane/examples/$(CLUSTER).yaml" || { echo "ERROR: no example Claim for CLUSTER=$(CLUSTER)" >&2; exit 2; }

require-deploy-user:
	@test -n "$(DEPLOY_USER)" || { echo "ERROR: set DEPLOY_USER to the authenticated non-privileged operator" >&2; exit 2; }
	@case "$(DEPLOY_USER)" in system:*|kubernetes-admin|*[!A-Za-z0-9._:@/-]*) echo "ERROR: unsafe DEPLOY_USER $(DEPLOY_USER)" >&2; exit 2;; esac

# Install order is deliberate, mirroring platform/robotics/open-rmf: the authority policy goes on
# BEFORE the XRD is served, so no window exists in which a DatabaseClaim could be created without
# the tuple in force. The API server's own CEL type-checking is then confirmed before the Composition
# lands: warnings there mean the expressions reference fields the schema lacks, which no offline
# model can detect (claim-authority-model-check would pass with the policy deleted).
#
# ACCEPT_PROTOTYPE_LIMITS is a SECOND acknowledgement, separate from APPROVE_MGMT. ADR-Platform-032
# is Accepted *architecturally* with four open bounds; installing means accepting them knowingly, so
# the gate names them rather than letting a successful install imply they are closed.
setup: validate require-mgmt-approval ## APPROVAL: install policy, evidence CRD, ProviderConfig, XRD and Composition
	@test "$(ACCEPT_PROTOTYPE_LIMITS)" = yes || { \
		echo "ERROR: this installs a capability with four open bounds (ADR-Platform-032 §13):" >&2; \
		echo "         1. no automated RestoreVerified collection — an operator admits evidence by hand" >&2; \
		echo "         2. no scheduled-Backup enumeration — the fixed evidence Backup is the anchor" >&2; \
		echo "         3. capability delivery unproven — pgvector needs the ImageVolume feature gate" >&2; \
		echo "         4. ProtectionReady is NOT an RPO bound (§10)" >&2; \
		echo "       Rerun with ACCEPT_PROTOTYPE_LIMITS=yes to install knowing these." >&2; exit 2; }
	@set -Eeuo pipefail; \
		MK="$(KUBECTL) --kubeconfig $(MGMT_KUBECONFIG)"; \
		POLICY=databaseclaim-authority.platform.openkubes.ai; \
		for f in crossplane/claim-admission-policy.yaml crossplane/restoreverified-crd.yaml \
		         crossplane/rbac/restoreverified-writer-clusterrole.yaml \
		         crossplane/rbac/restoreverified-writer-clusterrolebinding.yaml \
		         crossplane/rbac/restoreverified-reader-clusterrole.yaml \
		         crossplane/rbac/restoreverified-reader-clusterrolebinding.yaml \
		         crossplane/providerconfig-ok-robotics.yaml \
		         crossplane/xrd.yaml crossplane/composition.yaml; do \
			$$MK apply --dry-run=server -f "$$f" >/dev/null; \
			if $$MK diff -f "$$f" >/dev/null 2>&1; then echo "  ($$f: no change)"; else echo "  ($$f: will change)"; fi; \
		done; \
		read -r -p "Install the authority policy, evidence CRD, ProviderConfig, XRD and Composition on $(MGMT_CLUSTER)? Type yes: " answer; \
		test "$$answer" = yes || { echo "Aborted." >&2; exit 1; }; \
		$$MK apply -f crossplane/claim-admission-policy.yaml; \
		for i in $$(seq 1 15); do \
			gen="$$($$MK get validatingadmissionpolicy $$POLICY -o jsonpath='{.metadata.generation}')"; \
			obs="$$($$MK get validatingadmissionpolicy $$POLICY -o jsonpath='{.status.observedGeneration}')"; \
			test "$$gen" = "$$obs" -a -n "$$obs" && break; sleep 2; \
		done; \
		warn="$$($$MK get validatingadmissionpolicy $$POLICY -o jsonpath='{range .status.typeChecking.expressionWarnings[*]}{.fieldRef}{": "}{.warning}{"\n"}{end}')"; \
		test -z "$$warn" || { printf 'ERROR: the API server reports CEL type-check warnings; refusing to serve the XRD behind a policy it cannot evaluate:\n%s\n' "$$warn" >&2; exit 1; }; \
		echo "  authority policy compiled with no CEL type-check warnings"; \
		$$MK apply -f crossplane/restoreverified-crd.yaml; \
		$$MK wait --for=condition=Established crd/restoreverifieds.evidence.platform.openkubes.ai --timeout=60s; \
		for f in crossplane/rbac/restoreverified-writer-clusterrole.yaml \
		         crossplane/rbac/restoreverified-writer-clusterrolebinding.yaml \
		         crossplane/rbac/restoreverified-reader-clusterrole.yaml \
		         crossplane/rbac/restoreverified-reader-clusterrolebinding.yaml \
		         crossplane/providerconfig-ok-robotics.yaml; do $$MK apply -f "$$f"; done; \
		$$MK apply -f crossplane/xrd.yaml; \
		$$MK wait xrd/databases.platform.openkubes.ai --for=condition=Established --timeout=120s; \
		$$MK apply -f crossplane/composition.yaml
	@echo "OK: installed on $(MGMT_CLUSTER)."
	@echo "    Next: make bind APPROVE_MGMT=yes   (delegate DatabaseClaim authority)"
	@echo "    Then: make deploy CLUSTER=ok-robotics APPROVE_MGMT=yes DEPLOY_USER=<your-oidc-user>"

# Delegating claim authority is separate from installing the capability, because it hands a group the
# power to create Databases. It also PROVES both halves afterwards: that the editor group can create
# its authorized claim, and that it cannot read Secrets. A binding that grants the verb without the
# tuple, or with Secret access, is worse than no delegation.
bind: validate require-mgmt-approval ## APPROVAL: delegate DatabaseClaim authority, then prove both halves
	@set -Eeuo pipefail; \
		MK="$(KUBECTL) --kubeconfig $(MGMT_KUBECONFIG)"; \
		for f in crossplane/rbac/claim-editor-role.yaml crossplane/rbac/claim-editor-binding.yaml; do \
			$$MK apply --dry-run=server -f "$$f" >/dev/null; \
		done; \
		read -r -p "Delegate DatabaseClaim authority to oidc:database-claim-editors on $(MGMT_CLUSTER)? Type yes: " answer; \
		test "$$answer" = yes || { echo "Aborted." >&2; exit 1; }; \
		$$MK apply -f crossplane/rbac/claim-editor-role.yaml; \
		$$MK apply -f crossplane/rbac/claim-editor-binding.yaml; \
		AS="--as=oidc:bind-probe --as-group=oidc:database-claim-editors --as-group=system:authenticated"; \
		test "$$($$MK auth can-i create databaseclaims.platform.openkubes.ai -n $(CLAIM_NAMESPACE) $$AS)" = yes \
			|| { echo "ERROR: the delegated group cannot create DatabaseClaims — the binding did not take" >&2; exit 1; }; \
		for ns in $(CLAIM_NAMESPACE) crossplane-system kube-system default; do \
			test "$$($$MK auth can-i get secrets -n "$$ns" $$AS)" = no \
				|| { echo "ERROR: the claim editor can read Secrets in $$ns" >&2; exit 1; }; \
		done; \
		test "$$($$MK auth can-i create databases.platform.openkubes.ai --all-namespaces $$AS)" = no \
			|| { echo "ERROR: the claim editor can create composites directly, bypassing the admission tuple" >&2; exit 1; }
	@echo "OK: authority delegated and both halves proven — the group may create its authorized"
	@echo "    DatabaseClaim, and cannot read Secrets or create Databases directly."

# Submitting the claim is the last step and the only one that creates workload state. DEPLOY_USER is
# required for audit attribution and must be a real, non-privileged identity.
deploy: validate require-explicit-cluster require-deploy-user require-mgmt-approval ## APPROVAL: submit the DatabaseClaim for CLUSTER
	@set -Eeuo pipefail; \
		MK="$(KUBECTL) --kubeconfig $(MGMT_KUBECONFIG)"; \
		AS="--as=$(DEPLOY_USER) --as-group=oidc:database-claim-editors --as-group=system:authenticated"; \
		$$MK apply --dry-run=server -f "crossplane/examples/$(CLUSTER).yaml" $$AS >/dev/null; \
		read -r -p "Submit the DatabaseClaim for $(CLUSTER) as $(DEPLOY_USER)? Type yes: " answer; \
		test "$$answer" = yes || { echo "Aborted." >&2; exit 1; }; \
		$$MK apply -f "crossplane/examples/$(CLUSTER).yaml" $$AS; \
		$$MK wait --for=condition=Synced=True databaseclaim/$(CLUSTER) -n $(CLAIM_NAMESPACE) --timeout=5m || true; \
		$$MK get databaseclaim $(CLUSTER) -n $(CLAIM_NAMESPACE) -o wide; \
			echo "  Database composite (the drill needs BOTH name and uid):"; \
		ref="$$($$MK get databaseclaim $(CLUSTER) -n $(CLAIM_NAMESPACE) -o jsonpath='{.spec.resourceRef.name}')"; \
		printf '    --database-name %s\n' "$$ref"; \
		printf '    --database-uid  %s\n' "$$($$MK get database "$$ref" -o jsonpath='{.metadata.uid}')"
	@echo "NOTE: evidence does not appear on its own. RecoveryAssured=Valid requires a drill run and"
	@echo "      an operator-created RestoreVerified CR (ADR-Platform-032 §11.2); see drill/README.md."

status: require-mgmt-context ## Read DatabaseClaim and Database state from ok-mgmt
	@$(KUBECTL) --kubeconfig "$(MGMT_KUBECONFIG)" get databaseclaims -n "$(CLAIM_NAMESPACE)"
	@$(KUBECTL) --kubeconfig "$(MGMT_KUBECONFIG)" get databases

undeploy: require-explicit-cluster require-mgmt-approval ## APPROVAL: delete only the Claim; composed state stays orphaned
	@read -r -p "Delete DatabaseClaim $(CLUSTER) from $(MGMT_CLUSTER)? Type yes: " answer; test "$$answer" = yes
	@$(KUBECTL) --kubeconfig "$(MGMT_KUBECONFIG)" delete databaseclaim "$(CLUSTER)" -n "$(CLAIM_NAMESPACE)" --ignore-not-found
	@echo "NOTE: stateful provider-kubernetes Objects use deletionPolicy=Orphan; this target does not delete CNPG Clusters or PVCs."

.DEFAULT_GOAL := help
