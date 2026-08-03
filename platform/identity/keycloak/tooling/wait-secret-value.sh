#!/usr/bin/env bash
# Wait until a VSO-materialised Secret key holds an expected value.
#
# wait-vso-current.sh cannot do this job: after a Vault write the VaultStaticSecret generation is
# unchanged, so SecretSynced=True is already true and says nothing about whether the NEW value has
# landed. Rotation has to assert the value itself, and it must do so by comparison — never by
# printing either side.
set -Eeuo pipefail

: "${KUBECTL:?KUBECTL is required}"
: "${KUBECONFIG:?KUBECONFIG is required}"
: "${NAMESPACE:?NAMESPACE is required}"

SECRET="$1"; KEY="$2"; EXPECTED="$3"; TIMEOUT_S="${4:-180}"
[ -s "$EXPECTED" ] || { echo "ABORT: expected-value file is empty: $EXPECTED" >&2; exit 2; }

# Work dir retained by convention here (see keycloak-admin-cutover.sh): mode 700.
umask 077
_d="$(mktemp -d)"

for _ in $(seq 1 "$TIMEOUT_S"); do
  "$KUBECTL" --kubeconfig "$KUBECONFIG" get secret "$SECRET" -n "$NAMESPACE" \
    -o "jsonpath={.data.$KEY}" 2>/dev/null | base64 -d > "$_d/actual" 2>/dev/null || true
  if cmp -s "$_d/actual" "$EXPECTED"; then
    echo "      Secret $NAMESPACE/$SECRET key $KEY now matches the expected value"
    exit 0
  fi
  sleep 1
done
echo "ERROR: Secret $NAMESPACE/$SECRET key $KEY did not reach the expected value within ${TIMEOUT_S}s" >&2
exit 1
