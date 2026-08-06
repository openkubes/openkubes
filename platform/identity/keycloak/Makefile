# OK-81 phase 1 lifecycle, transcribed from PHASE1-RUNLOG.md.
# Local vendor inputs stay explicit so a reviewed checkout cannot turn into a network fetch.

SHELL := /bin/bash

KUBECTL ?= kubectl
HELM ?= helm
PYTHON ?= python3
JQ ?= jq
TIMEOUT ?= timeout

CLUSTER ?=
NAMESPACE ?=
KUBECONFIG ?=
MGMT_KUBECONFIG ?=
CONFIRM ?=
APPROVE_MGMT ?=
MGMT_CLUSTER ?= ok-mgmt
SYSTEM_NAMESPACE ?= kube-system

WORKSPACE ?= $(abspath $(CURDIR)/../../../..)
OPENKUBES_ROOT ?= $(abspath $(CURDIR)/../../..)
OK_CLUSTER ?= $(WORKSPACE)/ok-cluster
CHART_DIR ?= $(WORKSPACE)/keycloak/charts/keycloakx
CHART_TAG ?= keycloakx-7.2.2
CNPG_ROOT ?= $(WORKSPACE)/cnpg
CNPG_MANIFEST ?= $(CNPG_ROOT)/releases/cnpg-1.30.0.yaml
CNPG_TAG ?= v1.30.0
MANIFESTS ?= $(CURDIR)/manifests
TOOLING ?= $(CURDIR)/tooling
IDENTITIES_TEMPLATE ?= $(MANIFESTS)/identities.template.yaml
VSO_WIRING_TEMPLATE ?= $(MANIFESTS)/vso-wiring.template.yaml
DATABASE_TEMPLATE ?= $(MANIFESTS)/database.template.yaml
NETWORKPOLICY_TEMPLATE ?= $(MANIFESTS)/networkpolicy.template.yaml
REACHABILITY_TEMPLATE ?= $(MANIFESTS)/reachability.template.yaml
VALUES_FILE ?= $(CURDIR)/values-ok-shared.yaml
VAULT_EXAMPLES ?= $(OPENKUBES_ROOT)/platform/secrets/vault/crossplane/examples
VAULT_CONFIG ?= $(VAULT_EXAMPLES)/ok-shared-vaultconfig.yaml

VSO_NAMESPACE ?= vault-secrets-operator
VSO_CHART_VERSION ?= 1.5.0
VSO_RELEASE ?= vault-secrets-operator
VSO_CONNECTION ?= vault
VSO_AUTH ?= keycloak
VSO_SERVICE_ACCOUNT ?= sa-keycloak
VSO_ADMIN_SECRET ?= keycloak-admin
VSO_DB_SECRET ?= keycloak-db
VSO_REFRESH_AFTER ?= 60s
VSO_WAIT_TIMEOUT ?= 2m
VSO_KINDS ?= vaultconnections vaultauths vaultauthglobals vaultstaticsecrets vaultdynamicsecrets vaultpkisecrets hcpauths hcpvaultsecretsapps secrettransformations csisecrets

VAULT_NS ?= vault
# External consumer endpoint. Deliberately EMPTY by default: the LoadBalancer address is
# environment-specific and lives on the host cluster, so it cannot be discovered from here.
# When unset, baseline verifies Vault over an in-cluster port-forward and says plainly that the
# external passthrough route was not exercised — rather than silently implying it was.
VAULT_HOST ?=
VAULT_LB ?=
# In-cluster endpoint, used for everything that just needs to reach the API. The server
# certificate's SAN covers this name, so TLS verifies with no IP, no DNS entry and no LoadBalancer.
VAULT_SVC ?= vault-active
VAULT_SVC_PORT ?= 8200
VAULT_LOCAL_PORT ?= 18200
VAULT_INTERNAL_HOST ?= $(VAULT_SVC).$(VAULT_NS).svc.cluster.local
VAULT_BASE_URL ?= https://$(VAULT_INTERNAL_HOST):$(VAULT_LOCAL_PORT)
VAULT_RESOLVE ?= $(VAULT_INTERNAL_HOST):$(VAULT_LOCAL_PORT):127.0.0.1
VAULT_PODS ?= vault-0 vault-1 vault-2
VAULT_CA_SECRET ?= vault-server-tls
VAULT_CA_KEY ?= ca.crt
VAULT_CA_JSONPATH ?= {.data.ca\.crt}
VAULT_CA_DEST_SECRET ?= vault-ca
VAULT_SERVICE_ADDRESS ?= https://vault-active.$(VAULT_NS).svc.cluster.local:8200
VAULT_TLS_SERVER_NAME ?= vault-active.$(VAULT_NS).svc.cluster.local
VAULT_AUTH_MOUNT ?= kubernetes/$(CLUSTER)
VAULT_READER_ROLE ?= sa-keycloak
VAULT_SEED_ROLE ?= keycloak-seed
VAULT_SEED_SA ?= vault-seed-keycloak
VAULT_CONFIG_NAME ?= $(CLUSTER)
VAULT_REVIEWER_SECRET ?= $(CLUSTER)-reviewer-jwt
VAULT_REVIEWER_SA ?= vault-reviewer
VAULT_REVIEWER_TOKEN_SECRET ?= vault-reviewer-token
VAULT_REVIEWER_CRB ?= vault-reviewer-tr
MGMT_NAMESPACE ?= crossplane-system

KV_MOUNT ?= secret
KV_ADMIN_PATH ?= $(CLUSTER)/keycloak/admin
KV_DB_PATH ?= $(CLUSTER)/keycloak/db
KV_CROSS_CLUSTER_PROBE ?= secret/data/ok-robotics/obs/probe
# Break-glass only. Written by recover-admin, consumed by a human, deleted after the cutover.
KV_RECOVERY_PATH ?= $(CLUSTER)/keycloak/recovery
RECOVERY_USERNAME ?= recovery-admin

CNPG_NAMESPACE ?= cnpg-system
# Namespace of the ingress controller allowed to reach Keycloak's 8443 TLS listener.
INGRESS_NAMESPACE ?= ingress
CNPG_DEPLOYMENT ?= cnpg-controller-manager
CNPG_CLUSTER ?= keycloak-db
CNPG_WAIT_TIMEOUT ?= 5m
DB_NAME ?= keycloak
DB_USERNAME ?= keycloak
KEYCLOAK_RELEASE ?= keycloak
# The chart names the StatefulSet <release>-keycloakx, not <release>.
KEYCLOAK_STATEFULSET ?= $(KEYCLOAK_RELEASE)-keycloakx
KEYCLOAK_ADMIN_USERNAME ?= admin
# What the temporary bootstrap admin is renamed to so the permanent account can take `admin`.
# It exists only for the few seconds between the rename and the delete.
TEMP_ADMIN_USERNAME ?= bootstrap-admin
KEYCLOAK_WAIT_TIMEOUT ?= 5m
PORT ?= 8080
VERIFY_PORT ?= 18443
PORT_FORWARD_TIMEOUT ?= 30s
KEYCLOAK_HOST ?= keycloak.ok-shared.internal
KEYCLOAK_HOSTNAME ?= https://$(KEYCLOAK_HOST)
# The browser-visible origin stays on canonical HTTPS port 443. curl remaps that
# connection to the unprivileged local port used by kubectl port-forward.
KEYCLOAK_VERIFY_ORIGIN ?= $(KEYCLOAK_HOSTNAME):443
KEYCLOAK_TLS_SECRET ?= keycloak-server-tls
KEYCLOAK_TLS_ISSUER ?= ok-shared-internal-ca
KEYCLOAK_CERT_WAIT_TIMEOUT ?= 2m

SEED_SCRIPT ?= $(TOOLING)/seed-keycloak-credentials.sh
VSO_WAIT_SCRIPT ?= $(TOOLING)/wait-vso-current.sh
VERIFY_SCRIPT ?= $(TOOLING)/keycloak-conformance-test.sh
REALM_SCRIPT ?= $(TOOLING)/keycloak-realm-provision.sh
RMF_REALM_SCRIPT ?= $(TOOLING)/keycloak-rmf-realm-provision.sh
# ONE platform realm, not one per consumer: realms do not trust each other and each carries its own
# issuer and signing keys, so a realm per team means no SSO and a different issuer per API server.
PLATFORM_REALM ?= openkubes
KC_EXPECTED_ISSUER ?= $(KEYCLOAK_HOSTNAME)/realms/$(PLATFORM_REALM)
PLATFORM_GROUPS ?= openrmf-claim-editors platform-admins
# PER-CLUSTER clients: the client id is the token audience, so a token minted for one cluster cannot
# authenticate to another. Add a cluster here when it starts consuming central OIDC.
PLATFORM_CLIENTS ?= ok-mgmt
RMF_REALM ?= rmf-web
RMF_WEB_ORIGIN ?=
RMF_CREDENTIALS_NAMESPACE ?= crossplane-system
RMF_CREDENTIALS_SECRET ?= rmf-credentials
RMF_ADMIN_PASSWORD_KEY ?= rmfWebAdminPassword
RMF_REALM_LOCK ?= /tmp/openkubes-keycloak-rmf-realm.lock
APPROVE_RMF_REALM ?=
CUTOVER_SCRIPT ?= $(TOOLING)/keycloak-admin-cutover.sh
ROTATION_SCRIPT ?= $(TOOLING)/keycloak-rotation-test.sh
KV_PUT_SCRIPT ?= $(TOOLING)/vault-kv-put.sh
WAIT_SECRET_SCRIPT ?= $(TOOLING)/wait-secret-value.sh
RECOVER_SCRIPT ?= $(TOOLING)/keycloak-recover-admin.sh
BACKUP_SCRIPT ?= $(TOOLING)/keycloak-backup.sh
RESTORE_DRILL_SCRIPT ?= $(TOOLING)/keycloak-restore-drill.sh
BRUTE_FORCE_SCRIPT ?= $(TOOLING)/keycloak-brute-force.sh
BACKUP_DIR ?=
RESTORE_FILE ?=
APPROVE_CUTOVER ?=
APPROVE_RESTORE_DRILL ?=
APPROVE_NETWORK_POLICY ?=

.PHONY: help render diff require-cluster require-inputs require-tools require-chart require-cnpg require-vendors require-values-contract require-mgmt-approval \
	require-rmf-realm-inputs require-rmf-realm-approval \
	require-vault-config require-confirm require-cutover-approval require-restore-input require-restore-drill-approval require-network-policy-approval baseline install-vso identities vault-config seed \
	vso-wiring database reachability keycloak realm rmf-realm verify backup restore-drill brute-force network-policy recover-admin admin-cutover rotation-test post-check install teardown-keycloak \
	teardown-database teardown-vso-wiring teardown-identities teardown-reviewer teardown-vso teardown

help: ## Show available phase-1 lifecycle targets
	@awk 'BEGIN {FS = ":.*## "}; /^[a-zA-Z_-]+:.*## / {printf "  %-22s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

require-cluster:
	@test -n "$(CLUSTER)" || { echo "ERROR: CLUSTER is required, e.g. make $(MAKECMDGOALS) CLUSTER=<name> NAMESPACE=<namespace> KUBECONFIG=<path>" >&2; exit 2; }

require-inputs: require-cluster
	@test -n "$(NAMESPACE)" || { echo "ERROR: NAMESPACE is required" >&2; exit 2; }
	@test -n "$(KUBECONFIG)" || { echo "ERROR: KUBECONFIG is required for cluster $(CLUSTER)" >&2; exit 2; }
	@test -r "$(KUBECONFIG)" || { echo "ERROR: KUBECONFIG is not readable: $(KUBECONFIG)" >&2; exit 2; }

require-tools:
	@for tool in "$(KUBECTL)" "$(HELM)" "$(PYTHON)" "$(JQ)" "$(TIMEOUT)" openssl curl base64 sha256sum git realpath make rg; do \
		command -v "$$tool" >/dev/null || { echo "ERROR: required tool not found: $$tool" >&2; exit 2; }; \
	done

