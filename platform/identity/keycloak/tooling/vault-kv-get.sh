#!/usr/bin/env bash
# Read one KV v2 path as the scoped READ-ONLY reader identity (the same identity VSO uses).
# Writes each key to <outdir>/<key>. Values are never printed.
#
# Two identities exist on purpose: the seeder can write and not read, this one can read and not
# write. Neither can do the other's job, which is why both exist.
set -Eeuo pipefail

: "${KUBECTL:?KUBECTL is required}"
: "${KUBECONFIG:?KUBECONFIG is required}"
: "${NAMESPACE:?NAMESPACE is required}"
: "${VAULT_BASE_URL:?VAULT_BASE_URL is required}"
: "${VAULT_RESOLVE:?VAULT_RESOLVE is required}"
: "${VAULT_AUTH_MOUNT:?VAULT_AUTH_MOUNT is required}"
: "${VAULT_READER_ROLE:?VAULT_READER_ROLE is required}"
: "${VAULT_READER_SA:?VAULT_READER_SA is required}"

CA="$1"; KV_PATH="$2"; OUTDIR="$3"

umask 077
_d="$(mktemp -d)"
mkdir -p "$OUTDIR"

"$KUBECTL" --kubeconfig "$KUBECONFIG" create token "$VAULT_READER_SA" -n "$NAMESPACE" --duration=600s > "$_d/jwt"
[ -s "$_d/jwt" ] || { echo "ABORT: empty SA token" >&2; exit 1; }
python3 - "$_d" "$VAULT_READER_ROLE" <<'PY'
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
[ "$code" = 200 ] || { echo "ABORT: reader login http=$code" >&2; sed 's/^/      /' "$_d/body" >&2; exit 1; }
python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['auth']['client_token'],end='')" "$_d/body" > "$_d/vault-token"

cat > "$_d/get.curl" <<EOF
url = "$VAULT_BASE_URL/v1/$KV_PATH"
resolve = "$VAULT_RESOLVE"
cacert = "$CA"
header = "X-Vault-Token: $(cat "$_d/vault-token")"
EOF
code="$(curl -sS -o "$_d/body" -w '%{http_code}' --config "$_d/get.curl")"
[ "$code" = 200 ] || { echo "ABORT: read $KV_PATH http=$code" >&2; sed 's/^/      /' "$_d/body" >&2; exit 1; }
python3 - "$_d" "$OUTDIR" "$KV_PATH" <<'PY'
import json,os,sys
d,out,path=sys.argv[1],sys.argv[2],sys.argv[3]
r=json.load(open(f"{d}/body"))["data"]
for k,v in r["data"].items():
    with open(os.path.join(out,k),"w") as f: f.write(v)
print("      read %s version %s, keys: %s" % (path, r["metadata"]["version"], ",".join(sorted(r["data"]))))
PY
