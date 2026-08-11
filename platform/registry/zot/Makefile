SHELL := /bin/bash

KUBECTL ?= kubectl
HELM ?= helm
PYTHON ?= python3
JQ ?= jq
TIMEOUT ?= timeout

CLUSTER ?= ok-shared
NAMESPACE ?= zot
KUBECONFIG ?=
CONFIRM ?=
APPROVE_OIDC_CLIENT ?=

WORKSPACE ?= $(abspath $(CURDIR)/../../../..)
CHART_DIR ?= $(WORKSPACE)/zot/charts/zot
CHART_TAG ?= zot-0.1.122
VALUES_FILE ?= $(CURDIR)/values-ok-shared.yaml
MANIFESTS ?= $(CURDIR)/manifests
TOOLING ?= $(CURDIR)/tooling
CONFORMANCE ?= $(CURDIR)/conformance

NAMESPACE_TEMPLATE ?= $(MANIFESTS)/namespace.template.yaml
IDENTITIES_TEMPLATE ?= $(MANIFESTS)/identities.template.yaml
REACHABILITY_TEMPLATE ?= $(MANIFESTS)/reachability.template.yaml
METRICS_TEMPLATE ?= $(MANIFESTS)/metrics.template.yaml
SECRETS_SCRIPT ?= $(TOOLING)/reconcile-secrets.sh
OIDC_SCRIPT ?= $(TOOLING)/oidc-client.sh
POST_CHECK_SCRIPT ?= $(TOOLING)/post-check.sh
CONTRACT_JOB_SCRIPT ?= $(TOOLING)/in-cluster-contract.sh
OIDC_CONFORMANCE_SCRIPT ?= $(TOOLING)/oidc-conformance.sh
ZOTCTL ?= $(TOOLING)/zotctl.py

TAR ?= tar
BACKUP_DIR ?=
RELEASE_SET ?=
TRANSFER_DIR ?=
TRANSFER_ARTIFACT ?=
TRANSFER_INTEGRITY_MANIFEST ?=
RESTORE_ARTIFACT ?=
INTEGRITY_MANIFEST ?=
APPROVE_RESTORE_DRILL ?=
RETAIN_SCRATCH ?= no
SCRATCH_NAMESPACE ?=
SCRATCH_RELEASE ?= zot-restore-drill
OCI_PAGE_SIZE ?= 1000

RELEASE ?= zot
REGISTRY_HOST ?= registry.ok-shared.internal
REGISTRY_ORIGIN ?= https://$(REGISTRY_HOST)
# Discovered by tooling/registry-defaults.sh: DNS first (OK-57), else the LoadBalancer
# address the infrastructure cluster publishes for this cluster's ingress. Set it here or
# in the environment only to override that discovery.
REGISTRY_LB ?=
REGISTRY_LB_KUBECONFIG ?= $(HOME)/.kube/ok-infra.yaml

# The registry pod must resolve the Keycloak hostname to validate OIDC, because the issuer is the
# public name. It is aliased to this cluster's ingress ClusterIP, discovered at run time: that
# keeps the call inside the cluster instead of hairpinning out to the infrastructure VIP and back,
# and keeps this estate's addresses out of a public repository. Set KEYCLOAK_ALIAS_IP to override.
INGRESS_SERVICE ?= traefik
INGRESS_NAMESPACE ?= ingress
KEYCLOAK_ALIAS_IP ?=
define discover_keycloak_alias
alias_ip="$(KEYCLOAK_ALIAS_IP)"; \
if [ -z "$$alias_ip" ] && [ -n "$(KUBECONFIG)" ]; then \
  alias_ip="$$($(KUBECTL) --kubeconfig "$(KUBECONFIG)" -n "$(INGRESS_NAMESPACE)" get service "$(INGRESS_SERVICE)" -o jsonpath='{.spec.clusterIP}' 2>/dev/null || true)"; \
fi; \
if [ -n "$$alias_ip" ]; then \
  alias_args="--set-json hostAliases=[{\"ip\":\"$$alias_ip\",\"hostnames\":[\"$(KEYCLOAK_HOST)\"]}]"; \
else \
  alias_args=""; \
  echo "NOTE: no ingress ClusterIP discovered; rendering without the Keycloak hostAlias" >&2; \
fi
endef
TLS_SECRET ?= zot-server-tls
TLS_ISSUER ?= ok-shared-internal-ca
HTPASSWD_SECRET ?= zot-htpasswd
# Cleartext machine credentials live here and are NEVER mounted into the registry
# container: the zot chart projects an external Secret without an items filter.
MACHINE_SECRET ?= zot-machine-identities
CONFORMANCE_SECRET ?= zot-conformance-identities
OIDC_SECRET ?= zot-oidc
WAIT_TIMEOUT ?= 5m

