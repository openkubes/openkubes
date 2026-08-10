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

RELEASE ?= zot
REGISTRY_HOST ?= registry.ok-shared.internal
REGISTRY_ORIGIN ?= https://$(REGISTRY_HOST)
REGISTRY_LB ?= 192.168.100.207
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

.PHONY: help render diff require-inputs require-tools require-chart require-values-contract require-oidc-approval require-lifecycle-approval require-confirm \
	namespace identities reachability zot oidc-client metrics post-check smoke lifecycle contract-job oidc-conformance install \
	teardown-metrics teardown-zot teardown-reachability teardown-oidc-secret teardown-identities teardown-data teardown

help: ## Show registry-default lifecycle targets
	@awk 'BEGIN {FS = ":.*## "}; /^[a-zA-Z_-]+:.*## / {printf "  %-24s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

require-inputs:
	@test "$(CLUSTER)" = ok-shared || { echo "ERROR: registry-default Increment 1 is scoped to CLUSTER=ok-shared" >&2; exit 2; }
	@test -n "$(KUBECONFIG)" || { echo "ERROR: KUBECONFIG is required; use 'oks && make ... KUBECONFIG=$$$$KUBECONFIG'" >&2; exit 2; }
	@test -r "$(KUBECONFIG)" || { echo "ERROR: KUBECONFIG is not readable: $(KUBECONFIG)" >&2; exit 2; }
	@context="$$($(KUBECTL) --kubeconfig "$(KUBECONFIG)" config current-context)"; cluster="$$($(KUBECTL) --kubeconfig "$(KUBECONFIG)" config view --minify -o jsonpath='{.clusters[0].name}')"; \
		test "$$context" = ok-shared-admin@ok-shared || test "$$context" = ok-shared || test "$$cluster" = ok-shared || { echo "ERROR: kubeconfig identifies context '$$context' / cluster '$$cluster', not ok-shared" >&2; exit 2; }

require-tools:
	@for tool in "$(KUBECTL)" "$(HELM)" "$(PYTHON)" "$(JQ)" "$(TIMEOUT)" curl openssl htpasswd base64 sha256sum git realpath make rg sed; do \
		command -v "$$tool" >/dev/null || { echo "ERROR: required tool not found: $$tool" >&2; exit 2; }; \
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
		"$(VALUES_FILE)" "$(REGISTRY_HOST)" "$(TLS_SECRET)" "$(HTPASSWD_SECRET)" "$(OIDC_SECRET)" || { echo "ERROR: values/config contract mismatch" >&2; exit 2; }

require-oidc-approval:
	@test "$(APPROVE_OIDC_CLIENT)" = yes || { \
		echo "ERROR: oidc-client reconciles objects in the central $(PLATFORM_REALM) realm." >&2; \
		echo "       Review client, mapper, groups and conformance users; rerun with APPROVE_OIDC_CLIENT=yes." >&2; exit 2; }

require-lifecycle-approval:
	@test "$(APPROVE_LIFECYCLE_RESTART)" = yes || { \
		echo "ERROR: lifecycle rolls out a restart of the live registry, interrupting every client." >&2; \
		echo "       It also needs storage.gcDelay lowered from the shipped 1h to observe reclamation." >&2; \
		echo "       Rerun against a disposable/GC-tuned registry with APPROVE_LIFECYCLE_RESTART=yes." >&2; exit 2; }

require-confirm:
	@test "$(CONFIRM)" = yes || { echo "ERROR: teardown is destructive; rerun the reviewed target with CONFIRM=yes" >&2; exit 2; }

render: require-chart require-values-contract ## Render every manifest and the pinned Helm release
	@set -Eeuo pipefail; for t in "$(NAMESPACE_TEMPLATE)" "$(IDENTITIES_TEMPLATE)" "$(REACHABILITY_TEMPLATE)" "$(METRICS_TEMPLATE)"; do \
		echo "---"; NAMESPACE="$(NAMESPACE)" RELEASE="$(RELEASE)" REGISTRY_HOST="$(REGISTRY_HOST)" TLS_SECRET="$(TLS_SECRET)" TLS_ISSUER="$(TLS_ISSUER)" HTPASSWD_SECRET="$(HTPASSWD_SECRET)" MACHINE_SECRET="$(MACHINE_SECRET)" \
		$(PYTHON) -c 'import os,string,sys; print(string.Template(open(sys.argv[1]).read()).substitute(os.environ),end="")' "$$t"; \
	done; echo "---"; $(HELM) template "$(RELEASE)" "$(CHART_DIR)" -n "$(NAMESPACE)" -f "$(VALUES_FILE)" --skip-tests

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
		$(KUBECTL) --kubeconfig "$(KUBECONFIG)" get secret "$(KEYCLOAK_TLS_SECRET)" -n "$(KEYCLOAK_NAMESPACE)" -o jsonpath='{.data.ca\.crt}' | base64 -d > "$$d/ca.crt"; \
		test -s "$$d/ca.crt" || { echo "ERROR: Keycloak CA is absent" >&2; exit 1; }; \
		KC_ORIGIN="$(KEYCLOAK_ORIGIN)" KC_RESOLVE="$(KEYCLOAK_HOST):443:$(REGISTRY_LB)" KC_CACERT="$$d/ca.crt" \
		KEYCLOAK_ADMIN_USERNAME="$(KEYCLOAK_ADMIN_USERNAME)" PLATFORM_REALM="$(PLATFORM_REALM)" CLIENT_ID="$(CLIENT_ID)" \
		REDIRECT_URI="$(OIDC_REDIRECT_URI)" REGISTRY_ORIGIN="$(REGISTRY_ORIGIN)" WRITER_GROUP="$(WRITER_GROUP)" READER_GROUP="$(READER_GROUP)" \
		KUBECTL="$(KUBECTL)" KUBECONFIG="$(KUBECONFIG)" NAMESPACE="$(NAMESPACE)" OIDC_SECRET="$(OIDC_SECRET)" bash "$(OIDC_SCRIPT)" \
			3< <($(KUBECTL) --kubeconfig "$(KUBECONFIG)" get secret "$(KEYCLOAK_ADMIN_SECRET)" -n "$(KEYCLOAK_NAMESPACE)" -o jsonpath='{.data.password}' | base64 -d) \
			4< <($(KUBECTL) --kubeconfig "$(KUBECONFIG)" get secret "$(CONFORMANCE_SECRET)" -n "$(NAMESPACE)" -o jsonpath='{.data.writer-password}' | base64 -d) \
			5< <($(KUBECTL) --kubeconfig "$(KUBECONFIG)" get secret "$(CONFORMANCE_SECRET)" -n "$(NAMESPACE)" -o jsonpath='{.data.reader-password}' | base64 -d)