require-chart:
	@test -d "$(CHART_DIR)" || { echo "ERROR: pinned Keycloak chart checkout is absent: $(CHART_DIR) (override CHART_DIR)" >&2; exit 2; }
	@test -r "$(CHART_DIR)/Chart.yaml" || { echo "ERROR: Keycloak Chart.yaml is absent under CHART_DIR=$(CHART_DIR)" >&2; exit 2; }
	@actual="$$(git -C "$(CHART_DIR)" describe --tags --exact-match 2>/dev/null || true)"; \
		test "$$actual" = "$(CHART_TAG)" || { echo "ERROR: CHART_DIR must be checked out exactly at $(CHART_TAG); found '$${actual:-no exact tag}'" >&2; exit 2; }
	@git -C "$(CHART_DIR)" diff --quiet HEAD -- Chart.yaml templates values.yaml values.schema.json .helmignore README.md examples && \
		git -C "$(CHART_DIR)" diff --cached --quiet HEAD -- Chart.yaml templates values.yaml values.schema.json .helmignore README.md examples || { \
		echo "ERROR: applied Keycloak chart files differ from tag $(CHART_TAG); intentional pruning outside the runtime chart is allowed" >&2; exit 2; }

require-cnpg:
	@test -r "$(CNPG_MANIFEST)" || { echo "ERROR: pinned CNPG operator manifest is absent: $(CNPG_MANIFEST) (override CNPG_MANIFEST)" >&2; exit 2; }
	@repo="$$(dirname "$$(dirname "$(CNPG_MANIFEST)")")"; actual="$$(git -C "$$repo" describe --tags --exact-match 2>/dev/null || true)"; \
		test "$$actual" = "$(CNPG_TAG)" || { echo "ERROR: CNPG_MANIFEST must come from a checkout exactly at $(CNPG_TAG); found '$${actual:-no exact tag}'" >&2; exit 2; }
	@repo="$$(dirname "$$(dirname "$(CNPG_MANIFEST)")")"; rel="$$(realpath --relative-to="$$repo" "$(CNPG_MANIFEST)")"; \
		git -C "$$repo" diff --quiet HEAD -- "$$rel" && git -C "$$repo" diff --cached --quiet HEAD -- "$$rel" || { \
		echo "ERROR: CNPG_MANIFEST differs from tag $(CNPG_TAG): $(CNPG_MANIFEST)" >&2; exit 2; }

require-vendors: require-chart require-cnpg

# Values may be replaced, but they must stay coupled to the names and origin used by prior phases.
require-values-contract:
	@$(PYTHON) -c 'import sys,yaml; d=yaml.safe_load(open(sys.argv[1])); db=d["database"]; env=yaml.safe_load(d["extraEnv"]); by_name={x["name"]:x for x in env}; ref=lambda n,k: by_name[n]["valueFrom"]["secretKeyRef"]=={"name":sys.argv[5],"key":k}; assert db["hostname"]==sys.argv[2]+"-rw"; assert db["database"]==sys.argv[3]; assert db["username"]==sys.argv[4]; assert db["existingSecret"]==sys.argv[6]; assert ref("KC_BOOTSTRAP_ADMIN_USERNAME","username"); assert ref("KC_BOOTSTRAP_ADMIN_PASSWORD","password"); assert by_name["KC_HOSTNAME"]["value"]==sys.argv[7]; assert sys.argv[8]==sys.argv[7]+":443"; assert int(sys.argv[9]) > 1023; assert d["http"]["internalScheme"]=="HTTPS"; assert d["proxy"]["enabled"] is False; assert "KC_PROXY_HEADERS" not in by_name; assert by_name["KC_HTTPS_CERTIFICATE_FILE"]["value"].endswith("/tls.crt"); assert by_name["KC_HTTPS_CERTIFICATE_KEY_FILE"]["value"].endswith("/tls.key")' \
		"$(VALUES_FILE)" "$(CNPG_CLUSTER)" "$(DB_NAME)" "$(DB_USERNAME)" "$(VSO_ADMIN_SECRET)" "$(VSO_DB_SECRET)" "$(KEYCLOAK_HOSTNAME)" "$(KEYCLOAK_VERIFY_ORIGIN)" "$(VERIFY_PORT)" || { echo "ERROR: VALUES_FILE does not match CNPG/VSO/admin-bootstrap/TLS/origin variables" >&2; exit 2; }

require-mgmt-approval:
	@test -n "$(MGMT_KUBECONFIG)" || { echo "ERROR: MGMT_KUBECONFIG is required for the privileged $(MGMT_CLUSTER) target" >&2; exit 2; }
	@test -r "$(MGMT_KUBECONFIG)" || { echo "ERROR: MGMT_KUBECONFIG is not readable: $(MGMT_KUBECONFIG)" >&2; exit 2; }
	@test "$(APPROVE_MGMT)" = yes || { echo "ERROR: vault-config mutates $(MGMT_CLUSTER); review both applies, then rerun with APPROVE_MGMT=yes" >&2; exit 2; }
	@test -t 0 || { echo "ERROR: vault-config must be run attended from a terminal; unattended $(MGMT_CLUSTER) applies are forbidden" >&2; exit 2; }
	@context="$$( $(KUBECTL) --kubeconfig "$(MGMT_KUBECONFIG)" config current-context )"; \
		cluster="$$( $(KUBECTL) --kubeconfig "$(MGMT_KUBECONFIG)" config view --minify -o jsonpath='{.clusters[0].name}' )"; \
		test "$$context" = "$(MGMT_CLUSTER)" || test "$$cluster" = "$(MGMT_CLUSTER)" || { \
		echo "ERROR: MGMT_KUBECONFIG identifies context '$$context' / cluster '$$cluster', not $(MGMT_CLUSTER)" >&2; exit 2; }

require-rmf-realm-inputs: require-inputs require-tools
	@test "$(CLUSTER)" = ok-shared || { echo "ERROR: rmf-realm is scoped to central Keycloak on ok-shared, not $(CLUSTER)" >&2; exit 2; }
	@test -n "$(MGMT_KUBECONFIG)" || { echo "ERROR: MGMT_KUBECONFIG is required to read $(MGMT_NAMESPACE)/$(RMF_CREDENTIALS_SECRET)" >&2; exit 2; }
	@test -r "$(MGMT_KUBECONFIG)" || { echo "ERROR: MGMT_KUBECONFIG is not readable: $(MGMT_KUBECONFIG)" >&2; exit 2; }
	@test -n "$(RMF_WEB_ORIGIN)" || { echo "ERROR: RMF_WEB_ORIGIN is required, e.g. https://robotics.openkubes.local" >&2; exit 2; }
	@command -v flock >/dev/null || { echo "ERROR: required tool not found: flock" >&2; exit 2; }
	@$(PYTHON) -c 'import re,sys; assert re.fullmatch(r"https://[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?(?::[0-9]{1,5})?", sys.argv[1]), "RMF_WEB_ORIGIN must be one canonical HTTPS origin with no path, query, wildcard, or trailing slash"' "$(RMF_WEB_ORIGIN)"
	@context="$$( $(KUBECTL) --kubeconfig "$(KUBECONFIG)" config current-context )"; cluster="$$( $(KUBECTL) --kubeconfig "$(KUBECONFIG)" config view --minify -o jsonpath='{.clusters[0].name}' )"; \
		test "$$context" = ok-shared || test "$$cluster" = ok-shared || { echo "ERROR: KUBECONFIG identifies context '$$context' / cluster '$$cluster', not ok-shared" >&2; exit 2; }
	@context="$$( $(KUBECTL) --kubeconfig "$(MGMT_KUBECONFIG)" config current-context )"; cluster="$$( $(KUBECTL) --kubeconfig "$(MGMT_KUBECONFIG)" config view --minify -o jsonpath='{.clusters[0].name}' )"; \
		test "$$context" = "$(MGMT_CLUSTER)" || test "$$cluster" = "$(MGMT_CLUSTER)" || { echo "ERROR: MGMT_KUBECONFIG identifies context '$$context' / cluster '$$cluster', not $(MGMT_CLUSTER)" >&2; exit 2; }

require-rmf-realm-approval:
	@test "$(APPROVE_RMF_REALM)" = yes || { \
		echo "ERROR: rmf-realm mutates application identity objects on cluster $(CLUSTER)." >&2; \
		echo "       Review the origin and object contract, then rerun with APPROVE_RMF_REALM=yes." >&2; exit 2; }

# The management-plane writes are deliberately outside install: a workload install must never
# acquire permission to mutate ok-mgmt merely because its prerequisites are missing.
require-vault-config: require-cluster
	@test -n "$(MGMT_KUBECONFIG)" || { echo "ERROR: MGMT_KUBECONFIG is required to check the privileged VaultConfig prerequisite" >&2; exit 2; }
	@$(KUBECTL) --kubeconfig "$(MGMT_KUBECONFIG)" wait --for=condition=Synced=True "vaultconfig/$(VAULT_CONFIG_NAME)" --timeout=1s >/dev/null 2>&1 && \
		$(KUBECTL) --kubeconfig "$(MGMT_KUBECONFIG)" wait --for=condition=Ready=True "vaultconfig/$(VAULT_CONFIG_NAME)" --timeout=1s >/dev/null 2>&1 || { \
		echo "ERROR: VaultConfig $(VAULT_CONFIG_NAME) is not currently Synced=True and Ready=True on $(MGMT_CLUSTER)." >&2; \
		echo "       Review and run 'make vault-config ... APPROVE_MGMT=yes' separately; install will not apply it." >&2; exit 2; }

# The cutover deletes the only account that can currently administer Keycloak, and rotation changes
# a live credential. Both are recoverable, neither is silent, and neither runs unattended.
require-cutover-approval:
	@test "$(APPROVE_CUTOVER)" = yes || { \
		echo "ERROR: this target mutates live admin/database credentials on cluster $(CLUSTER)." >&2; \
		echo "       Review the sequence, then rerun with APPROVE_CUTOVER=yes." >&2; exit 2; }
	@test -t 0 || { echo "ERROR: credential cutover/rotation must be run attended from a terminal" >&2; exit 2; }

require-restore-input:
	@test -n "$(RESTORE_FILE)" || { echo "ERROR: RESTORE_FILE is required, e.g. make restore-drill RESTORE_FILE=/path/to/keycloak.dump ..." >&2; exit 2; }
	@test -r "$(RESTORE_FILE)" || { echo "ERROR: RESTORE_FILE is not readable: $(RESTORE_FILE)" >&2; exit 2; }

# The drill never connects Keycloak to the scratch database, but create/drop on the live
# PostgreSQL server is still attended and explicit, matching the existing cutover guard.
require-restore-drill-approval:
	@test "$(APPROVE_RESTORE_DRILL)" = yes || { \
		echo "ERROR: restore-drill creates and drops a scratch database on cluster $(CLUSTER)." >&2; \
		echo "       Review the sequence, then rerun with APPROVE_RESTORE_DRILL=yes." >&2; exit 2; }
	@test -t 0 || { echo "ERROR: restore-drill must be run attended from a terminal" >&2; exit 2; }

require-network-policy-approval:
	@test "$(APPROVE_NETWORK_POLICY)" = yes || { \
		echo "ERROR: network-policy changes live traffic isolation on cluster $(CLUSTER)." >&2; \
		echo "       Review the rendered policy and rollback path, then rerun with APPROVE_NETWORK_POLICY=yes." >&2; exit 2; }
	@test -t 0 || { echo "ERROR: network-policy must be run attended from a terminal" >&2; exit 2; }

require-confirm:
	@test "$(CONFIRM)" = yes || { \
		echo "ERROR: teardown deletes CNPG Cluster $(CNPG_CLUSTER); its Delete-reclaim PVC contains all Keycloak realm state." >&2; \
		echo "       Back up the database, then rerun with CONFIRM=yes." >&2; exit 2; }

