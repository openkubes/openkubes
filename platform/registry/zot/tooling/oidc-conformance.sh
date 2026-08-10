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

run_id=${RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)-$$}
safe_id=$(printf '%s' "$run_id" | tr '[:upper:]_' '[:lower:]-' | tr -cd 'a-z0-9-' | cut -c1-40)
[ -n "$safe_id" ] || { echo "ERROR: RUN_ID has no safe characters" >&2; exit 2; }
d=$(mktemp -d)
test -d "$d"
trap 'rm -rf -- "$d"' EXIT INT TERM
"$KUBECTL" --kubeconfig "$KUBECONFIG" get secret zot-server-tls -n "$NAMESPACE" -o jsonpath='{.data.ca\.crt}' | base64 -d > "$d/ca.crt"
test -s "$d/ca.crt" || { echo "ERROR: registry CA is empty" >&2; exit 1; }

REGISTRY_HOST="$REGISTRY_HOST" REGISTRY_LB="$REGISTRY_LB" KEYCLOAK_HOST="$KEYCLOAK_HOST" RUN_ID="$safe_id" CA_FILE="$d/ca.crt" \
  python3 "$(dirname "$0")/oidc-conformance.py" \
  3< <("$KUBECTL" --kubeconfig "$KUBECONFIG" get secret "$KEYCLOAK_ADMIN_SECRET" -n "$KEYCLOAK_NAMESPACE" -o jsonpath='{.data.password}' | base64 -d) \
  4< <("$KUBECTL" --kubeconfig "$KUBECONFIG" get secret "$CONFORMANCE_SECRET" -n "$NAMESPACE" -o jsonpath='{.data.writer-password}' | base64 -d) \
  5< <("$KUBECTL" --kubeconfig "$KUBECONFIG" get secret "$CONFORMANCE_SECRET" -n "$NAMESPACE" -o jsonpath='{.data.reader-password}' | base64 -d) \
  6< <("$KUBECTL" --kubeconfig "$KUBECONFIG" get secret "$OIDC_SECRET" -n "$NAMESPACE" -o jsonpath='{.data.credentials\.json}' | base64 -d)