zot: require-inputs require-tools require-chart require-values-contract ## Install or upgrade zot from the pinned local chart and wait Ready
	@$(KUBECTL) --kubeconfig "$(KUBECONFIG)" get secret "$(TLS_SECRET)" "$(HTPASSWD_SECRET)" "$(MACHINE_SECRET)" "$(OIDC_SECRET)" -n "$(NAMESPACE)" >/dev/null
	@$(HELM) template "$(RELEASE)" "$(CHART_DIR)" -n "$(NAMESPACE)" -f "$(VALUES_FILE)" --skip-tests >/dev/null
	@$(HELM) upgrade --install "$(RELEASE)" "$(CHART_DIR)" -n "$(NAMESPACE)" -f "$(VALUES_FILE)" --kubeconfig "$(KUBECONFIG)"
	@$(KUBECTL) --kubeconfig "$(KUBECONFIG)" rollout status statefulset/$(RELEASE) -n "$(NAMESPACE)" --timeout="$(WAIT_TIMEOUT)"

metrics: require-inputs require-tools ## Apply authenticated ServiceMonitor registration and assert admission
	@NAMESPACE="$(NAMESPACE)" RELEASE="$(RELEASE)" REGISTRY_HOST="$(REGISTRY_HOST)" TLS_SECRET="$(TLS_SECRET)" MACHINE_SECRET="$(MACHINE_SECRET)" \
		$(PYTHON) -c 'import os,string,sys; print(string.Template(open(sys.argv[1]).read()).substitute(os.environ),end="")' "$(METRICS_TEMPLATE)" | \
		$(KUBECTL) --kubeconfig "$(KUBECONFIG)" apply -f -
	@$(KUBECTL) --kubeconfig "$(KUBECONFIG)" get servicemonitor "$(RELEASE)" -n "$(NAMESPACE)" -o name

post-check: require-inputs require-tools ## Read-only: assert live readiness, TLS route, auth, metrics and ServiceMonitor selector match
	@KUBECTL="$(KUBECTL)" KUBECONFIG="$(KUBECONFIG)" NAMESPACE="$(NAMESPACE)" RELEASE="$(RELEASE)" REGISTRY_HOST="$(REGISTRY_HOST)" REGISTRY_LB="$(REGISTRY_LB)" TLS_SECRET="$(TLS_SECRET)" MACHINE_SECRET="$(MACHINE_SECRET)" bash "$(POST_CHECK_SCRIPT)"

smoke: require-inputs require-tools ## Run the ported OCI smoke contract through TLS passthrough
	@KUBECTL="$(KUBECTL)" KUBECONFIG="$(KUBECONFIG)" REGISTRY_NAMESPACE="$(NAMESPACE)" REGISTRY_HOST="$(REGISTRY_HOST)" REGISTRY_LB="$(REGISTRY_LB)" bash "$(CONFORMANCE)/smoke.sh"

lifecycle: require-inputs require-tools require-lifecycle-approval ## APPROVAL: RESTARTS the live registry; needs a GC-tuned deployment, not Increment 1 evidence
	@KUBECTL="$(KUBECTL)" KUBECONFIG="$(KUBECONFIG)" REGISTRY_NAMESPACE="$(NAMESPACE)" REGISTRY_HOST="$(REGISTRY_HOST)" REGISTRY_LB="$(REGISTRY_LB)" bash "$(CONFORMANCE)/lifecycle.sh"

contract-job: require-inputs require-tools ## Run in-cluster OCI 1.1 push/pull/digest/referrers contract (not a kubelet image pull)
	@KUBECTL="$(KUBECTL)" KUBECONFIG="$(KUBECONFIG)" NAMESPACE="$(NAMESPACE)" REGISTRY_HOST="$(REGISTRY_HOST)" REGISTRY_LB="$(REGISTRY_LB)" TLS_SECRET="$(TLS_SECRET)" MACHINE_SECRET="$(MACHINE_SECRET)" bash "$(CONTRACT_JOB_SCRIPT)"

oidc-conformance: require-inputs require-tools require-oidc-approval ## APPROVAL: prove human OIDC group authz including temporary membership removal and restoration
	@KUBECTL="$(KUBECTL)" KUBECONFIG="$(KUBECONFIG)" NAMESPACE="$(NAMESPACE)" REGISTRY_HOST="$(REGISTRY_HOST)" REGISTRY_LB="$(REGISTRY_LB)" bash "$(OIDC_CONFORMANCE_SCRIPT)"

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