# Vault is live shared infrastructure; establish TLS, health, and every Raft peer before mutation.
# The run log retracts exact index equality but defines no safe lag threshold, so indices are
# printed for review while sealed/HA state is asserted mechanically.
# The manifests are templates, so what gets applied is not directly readable from the repo and not
# directly diffable against the cluster. Rather than commit a second, rendered copy that can drift
# from the template, render on demand: `render` shows exactly what `install` would apply, and
# `diff` compares that against the live cluster. `diff` is also a drift detector — a committed copy
# could only ever report itself as correct.
render: require-cluster ## Print the manifests exactly as install would apply them
	@set -Eeuo pipefail; for t in "$(IDENTITIES_TEMPLATE)" "$(VSO_WIRING_TEMPLATE)" "$(DATABASE_TEMPLATE)" "$(REACHABILITY_TEMPLATE)" "$(NETWORKPOLICY_TEMPLATE)"; do \
		echo "---"; \
		NAMESPACE="$(NAMESPACE)" SYSTEM_NAMESPACE="$(SYSTEM_NAMESPACE)" CNPG_CLUSTER="$(CNPG_CLUSTER)" CNPG_NAMESPACE="$(CNPG_NAMESPACE)" INGRESS_NAMESPACE="$(INGRESS_NAMESPACE)" KEYCLOAK_RELEASE="$(KEYCLOAK_RELEASE)" KEYCLOAK_HOST="$(KEYCLOAK_HOST)" KEYCLOAK_TLS_SECRET="$(KEYCLOAK_TLS_SECRET)" KEYCLOAK_TLS_ISSUER="$(KEYCLOAK_TLS_ISSUER)" DB_NAME="$(DB_NAME)" DB_USERNAME="$(DB_USERNAME)" KV_MOUNT="$(KV_MOUNT)" KV_ADMIN_PATH="$(KV_ADMIN_PATH)" KV_DB_PATH="$(KV_DB_PATH)" VAULT_AUTH_MOUNT="$(VAULT_AUTH_MOUNT)" VAULT_CA_DEST_SECRET="$(VAULT_CA_DEST_SECRET)" VAULT_READER_ROLE="$(VAULT_READER_ROLE)" VAULT_REVIEWER_CRB="$(VAULT_REVIEWER_CRB)" VAULT_REVIEWER_SA="$(VAULT_REVIEWER_SA)" VAULT_REVIEWER_TOKEN_SECRET="$(VAULT_REVIEWER_TOKEN_SECRET)" VAULT_SEED_SA="$(VAULT_SEED_SA)" VAULT_SERVICE_ADDRESS="$(VAULT_SERVICE_ADDRESS)" VSO_ADMIN_SECRET="$(VSO_ADMIN_SECRET)" VSO_AUTH="$(VSO_AUTH)" VSO_CONNECTION="$(VSO_CONNECTION)" VSO_DB_SECRET="$(VSO_DB_SECRET)" VSO_REFRESH_AFTER="$(VSO_REFRESH_AFTER)" VSO_SERVICE_ACCOUNT="$(VSO_SERVICE_ACCOUNT)" \
		$(PYTHON) -c 'import os,string,sys; print(string.Template(open(sys.argv[1]).read()).substitute(os.environ), end="")' "$$t"; \
	done

diff: require-inputs ## Diff the rendered manifests against the live cluster (exit 1 = drift)
	@set -Eeuo pipefail; d="$$(mktemp -d)"; trap 'rm -rf -- "$$d"' EXIT INT TERM; \
		$(MAKE) --no-print-directory render CLUSTER="$(CLUSTER)" NAMESPACE="$(NAMESPACE)" > "$$d/rendered.yaml"; \
		$(KUBECTL) --kubeconfig "$(KUBECONFIG)" diff -f "$$d/rendered.yaml" && echo "no drift: live cluster matches the rendered manifests"

baseline: require-inputs require-tools ## Run the recorded read-only Vault baseline probes
	@set -Eeuo pipefail; umask 077; d="$$(mktemp -d)"; test -d "$$d"; trap 'rm -rf -- "$$d"' EXIT INT TERM; \
		$(KUBECTL) --kubeconfig "$(KUBECONFIG)" get secret "$(VAULT_CA_SECRET)" -n "$(VAULT_NS)" -o jsonpath='$(VAULT_CA_JSONPATH)' | base64 -d > "$$d/ca.pem"; \
		if [ -n "$(VAULT_LB)" ] && [ -n "$(VAULT_HOST)" ]; then \
			probe_host="$(VAULT_HOST)"; probe_target="$(VAULT_LB):443"; probe_resolve="$(VAULT_HOST):443:$(VAULT_LB)"; probe_url="https://$(VAULT_HOST)/v1/sys/health"; \
			echo "Probing the EXTERNAL consumer endpoint $$probe_target (SNI $$probe_host)"; \
			bash -c "cat < /dev/null > /dev/tcp/$(VAULT_LB)/443"; \
		else \
			echo "NOTE: VAULT_LB/VAULT_HOST unset — probing Vault over an in-cluster port-forward."; \
			echo "      The external LoadBalancer/SNI passthrough route is NOT exercised by this run."; \
			$(KUBECTL) --kubeconfig "$(KUBECONFIG)" port-forward -n "$(VAULT_NS)" "svc/$(VAULT_SVC)" "$(VAULT_LOCAL_PORT):$(VAULT_SVC_PORT)" --address=127.0.0.1 > "$$d/pf.log" 2>&1 & pf=$$!; \
			trap 'kill $$pf 2>/dev/null || true; rm -rf -- "$$d"' EXIT INT TERM; \
			for i in $$(seq 1 30); do (exec 3<>/dev/tcp/127.0.0.1/$(VAULT_LOCAL_PORT)) 2>/dev/null && break || sleep 1; done; \
			probe_host="$(VAULT_INTERNAL_HOST)"; probe_target="127.0.0.1:$(VAULT_LOCAL_PORT)"; probe_resolve="$(VAULT_RESOLVE)"; probe_url="$(VAULT_BASE_URL)/v1/sys/health"; \
		fi; \
		test -s "$$d/ca.pem" || { echo "ERROR: Vault CA is empty" >&2; exit 1; }; \
		openssl x509 -in "$$d/ca.pem" -noout -subject -issuer -dates; \
		echo | openssl s_client -connect "$$probe_target" -servername "$$probe_host" -CAfile "$$d/ca.pem" 2>/dev/null | openssl x509 -out "$$d/served.pem"; \
		openssl x509 -in "$$d/served.pem" -noout -subject -issuer -dates -ext subjectAltName; \
		openssl x509 -in "$$d/served.pem" -noout -checkhost "$$probe_host" >/dev/null; \
		ca_subject="$$(openssl x509 -in "$$d/ca.pem" -noout -subject -nameopt RFC2253)"; served_issuer="$$(openssl x509 -in "$$d/served.pem" -noout -issuer -nameopt RFC2253)"; \
		test "$${ca_subject#subject=}" = "$${served_issuer#issuer=}" || { echo "ERROR: served Vault certificate was not issued by the configured CA" >&2; exit 1; }; \
		echo | openssl s_client -connect "$$probe_target" -servername "$$probe_host" -CAfile "$$d/ca.pem" > "$$d/tls.out" 2>&1; \
		grep -F 'Verify return code: 0 (ok)' "$$d/tls.out"; \
		code="$$(curl -sS -o "$$d/health.json" -w '%{http_code}' --resolve "$$probe_resolve" --cacert "$$d/ca.pem" "$$probe_url")"; \
		test "$$code" = 200 || { echo "ERROR: Vault health returned HTTP $$code" >&2; $(JQ) . "$$d/health.json" >&2 || true; exit 1; }; \
		$(JQ) -e '.initialized == true and .sealed == false and .standby == false and (.version | length > 0) and (.cluster_name | length > 0)' "$$d/health.json" >/dev/null || { \
			echo "ERROR: Vault health JSON failed the baseline assertion. Observed:" >&2; \
			$(JQ) -r '"  initialized=\(.initialized)  sealed=\(.sealed)  standby=\(.standby)  version=\(.version // "<absent>")  cluster_name=\(.cluster_name // "<absent>")"' "$$d/health.json" >&2 || cat "$$d/health.json" >&2; \
			echo "  NOTE: standby=true here usually means the port-forward reached a Raft STANDBY rather than" >&2; \
			echo "        the leader, which happens transiently while the cluster is churning. Re-run before" >&2; \
			echo "        treating it as a Vault regression." >&2; \
			exit 1; }; \
		: > "$$d/peers.jsonl"; for pod in $(VAULT_PODS); do $(KUBECTL) --kubeconfig "$(KUBECONFIG)" exec -n "$(VAULT_NS)" "$$pod" -- vault status -format=json | tee -a "$$d/peers.jsonl"; done; \
		$(JQ) -s -e 'length > 0 and all(.[]; .sealed == false and .ha_enabled == true and (.raft_committed_index | type == "number"))' "$$d/peers.jsonl" >/dev/null || { \
			echo "ERROR: a Vault peer failed the baseline assertion. Observed per peer:" >&2; \
			$(JQ) -sr '.[] | "  sealed=\(.sealed)  ha_enabled=\(.ha_enabled)  raft_committed_index=\(.raft_committed_index // "<absent>")"' "$$d/peers.jsonl" >&2 || cat "$$d/peers.jsonl" >&2; \
			exit 1; }; \
		echo -n 'Vault raft_committed_index values (review for close, advancing peers): '; $(JQ) -sr 'map(.raft_committed_index) | @json' "$$d/peers.jsonl"

# Starting VSO reconciles every pre-existing CR, so a non-empty inventory is a hard stop.
install-vso: require-inputs require-tools ## Preflight and install pinned VSO through ok-cluster
	@# The hazard this guards is ACTIVATION: starting the operator makes every pre-existing CR
	@# reconcile at once. If the operator is already running there is nothing to activate, and its
	@# own CRs are expected — enforcing then makes `install` non-rerunnable against a live system.
	@set -Eeuo pipefail; if $(KUBECTL) --kubeconfig "$(KUBECONFIG)" get deployment -n "$(VSO_NAMESPACE)" vault-secrets-operator-controller-manager >/dev/null 2>&1; then \
		echo "VSO already running; skipping the pre-activation CR enumeration."; \
	 else for kind in $(VSO_KINDS); do \
		out="$$(mktemp)"; trap 'rm -f -- "$$out"' EXIT INT TERM; \
		$(KUBECTL) --kubeconfig "$(KUBECONFIG)" get "$$kind.secrets.hashicorp.com" -A --no-headers > "$$out"; \
		test ! -s "$$out" || { echo "ERROR: pre-existing $$kind would reconcile as soon as VSO starts:" >&2; cat "$$out" >&2; exit 1; }; \
		rm -f -- "$$out"; trap - EXIT INT TERM; \
	done; fi
	@set -Eeuo pipefail; d="$$(mktemp -d)"; test -d "$$d"; trap 'rm -rf -- "$$d"' EXIT INT TERM; \
		$(KUBECTL) --kubeconfig "$(KUBECONFIG)" get crd vaultstaticsecrets.secrets.hashicorp.com -o json; \
		$(KUBECTL) --kubeconfig "$(KUBECONFIG)" get namespace > "$$d/namespaces"; grep -iE 'vault-secrets|vso' "$$d/namespaces" || true; \
		$(KUBECTL) --kubeconfig "$(KUBECONFIG)" get secret -A --field-selector type=helm.sh/release.v1 --no-headers > "$$d/releases"; grep -i vso "$$d/releases" || true; \
		$(KUBECTL) --kubeconfig "$(KUBECONFIG)" get clusterrole,clusterrolebinding --no-headers > "$$d/rbac"; \
		printf 'Existing VSO cluster RBAC objects: '; grep -c vault-secrets-operator "$$d/rbac" || true
	@test -d "$(OK_CLUSTER)" || { echo "ERROR: ok-cluster checkout is absent: $(OK_CLUSTER) (override OK_CLUSTER)" >&2; exit 2; }
	@make -C "$(OK_CLUSTER)" install-vso CLUSTER="$(CLUSTER)" VSO_NAMESPACE="$(VSO_NAMESPACE)" VSO_CHART_VERSION="$(VSO_CHART_VERSION)"
	@$(KUBECTL) --kubeconfig "$(KUBECONFIG)" wait --for=condition=Established crd/vaultstaticsecrets.secrets.hashicorp.com --timeout="$(VSO_WAIT_TIMEOUT)"
	@$(KUBECTL) --kubeconfig "$(KUBECONFIG)" rollout status deployment/$(VSO_RELEASE)-controller-manager -n "$(VSO_NAMESPACE)" --timeout="$(VSO_WAIT_TIMEOUT)"