KEYCLOAK_NAMESPACE ?= keycloak
KEYCLOAK_STATEFULSET ?= keycloak-keycloakx
KEYCLOAK_HOST ?= keycloak.ok-shared.internal
KEYCLOAK_ORIGIN ?= https://$(KEYCLOAK_HOST):443
KEYCLOAK_TLS_SECRET ?= keycloak-server-tls
KEYCLOAK_ADMIN_SECRET ?= keycloak-admin
KEYCLOAK_ADMIN_USERNAME ?= admin
PLATFORM_REALM ?= openkubes
CLIENT_ID ?= registry-default
WRITER_GROUP ?= registry-writers
READER_GROUP ?= registry-readers
OIDC_REDIRECT_URI ?= $(REGISTRY_ORIGIN)/zot/auth/callback/oidc

.PHONY: help render diff require-inputs require-tools require-backup-tools require-verify-tools require-restore-tools require-chart require-values-contract require-oidc-approval require-lifecycle-approval require-release-set require-transfer-input require-restore-input require-restore-drill-approval require-confirm \
	namespace identities reachability zot oidc-client metrics post-check smoke lifecycle contract-job oidc-conformance backup verify-backup restore-drill release-export verify-release offline-transfer-drill install \
	teardown-metrics teardown-zot teardown-reachability teardown-oidc-secret teardown-identities teardown-data teardown

help: ## Show registry-default lifecycle targets
	@awk 'BEGIN {FS = ":.*## "}; /^[a-zA-Z_-]+:.*## / {printf "  %-24s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

require-inputs:
	@test "$(RELEASE)" = zot || { echo "ERROR: RELEASE must be 'zot' for Increment 1." >&2; \
		echo "       The chart's fullname only collapses to the bare release name because 'zot' contains the chart name;" >&2; \
		echo "       any other value desynchronises the StatefulSet name, the IngressRouteTCP target and the Service lookup." >&2; exit 2; }
	@test "$(CLUSTER)" = ok-shared || { echo "ERROR: registry-default Increment 1 is scoped to CLUSTER=ok-shared" >&2; exit 2; }
	@test -n "$(KUBECONFIG)" || { echo 'ERROR: KUBECONFIG is required; run: oks && make ... KUBECONFIG="$$KUBECONFIG"' >&2; exit 2; }
	@test -r "$(KUBECONFIG)" || { echo "ERROR: KUBECONFIG is not readable: $(KUBECONFIG)" >&2; exit 2; }
	@context="$$($(KUBECTL) --kubeconfig "$(KUBECONFIG)" config current-context)"; cluster="$$($(KUBECTL) --kubeconfig "$(KUBECONFIG)" config view --minify -o jsonpath='{.clusters[0].name}')"; \
		test "$$context" = ok-shared-admin@ok-shared || test "$$context" = ok-shared || test "$$cluster" = ok-shared || { echo "ERROR: kubeconfig identifies context '$$context' / cluster '$$cluster', not ok-shared" >&2; exit 2; }

require-tools:
	@for tool in "$(KUBECTL)" "$(HELM)" "$(PYTHON)" "$(JQ)" "$(TIMEOUT)" curl openssl htpasswd base64 sha256sum git make grep sed; do \
		command -v "$$tool" >/dev/null || { echo "ERROR: required tool not found: $$tool" >&2; exit 2; }; \
	done
	@$(PYTHON) -c 'import yaml' >/dev/null 2>&1 || { echo "ERROR: PyYAML is required by the values contract and the manifest renderer" >&2; exit 2; }

require-backup-tools:
	@for tool in "$(KUBECTL)" "$(PYTHON)" "$(JQ)" "$(TAR)" curl base64 find sha256sum stat make; do \
		command -v "$$tool" >/dev/null || { echo "ERROR: backup tool not found: $$tool" >&2; exit 2; }; \
	done

require-verify-tools:
	@command -v "$(PYTHON)" >/dev/null || { echo "ERROR: verifier tool not found: $(PYTHON)" >&2; exit 2; }

require-restore-tools: require-backup-tools
	@for tool in "$(HELM)" cmp; do \
		command -v "$$tool" >/dev/null || { echo "ERROR: restore-drill tool not found: $$tool" >&2; exit 2; }; \
	done

