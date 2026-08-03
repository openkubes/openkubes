#!/usr/bin/env bash
# Write one KV v2 payload as the scoped write-only seeder identity.
# Deliberately NOT cas=0: this updates an already-seeded path, which is what rotation is.
# The value never touches argv, stdout or a log — only files under a private temp dir.
set -Eeuo pipefail

: "${KUBECTL:?KUBECTL is required}"
: "${KUBECONFIG:?KUBECONFIG is required}"
: "${NAMESPACE:?NAMESPACE is required}"
: "${VAULT_BASE_URL:?VAULT_BASE_URL is required}"
: "${VAULT_RESOLVE:?VAULT_RESOLVE is required}"
: "${VAULT_AUTH_MOUNT:?VAULT_AUTH_MOUNT is required}"
: "${VAULT_SEED_ROLE:?VAULT_SEED_ROLE is required}"
: "${VAULT_SEED_SA:?VAULT_SEED_SA is required}"

CA="$1"        # public CA pem
KV_PATH="$2"   # full KV v2 data path, e.g. secret/data/ok-shared/keycloak/admin
DATA="$3"      # file holding the JSON *data* object only

# Work dir retained by convention here (see keycloak-admin-cutover.sh): mode 700, holds a Vault
# token and the payload. Remove it yourself when done.
umask 077
_d="$(mktemp -d)"

"$KUBECTL" --kubeconfig "$KUBECONFIG" create token "$VAULT_SEED_SA" -n "$NAMESPACE" --duration=600s > "$_d/jwt"
[ -s "$_d/jwt" ] || { echo "ABORT: empty SA token" >&2; exit 1; }

python3 - "$_d" "$VAULT_SEED_ROLE" <<'PY'
import json,sys
d,role=sys.argv[1],sys.argv[2]
json.dump({"role":role,"jwt":open(f"{d}/jwt").read().strip()}, open(f"{d}/login.json","w"))
PY
cat > "$_d/login.curl" <<EOF
url = "$VAULT_BASE_URL/v1/auth/$VAULT_AUTH_MOUNT/login"
resolve = "$VAULT_RESOLVE"
cacert = "$CA"
request = "POST"
data-binary = "@$_d/login.json"
EOF
code="$(curl -sS -o "$_d/body" -w '%{http_code}' --config "$_d/login.curl")"
[ "$code" = 200 ] || { echo "ABORT: seeder login http=$code" >&2; sed 's/^/      /' "$_d/body" >&2; exit 1; }
python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['auth']['client_token'],end='')" "$_d/body" > "$_d/vault-token"

python3 - "$_d" "$DATA" <<'PY'
import json,sys
d,src=sys.argv[1],sys.argv[2]
json.dump({"data":json.load(open(src))}, open(f"{d}/put.json","w"))
PY
cat > "$_d/put.curl" <<EOF
url = "$VAULT_BASE_URL/v1/$KV_PATH"
resolve = "$VAULT_RESOLVE"
cacert = "$CA"
request = "POST"
header = "X-Vault-Token: $(cat "$_d/vault-token")"
data-binary = "@$_d/put.json"
EOF
code="$(curl -sS -o "$_d/body" -w '%{http_code}' --config "$_d/put.curl")"
[ "$code" = 200 ] || { echo "ABORT: write $KV_PATH http=$code" >&2; sed 's/^/      /' "$_d/body" >&2; exit 1; }
python3 -c "import json,sys;print('      %s version:'%sys.argv[2], json.load(open(sys.argv[1]))['data']['version'])" "$_d/body" "$KV_PATH"