# The namespace must precede its ServiceAccounts; server dry-run cannot model that multi-doc order.
identities: require-inputs require-tools ## Apply and verify namespace, reviewer, reader, and seeder identities
	@set -Eeuo pipefail; d="$$(mktemp -d)"; test -d "$$d"; trap 'rm -rf -- "$$d"' EXIT INT TERM; \
		NAMESPACE="$(NAMESPACE)" SYSTEM_NAMESPACE="$(SYSTEM_NAMESPACE)" VAULT_REVIEWER_SA="$(VAULT_REVIEWER_SA)" VAULT_REVIEWER_TOKEN_SECRET="$(VAULT_REVIEWER_TOKEN_SECRET)" \
		VAULT_REVIEWER_CRB="$(VAULT_REVIEWER_CRB)" VSO_SERVICE_ACCOUNT="$(VSO_SERVICE_ACCOUNT)" VAULT_SEED_SA="$(VAULT_SEED_SA)" \
		$(PYTHON) -c 'import os,string,sys; print(string.Template(open(sys.argv[1]).read()).substitute(os.environ), end="")' "$(IDENTITIES_TEMPLATE)" > "$$d/identities.yaml"; \
		$(KUBECTL) --kubeconfig "$(KUBECONFIG)" apply -f "$$d/identities.yaml"; \
		for i in $$(seq 1 30); do \
			tok="$$($(KUBECTL) --kubeconfig "$(KUBECONFIG)" get secret $(VAULT_REVIEWER_TOKEN_SECRET) -n "$(SYSTEM_NAMESPACE)" -o jsonpath='{.data.token}' 2>/dev/null || true)"; \
			test -n "$$tok" && break; sleep 2; \
		done; \
		test -n "$$tok" || { echo "ERROR: reviewer token Secret was not populated by the token controller" >&2; exit 1; }; \
		test "$$($(KUBECTL) --kubeconfig "$(KUBECONFIG)" auth can-i create tokenreviews.authentication.k8s.io --as=system:serviceaccount:$(SYSTEM_NAMESPACE):$(VAULT_REVIEWER_SA))" = yes; \
		test "$$($(KUBECTL) --kubeconfig "$(KUBECONFIG)" auth can-i create subjectaccessreviews.authorization.k8s.io --as=system:serviceaccount:$(SYSTEM_NAMESPACE):$(VAULT_REVIEWER_SA))" = yes; \
		test "$$($(KUBECTL) --kubeconfig "$(KUBECONFIG)" auth can-i list secrets -n "$(NAMESPACE)" --as=system:serviceaccount:$(NAMESPACE):$(VAULT_SEED_SA))" = no; \
		test "$$($(KUBECTL) --kubeconfig "$(KUBECONFIG)" auth can-i create tokenreviews.authentication.k8s.io --as=system:serviceaccount:$(NAMESPACE):$(VSO_SERVICE_ACCOUNT))" = no

# This is intentionally never a dependency of install: both ok-mgmt applies require separate review.
vault-config: require-inputs require-tools require-mgmt-approval ## APPROVAL: copy reviewer JWT and apply VaultConfig on ok-mgmt
	@set -Eeuo pipefail; umask 077; d="$$(mktemp -d)"; test -d "$$d"; trap 'rm -rf -- "$$d"' EXIT INT TERM; \
		$(PYTHON) -c 'import sys,yaml; d=yaml.safe_load(open(sys.argv[1])); assert d["metadata"]["name"] == sys.argv[2] and d["spec"]["clusterName"] == sys.argv[2], "VAULT_CONFIG does not match CLUSTER"' "$(VAULT_CONFIG)" "$(CLUSTER)"; \
		$(KUBECTL) --kubeconfig "$(KUBECONFIG)" get secret "$(VAULT_REVIEWER_TOKEN_SECRET)" -n "$(SYSTEM_NAMESPACE)" -o jsonpath='{.data.token}' | base64 -d > "$$d/token"; \
		test -s "$$d/token" || { echo "ERROR: reviewer JWT is empty" >&2; exit 1; }; \
		read -r -p "Apply reviewer JWT Secret to $(MGMT_CLUSTER)? Type yes: " answer; test "$$answer" = yes || { echo "Aborted." >&2; exit 1; }; \
		$(KUBECTL) --kubeconfig "$(MGMT_KUBECONFIG)" create secret generic "$(VAULT_REVIEWER_SECRET)" -n "$(MGMT_NAMESPACE)" --from-file=token="$$d/token" --dry-run=client -o yaml | $(KUBECTL) --kubeconfig "$(MGMT_KUBECONFIG)" apply -f -; \
		$(KUBECTL) --kubeconfig "$(MGMT_KUBECONFIG)" apply --dry-run=server -f "$(VAULT_CONFIG)"; \
		read -r -p "Apply reviewed VaultConfig XR to $(MGMT_CLUSTER)? Type yes: " answer; test "$$answer" = yes || { echo "Aborted." >&2; exit 1; }; \
		$(KUBECTL) --kubeconfig "$(MGMT_KUBECONFIG)" apply -f "$(VAULT_CONFIG)"; \
		$(KUBECTL) --kubeconfig "$(MGMT_KUBECONFIG)" wait --for=condition=Synced=True "vaultconfig/$(VAULT_CONFIG_NAME)" --timeout=2m; \
		$(KUBECTL) --kubeconfig "$(MGMT_KUBECONFIG)" wait --for=condition=Ready=True "vaultconfig/$(VAULT_CONFIG_NAME)" --timeout=2m

# cas=0 is deliberate: rerunning seed must fail instead of silently rotating credentials.
seed: require-inputs require-tools require-vault-config ## Seed one-time admin and database credentials through the write-only identity
	@set -Eeuo pipefail; umask 077; d="$$(mktemp -d)"; test -d "$$d"; trap 'rm -rf -- "$$d"' EXIT INT TERM; \
		$(KUBECTL) --kubeconfig "$(KUBECONFIG)" get secret "$(VAULT_CA_SECRET)" -n "$(VAULT_NS)" -o jsonpath='$(VAULT_CA_JSONPATH)' | base64 -d > "$$d/ca.pem"; \
		test -s "$$d/ca.pem" || { echo "ERROR: Vault CA is empty" >&2; exit 1; }; \
		$(KUBECTL) --kubeconfig "$(KUBECONFIG)" port-forward -n "$(VAULT_NS)" "svc/$(VAULT_SVC)" "$(VAULT_LOCAL_PORT):$(VAULT_SVC_PORT)" --address=127.0.0.1 > "$$d/pf.log" 2>&1 & pf=$$!; \
		trap 'kill $$pf 2>/dev/null || true; rm -rf -- "$$d"' EXIT INT TERM; \
		for i in $$(seq 1 30); do curl -sS -o /dev/null --cacert "$$d/ca.pem" "$(VAULT_BASE_URL)/v1/sys/health" --resolve "$(VAULT_RESOLVE)" && break || sleep 1; done; \
		KUBECTL="$(KUBECTL)" KUBECONFIG="$(KUBECONFIG)" NAMESPACE="$(NAMESPACE)" VAULT_BASE_URL="$(VAULT_BASE_URL)" VAULT_RESOLVE="$(VAULT_RESOLVE)" \
		VAULT_AUTH_MOUNT="$(VAULT_AUTH_MOUNT)" VAULT_SEED_ROLE="$(VAULT_SEED_ROLE)" VAULT_SEED_SA="$(VAULT_SEED_SA)" \
		KEYCLOAK_ADMIN_USERNAME="$(KEYCLOAK_ADMIN_USERNAME)" DB_USERNAME="$(DB_USERNAME)" \
		KV_ADMIN_PATH="$(KV_MOUNT)/data/$(KV_ADMIN_PATH)" KV_DB_PATH="$(KV_MOUNT)/data/$(KV_DB_PATH)" \
		KV_CROSS_CLUSTER_PROBE="$(KV_CROSS_CLUSTER_PROBE)" bash "$(SEED_SCRIPT)" "$$d/ca.pem"

# The CA copy is namespace-local because VaultConnection cannot reference a Secret across namespaces.
vso-wiring: require-inputs require-tools ## Apply VSO connection/auth/secrets and wait for current-generation sync
	@set -Eeuo pipefail; umask 077; d="$$(mktemp -d)"; test -d "$$d"; trap 'rm -rf -- "$$d"' EXIT INT TERM; \
		$(KUBECTL) --kubeconfig "$(KUBECONFIG)" get secret "$(VAULT_CA_SECRET)" -n "$(VAULT_NS)" -o jsonpath='$(VAULT_CA_JSONPATH)' | base64 -d > "$$d/ca.crt"; \
		$(KUBECTL) --kubeconfig "$(KUBECONFIG)" create secret generic "$(VAULT_CA_DEST_SECRET)" -n "$(NAMESPACE)" --from-file=ca.crt="$$d/ca.crt" --dry-run=client -o yaml | $(KUBECTL) --kubeconfig "$(KUBECONFIG)" apply -f -; \
		NAMESPACE="$(NAMESPACE)" VSO_CONNECTION="$(VSO_CONNECTION)" VSO_AUTH="$(VSO_AUTH)" VSO_SERVICE_ACCOUNT="$(VSO_SERVICE_ACCOUNT)" \
		VSO_ADMIN_SECRET="$(VSO_ADMIN_SECRET)" VSO_DB_SECRET="$(VSO_DB_SECRET)" VSO_REFRESH_AFTER="$(VSO_REFRESH_AFTER)" \
		VAULT_CA_DEST_SECRET="$(VAULT_CA_DEST_SECRET)" VAULT_SERVICE_ADDRESS="$(VAULT_SERVICE_ADDRESS)" VAULT_TLS_SERVER_NAME="$(VAULT_TLS_SERVER_NAME)" \
		VAULT_AUTH_MOUNT="$(VAULT_AUTH_MOUNT)" VAULT_READER_ROLE="$(VAULT_READER_ROLE)" KV_MOUNT="$(KV_MOUNT)" \
		KV_ADMIN_PATH="$(KV_ADMIN_PATH)" KV_DB_PATH="$(KV_DB_PATH)" \
		$(PYTHON) -c 'import os,string,sys; print(string.Template(open(sys.argv[1]).read()).substitute(os.environ), end="")' "$(VSO_WIRING_TEMPLATE)" > "$$d/vso.yaml"; \
		$(KUBECTL) --kubeconfig "$(KUBECONFIG)" apply -f "$$d/vso.yaml"; \
		KUBECTL="$(KUBECTL)" TIMEOUT="$(TIMEOUT)" KUBECONFIG="$(KUBECONFIG)" NAMESPACE="$(NAMESPACE)" WAIT_TIMEOUT="$(VSO_WAIT_TIMEOUT)" \
		bash "$(VSO_WAIT_SCRIPT)" "$(VSO_ADMIN_SECRET)" "$(VSO_DB_SECRET)"; \
		$(KUBECTL) --kubeconfig "$(KUBECONFIG)" get secret "$(VSO_DB_SECRET)" -n "$(NAMESPACE)" -o json | \
		$(JQ) -e --arg username "$$(printf '%s' "$(DB_USERNAME)" | base64 | tr -d '\n')" '.type == "kubernetes.io/basic-auth" and .metadata.labels["cnpg.io/reload"] == "true" and .data.username == $$username and (.data.password | length > 0)' >/dev/null; \
		$(KUBECTL) --kubeconfig "$(KUBECONFIG)" get secret "$(VSO_ADMIN_SECRET)" -n "$(NAMESPACE)" -o json | \
		$(JQ) -e '(.data.username | length > 0) and (.data.password | length > 0)' >/dev/null