require-chart:
	@test -d "$(CHART_DIR)" || { echo "ERROR: pinned zot chart checkout is absent: $(CHART_DIR) (override CHART_DIR)" >&2; \
		echo "       Create it once from the workspace root -- it is workspace-local, not part of any repository:" >&2; \
		echo "         git clone --no-checkout https://github.com/project-zot/helm-charts zot" >&2; \
		echo "         git -C zot checkout tags/$(CHART_TAG)" >&2; exit 2; }
	@test -r "$(CHART_DIR)/Chart.yaml" || { echo "ERROR: zot Chart.yaml is absent under CHART_DIR=$(CHART_DIR)" >&2; exit 2; }
	@actual="$$(git -C "$(CHART_DIR)" describe --tags --exact-match 2>/dev/null || true)"; \
		test "$$actual" = "$(CHART_TAG)" || { echo "ERROR: CHART_DIR must be checked out exactly at $(CHART_TAG); found '$${actual:-no exact tag}'" >&2; exit 2; }
	@git -C "$(CHART_DIR)" diff --quiet HEAD -- Chart.yaml templates values.yaml .helmignore README.md && \
		git -C "$(CHART_DIR)" diff --cached --quiet HEAD -- Chart.yaml templates values.yaml .helmignore README.md || { \
		echo "ERROR: runtime zot chart files differ from tag $(CHART_TAG)" >&2; exit 2; }

require-values-contract:
	@$(PYTHON) -c 'import json,sys,yaml; p,host,tls,htpasswd,oidc=sys.argv[1:]; v=yaml.safe_load(open(p,encoding="utf-8")); c=json.loads(v["configFiles"]["config.json"]); assert v["image"]["tag"].startswith("v2.1.20@sha256:"); assert v["service"]["type"]=="ClusterIP" and not v["ingress"]["enabled"]; assert v["persistence"] is True and v["pvc"]["storageClassName"]=="local-path"; assert c["http"]["externalUrl"]=="https://"+host; assert c["http"]["auth"]["apikey"] is True; assert c["http"]["auth"]["sessionKeysFile"]=="/oidc/session-keys.json"; provider=c["http"]["auth"]["openid"]["providers"]["oidc"]; assert provider["issuer"]=="https://keycloak.ok-shared.internal/realms/openkubes"; assert provider["claimMapping"]=={"username":"preferred_username","groups":"groups"}; assert c["http"]["accessControl"]["metrics"]["users"]==["zot-metrics"]; assert set(c["http"]["accessControl"]["repositories"]["openkubes/human/**"]["policies"][0]["groups"])=={"registry-writers"}; mounts={x["secretName"]:x["mountPath"] for x in v["externalSecrets"]}; assert mounts[tls]=="/tls" and mounts[htpasswd]=="/auth" and mounts[oidc]=="/oidc"' \
		"$(VALUES_FILE)" "$(REGISTRY_HOST)" "$(TLS_SECRET)" "$(HTPASSWD_SECRET)" "$(OIDC_SECRET)" || { echo "ERROR: values/config contract mismatch (the Python error above names the failing assertion)" >&2; exit 2; }

require-oidc-approval:
	@test "$(APPROVE_OIDC_CLIENT)" = yes || { \
		echo "ERROR: oidc-client reconciles objects in the central $(PLATFORM_REALM) realm." >&2; \
		echo "       Review client, mapper, groups and conformance users; rerun with APPROVE_OIDC_CLIENT=yes." >&2; exit 2; }

require-lifecycle-approval:
	@test "$(APPROVE_LIFECYCLE_RESTART)" = yes || { \
		echo "ERROR: lifecycle rolls out a restart of the live registry, interrupting every client." >&2; \
		echo "       It also needs storage.gcDelay lowered from the shipped 1h to observe reclamation." >&2; \
		echo "       Rerun against a disposable/GC-tuned registry with APPROVE_LIFECYCLE_RESTART=yes." >&2; exit 2; }

require-restore-input:
	@test -n "$(RESTORE_ARTIFACT)" || { echo "ERROR: RESTORE_ARTIFACT is required" >&2; exit 2; }
	@test -r "$(RESTORE_ARTIFACT)" || { echo "ERROR: restore artifact is not readable: $(RESTORE_ARTIFACT)" >&2; exit 2; }
	@test -n "$(INTEGRITY_MANIFEST)" || { echo "ERROR: INTEGRITY_MANIFEST is required" >&2; exit 2; }
	@test -r "$(INTEGRITY_MANIFEST)" || { echo "ERROR: integrity manifest is not readable: $(INTEGRITY_MANIFEST)" >&2; exit 2; }

require-release-set:
	@test -n "$(RELEASE_SET)" || { echo "ERROR: RELEASE_SET is required" >&2; exit 2; }
	@test -r "$(RELEASE_SET)" || { echo "ERROR: release set is not readable: $(RELEASE_SET)" >&2; exit 2; }
	@test -n "$(TRANSFER_DIR)" || { echo "ERROR: TRANSFER_DIR is required" >&2; exit 2; }
	@test -d "$(TRANSFER_DIR)" || { echo "ERROR: TRANSFER_DIR is not an existing directory: $(TRANSFER_DIR)" >&2; exit 2; }

