#!/usr/bin/env bash
set -Eeuo pipefail
case $- in *x*) set +x ;; esac

: "${KUBECTL:=kubectl}"
: "${KUBECONFIG:?KUBECONFIG is required}"
: "${NAMESPACE:=zot}"
: "${REGISTRY_HOST:=registry.ok-shared.internal}"
: "${REGISTRY_LB:=192.168.100.207}"
: "${KEYCLOAK_HOST:=keycloak.ok-shared.internal}"
: "${KEYCLOAK_NAMESPACE:=keycloak}"
: "${KEYCLOAK_ADMIN_SECRET:=keycloak-admin}"
: "${CONFORMANCE_SECRET:=zot-conformance-identities}"
: "${OIDC_SECRET:=zot-oidc}"
: "${TLS_SECRET:=zot-server-tls}"
# These must arrive from the same Makefile variables that oidc-client used to reconcile the
# realm. If they are allowed to default independently on each side, `make oidc-client
# WRITER_GROUP=foo` reconciles foo while this asserts registry-writers -- and if a stale
# registry-writers group survives from an earlier run, the assertion passes against a group
# the registry no longer uses.
: "${PLATFORM_REALM:=openkubes}"
: "${CLIENT_ID:=registry-default}"
: "${WRITER_GROUP:=registry-writers}"
: "${READER_GROUP:=registry-readers}"
: "${KEYCLOAK_ADMIN_USERNAME:=admin}"

run_id=${RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)-$$}
safe_id=$(printf '%s' "$run_id" | tr '[:upper:]_' '[:lower:]-' | tr -cd 'a-z0-9-' | cut -c1-40)
[ -n "$safe_id" ] || { echo "ERROR: RUN_ID has no safe characters" >&2; exit 2; }
d=$(mktemp -d)
test -d "$d"
trap 'rm -rf -- "$d"' EXIT INT TERM
"$KUBECTL" --kubeconfig "$KUBECONFIG" get secret "$TLS_SECRET" -n "$NAMESPACE" -o jsonpath='{.data.ca\.crt}' | base64 -d > "$d/ca.crt"
test -s "$d/ca.crt" || { echo "ERROR: registry CA is empty" >&2; exit 1; }

# Usernames come from the Secret that created them, not from a second hardcoded copy.
writer_username=$("$KUBECTL" --kubeconfig "$KUBECONFIG" get secret "$CONFORMANCE_SECRET" -n "$NAMESPACE" -o jsonpath='{.data.writer-username}' | base64 -d)
reader_username=$("$KUBECTL" --kubeconfig "$KUBECONFIG" get secret "$CONFORMANCE_SECRET" -n "$NAMESPACE" -o jsonpath='{.data.reader-username}' | base64 -d)
[ -n "$writer_username" ] && [ -n "$reader_username" ] || { echo "ERROR: $CONFORMANCE_SECRET is missing writer-username/reader-username" >&2; exit 1; }

REGISTRY_HOST="$REGISTRY_HOST" REGISTRY_LB="$REGISTRY_LB" KEYCLOAK_HOST="$KEYCLOAK_HOST" RUN_ID="$safe_id" CA_FILE="$d/ca.crt" \
  PLATFORM_REALM="$PLATFORM_REALM" CLIENT_ID="$CLIENT_ID" WRITER_GROUP="$WRITER_GROUP" READER_GROUP="$READER_GROUP" \
  KEYCLOAK_ADMIN_USERNAME="$KEYCLOAK_ADMIN_USERNAME" WRITER_USERNAME="$writer_username" READER_USERNAME="$reader_username" \
  python3 "$(dirname "$0")/oidc-conformance.py" \
  3< <("$KUBECTL" --kubeconfig "$KUBECONFIG" get secret "$KEYCLOAK_ADMIN_SECRET" -n "$KEYCLOAK_NAMESPACE" -o jsonpath='{.data.password}' | base64 -d) \
  4< <("$KUBECTL" --kubeconfig "$KUBECONFIG" get secret "$CONFORMANCE_SECRET" -n "$NAMESPACE" -o jsonpath='{.data.writer-password}' | base64 -d) \
  5< <("$KUBECTL" --kubeconfig "$KUBECONFIG" get secret "$CONFORMANCE_SECRET" -n "$NAMESPACE" -o jsonpath='{.data.reader-password}' | base64 -d) \
  6< <("$KUBECTL" --kubeconfig "$KUBECONFIG" get secret "$OIDC_SECRET" -n "$NAMESPACE" -o jsonpath='{.data.credentials\.json}' | base64 -d)