# Server-side apply avoids oversized CRD annotations; restart after Established clears stale discovery.
database: require-inputs require-tools require-cnpg ## Install pinned CNPG, then create and wait for the database
	@$(KUBECTL) --kubeconfig "$(KUBECONFIG)" apply --server-side --force-conflicts -f "$(CNPG_MANIFEST)"
	@$(KUBECTL) --kubeconfig "$(KUBECONFIG)" wait --for=condition=Established crd/clusters.postgresql.cnpg.io crd/poolers.postgresql.cnpg.io --timeout="$(CNPG_WAIT_TIMEOUT)"
	@$(KUBECTL) --kubeconfig "$(KUBECONFIG)" rollout restart deployment/$(CNPG_DEPLOYMENT) -n "$(CNPG_NAMESPACE)"
	@$(KUBECTL) --kubeconfig "$(KUBECONFIG)" rollout status deployment/$(CNPG_DEPLOYMENT) -n "$(CNPG_NAMESPACE)" --timeout="$(CNPG_WAIT_TIMEOUT)"
	@set -Eeuo pipefail; d="$$(mktemp -d)"; test -d "$$d"; trap 'rm -rf -- "$$d"' EXIT INT TERM; \
		NAMESPACE="$(NAMESPACE)" CNPG_CLUSTER="$(CNPG_CLUSTER)" VSO_DB_SECRET="$(VSO_DB_SECRET)" DB_NAME="$(DB_NAME)" DB_USERNAME="$(DB_USERNAME)" \
		$(PYTHON) -c 'import os,string,sys; print(string.Template(open(sys.argv[1]).read()).substitute(os.environ), end="")' "$(DATABASE_TEMPLATE)" > "$$d/database.yaml"; \
		$(KUBECTL) --kubeconfig "$(KUBECONFIG)" apply -f "$$d/database.yaml"
	@$(KUBECTL) --kubeconfig "$(KUBECONFIG)" wait --for=condition=Ready=True "cluster.postgresql.cnpg.io/$(CNPG_CLUSTER)" -n "$(NAMESPACE)" --timeout="$(CNPG_WAIT_TIMEOUT)"
	@$(KUBECTL) --kubeconfig "$(KUBECONFIG)" wait --for=jsonpath='{.status.phase}'=Bound pvc -l "cnpg.io/cluster=$(CNPG_CLUSTER)" -n "$(NAMESPACE)" --timeout="$(CNPG_WAIT_TIMEOUT)"

reachability: require-inputs require-tools ## Apply the Keycloak server Certificate and TLS-passthrough route
	@set -Eeuo pipefail; d="$$(mktemp -d)"; test -d "$$d"; trap 'rm -rf -- "$$d"' EXIT INT TERM; \
		NAMESPACE="$(NAMESPACE)" KEYCLOAK_RELEASE="$(KEYCLOAK_RELEASE)" KEYCLOAK_HOST="$(KEYCLOAK_HOST)" KEYCLOAK_TLS_SECRET="$(KEYCLOAK_TLS_SECRET)" KEYCLOAK_TLS_ISSUER="$(KEYCLOAK_TLS_ISSUER)" \
		$(PYTHON) -c 'import os,string,sys; print(string.Template(open(sys.argv[1]).read()).substitute(os.environ), end="")' "$(REACHABILITY_TEMPLATE)" > "$$d/reachability.yaml"; \
		$(KUBECTL) --kubeconfig "$(KUBECONFIG)" apply -f "$$d/reachability.yaml"; \
		$(KUBECTL) --kubeconfig "$(KUBECONFIG)" wait --for=condition=Ready=True "certificate/$(KEYCLOAK_TLS_SECRET)" -n "$(NAMESPACE)" --timeout="$(KEYCLOAK_CERT_WAIT_TIMEOUT)"; \
		$(KUBECTL) --kubeconfig "$(KUBECONFIG)" get secret "$(KEYCLOAK_TLS_SECRET)" -n "$(NAMESPACE)" -o name

# The local chart is rendered immediately before install so the reviewed tree is the applied tree.
keycloak: require-inputs require-tools require-chart require-values-contract ## Render and install Keycloak from the pinned local chart
	@$(HELM) template "$(KEYCLOAK_RELEASE)" "$(CHART_DIR)" -n "$(NAMESPACE)" -f "$(VALUES_FILE)" >/dev/null
	@$(HELM) upgrade --install "$(KEYCLOAK_RELEASE)" "$(CHART_DIR)" -n "$(NAMESPACE)" -f "$(VALUES_FILE)" --kubeconfig "$(KUBECONFIG)"
	@$(KUBECTL) --kubeconfig "$(KUBECONFIG)" rollout status statefulset/$(KEYCLOAK_STATEFULSET) -n "$(NAMESPACE)" --timeout="$(KEYCLOAK_WAIT_TIMEOUT)"

# realm does not consume VALUES_FILE, so coupling it to require-values-contract would mix concerns.
# Assert the canonical origin it does rely on directly; the forward remains process-owned so every
# success, failure, signal, or timeout reaps it.
realm: require-inputs require-tools ## Provision the platform realm, its groups, and one OIDC client per cluster (idempotent)
	@set -Eeuo pipefail; \
		$(PYTHON) -c 'import sys; assert sys.argv[2]==sys.argv[1]+":443", f"realm origin {sys.argv[2]!r} is not canonical HTTPS for KC_HOSTNAME {sys.argv[1]!r}"; assert int(sys.argv[3]) > 1023, "VERIFY_PORT must be unprivileged"' "$(KEYCLOAK_HOSTNAME)" "$(KEYCLOAK_VERIFY_ORIGIN)" "$(VERIFY_PORT)"; \
		$(PYTHON) -c 'import socket,sys; s=socket.socket(); s.bind(("127.0.0.1", int(sys.argv[1]))); s.close()' "$(VERIFY_PORT)" || { echo "ERROR: localhost:$(VERIFY_PORT) is already bound; refusing to risk the wrong Keycloak origin" >&2; exit 1; }; \
		d="$$(mktemp -d)"; test -d "$$d"; pf_pid=''; cleanup() { if test -n "$$pf_pid"; then kill "$$pf_pid" 2>/dev/null || true; wait "$$pf_pid" 2>/dev/null || true; fi; rm -rf -- "$$d"; }; trap cleanup EXIT INT TERM; \
		$(KUBECTL) --kubeconfig "$(KUBECONFIG)" get secret "$(KEYCLOAK_TLS_SECRET)" -n "$(NAMESPACE)" -o jsonpath='{.data.ca\.crt}' | base64 -d > "$$d/ca.crt"; test -s "$$d/ca.crt" || { echo "ERROR: $(KEYCLOAK_TLS_SECRET) has no CA certificate" >&2; exit 1; }; \
		$(KUBECTL) --kubeconfig "$(KUBECONFIG)" port-forward -n "$(NAMESPACE)" statefulset/$(KEYCLOAK_STATEFULSET) "$(VERIFY_PORT):8443" --address=127.0.0.1 > "$$d/port-forward.log" 2>&1 & pf_pid=$$!; \
		set +o pipefail; $(TIMEOUT) "$(PORT_FORWARD_TIMEOUT)" tail -n +1 -F "$$d/port-forward.log" | grep -m1 -F "Forwarding from 127.0.0.1:$(VERIFY_PORT)" >/dev/null; statuses=("$${PIPESTATUS[@]}"); set -o pipefail; \
		test "$${statuses[1]}" = 0 || { echo "ERROR: port-forward did not become ready" >&2; cat "$$d/port-forward.log" >&2; exit 1; }; \
		kill -0 "$$pf_pid" 2>/dev/null || { echo "ERROR: port-forward exited before conformance" >&2; cat "$$d/port-forward.log" >&2; exit 1; }; \
		KUBECTL="$(KUBECTL)" KUBECONFIG="$(KUBECONFIG)" NAMESPACE="$(NAMESPACE)" KC_ORIGIN="$(KEYCLOAK_VERIFY_ORIGIN)" KC_RESOLVE="$(KEYCLOAK_HOST):443:127.0.0.1" KC_CONNECT="$(KEYCLOAK_HOST):443:127.0.0.1:$(VERIFY_PORT)" KC_CACERT="$$d/ca.crt" KC_EXPECTED_ISSUER="$(KC_EXPECTED_ISSUER)" KEYCLOAK_ADMIN_USERNAME="$(KEYCLOAK_ADMIN_USERNAME)" VSO_ADMIN_SECRET="$(VSO_ADMIN_SECRET)" PLATFORM_REALM="$(PLATFORM_REALM)" PLATFORM_GROUPS="$(PLATFORM_GROUPS)" PLATFORM_CLIENTS="$(PLATFORM_CLIENTS)" bash "$(REALM_SCRIPT)"

# Only public CA and port-forward diagnostics enter the work directory. Both passwords are streamed
# from their source Secrets into inherited descriptors and are never placed in argv, the environment,
# a log, or a file. flock prevents two reconcilers from sharing the fixed localhost port.
rmf-realm: require-rmf-realm-inputs require-rmf-realm-approval ## APPROVAL: provision the RMF Web application realm on ok-shared (idempotent)
	@set -Eeuo pipefail; umask 077; \
		exec 9>"$(RMF_REALM_LOCK)"; flock -n 9 || { echo "ERROR: another RMF realm provisioner holds $(RMF_REALM_LOCK)" >&2; exit 1; }; \
		$(PYTHON) -c 'import sys; assert sys.argv[2]==sys.argv[1]+":443", f"RMF realm origin {sys.argv[2]!r} is not canonical HTTPS for KC_HOSTNAME {sys.argv[1]!r}"; assert int(sys.argv[3]) > 1023, "VERIFY_PORT must be unprivileged"' "$(KEYCLOAK_HOSTNAME)" "$(KEYCLOAK_VERIFY_ORIGIN)" "$(VERIFY_PORT)"; \
		$(PYTHON) -c 'import socket,sys; s=socket.socket(); s.bind(("127.0.0.1", int(sys.argv[1]))); s.close()' "$(VERIFY_PORT)" || { echo "ERROR: localhost:$(VERIFY_PORT) is already bound; refusing to risk the wrong Keycloak origin" >&2; exit 1; }; \
		d="$$(mktemp -d)"; test -d "$$d"; pf_pid=''; cleanup() { if test -n "$$pf_pid"; then kill "$$pf_pid" 2>/dev/null || true; wait "$$pf_pid" 2>/dev/null || true; fi; rm -rf -- "$$d"; }; trap cleanup EXIT INT TERM; \
		$(KUBECTL) --kubeconfig "$(KUBECONFIG)" get secret "$(KEYCLOAK_TLS_SECRET)" -n "$(NAMESPACE)" -o jsonpath='{.data.ca\.crt}' | base64 -d > "$$d/ca.crt"; test -s "$$d/ca.crt" || { echo "ERROR: $(KEYCLOAK_TLS_SECRET) has no CA certificate" >&2; exit 1; }; \
		$(KUBECTL) --kubeconfig "$(KUBECONFIG)" port-forward -n "$(NAMESPACE)" statefulset/$(KEYCLOAK_STATEFULSET) "$(VERIFY_PORT):8443" --address=127.0.0.1 > "$$d/port-forward.log" 2>&1 & pf_pid=$$!; \
		set +o pipefail; $(TIMEOUT) "$(PORT_FORWARD_TIMEOUT)" tail -n +1 -F "$$d/port-forward.log" | grep -m1 -F "Forwarding from 127.0.0.1:$(VERIFY_PORT)" >/dev/null; statuses=("$${PIPESTATUS[@]}"); set -o pipefail; \
		test "$${statuses[1]}" = 0 || { echo "ERROR: port-forward did not become ready" >&2; cat "$$d/port-forward.log" >&2; exit 1; }; \
		kill -0 "$$pf_pid" 2>/dev/null || { echo "ERROR: port-forward exited before RMF realm provisioning" >&2; cat "$$d/port-forward.log" >&2; exit 1; }; \
		KC_ORIGIN="$(KEYCLOAK_VERIFY_ORIGIN)" KC_RESOLVE="$(KEYCLOAK_HOST):443:127.0.0.1" KC_CONNECT="$(KEYCLOAK_HOST):443:127.0.0.1:$(VERIFY_PORT)" KC_CACERT="$$d/ca.crt" \
		KEYCLOAK_ADMIN_USERNAME="$(KEYCLOAK_ADMIN_USERNAME)" RMF_REALM="$(RMF_REALM)" RMF_WEB_ORIGIN="$(RMF_WEB_ORIGIN)" \
		bash "$(RMF_REALM_SCRIPT)" \
			3< <($(KUBECTL) --kubeconfig "$(KUBECONFIG)" get secret "$(VSO_ADMIN_SECRET)" -n "$(NAMESPACE)" -o jsonpath='{.data.password}' | base64 -d) \
			4< <($(KUBECTL) --kubeconfig "$(MGMT_KUBECONFIG)" get secret "$(RMF_CREDENTIALS_SECRET)" -n "$(RMF_CREDENTIALS_NAMESPACE)" -o "jsonpath={.data.$(RMF_ADMIN_PASSWORD_KEY)}" | base64 -d)