require-transfer-input:
	@test -n "$(TRANSFER_ARTIFACT)" || { echo "ERROR: TRANSFER_ARTIFACT is required" >&2; exit 2; }
	@test -r "$(TRANSFER_ARTIFACT)" || { echo "ERROR: transfer artifact is not readable: $(TRANSFER_ARTIFACT)" >&2; exit 2; }
	@test -n "$(TRANSFER_INTEGRITY_MANIFEST)" || { echo "ERROR: TRANSFER_INTEGRITY_MANIFEST is required" >&2; exit 2; }
	@test -r "$(TRANSFER_INTEGRITY_MANIFEST)" || { echo "ERROR: transfer integrity manifest is not readable: $(TRANSFER_INTEGRITY_MANIFEST)" >&2; exit 2; }

require-restore-drill-approval:
	@test "$(APPROVE_RESTORE_DRILL)" = yes || { \
		echo "ERROR: restore-drill creates an isolated scratch registry on cluster $(CLUSTER)." >&2; \
		echo "       Review the artifact, isolation guards and cleanup; rerun with APPROVE_RESTORE_DRILL=yes." >&2; exit 2; }
	@test -t 0 || { echo "ERROR: restore-drill must be run attended from a terminal" >&2; exit 2; }

require-confirm:
	@test "$(CONFIRM)" = yes || { echo "ERROR: teardown is destructive; rerun the reviewed target with CONFIRM=yes" >&2; exit 2; }

render: require-tools require-chart require-values-contract ## Render every manifest and the pinned Helm release
	@set -Eeuo pipefail; for t in "$(NAMESPACE_TEMPLATE)" "$(IDENTITIES_TEMPLATE)" "$(REACHABILITY_TEMPLATE)" "$(METRICS_TEMPLATE)"; do \
		echo "---"; NAMESPACE="$(NAMESPACE)" RELEASE="$(RELEASE)" REGISTRY_HOST="$(REGISTRY_HOST)" TLS_SECRET="$(TLS_SECRET)" TLS_ISSUER="$(TLS_ISSUER)" HTPASSWD_SECRET="$(HTPASSWD_SECRET)" MACHINE_SECRET="$(MACHINE_SECRET)" \
		$(PYTHON) -c 'import os,string,sys; print(string.Template(open(sys.argv[1]).read()).substitute(os.environ),end="")' "$$t"; \
	done; echo "---"; $(discover_keycloak_alias); \
		$(HELM) template "$(RELEASE)" "$(CHART_DIR)" -n "$(NAMESPACE)" -f "$(VALUES_FILE)" $$alias_args --skip-tests

diff: require-inputs require-tools require-chart require-values-contract ## Diff rendered manifests and Helm output against ok-shared
	@set -Eeuo pipefail; d="$$(mktemp -d)"; test -d "$$d"; trap 'rm -rf -- "$$d"' EXIT INT TERM; \
		$(MAKE) --no-print-directory render > "$$d/rendered.yaml"; \
		$(KUBECTL) --kubeconfig "$(KUBECONFIG)" diff -f "$$d/rendered.yaml" && echo "no drift: live objects match rendered input"

namespace: require-inputs require-tools ## Apply the dedicated zot namespace
	@NAMESPACE="$(NAMESPACE)" $(PYTHON) -c 'import os,string,sys; print(string.Template(open(sys.argv[1]).read()).substitute(os.environ),end="")' "$(NAMESPACE_TEMPLATE)" | \
		$(KUBECTL) --kubeconfig "$(KUBECONFIG)" apply -f -

identities: require-inputs require-tools ## Apply service identities and create out-of-band htpasswd/conformance Secrets
	@NAMESPACE="$(NAMESPACE)" $(PYTHON) -c 'import os,string,sys; print(string.Template(open(sys.argv[1]).read()).substitute(os.environ),end="")' "$(IDENTITIES_TEMPLATE)" | \
		$(KUBECTL) --kubeconfig "$(KUBECONFIG)" apply -f -
	@KUBECTL="$(KUBECTL)" KUBECONFIG="$(KUBECONFIG)" NAMESPACE="$(NAMESPACE)" HTPASSWD_SECRET="$(HTPASSWD_SECRET)" MACHINE_SECRET="$(MACHINE_SECRET)" CONFORMANCE_SECRET="$(CONFORMANCE_SECRET)" bash "$(SECRETS_SCRIPT)"

