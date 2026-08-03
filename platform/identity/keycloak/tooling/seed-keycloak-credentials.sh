#!/usr/bin/env bash
# OK-81 step 2.5 — seed Keycloak's admin and DB passwords into Vault KV v2 as the
# scoped seeder identity. No break-glass. Credentials never touch argv, stdout or a log.
set -Eeuo pipefail

: "${KUBECTL:?KUBECTL is required}"
: "${KUBECONFIG:?KUBECONFIG is required}"
: "${NAMESPACE:?NAMESPACE is required}"
: "${VAULT_BASE_URL:?VAULT_BASE_URL is required (e.g. https://vault-active.vault.svc.cluster.local:8200)}"
: "${VAULT_RESOLVE:?VAULT_RESOLVE is required (curl --resolve triple pointing that host at a reachable address)}"
: "${VAULT_AUTH_MOUNT:?VAULT_AUTH_MOUNT is required}"
: "${VAULT_SEED_ROLE:?VAULT_SEED_ROLE is required}"
: "${VAULT_SEED_SA:?VAULT_SEED_SA is required}"
: "${KEYCLOAK_ADMIN_USERNAME:?KEYCLOAK_ADMIN_USERNAME is required}"
: "${DB_USERNAME:?DB_USERNAME is required}"
: "${KV_ADMIN_PATH:?KV_ADMIN_PATH is required}"
: "${KV_DB_PATH:?KV_DB_PATH is required}"
: "${KV_CROSS_CLUSTER_PROBE:?KV_CROSS_CLUSTER_PROBE is required}"
CA="$1"          # public CA pem for TLS verification

_d=""
cleanup() { [ -n "$_d" ] && rm -rf -- "$_d"; }
trap cleanup EXIT INT TERM
umask 077
_d="$(mktemp -d)"
[ -d "$_d" ] || { echo "ABORT: no temp dir" >&2; exit 1; }

api() {  # api <config-file> ; prints http code, body to $_d/body
  curl -sS -o "$_d/body" -w '%{http_code}' --config "$1"
}

echo "[1/6] generate two independent passwords (32 bytes of entropy each)"
openssl rand -base64 32 | tr -d '\n' > "$_d/admin-password"
openssl rand -base64 32 | tr -d '\n' > "$_d/db-password"
printf '%s' "$KEYCLOAK_ADMIN_USERNAME" > "$_d/admin-username"
printf '%s' "$DB_USERNAME" > "$_d/db-username"
for f in admin-password db-password; do
  [ -s "$_d/$f" ] || { echo "ABORT: $f empty" >&2; exit 1; }
done
echo "      admin-password bytes=$(wc -c < "$_d/admin-password") db-password bytes=$(wc -c < "$_d/db-password")"

echo "[2/6] mint a ServiceAccount token for $NAMESPACE/$VAULT_SEED_SA (>=600s: this cluster enforces a 10-minute minimum)"
"$KUBECTL" --kubeconfig "$KUBECONFIG" create token "$VAULT_SEED_SA" -n "$NAMESPACE" --duration=600s > "$_d/jwt"
[ -s "$_d/jwt" ] || { echo "ABORT: empty SA token — below the TokenRequest minimum?" >&2; exit 1; }
echo "      jwt bytes=$(wc -c < "$_d/jwt")"

echo "[3/6] exchange it for a Vault token via auth/$VAULT_AUTH_MOUNT role $VAULT_SEED_ROLE"
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
code="$(api "$_d/login.curl")"
[ "$code" = "200" ] || { echo "ABORT: login http=$code" >&2; sed 's/^/      /' "$_d/body" >&2; exit 1; }
python3 - "$_d" <<'PY'
import json,sys
d=sys.argv[1]
r=json.load(open(f"{d}/body"))
open(f"{d}/vault-token","w").write(r["auth"]["client_token"])
print("      policies:", r["auth"]["token_policies"], "ttl:", r["auth"]["lease_duration"], "renewable:", r["auth"]["renewable"])
PY

echo "[4/6] write both sub-paths with cas=0 (atomic: fails if the path already exists)"
python3 - "$_d" <<'PY2'
import json,sys
d=sys.argv[1]
json.dump({"options":{"cas":0},"data":{
  "username":open(f"{d}/admin-username").read(),"password":open(f"{d}/admin-password").read()}},
  open(f"{d}/kv-admin.json","w"))
json.dump({"options":{"cas":0},"data":{
  "username":open(f"{d}/db-username").read(),"password":open(f"{d}/db-password").read()}},
  open(f"{d}/kv-db.json","w"))
PY2
for pair in "admin:$KV_ADMIN_PATH" "db:$KV_DB_PATH"; do
  key="${pair%%:*}"; path="${pair#*:}"
  cat > "$_d/put.curl" <<EOF
url = "$VAULT_BASE_URL/v1/$path"
resolve = "$VAULT_RESOLVE"
cacert = "$CA"
request = "POST"
header = "X-Vault-Token: $(cat "$_d/vault-token")"
data-binary = "@$_d/kv-$key.json"
EOF
  code="$(api "$_d/put.curl")"
  if [ "$code" = "200" ]; then
    python3 -c "import json;r=json.load(open('$_d/body'));print('      $path version:',r['data']['version'],'(created)')"
  elif [ "$code" = "400" ] && grep -q 'check-and-set parameter did not match' "$_d/body"; then
    # cas=0 means "create only". This exact error means the path already holds a value, which is
    # the normal state after a teardown/install cycle: teardown deliberately leaves KV intact.
    # The existing Vault value stays authoritative and the password generated above is discarded —
    # that is why the admin credential survives a rebuild. Any OTHER 400 is still a failure.
    echo "      $path already seeded — keeping the existing Vault value (not overwritten)"
  else
    echo "      write $path http=$code" >&2; sed 's/^/      /' "$_d/body" >&2; exit 1
  fi
done

echo "[5/6] NEGATIVE: the seeder must NOT be able to read back what it wrote"
cat > "$_d/get.curl" <<EOF
url = "$VAULT_BASE_URL/v1/$KV_ADMIN_PATH"
resolve = "$VAULT_RESOLVE"
cacert = "$CA"
header = "X-Vault-Token: $(cat "$_d/vault-token")"
EOF
code="$(api "$_d/get.curl")"
if [ "$code" = "403" ]; then
  echo "      NEG ok   read denied (http 403) — write-only scope holds"
elif [ "$code" = "200" ]; then
  echo "      NEG FAIL read ALLOWED (http 200) — the seeder can read; scope is wrong" >&2; exit 1
else
  echo "      NEG FAIL non-permission failure http=$code" >&2; sed 's/^/      /' "$_d/body" >&2; exit 1
fi

echo "[6/6] NEGATIVE: the seeder must NOT reach another cluster's path"
cat > "$_d/other.curl" <<EOF
url = "$VAULT_BASE_URL/v1/$KV_CROSS_CLUSTER_PROBE"
resolve = "$VAULT_RESOLVE"
cacert = "$CA"
request = "POST"
header = "X-Vault-Token: $(cat "$_d/vault-token")"
data-binary = "{\"data\":{\"x\":\"y\"}}"
EOF
code="$(api "$_d/other.curl")"
if [ "$code" = "403" ]; then
  echo "      NEG ok   cross-cluster write denied (http 403)"
else
  echo "      NEG FAIL cross-cluster write http=$code — expected 403" >&2; exit 1
fi

echo "RESULT: PASS — seeded $KV_ADMIN_PATH and $KV_DB_PATH; read-back and cross-cluster write both denied"
trap - EXIT INT TERM
cleanup
exit 0