verify: require-inputs require-tools require-values-contract ## Run the recorded OIDC conformance test through an owned port-forward
	@set -Eeuo pipefail; \
		$(PYTHON) -c 'import sys; assert sys.argv[2]==sys.argv[1]+":443", f"conformance origin {sys.argv[2]!r} is not canonical HTTPS for KC_HOSTNAME {sys.argv[1]!r}"; assert int(sys.argv[3]) > 1023, "VERIFY_PORT must be unprivileged"' "$(KEYCLOAK_HOSTNAME)" "$(KEYCLOAK_VERIFY_ORIGIN)" "$(VERIFY_PORT)"; \
		$(PYTHON) -c 'import socket,sys; s=socket.socket(); s.bind(("127.0.0.1", int(sys.argv[1]))); s.close()' "$(VERIFY_PORT)" || { echo "ERROR: localhost:$(VERIFY_PORT) is already bound; refusing to risk the wrong Keycloak origin" >&2; exit 1; }; \
		d="$$(mktemp -d)"; test -d "$$d"; pf_pid=''; cleanup() { if test -n "$$pf_pid"; then kill "$$pf_pid" 2>/dev/null || true; wait "$$pf_pid" 2>/dev/null || true; fi; rm -rf -- "$$d"; }; trap cleanup EXIT INT TERM; \
		$(KUBECTL) --kubeconfig "$(KUBECONFIG)" get secret "$(KEYCLOAK_TLS_SECRET)" -n "$(NAMESPACE)" -o jsonpath='{.data.ca\.crt}' | base64 -d > "$$d/ca.crt"; test -s "$$d/ca.crt" || { echo "ERROR: $(KEYCLOAK_TLS_SECRET) has no CA certificate" >&2; exit 1; }; \
		$(KUBECTL) --kubeconfig "$(KUBECONFIG)" port-forward -n "$(NAMESPACE)" statefulset/$(KEYCLOAK_STATEFULSET) "$(VERIFY_PORT):8443" --address=127.0.0.1 > "$$d/port-forward.log" 2>&1 & pf_pid=$$!; \
		set +o pipefail; $(TIMEOUT) "$(PORT_FORWARD_TIMEOUT)" tail -n +1 -F "$$d/port-forward.log" | grep -m1 -F "Forwarding from 127.0.0.1:$(VERIFY_PORT)" >/dev/null; statuses=("$${PIPESTATUS[@]}"); set -o pipefail; \
		test "$${statuses[1]}" = 0 || { echo "ERROR: port-forward did not become ready" >&2; cat "$$d/port-forward.log" >&2; exit 1; }; \
		kill -0 "$$pf_pid" 2>/dev/null || { echo "ERROR: port-forward exited before conformance" >&2; cat "$$d/port-forward.log" >&2; exit 1; }; \
		KUBECTL="$(KUBECTL)" KUBECONFIG="$(KUBECONFIG)" NAMESPACE="$(NAMESPACE)" KC_ORIGIN="$(KEYCLOAK_VERIFY_ORIGIN)" KC_RESOLVE="$(KEYCLOAK_HOST):443:127.0.0.1" KC_CONNECT="$(KEYCLOAK_HOST):443:127.0.0.1:$(VERIFY_PORT)" KC_CACERT="$$d/ca.crt" KC_EXPECTED_ISSUER="$(KEYCLOAK_HOSTNAME)" KEYCLOAK_ADMIN_USERNAME="$(KEYCLOAK_ADMIN_USERNAME)" bash "$(VERIFY_SCRIPT)"

backup: require-inputs require-tools ## Stream a compressed custom-format database dump to local retained storage
	@KUBECTL="$(KUBECTL)" KUBECONFIG="$(KUBECONFIG)" NAMESPACE="$(NAMESPACE)" \
		CNPG_CLUSTER="$(CNPG_CLUSTER)" DB_NAME="$(DB_NAME)" DB_USERNAME="$(DB_USERNAME)" \
		DB_SECRET="$(VSO_DB_SECRET)" BACKUP_DIR="$(BACKUP_DIR)" bash "$(BACKUP_SCRIPT)"

restore-drill: require-inputs require-tools require-restore-input require-restore-drill-approval ## APPROVAL: restore a dump into an isolated scratch database and assert realm/client rows
	@KUBECTL="$(KUBECTL)" KUBECONFIG="$(KUBECONFIG)" NAMESPACE="$(NAMESPACE)" \
		CNPG_CLUSTER="$(CNPG_CLUSTER)" DB_NAME="$(DB_NAME)" DB_USERNAME="$(DB_USERNAME)" \
		DB_SECRET="$(VSO_DB_SECRET)" APPROVE_RESTORE_DRILL="$(APPROVE_RESTORE_DRILL)" \
		bash "$(RESTORE_DRILL_SCRIPT)" "$(RESTORE_FILE)"

# Brute-force settings are written as a complete explicit policy and then re-read by the script.
brute-force: require-inputs require-tools require-values-contract ## Enable and re-read the master realm brute-force lockout policy
	@set -Eeuo pipefail; umask 077; \
		$(PYTHON) -c 'import socket,sys; s=socket.socket(); s.bind(("127.0.0.1", int(sys.argv[1]))); s.close()' "$(PORT)" || { echo "ERROR: localhost:$(PORT) is already bound; refusing to risk the wrong Keycloak origin" >&2; exit 1; }; \
		d="$$(mktemp -d)"; test -d "$$d"; pf_pid=''; \
		cleanup() { if test -n "$$pf_pid"; then kill "$$pf_pid" 2>/dev/null || true; wait "$$pf_pid" 2>/dev/null || true; fi; echo "      make work dir RETAINED: $$d"; }; trap cleanup EXIT INT TERM; \
		$(KUBECTL) --kubeconfig "$(KUBECONFIG)" port-forward -n "$(NAMESPACE)" statefulset/$(KEYCLOAK_STATEFULSET) "$(PORT):8080" --address=127.0.0.1 > "$$d/port-forward.log" 2>&1 & pf_pid=$$!; \
		set +o pipefail; $(TIMEOUT) "$(PORT_FORWARD_TIMEOUT)" tail -n +1 -F "$$d/port-forward.log" | grep -m1 -F "Forwarding from 127.0.0.1:$(PORT)" >/dev/null; statuses=("$${PIPESTATUS[@]}"); set -o pipefail; \
		test "$${statuses[1]}" = 0 || { echo "ERROR: port-forward did not become ready" >&2; cat "$$d/port-forward.log" >&2; exit 1; }; \
		kill -0 "$$pf_pid" 2>/dev/null || { echo "ERROR: port-forward exited before brute-force configuration" >&2; cat "$$d/port-forward.log" >&2; exit 1; }; \
		KUBECTL="$(KUBECTL)" KUBECONFIG="$(KUBECONFIG)" NAMESPACE="$(NAMESPACE)" KC_PORT="$(PORT)" \
		KEYCLOAK_ADMIN_USERNAME="$(KEYCLOAK_ADMIN_USERNAME)" VSO_ADMIN_SECRET="$(VSO_ADMIN_SECRET)" bash "$(BRUTE_FORCE_SCRIPT)"

# Apply last. A failed proof restores each pre-existing policy in place and deletes only policies
# introduced by this run. Re-running against an already-isolated cluster therefore cannot leave it
# with fewer policies. The proof deliberately does not mutate Secrets: unchanged CNPG passwords do
# not cause managed-role resourceVersions to advance, so that former wait was both slow and unsound.
network-policy: require-inputs require-tools require-network-policy-approval ## APPROVAL: apply isolation; prove allowed traffic healthy and external traffic blocked
	@set -Eeuo pipefail; umask 077; d="$$(mktemp -d)"; test -d "$$d"; mkdir "$$d/previous"; verified=0; touched=0; probe_created=0; probe="ok81-netpol-$$(date +%s)-$$$$"; \
		cleanup() { rc=$$?; trap - EXIT; if test "$$probe_created" = 1; then $(KUBECTL) --kubeconfig "$(KUBECONFIG)" delete pod "$$probe" -n default --ignore-not-found --wait=false >/dev/null || rc=1; fi; if test "$$touched" = 1 && test "$$verified" != 1; then echo "ERROR: a live proof failed; restoring the exact pre-run NetworkPolicy set" >&2; for n in default-deny keycloak keycloak-db; do if test -f "$$d/previous/$$n.json"; then $(KUBECTL) --kubeconfig "$(KUBECONFIG)" apply -f "$$d/previous/$$n.json" || rc=1; else $(KUBECTL) --kubeconfig "$(KUBECONFIG)" delete networkpolicy "$$n" -n "$(NAMESPACE)" --ignore-not-found || rc=1; fi; done; fi; echo "      make work dir RETAINED: $$d"; exit $$rc; }; trap cleanup EXIT; \
		NAMESPACE="$(NAMESPACE)" CNPG_CLUSTER="$(CNPG_CLUSTER)" CNPG_NAMESPACE="$(CNPG_NAMESPACE)" INGRESS_NAMESPACE="$(INGRESS_NAMESPACE)" KEYCLOAK_RELEASE="$(KEYCLOAK_RELEASE)" \
		$(PYTHON) -c 'import os,string,sys; print(string.Template(open(sys.argv[1]).read()).substitute(os.environ), end="")' "$(NETWORKPOLICY_TEMPLATE)" > "$$d/networkpolicy.yaml"; \
		for n in default-deny keycloak keycloak-db; do $(KUBECTL) --kubeconfig "$(KUBECONFIG)" get networkpolicy "$$n" -n "$(NAMESPACE)" --ignore-not-found -o json > "$$d/previous/$$n.candidate"; if test -s "$$d/previous/$$n.candidate"; then $(JQ) 'del(.metadata.creationTimestamp,.metadata.generation,.metadata.managedFields,.metadata.resourceVersion,.metadata.uid)' "$$d/previous/$$n.candidate" > "$$d/previous/$$n.json"; fi; done; \
		touched=1; $(KUBECTL) --kubeconfig "$(KUBECONFIG)" apply -f "$$d/networkpolicy.yaml"; \
		$(MAKE) --no-print-directory verify CLUSTER="$(CLUSTER)" NAMESPACE="$(NAMESPACE)" KUBECONFIG="$(KUBECONFIG)"; \
		kc_ip="$$($(KUBECTL) --kubeconfig "$(KUBECONFIG)" get service "$(KEYCLOAK_RELEASE)-keycloakx-http" -n "$(NAMESPACE)" -o jsonpath='{.spec.clusterIP}')"; \
		db_ip="$$($(KUBECTL) --kubeconfig "$(KUBECONFIG)" get service "$(CNPG_CLUSTER)-rw" -n "$(NAMESPACE)" -o jsonpath='{.spec.clusterIP}')"; \
		test -n "$$kc_ip" && test -n "$$db_ip" || { echo "ERROR: isolation probe service ClusterIP lookup failed" >&2; exit 1; }; \
		existing="$$($(KUBECTL) --kubeconfig "$(KUBECONFIG)" get pod "$$probe" -n default --ignore-not-found -o name)"; test -z "$$existing" || { echo "ERROR: probe pod already exists: default/$$probe" >&2; exit 1; }; \
		$(KUBECTL) --kubeconfig "$(KUBECONFIG)" run "$$probe" -n default --image=docker.io/busybox:1.37.0@sha256:9532d8c39891ca2ecde4d30d7710e01fb739c87a8b9299685c63704296b16028 --restart=Never --command -- sleep 300; probe_created=1; \
		$(KUBECTL) --kubeconfig "$(KUBECONFIG)" wait --for=condition=Ready pod/"$$probe" -n default --timeout=90s; \
		$(KUBECTL) --kubeconfig "$(KUBECONFIG)" exec -n default "$$probe" -- sh -ceu 'check_blocked() { if nc -z -w 3 "$$1" "$$2"; then echo "$$3:$$2 OPEN"; return 1; else echo "$$3:$$2 BLOCKED"; fi; }; check_blocked "$$1" 9000 keycloak-keycloakx-http; check_blocked "$$2" 5432 keycloak-db-rw' -- "$$kc_ip" "$$db_ip"; \
		st="$$($(KUBECTL) --kubeconfig "$(KUBECONFIG)" get cluster.postgresql.cnpg.io "$(CNPG_CLUSTER)" -n "$(NAMESPACE)" -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}')"; \
		test "$$st" = True || { echo "ERROR: CNPG Cluster $(CNPG_CLUSTER) Ready=$${st:-<none>}, expected True" >&2; exit 1; }; \
		cnpg_pod="$$($(KUBECTL) --kubeconfig "$(KUBECONFIG)" get pod -n "$(NAMESPACE)" -l 'cnpg.io/cluster=$(CNPG_CLUSTER),role=primary' -o jsonpath='{.items[0].metadata.name}')"; \
		test -n "$$cnpg_pod" || { echo "ERROR: CNPG primary pod not found" >&2; exit 1; }; \
		$(KUBECTL) --kubeconfig "$(KUBECONFIG)" logs -n "$(NAMESPACE)" "$$cnpg_pod" --all-containers=true --since=10m > "$$d/cnpg.log"; \
		if rg -F 'apiServerReachable:false' "$$d/cnpg.log"; then echo "ERROR: CNPG instance reported apiServerReachable:false in the last 10 minutes" >&2; exit 1; fi; \
		$(KUBECTL) --kubeconfig "$(KUBECONFIG)" get networkpolicy -n "$(NAMESPACE)" default-deny keycloak keycloak-db; \
		verified=1; echo "RESULT: PASS — allowed Keycloak traffic is healthy; external ports 9000/5432 are BLOCKED; CNPG is Ready=True with API reachability intact"