reachability: require-inputs require-tools ## Apply Certificate and Traefik TLS-passthrough route
	@set -Eeuo pipefail; d="$$(mktemp -d)"; test -d "$$d"; trap 'rm -rf -- "$$d"' EXIT INT TERM; \
		NAMESPACE="$(NAMESPACE)" RELEASE="$(RELEASE)" REGISTRY_HOST="$(REGISTRY_HOST)" TLS_SECRET="$(TLS_SECRET)" TLS_ISSUER="$(TLS_ISSUER)" \
		$(PYTHON) -c 'import os,string,sys; print(string.Template(open(sys.argv[1]).read()).substitute(os.environ),end="")' "$(REACHABILITY_TEMPLATE)" > "$$d/reachability.yaml"; \
		$(KUBECTL) --kubeconfig "$(KUBECONFIG)" apply -f "$$d/reachability.yaml"; \
		$(KUBECTL) --kubeconfig "$(KUBECONFIG)" wait --for=condition=Ready=True certificate/$(TLS_SECRET) -n "$(NAMESPACE)" --timeout="$(WAIT_TIMEOUT)"

oidc-client: require-inputs require-tools require-oidc-approval ## APPROVAL: reconcile zot client, groups mapper, profile groups and conformance users in central Keycloak
	@set -Eeuo pipefail; umask 077; d="$$(mktemp -d)"; test -d "$$d"; trap 'rm -rf -- "$$d"' EXIT INT TERM; \
		REGISTRY_HOST="$(REGISTRY_HOST)" REGISTRY_LB="$(REGISTRY_LB)" REGISTRY_LB_KUBECONFIG="$(REGISTRY_LB_KUBECONFIG)" \
			. "$(TOOLING)/registry-defaults.sh"; \
		$(KUBECTL) --kubeconfig "$(KUBECONFIG)" get secret "$(KEYCLOAK_TLS_SECRET)" -n "$(KEYCLOAK_NAMESPACE)" -o jsonpath='{.data.ca\.crt}' | base64 -d > "$$d/ca.crt"; \
		test -s "$$d/ca.crt" || { echo "ERROR: Keycloak CA is absent" >&2; exit 1; }; \
		KC_ORIGIN="$(KEYCLOAK_ORIGIN)" KC_RESOLVE="$(KEYCLOAK_HOST):443:$$REGISTRY_LB" KC_CACERT="$$d/ca.crt" \
		KEYCLOAK_ADMIN_USERNAME="$(KEYCLOAK_ADMIN_USERNAME)" PLATFORM_REALM="$(PLATFORM_REALM)" CLIENT_ID="$(CLIENT_ID)" \
		REDIRECT_URI="$(OIDC_REDIRECT_URI)" REGISTRY_ORIGIN="$(REGISTRY_ORIGIN)" WRITER_GROUP="$(WRITER_GROUP)" READER_GROUP="$(READER_GROUP)" \
		KUBECTL="$(KUBECTL)" KUBECONFIG="$(KUBECONFIG)" NAMESPACE="$(NAMESPACE)" OIDC_SECRET="$(OIDC_SECRET)" bash "$(OIDC_SCRIPT)" \
			3< <($(KUBECTL) --kubeconfig "$(KUBECONFIG)" get secret "$(KEYCLOAK_ADMIN_SECRET)" -n "$(KEYCLOAK_NAMESPACE)" -o jsonpath='{.data.password}' | base64 -d) \
			4< <($(KUBECTL) --kubeconfig "$(KUBECONFIG)" get secret "$(CONFORMANCE_SECRET)" -n "$(NAMESPACE)" -o jsonpath='{.data.writer-password}' | base64 -d) \
			5< <($(KUBECTL) --kubeconfig "$(KUBECONFIG)" get secret "$(CONFORMANCE_SECRET)" -n "$(NAMESPACE)" -o jsonpath='{.data.reader-password}' | base64 -d)

zot: require-inputs require-tools require-chart require-values-contract ## Install or upgrade zot from the pinned local chart and wait Ready
	@$(KUBECTL) --kubeconfig "$(KUBECONFIG)" get secret "$(TLS_SECRET)" "$(HTPASSWD_SECRET)" "$(MACHINE_SECRET)" "$(OIDC_SECRET)" -n "$(NAMESPACE)" >/dev/null
	@set -Eeuo pipefail; $(discover_keycloak_alias); \
		$(HELM) template "$(RELEASE)" "$(CHART_DIR)" -n "$(NAMESPACE)" -f "$(VALUES_FILE)" $$alias_args --skip-tests >/dev/null; \
		$(HELM) upgrade --install "$(RELEASE)" "$(CHART_DIR)" -n "$(NAMESPACE)" -f "$(VALUES_FILE)" $$alias_args --kubeconfig "$(KUBECONFIG)"
	@$(KUBECTL) --kubeconfig "$(KUBECONFIG)" rollout status statefulset/$(RELEASE) -n "$(NAMESPACE)" --timeout="$(WAIT_TIMEOUT)"

