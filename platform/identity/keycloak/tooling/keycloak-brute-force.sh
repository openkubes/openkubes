#!/usr/bin/env bash
# Enable and verify the master realm's explicit brute-force lockout policy.
# The caller owns the localhost port-forward. Credentials and tokens stay in a
# retained mode-700 work directory and never appear in argv or output.
set -Eeuo pipefail

: "${KUBECTL:?KUBECTL is required}"
: "${KUBECONFIG:?KUBECONFIG is required}"
: "${NAMESPACE:?NAMESPACE is required}"
: "${KC_PORT:?KC_PORT is required}"
: "${KEYCLOAK_ADMIN_USERNAME:?KEYCLOAK_ADMIN_USERNAME is required}"
: "${VSO_ADMIN_SECRET:?VSO_ADMIN_SECRET is required}"

KC="http://localhost:${KC_PORT}"
umask 077
_d="$(mktemp -d)"
test -d "$_d" || { echo "ERROR: failed to create work directory" >&2; exit 1; }

keep() {
  echo "      work dir RETAINED: $_d"
  echo "      WARNING: it contains plaintext Keycloak credential/token material; remove it securely after review."
}
trap keep EXIT INT TERM

"$KUBECTL" --kubeconfig "$KUBECONFIG" get secret "$VSO_ADMIN_SECRET" -n "$NAMESPACE" \
  -o jsonpath='{.data.password}' | base64 -d > "$_d/admin-password"
test -s "$_d/admin-password" || { echo "ERROR: admin password is empty" >&2; exit 1; }

code="$(curl -sS -o "$_d/token-response.json" -w '%{http_code}' \
  -X POST "$KC/realms/master/protocol/openid-connect/token" \
  --data-urlencode 'client_id=admin-cli' \
  --data-urlencode "username=$KEYCLOAK_ADMIN_USERNAME" \
  --data-urlencode "password@$_d/admin-password" \
  --data-urlencode 'grant_type=password')"
test "$code" = 200 || { echo "ERROR: admin token request returned http=$code" >&2; exit 1; }
python3 - "$_d/token-response.json" "$_d/token" <<'PY'
import json, sys
response = json.load(open(sys.argv[1]))
open(sys.argv[2], "w").write(response["access_token"])
PY
test -s "$_d/token" || { echo "ERROR: admin token is empty" >&2; exit 1; }

python3 - "$_d/token" "$_d/admin.curl" <<'PY'
import sys
token = open(sys.argv[1]).read()
open(sys.argv[2], "w").write('header = "Authorization: Bearer %s"\n' % token)
PY

code="$(curl -sS --config "$_d/admin.curl" -o "$_d/realm-before.json" -w '%{http_code}' \
  "$KC/admin/realms/master")"
test "$code" = 200 || { echo "ERROR: master realm read returned http=$code" >&2; exit 1; }

python3 - "$_d/realm-before.json" "$_d/realm-update.json" <<'PY'
import json, sys
r = json.load(open(sys.argv[1]))
# Five failures limits credential stuffing without making a single typo disruptive.
r["bruteForceProtected"] = True
r["failureFactor"] = 5
# Use temporary, escalating lockouts so legitimate users recover without an admin unlock.
r["permanentLockout"] = False
r["waitIncrementSeconds"] = 60
# Repeated attempts inside one second are automated; lock them for at least one minute.
r["quickLoginCheckMilliSeconds"] = 1000
r["minimumQuickLoginWaitSeconds"] = 60
# Cap one temporary lockout at 15 minutes while retaining useful attack resistance.
r["maxFailureWaitSeconds"] = 900
# Forget the failure history after 12 quiet hours so old mistakes do not accumulate forever.
r["maxDeltaTimeSeconds"] = 43200
json.dump(r, open(sys.argv[2], "w"))
PY

code="$(curl -sS --config "$_d/admin.curl" -o "$_d/update-response" -w '%{http_code}' \
  -X PUT -H 'Content-Type: application/json' --data-binary "@$_d/realm-update.json" \
  "$KC/admin/realms/master")"
test "$code" = 204 || { echo "ERROR: master realm update returned http=$code" >&2; exit 1; }

code="$(curl -sS --config "$_d/admin.curl" -o "$_d/realm-after.json" -w '%{http_code}' \
  "$KC/admin/realms/master")"
test "$code" = 200 || { echo "ERROR: master realm re-read returned http=$code" >&2; exit 1; }
python3 - "$_d/realm-after.json" <<'PY'
import json, sys
r = json.load(open(sys.argv[1]))
expected = {
    "bruteForceProtected": True,
    "permanentLockout": False,
    "failureFactor": 5,
    "waitIncrementSeconds": 60,
    "quickLoginCheckMilliSeconds": 1000,
    "minimumQuickLoginWaitSeconds": 60,
    "maxFailureWaitSeconds": 900,
    "maxDeltaTimeSeconds": 43200,
}
wrong = {k: (r.get(k), v) for k, v in expected.items() if r.get(k) != v}
if wrong:
    raise SystemExit("ERROR: master realm brute-force policy mismatch: %r" % wrong)
print("RESULT: PASS — master realm brute-force protection enabled and all lockout parameters re-read")
PY