# Both of the following need Keycloak AND Vault at once: the credential is changed in Keycloak and
# escrowed in Vault in the same transaction-shaped sequence, so the port-forwards are opened
# together and owned by the target rather than left to the script.
define kc_and_vault_pf
set -Eeuo pipefail; umask 077; \
	for p in "$(PORT)" "$(VAULT_LOCAL_PORT)"; do \
		$(PYTHON) -c 'import socket,sys; s=socket.socket(); s.bind(("127.0.0.1", int(sys.argv[1]))); s.close()' "$$p" || \
		{ echo "ERROR: localhost:$$p is already bound; refusing to risk the wrong endpoint" >&2; exit 1; }; \
	done; \
	d="$$(mktemp -d)"; test -d "$$d"; kc_pf=''; v_pf=''; \
	cleanup() { for p in "$$kc_pf" "$$v_pf"; do test -n "$$p" && { kill "$$p" 2>/dev/null || true; wait "$$p" 2>/dev/null || true; }; done; echo "      make work dir RETAINED: $$d"; }; \
	trap cleanup EXIT INT TERM; \
	$(KUBECTL) --kubeconfig "$(KUBECONFIG)" get secret "$(VAULT_CA_SECRET)" -n "$(VAULT_NS)" -o jsonpath='$(VAULT_CA_JSONPATH)' | base64 -d > "$$d/ca.pem"; \
	test -s "$$d/ca.pem" || { echo "ERROR: Vault CA is empty" >&2; exit 1; }; \
	$(KUBECTL) --kubeconfig "$(KUBECONFIG)" port-forward -n "$(NAMESPACE)" statefulset/$(KEYCLOAK_STATEFULSET) "$(PORT):8080" --address=127.0.0.1 > "$$d/kc-pf.log" 2>&1 & kc_pf=$$!; \
	$(KUBECTL) --kubeconfig "$(KUBECONFIG)" port-forward -n "$(VAULT_NS)" "svc/$(VAULT_SVC)" "$(VAULT_LOCAL_PORT):$(VAULT_SVC_PORT)" --address=127.0.0.1 > "$$d/vault-pf.log" 2>&1 & v_pf=$$!; \
	set +o pipefail; $(TIMEOUT) "$(PORT_FORWARD_TIMEOUT)" tail -n +1 -F "$$d/kc-pf.log" | grep -m1 -F "Forwarding from 127.0.0.1:$(PORT)" >/dev/null; s1=("$${PIPESTATUS[@]}"); \
	$(TIMEOUT) "$(PORT_FORWARD_TIMEOUT)" tail -n +1 -F "$$d/vault-pf.log" | grep -m1 -F "Forwarding from 127.0.0.1:$(VAULT_LOCAL_PORT)" >/dev/null; s2=("$${PIPESTATUS[@]}"); set -o pipefail; \
	test "$${s1[1]}" = 0 || { echo "ERROR: Keycloak port-forward did not become ready" >&2; cat "$$d/kc-pf.log" >&2; exit 1; }; \
	test "$${s2[1]}" = 0 || { echo "ERROR: Vault port-forward did not become ready" >&2; cat "$$d/vault-pf.log" >&2; exit 1; }; \
	kill -0 "$$kc_pf" 2>/dev/null && kill -0 "$$v_pf" 2>/dev/null || { echo "ERROR: a port-forward exited early" >&2; exit 1; }; \
	for i in $$(seq 1 30); do curl -sS -o /dev/null --cacert "$$d/ca.pem" "$(VAULT_BASE_URL)/v1/sys/health" --resolve "$(VAULT_RESOLVE)" && break || sleep 1; done
endef

recover-admin: require-inputs require-tools require-cutover-approval ## APPROVAL: break-glass — create a temporary admin when no known credential works
	@set -Eeuo pipefail; umask 077; d="$$(mktemp -d)"; test -d "$$d"; v_pf=''; \
		cleanup() { test -n "$$v_pf" && { kill "$$v_pf" 2>/dev/null || true; wait "$$v_pf" 2>/dev/null || true; }; echo "      make work dir RETAINED: $$d"; }; trap cleanup EXIT INT TERM; \
		$(KUBECTL) --kubeconfig "$(KUBECONFIG)" get secret "$(VAULT_CA_SECRET)" -n "$(VAULT_NS)" -o jsonpath='$(VAULT_CA_JSONPATH)' | base64 -d > "$$d/ca.pem"; \
		test -s "$$d/ca.pem" || { echo "ERROR: Vault CA is empty" >&2; exit 1; }; \
		$(KUBECTL) --kubeconfig "$(KUBECONFIG)" port-forward -n "$(VAULT_NS)" "svc/$(VAULT_SVC)" "$(VAULT_LOCAL_PORT):$(VAULT_SVC_PORT)" --address=127.0.0.1 > "$$d/vault-pf.log" 2>&1 & v_pf=$$!; \
		for i in $$(seq 1 30); do curl -sS -o /dev/null --cacert "$$d/ca.pem" "$(VAULT_BASE_URL)/v1/sys/health" --resolve "$(VAULT_RESOLVE)" && break || sleep 1; done; \
		KUBECTL="$(KUBECTL)" KUBECONFIG="$(KUBECONFIG)" NAMESPACE="$(NAMESPACE)" \
		KEYCLOAK_POD="$(KEYCLOAK_STATEFULSET)-0" RECOVERY_USERNAME="$(RECOVERY_USERNAME)" \
		KV_RECOVERY_PATH="$(KV_MOUNT)/data/$(KV_RECOVERY_PATH)" \
		VAULT_BASE_URL="$(VAULT_BASE_URL)" VAULT_RESOLVE="$(VAULT_RESOLVE)" VAULT_AUTH_MOUNT="$(VAULT_AUTH_MOUNT)" \
		VAULT_SEED_ROLE="$(VAULT_SEED_ROLE)" VAULT_SEED_SA="$(VAULT_SEED_SA)" KV_PUT_SCRIPT="$(KV_PUT_SCRIPT)" \
		bash "$(RECOVER_SCRIPT)" "$$d/ca.pem"

admin-cutover: require-inputs require-tools require-cutover-approval ## APPROVAL: replace the temporary bootstrap admin with a permanent one and escrow it
	@$(kc_and_vault_pf); \
		KUBECTL="$(KUBECTL)" KUBECONFIG="$(KUBECONFIG)" NAMESPACE="$(NAMESPACE)" KC_PORT="$(PORT)" \
		ADMIN_USERNAME="$(KEYCLOAK_ADMIN_USERNAME)" TEMP_ADMIN_USERNAME="$(TEMP_ADMIN_USERNAME)" \
		VSO_ADMIN_SECRET="$(VSO_ADMIN_SECRET)" KV_ADMIN_PATH="$(KV_MOUNT)/data/$(KV_ADMIN_PATH)" \
		VAULT_BASE_URL="$(VAULT_BASE_URL)" VAULT_RESOLVE="$(VAULT_RESOLVE)" VAULT_AUTH_MOUNT="$(VAULT_AUTH_MOUNT)" \
		VAULT_SEED_ROLE="$(VAULT_SEED_ROLE)" VAULT_SEED_SA="$(VAULT_SEED_SA)" \
		KV_PUT_SCRIPT="$(KV_PUT_SCRIPT)" WAIT_SECRET_SCRIPT="$(WAIT_SECRET_SCRIPT)" \
		bash "$(CUTOVER_SCRIPT)" "$$d/ca.pem"

rotation-test: require-inputs require-tools require-cutover-approval ## APPROVAL: exercise admin and database credential rotation end to end
	@$(kc_and_vault_pf); \
		KUBECTL="$(KUBECTL)" KUBECONFIG="$(KUBECONFIG)" NAMESPACE="$(NAMESPACE)" KC_PORT="$(PORT)" \
		ADMIN_USERNAME="$(KEYCLOAK_ADMIN_USERNAME)" VSO_ADMIN_SECRET="$(VSO_ADMIN_SECRET)" VSO_DB_SECRET="$(VSO_DB_SECRET)" \
		KV_ADMIN_PATH="$(KV_MOUNT)/data/$(KV_ADMIN_PATH)" KV_DB_PATH="$(KV_MOUNT)/data/$(KV_DB_PATH)" \
		CNPG_CLUSTER="$(CNPG_CLUSTER)" DB_NAME="$(DB_NAME)" DB_USERNAME="$(DB_USERNAME)" \
		KEYCLOAK_STATEFULSET="$(KEYCLOAK_STATEFULSET)" KEYCLOAK_WAIT_TIMEOUT="$(KEYCLOAK_WAIT_TIMEOUT)" \
		VAULT_BASE_URL="$(VAULT_BASE_URL)" VAULT_RESOLVE="$(VAULT_RESOLVE)" VAULT_AUTH_MOUNT="$(VAULT_AUTH_MOUNT)" \
		VAULT_SEED_ROLE="$(VAULT_SEED_ROLE)" VAULT_SEED_SA="$(VAULT_SEED_SA)" \
		KV_PUT_SCRIPT="$(KV_PUT_SCRIPT)" WAIT_SECRET_SCRIPT="$(WAIT_SECRET_SCRIPT)" \
		bash "$(ROTATION_SCRIPT)" "$$d/ca.pem"