metrics: require-inputs require-tools ## Apply authenticated ServiceMonitor registration and assert admission
	@NAMESPACE="$(NAMESPACE)" RELEASE="$(RELEASE)" REGISTRY_HOST="$(REGISTRY_HOST)" TLS_SECRET="$(TLS_SECRET)" MACHINE_SECRET="$(MACHINE_SECRET)" \
		$(PYTHON) -c 'import os,string,sys; print(string.Template(open(sys.argv[1]).read()).substitute(os.environ),end="")' "$(METRICS_TEMPLATE)" | \
		$(KUBECTL) --kubeconfig "$(KUBECONFIG)" apply -f -
	@$(KUBECTL) --kubeconfig "$(KUBECONFIG)" get servicemonitor "$(RELEASE)" -n "$(NAMESPACE)" -o name

post-check: require-inputs require-tools ## Read-only: assert live readiness, TLS route, auth, metrics and ServiceMonitor selector match
	@KUBECTL="$(KUBECTL)" KUBECONFIG="$(KUBECONFIG)" NAMESPACE="$(NAMESPACE)" RELEASE="$(RELEASE)" REGISTRY_HOST="$(REGISTRY_HOST)" REGISTRY_LB="$(REGISTRY_LB)" REGISTRY_LB_KUBECONFIG="$(REGISTRY_LB_KUBECONFIG)" TLS_SECRET="$(TLS_SECRET)" MACHINE_SECRET="$(MACHINE_SECRET)" VALUES_FILE="$(VALUES_FILE)" bash "$(POST_CHECK_SCRIPT)"

smoke: require-inputs require-tools ## Run the ported OCI smoke contract through TLS passthrough
	@KUBECTL="$(KUBECTL)" KUBECONFIG="$(KUBECONFIG)" REGISTRY_NAMESPACE="$(NAMESPACE)" REGISTRY_HOST="$(REGISTRY_HOST)" REGISTRY_LB="$(REGISTRY_LB)" REGISTRY_LB_KUBECONFIG="$(REGISTRY_LB_KUBECONFIG)" bash "$(CONFORMANCE)/smoke.sh"

lifecycle: require-inputs require-tools require-lifecycle-approval ## APPROVAL: RESTARTS the live registry; needs a GC-tuned deployment, not Increment 1 evidence
	@KUBECTL="$(KUBECTL)" KUBECONFIG="$(KUBECONFIG)" REGISTRY_NAMESPACE="$(NAMESPACE)" REGISTRY_HOST="$(REGISTRY_HOST)" REGISTRY_LB="$(REGISTRY_LB)" REGISTRY_LB_KUBECONFIG="$(REGISTRY_LB_KUBECONFIG)" bash "$(CONFORMANCE)/lifecycle.sh"

contract-job: require-inputs require-tools ## Run in-cluster OCI 1.1 push/pull/digest/referrers contract (not a kubelet image pull)
	@KUBECTL="$(KUBECTL)" KUBECONFIG="$(KUBECONFIG)" NAMESPACE="$(NAMESPACE)" REGISTRY_HOST="$(REGISTRY_HOST)" REGISTRY_LB="$(REGISTRY_LB)" REGISTRY_LB_KUBECONFIG="$(REGISTRY_LB_KUBECONFIG)" TLS_SECRET="$(TLS_SECRET)" MACHINE_SECRET="$(MACHINE_SECRET)" bash "$(CONTRACT_JOB_SCRIPT)"

oidc-conformance: require-inputs require-tools require-oidc-approval ## APPROVAL: prove human OIDC group authz including temporary membership removal and restoration
	@KUBECTL="$(KUBECTL)" KUBECONFIG="$(KUBECONFIG)" NAMESPACE="$(NAMESPACE)" REGISTRY_HOST="$(REGISTRY_HOST)" REGISTRY_LB="$(REGISTRY_LB)" REGISTRY_LB_KUBECONFIG="$(REGISTRY_LB_KUBECONFIG)" \
		KEYCLOAK_HOST="$(KEYCLOAK_HOST)" KEYCLOAK_NAMESPACE="$(KEYCLOAK_NAMESPACE)" KEYCLOAK_ADMIN_SECRET="$(KEYCLOAK_ADMIN_SECRET)" \
		KEYCLOAK_ADMIN_USERNAME="$(KEYCLOAK_ADMIN_USERNAME)" PLATFORM_REALM="$(PLATFORM_REALM)" CLIENT_ID="$(CLIENT_ID)" \
		WRITER_GROUP="$(WRITER_GROUP)" READER_GROUP="$(READER_GROUP)" TLS_SECRET="$(TLS_SECRET)" \
		CONFORMANCE_SECRET="$(CONFORMANCE_SECRET)" OIDC_SECRET="$(OIDC_SECRET)" bash "$(OIDC_CONFORMANCE_SCRIPT)"

backup: require-inputs require-backup-tools ## Export OCI content and a verifiable integrity manifest to operator-supplied off-cluster storage
	@REGISTRY_LB_KUBECONFIG="$(REGISTRY_LB_KUBECONFIG)" $(PYTHON) "$(ZOTCTL)" backup --kubectl "$(KUBECTL)" --kubeconfig "$(KUBECONFIG)" \
		--namespace "$(NAMESPACE)" --release "$(RELEASE)" \
		--registry-host "$(REGISTRY_HOST)" $(if $(REGISTRY_LB),--registry-lb "$(REGISTRY_LB)",) \
		--tls-secret "$(TLS_SECRET)" --machine-secret "$(MACHINE_SECRET)" \
		--conformance-secret "$(CONFORMANCE_SECRET)" \
		--keycloak-host "$(KEYCLOAK_HOST)" --page-size "$(OCI_PAGE_SIZE)" \
		--backup-dir "$(BACKUP_DIR)"

verify-backup: require-restore-tools require-restore-input ## Verify detached artifact integrity and every OCI blob without cluster access
	@$(PYTHON) "$(ZOTCTL)" verify "$(RESTORE_ARTIFACT)" "$(INTEGRITY_MANIFEST)"

restore-drill: require-inputs require-restore-tools require-chart require-restore-input require-restore-drill-approval ## APPROVAL: restore into an isolated scratch zot and prove pull-by-digest byte identity
	@$(PYTHON) "$(ZOTCTL)" restore-drill --kubectl "$(KUBECTL)" --kubeconfig "$(KUBECONFIG)" \
		--helm "$(HELM)" --chart-dir "$(CHART_DIR)" --values-file "$(VALUES_FILE)" \
		--namespace "$(NAMESPACE)" --release "$(RELEASE)" \
		$(if $(filter yes,$(APPROVE_RESTORE_DRILL)),--approve,) \
		$(if $(filter yes,$(RETAIN_SCRATCH)),--retain-scratch,) \
		$(if $(SCRATCH_NAMESPACE),--scratch-namespace "$(SCRATCH_NAMESPACE)",) \
		$(if $(SCRATCH_RELEASE),--scratch-release "$(SCRATCH_RELEASE)",) \
		"$(RESTORE_ARTIFACT)" "$(INTEGRITY_MANIFEST)"

release-export: require-inputs require-backup-tools require-release-set ## Export one named immutable release and refuse an incomplete descriptor/referrer closure
	@REGISTRY_LB_KUBECONFIG="$(REGISTRY_LB_KUBECONFIG)" $(PYTHON) "$(ZOTCTL)" release-export "$(RELEASE_SET)" --kubectl "$(KUBECTL)" --kubeconfig "$(KUBECONFIG)" \
		--namespace "$(NAMESPACE)" --release "$(RELEASE)" \
		--registry-host "$(REGISTRY_HOST)" $(if $(REGISTRY_LB),--registry-lb "$(REGISTRY_LB)",) \
		--tls-secret "$(TLS_SECRET)" --machine-secret "$(MACHINE_SECRET)" \
		--conformance-secret "$(CONFORMANCE_SECRET)" \
		--keycloak-host "$(KEYCLOAK_HOST)" --page-size "$(OCI_PAGE_SIZE)" \
		--backup-dir "$(TRANSFER_DIR)"

verify-release: require-verify-tools require-transfer-input ## Verify release integrity and descriptor/referrer completeness with no cluster or source access
	@$(PYTHON) "$(ZOTCTL)" verify "$(TRANSFER_ARTIFACT)" "$(TRANSFER_INTEGRITY_MANIFEST)"

offline-transfer-drill: require-transfer-input ## APPROVAL: import a release into a fresh scratch zot and pull every member by digest
	@$(MAKE) --no-print-directory restore-drill \
		KUBECONFIG="$(KUBECONFIG)" \
		RESTORE_ARTIFACT="$(TRANSFER_ARTIFACT)" \
		INTEGRITY_MANIFEST="$(TRANSFER_INTEGRITY_MANIFEST)" \
		APPROVE_RESTORE_DRILL="$(APPROVE_RESTORE_DRILL)" \
		RETAIN_SCRATCH="$(RETAIN_SCRATCH)" \
		SCRATCH_NAMESPACE="$(SCRATCH_NAMESPACE)" \
		SCRATCH_RELEASE="$(SCRATCH_RELEASE)"