post-check: require-inputs require-tools ## Re-run baseline and assert phase-1 resources remain current
	@$(MAKE) --no-print-directory baseline CLUSTER="$(CLUSTER)" NAMESPACE="$(NAMESPACE)" KUBECONFIG="$(KUBECONFIG)" VAULT_NS="$(VAULT_NS)" VAULT_HOST="$(VAULT_HOST)" VAULT_LB="$(VAULT_LB)"
	@KUBECTL="$(KUBECTL)" TIMEOUT="$(TIMEOUT)" KUBECONFIG="$(KUBECONFIG)" NAMESPACE="$(NAMESPACE)" WAIT_TIMEOUT="$(VSO_WAIT_TIMEOUT)" bash "$(VSO_WAIT_SCRIPT)" "$(VSO_ADMIN_SECRET)" "$(VSO_DB_SECRET)"
	@# Assert current state by reading it. `kubectl wait --timeout=1s` was used here as an
	@# "already true" check, but it must establish a watch within that second and raced against a
	@# cluster reporting Ready=True — a false failure. A direct read has no such race.
	@st="$$($(KUBECTL) --kubeconfig "$(KUBECONFIG)" get cluster.postgresql.cnpg.io "$(CNPG_CLUSTER)" -n "$(NAMESPACE)" -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}')"; \
		test "$$st" = True || { echo "ERROR: CNPG Cluster $(CNPG_CLUSTER) Ready=$${st:-<none>}, expected True" >&2; exit 1; }
	@r="$$($(KUBECTL) --kubeconfig "$(KUBECONFIG)" get statefulset "$(KEYCLOAK_STATEFULSET)" -n "$(NAMESPACE)" -o jsonpath='{.status.readyReplicas}')"; \
		w="$$($(KUBECTL) --kubeconfig "$(KUBECONFIG)" get statefulset "$(KEYCLOAK_STATEFULSET)" -n "$(NAMESPACE)" -o jsonpath='{.spec.replicas}')"; \
		test -n "$$r" && test "$$r" = "$$w" || { echo "ERROR: StatefulSet $(KEYCLOAK_STATEFULSET) ready $${r:-0}/$$w" >&2; exit 1; }

# Post-install hardening. Separate from `install` as a named phase, but CALLED BY it: a rebuild that
# silently came back unhardened is the failure this prevents — a teardown/install cycle restored a
# working Keycloak whose brute-force policy and NetworkPolicies were both gone, because they live in
# realm attributes and the namespace respectively and neither survives a teardown.
# Order is deliberate: brute-force first (a realm setting, trivially reversible), NetworkPolicy last
# because it changes live traffic isolation and runs the heaviest live proof.
harden: require-inputs require-tools require-network-policy-approval ## APPROVAL: post-install hardening — brute-force policy, then NetworkPolicy isolation
	@$(MAKE) --no-print-directory brute-force CLUSTER="$(CLUSTER)" NAMESPACE="$(NAMESPACE)" KUBECONFIG="$(KUBECONFIG)"
	@$(MAKE) --no-print-directory network-policy CLUSTER="$(CLUSTER)" NAMESPACE="$(NAMESPACE)" KUBECONFIG="$(KUBECONFIG)" APPROVE_NETWORK_POLICY="$(APPROVE_NETWORK_POLICY)"

install: require-cutover-approval require-inputs require-tools require-vendors require-vault-config ## APPROVAL(x2): install phase 1, promote the bootstrap account to permanent admin, then harden (needs APPROVE_CUTOVER + APPROVE_NETWORK_POLICY)
	@$(MAKE) --no-print-directory baseline CLUSTER="$(CLUSTER)" NAMESPACE="$(NAMESPACE)" KUBECONFIG="$(KUBECONFIG)"
	@$(MAKE) --no-print-directory install-vso CLUSTER="$(CLUSTER)" NAMESPACE="$(NAMESPACE)" KUBECONFIG="$(KUBECONFIG)"
	@$(MAKE) --no-print-directory identities CLUSTER="$(CLUSTER)" NAMESPACE="$(NAMESPACE)" KUBECONFIG="$(KUBECONFIG)"
	@$(MAKE) --no-print-directory seed CLUSTER="$(CLUSTER)" NAMESPACE="$(NAMESPACE)" KUBECONFIG="$(KUBECONFIG)" MGMT_KUBECONFIG="$(MGMT_KUBECONFIG)"
	@$(MAKE) --no-print-directory vso-wiring CLUSTER="$(CLUSTER)" NAMESPACE="$(NAMESPACE)" KUBECONFIG="$(KUBECONFIG)"
	@$(MAKE) --no-print-directory database CLUSTER="$(CLUSTER)" NAMESPACE="$(NAMESPACE)" KUBECONFIG="$(KUBECONFIG)"
	@$(MAKE) --no-print-directory reachability CLUSTER="$(CLUSTER)" NAMESPACE="$(NAMESPACE)" KUBECONFIG="$(KUBECONFIG)"
	@$(MAKE) --no-print-directory keycloak CLUSTER="$(CLUSTER)" NAMESPACE="$(NAMESPACE)" KUBECONFIG="$(KUBECONFIG)"
	@$(MAKE) --no-print-directory admin-cutover CLUSTER="$(CLUSTER)" NAMESPACE="$(NAMESPACE)" KUBECONFIG="$(KUBECONFIG)" APPROVE_CUTOVER="$(APPROVE_CUTOVER)"
	@$(MAKE) --no-print-directory verify CLUSTER="$(CLUSTER)" NAMESPACE="$(NAMESPACE)" KUBECONFIG="$(KUBECONFIG)"
	@$(MAKE) --no-print-directory harden CLUSTER="$(CLUSTER)" NAMESPACE="$(NAMESPACE)" KUBECONFIG="$(KUBECONFIG)" APPROVE_NETWORK_POLICY="$(APPROVE_NETWORK_POLICY)"
	@$(MAKE) --no-print-directory post-check CLUSTER="$(CLUSTER)" NAMESPACE="$(NAMESPACE)" KUBECONFIG="$(KUBECONFIG)"

teardown-keycloak: require-inputs require-tools ## Remove the Keycloak Helm release
	@$(HELM) uninstall "$(KEYCLOAK_RELEASE)" -n "$(NAMESPACE)" --kubeconfig "$(KUBECONFIG)"

# Delete-reclaim PVCs make this irreversible; the top-level teardown guard runs before this target.
teardown-database: require-inputs require-tools require-cnpg require-confirm ## Delete realm data and remove the CNPG operator
	@$(KUBECTL) --kubeconfig "$(KUBECONFIG)" delete "cluster.postgresql.cnpg.io/$(CNPG_CLUSTER)" -n "$(NAMESPACE)" --wait=true
	@$(KUBECTL) --kubeconfig "$(KUBECONFIG)" delete -f "$(CNPG_MANIFEST)" --wait=true

teardown-vso-wiring: require-inputs require-tools ## Remove VSO CRs in reverse dependency order, then their public CA copy
	@$(KUBECTL) --kubeconfig "$(KUBECONFIG)" delete vaultstaticsecret "$(VSO_ADMIN_SECRET)" "$(VSO_DB_SECRET)" -n "$(NAMESPACE)" --ignore-not-found --wait=true
	@$(KUBECTL) --kubeconfig "$(KUBECONFIG)" delete vaultauth "$(VSO_AUTH)" -n "$(NAMESPACE)" --ignore-not-found --wait=true
	@$(KUBECTL) --kubeconfig "$(KUBECONFIG)" delete vaultconnection "$(VSO_CONNECTION)" -n "$(NAMESPACE)" --ignore-not-found --wait=true
	@$(KUBECTL) --kubeconfig "$(KUBECONFIG)" delete secret "$(VAULT_CA_DEST_SECRET)" -n "$(NAMESPACE)" --ignore-not-found

teardown-identities: require-inputs require-tools ## Remove the app namespace; the reviewer identity is RETAINED
	@$(KUBECTL) --kubeconfig "$(KUBECONFIG)" delete namespace "$(NAMESPACE)" --ignore-not-found --wait=true
	@echo "NOTICE: reviewer identity RETAINED ($(SYSTEM_NAMESPACE)/$(VAULT_REVIEWER_SA), $(VAULT_REVIEWER_CRB), $(VAULT_REVIEWER_TOKEN_SECRET))."
	@echo "        It is part of the Vault-side configuration this teardown deliberately preserves:"
	@echo "        the auth mount on Vault authenticates TokenReview with that ServiceAccount's JWT,"
	@echo "        copied to $(MGMT_CLUSTER). Deleting and recreating the SA invalidates the stored"
	@echo "        JWT and every subsequent Vault login fails 403 — proven by a real teardown/install"
	@echo "        cycle. Removing it therefore requires refreshing the JWT on $(MGMT_CLUSTER), which"
	@echo "        is a privileged step: see 'make vault-config'."

teardown-reviewer: require-inputs require-tools require-confirm ## Remove the retained reviewer identity (breaks Vault auth until the JWT is refreshed)
	@echo "WARNING: after this, Vault logins on mount $(VAULT_AUTH_MOUNT) fail until the reviewer JWT"
	@echo "         on $(MGMT_CLUSTER) is refreshed via 'make vault-config ... APPROVE_MGMT=yes'."
	@$(KUBECTL) --kubeconfig "$(KUBECONFIG)" delete clusterrolebinding "$(VAULT_REVIEWER_CRB)" --ignore-not-found
	@$(KUBECTL) --kubeconfig "$(KUBECONFIG)" delete secret "$(VAULT_REVIEWER_TOKEN_SECRET)" -n "$(SYSTEM_NAMESPACE)" --ignore-not-found
	@$(KUBECTL) --kubeconfig "$(KUBECONFIG)" delete serviceaccount "$(VAULT_REVIEWER_SA)" -n "$(SYSTEM_NAMESPACE)" --ignore-not-found

teardown-vso: require-inputs require-tools ## Uninstall VSO and its namespace; retain cluster-scoped CRDs
	@$(HELM) uninstall "$(VSO_RELEASE)" -n "$(VSO_NAMESPACE)" --kubeconfig "$(KUBECONFIG)"
	@$(KUBECTL) --kubeconfig "$(KUBECONFIG)" delete namespace "$(VSO_NAMESPACE)" --ignore-not-found --wait=true
	@echo "VSO CRDs retained by design."

teardown: require-inputs require-tools require-cnpg require-confirm ## Reverse phase 1; requires CONFIRM=yes because database state is destroyed
	@$(MAKE) --no-print-directory teardown-keycloak CLUSTER="$(CLUSTER)" NAMESPACE="$(NAMESPACE)" KUBECONFIG="$(KUBECONFIG)"
	@$(MAKE) --no-print-directory teardown-database CLUSTER="$(CLUSTER)" NAMESPACE="$(NAMESPACE)" KUBECONFIG="$(KUBECONFIG)" CONFIRM="$(CONFIRM)"
	@$(MAKE) --no-print-directory teardown-vso-wiring CLUSTER="$(CLUSTER)" NAMESPACE="$(NAMESPACE)" KUBECONFIG="$(KUBECONFIG)"
	@$(MAKE) --no-print-directory teardown-identities CLUSTER="$(CLUSTER)" NAMESPACE="$(NAMESPACE)" KUBECONFIG="$(KUBECONFIG)"
	@$(MAKE) --no-print-directory teardown-vso CLUSTER="$(CLUSTER)" NAMESPACE="$(NAMESPACE)" KUBECONFIG="$(KUBECONFIG)"
	@echo "NOTICE: VaultConfig, reviewer JWT on $(MGMT_CLUSTER), Vault auth/policies/roles, and KV entries were NOT removed."
	@echo "        Their removal is a separate privileged decision; the seeder cannot delete KV state."

.DEFAULT_GOAL := help