install: require-inputs require-tools require-chart require-values-contract require-oidc-approval ## APPROVAL: install Increment 1 end to end (requires APPROVE_OIDC_CLIENT=yes)
	@$(MAKE) --no-print-directory namespace KUBECONFIG="$(KUBECONFIG)"
	@$(MAKE) --no-print-directory identities KUBECONFIG="$(KUBECONFIG)"
	@$(MAKE) --no-print-directory reachability KUBECONFIG="$(KUBECONFIG)"
	@$(MAKE) --no-print-directory oidc-client KUBECONFIG="$(KUBECONFIG)" APPROVE_OIDC_CLIENT="$(APPROVE_OIDC_CLIENT)"
	@$(MAKE) --no-print-directory zot KUBECONFIG="$(KUBECONFIG)"
	@$(MAKE) --no-print-directory metrics KUBECONFIG="$(KUBECONFIG)"
	@$(MAKE) --no-print-directory post-check KUBECONFIG="$(KUBECONFIG)"

teardown-metrics: require-inputs require-tools require-confirm ## Remove the ServiceMonitor (requires CONFIRM=yes)
	@$(KUBECTL) --kubeconfig "$(KUBECONFIG)" delete servicemonitor "$(RELEASE)" -n "$(NAMESPACE)" --ignore-not-found

teardown-zot: require-inputs require-tools require-confirm ## Uninstall zot while retaining its PVC (requires CONFIRM=yes)
	@set -Eeuo pipefail; releases="$$($(HELM) list --all --short --filter '^$(RELEASE)$$$$' -n "$(NAMESPACE)" --kubeconfig "$(KUBECONFIG)")"; \
	if [ "$$releases" = "$(RELEASE)" ]; then \
		$(HELM) uninstall "$(RELEASE)" -n "$(NAMESPACE)" --kubeconfig "$(KUBECONFIG)"; \
	elif [ -z "$$releases" ]; then \
		echo "UNCHANGED: Helm release $(NAMESPACE)/$(RELEASE) is already absent"; \
	else \
		echo "ERROR: exact Helm release lookup returned unexpected result: $$releases" >&2; exit 1; \
	fi
	@echo "NOTICE: registry PVC and all artifact content were retained."

teardown-reachability: require-inputs require-tools require-confirm ## Remove TLS route and Certificate (requires CONFIRM=yes)
	@$(KUBECTL) --kubeconfig "$(KUBECONFIG)" delete "ingressroutetcp/$(RELEASE)" "certificate/$(TLS_SECRET)" -n "$(NAMESPACE)" --ignore-not-found

teardown-oidc-secret: require-inputs require-tools require-confirm ## Remove only the namespace OIDC Secret; retain central realm objects (requires CONFIRM=yes)
	@$(KUBECTL) --kubeconfig "$(KUBECONFIG)" delete secret "$(OIDC_SECRET)" -n "$(NAMESPACE)" --ignore-not-found
	@echo "NOTICE: central Keycloak client, mapper, groups and conformance users were retained deliberately."

teardown-identities: require-inputs require-tools require-confirm ## Remove non-data identities and credential Secrets (requires CONFIRM=yes)
	@$(KUBECTL) --kubeconfig "$(KUBECONFIG)" delete serviceaccount zot zot-contract -n "$(NAMESPACE)" --ignore-not-found
	@$(KUBECTL) --kubeconfig "$(KUBECONFIG)" delete configmap zot-contract-script -n "$(NAMESPACE)" --ignore-not-found
	@$(KUBECTL) --kubeconfig "$(KUBECONFIG)" delete secret "$(HTPASSWD_SECRET)" "$(MACHINE_SECRET)" "$(CONFORMANCE_SECRET)" -n "$(NAMESPACE)" --ignore-not-found

teardown-data: require-inputs require-tools require-confirm ## IRREVERSIBLE: delete the registry PVC and artifact content (requires CONFIRM=yes)
	@$(KUBECTL) --kubeconfig "$(KUBECONFIG)" delete pvc -l app.kubernetes.io/instance=$(RELEASE) -n "$(NAMESPACE)" --wait=true

teardown: require-inputs require-tools require-confirm ## Reverse Increment 1 but retain PVC data and central Keycloak objects (requires CONFIRM=yes)
	@$(MAKE) --no-print-directory teardown-metrics KUBECONFIG="$(KUBECONFIG)" CONFIRM=yes
	@$(MAKE) --no-print-directory teardown-zot KUBECONFIG="$(KUBECONFIG)" CONFIRM=yes
	@$(MAKE) --no-print-directory teardown-reachability KUBECONFIG="$(KUBECONFIG)" CONFIRM=yes
	@$(MAKE) --no-print-directory teardown-oidc-secret KUBECONFIG="$(KUBECONFIG)" CONFIRM=yes
	@$(MAKE) --no-print-directory teardown-identities KUBECONFIG="$(KUBECONFIG)" CONFIRM=yes
	@echo "NOTICE: namespace, PVC/data, and central Keycloak objects were retained. Run teardown-data separately only after backup."
