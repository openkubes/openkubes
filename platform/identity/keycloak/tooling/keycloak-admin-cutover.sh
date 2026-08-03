#!/usr/bin/env bash
# OK-81 step 5.7 — replace Keycloak's temporary bootstrap admin with a permanent one.
#
# The banner "You are logged in as a temporary admin user…" is not cosmetic and not a guess: it is
# driven by the user attribute is_temporary_admin=["true"], which Keycloak sets on the account the
# KC_BOOTSTRAP_ADMIN_* variables create. Only deleting that account clears it — renaming it does
# not, because the attribute follows the account, not the name.
#
# The complication this script exists to solve: the bootstrap account is ALREADY called `admin`,
# which is the name the permanent account must have. Usernames are unique per realm, so the name
# has to be freed first. The order below never leaves the realm without a working admin:
#
#   rename temporary admin -> $TEMP_ADMIN_USERNAME   (frees the name; account still fully usable)
#   create permanent $ADMIN_USERNAME + realm role admin
#   verify the permanent account really is an admin, and carries no temporary flag
#   delete the temporary account USING THE PERMANENT ONE'S TOKEN  (proves the new account's power
#                                                                  before the old one is gone)
#   escrow the new password to Vault, wait for VSO, verify the materialised Secret authenticates
#
# set -e, not accumulate-and-report: a destructive sequence must not continue past a failure.
set -Eeuo pipefail

: "${KUBECTL:?KUBECTL is required}"
: "${KUBECONFIG:?KUBECONFIG is required}"
: "${NAMESPACE:?NAMESPACE is required}"
: "${KC_PORT:?KC_PORT is required}"
: "${ADMIN_USERNAME:?ADMIN_USERNAME is required (the permanent account)}"
: "${TEMP_ADMIN_USERNAME:?TEMP_ADMIN_USERNAME is required (what the temporary account is renamed to)}"
: "${VSO_ADMIN_SECRET:?VSO_ADMIN_SECRET is required}"
: "${KV_ADMIN_PATH:?KV_ADMIN_PATH is required}"
: "${KV_PUT_SCRIPT:?KV_PUT_SCRIPT is required}"
: "${WAIT_SECRET_SCRIPT:?WAIT_SECRET_SCRIPT is required}"
CA="$1"

KC="http://localhost:$KC_PORT"
NS="$NAMESPACE"
step() { printf '\n== %s\n' "$1"; }
ok()   { printf '   ok   %s\n' "$1"; }
die()  { printf '   FAIL %s\n' "$1" >&2; exit 1; }

RESTORE_EDIT_USERNAME=0
umask 077
_d="$(mktemp -d)"
# The work dir is RETAINED, deliberately. An earlier version deleted it on exit and a failed
# assertion in step 9 destroyed the only copy of the freshly generated permanent-admin password,
# locking the console out until a break-glass recovery. Escrow now happens before anything
# destructive, and the dir survives regardless. It is mode 700 and holds plaintext credentials.
cleanup() {
  # The rename needs master's editUsernameAllowed on. Restore it even if a later step dies, so a
  # failed cutover cannot leave the realm permanently more permissive than it was found.
  if [ "$RESTORE_EDIT_USERNAME" = 1 ] && [ -f "$_d/old.curl" ]; then
    printf '{"editUsernameAllowed":false}' > "$_d/restore.json"
    curl -sS --config "$_d/old.curl" -o /dev/null -X PUT -H 'Content-Type: application/json' \
      --data-binary "@$_d/restore.json" "$KC/admin/realms/master" || true
    echo "   ..   restored master editUsernameAllowed=false (cleanup path)" >&2
  fi
  echo "      work dir RETAINED (mode 700, contains plaintext credentials): $_d"
}
trap cleanup EXIT INT TERM
echo "      work dir: $_d"

# ---------------------------------------------------------------- current credential and token
"$KUBECTL" --kubeconfig "$KUBECONFIG" get secret "$VSO_ADMIN_SECRET" -n "$NS" \
  -o jsonpath='{.data.password}' | base64 -d > "$_d/pw-old"
[ -s "$_d/pw-old" ] || die "no current admin password in $VSO_ADMIN_SECRET"

token() { # token <username> <password-file> <out-prefix> ; prints http code
  curl -sS -o "$_d/$3.json" -w '%{http_code}' \
    -d client_id=admin-cli -d grant_type=password -d "username=$1" \
    --data-urlencode "password@$2" \
    "$KC/realms/master/protocol/openid-connect/token"
}
authfile() { # authfile <token-json> <out.curl>
  python3 -c "
import json,sys
t=json.load(open(sys.argv[1]))['access_token']
open(sys.argv[2],'w').write('header = \"Authorization: Bearer %s\"\n' % t)" "$1" "$2"
}
api() { # api <auth.curl> METHOD PATH [jsonfile] ; prints http code, body in $_d/out
  local a="$1" m="$2" p="$3" f="${4:-}"
  if [ -n "$f" ]; then
    curl -sS --config "$a" -o "$_d/out" -w '%{http_code}' -X "$m" \
      -H 'Content-Type: application/json' --data-binary "@$f" "$KC$p"
  else
    curl -sS --config "$a" -o "$_d/out" -w '%{http_code}' -X "$m" "$KC$p"
  fi
}

step "1. authenticate with the credential currently in $VSO_ADMIN_SECRET"
c="$(token "$ADMIN_USERNAME" "$_d/pw-old" tok-old)"
[ "$c" = 200 ] || die "current admin token http=$c"
authfile "$_d/tok-old.json" "$_d/old.curl"
ok "authenticated as $ADMIN_USERNAME"

step "2. establish the before-state: exactly one temporary admin, and it owns the wanted name"
c="$(api "$_d/old.curl" GET "/admin/realms/master/users?briefRepresentation=false")"
[ "$c" = 200 ] || die "user list http=$c"
cp "$_d/out" "$_d/users-before.json"
python3 - "$_d" "$ADMIN_USERNAME" <<'PY' || exit 1
import json,sys
d,want=sys.argv[1],sys.argv[2]
us=json.load(open(f"{d}/users-before.json"))
temp=[u for u in us if (u.get("attributes") or {}).get("is_temporary_admin")==["true"]]
perm=[u for u in us if u["username"]==want and (u.get("attributes") or {}).get("is_temporary_admin")!=["true"]]
if perm:
    print(f"   ok   {want} already exists WITHOUT the temporary flag — cutover already done")
    sys.exit(3)
if len(temp)!=1:
    print(f"   FAIL expected exactly 1 temporary admin, found {len(temp)}", file=sys.stderr); sys.exit(1)
if temp[0]["username"]!=want:
    print(f"   FAIL temporary admin is {temp[0]['username']!r}, not {want!r}; the name may already be free",
          file=sys.stderr); sys.exit(1)
open(f"{d}/temp-id","w").write(temp[0]["id"])
print(f"   ok   temporary admin {temp[0]['username']} id={temp[0]['id']} carries is_temporary_admin=true")
print(f"   ok   this is the account the console banner is about")
PY
rc=$?; [ "$rc" = 3 ] && { echo "RESULT: already cut over — nothing to do"; exit 0; }
TEMP_ID="$(cat "$_d/temp-id")"

step "3. generate the permanent password (32 bytes of entropy, file only)"
openssl rand -base64 32 | tr -d '\n' > "$_d/pw-new"
[ -s "$_d/pw-new" ] || die "empty generated password"
ok "generated, bytes=$(wc -c < "$_d/pw-new")"

step "4. free the name: rename the temporary admin to $TEMP_ADMIN_USERNAME"
# master ships editUsernameAllowed=false, which marks username read-only in the user profile — and
# that applies to the admin REST API too, not just self-service. A rename returns
# 400 error-user-attribute-read-only until the flag is on. Turn it on for the rename only.
c="$(api "$_d/old.curl" GET "/admin/realms/master")"
[ "$c" = 200 ] || die "realm read http=$c"
was="$(python3 -c "import json,sys;print(str(json.load(open(sys.argv[1])).get('editUsernameAllowed',False)).lower())" "$_d/out")"
if [ "$was" = false ]; then
  printf '{"editUsernameAllowed":true}' > "$_d/edit-on.json"
  c="$(api "$_d/old.curl" PUT "/admin/realms/master" "$_d/edit-on.json")"
  [ "$c" = 204 ] || { cat "$_d/out" >&2; die "could not enable editUsernameAllowed (http=$c)"; }
  RESTORE_EDIT_USERNAME=1
  ok "master editUsernameAllowed temporarily enabled (was false)"
fi
printf '{"username":"%s"}' "$TEMP_ADMIN_USERNAME" > "$_d/rename.json"
c="$(api "$_d/old.curl" PUT "/admin/realms/master/users/$TEMP_ID" "$_d/rename.json")"
[ "$c" = 204 ] || { cat "$_d/out" >&2; die "rename http=$c (expected 204)"; }
if [ "$RESTORE_EDIT_USERNAME" = 1 ]; then
  printf '{"editUsernameAllowed":false}' > "$_d/edit-off.json"
  c="$(api "$_d/old.curl" PUT "/admin/realms/master" "$_d/edit-off.json")"
  [ "$c" = 204 ] || { cat "$_d/out" >&2; die "could not restore editUsernameAllowed=false (http=$c)"; }
  RESTORE_EDIT_USERNAME=0
  c="$(api "$_d/old.curl" GET "/admin/realms/master")"
  now="$(python3 -c "import json,sys;print(str(json.load(open(sys.argv[1])).get('editUsernameAllowed',False)).lower())" "$_d/out")"
  [ "$now" = false ] || die "master editUsernameAllowed is $now, expected false"
  ok "master editUsernameAllowed restored to false and re-read to confirm"
fi
c="$(api "$_d/old.curl" GET "/admin/realms/master/users/$TEMP_ID")"
got="$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['username'])" "$_d/out")"
[ "$got" = "$TEMP_ADMIN_USERNAME" ] || die "rename did not stick: username is $got"
ok "temporary admin is now $TEMP_ADMIN_USERNAME; the name $ADMIN_USERNAME is free"

step "5. create the permanent admin $ADMIN_USERNAME"
python3 - "$_d" "$ADMIN_USERNAME" <<'PY'
import json,sys
d,name=sys.argv[1],sys.argv[2]
json.dump({"username":name,"enabled":True,"emailVerified":True,"requiredActions":[],
           "credentials":[{"type":"password","value":open(f"{d}/pw-new").read(),"temporary":False}]},
          open(f"{d}/create.json","w"))
PY
c="$(api "$_d/old.curl" POST "/admin/realms/master/users" "$_d/create.json")"
[ "$c" = 201 ] || { cat "$_d/out" >&2; die "create user http=$c (expected 201)"; }
c="$(api "$_d/old.curl" GET "/admin/realms/master/users?username=$ADMIN_USERNAME&exact=true")"
NEW_ID="$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))[0]['id'])" "$_d/out")"
[ -n "$NEW_ID" ] || die "created user has no id"
ok "created $ADMIN_USERNAME id=$NEW_ID"

step "6. grant it the master realm role 'admin'"
c="$(api "$_d/old.curl" GET "/admin/realms/master/roles/admin")"
[ "$c" = 200 ] || die "realm role admin lookup http=$c"
python3 -c "
import json,sys
r=json.load(open(sys.argv[1]))
json.dump([{'id':r['id'],'name':r['name']}], open(sys.argv[2],'w'))" "$_d/out" "$_d/role.json"
c="$(api "$_d/old.curl" POST "/admin/realms/master/users/$NEW_ID/role-mappings/realm" "$_d/role.json")"
[ "$c" = 204 ] || { cat "$_d/out" >&2; die "role assignment http=$c"; }
ok "realm role admin assigned"

step "7. verify the permanent account BEFORE deleting anything"
c="$(token "$ADMIN_USERNAME" "$_d/pw-new" tok-new)"
[ "$c" = 200 ] || { cat "$_d/tok-new.json" >&2; die "permanent admin token http=$c"; }
authfile "$_d/tok-new.json" "$_d/new.curl"
ok "permanent admin authenticates with the new password"
c="$(api "$_d/new.curl" GET "/admin/realms")"
[ "$c" = 200 ] || die "permanent admin cannot list realms (http=$c) — not actually an admin"
python3 -c "
import json,sys
rs=[r['realm'] for r in json.load(open(sys.argv[1]))]
assert 'master' in rs, rs
print('   ok   permanent admin has real admin power: realms visible = %s' % ','.join(sorted(rs)))" "$_d/out"
c="$(api "$_d/new.curl" GET "/admin/realms/master/users/$NEW_ID")"
python3 -c "
import json,sys
u=json.load(open(sys.argv[1]))
a=(u.get('attributes') or {})
assert a.get('is_temporary_admin') is None, a
print('   ok   permanent admin carries NO is_temporary_admin attribute — no banner for this account')" "$_d/out"

step "8. escrow the new password BEFORE anything destructive happens"
# Ordering is load-bearing, learned the hard way: an earlier version escrowed last, a later
# assertion failed, and the generated password existed nowhere but a temp dir. Escrow first means
# the worst case of any later failure is a half-finished cutover with both accounts still usable.
python3 - "$_d" "$ADMIN_USERNAME" <<'PY'
import json,sys
d,name=sys.argv[1],sys.argv[2]
json.dump({"username":name,"password":open(f"{d}/pw-new").read()}, open(f"{d}/kv.json","w"))
PY
bash "$KV_PUT_SCRIPT" "$CA" "$KV_ADMIN_PATH" "$_d/kv.json"
bash "$WAIT_SECRET_SCRIPT" "$VSO_ADMIN_SECRET" password "$_d/pw-new" 180
"$KUBECTL" --kubeconfig "$KUBECONFIG" get secret "$VSO_ADMIN_SECRET" -n "$NS" \
  -o jsonpath='{.data.password}' | base64 -d > "$_d/pw-from-secret"
c="$(token "$ADMIN_USERNAME" "$_d/pw-from-secret" tok-secret)"
[ "$c" = 200 ] || die "the credential materialised from Vault does not authenticate (http=$c)"
ok "escrowed at $KV_ADMIN_PATH, materialised into $VSO_ADMIN_SECRET, and it authenticates"

step "9. delete the temporary admin, using the permanent admin's own token"
c="$(api "$_d/new.curl" DELETE "/admin/realms/master/users/$TEMP_ID")"
[ "$c" = 204 ] || { cat "$_d/out" >&2; die "delete temporary admin http=$c"; }
ok "temporary admin ($TEMP_ADMIN_USERNAME) deleted"

step "10. assert the end state the banner depends on"
c="$(api "$_d/new.curl" GET "/admin/realms/master/users?briefRepresentation=false")"
python3 - "$_d" "$ADMIN_USERNAME" <<'PY' || die "end-state assertion failed"
import json,sys
d,want=sys.argv[1],sys.argv[2]
us=json.load(open(f"{d}/out"))
temp=[u["username"] for u in us if (u.get("attributes") or {}).get("is_temporary_admin")==["true"]]
names=sorted(u["username"] for u in us)
assert not temp, f"still temporary: {temp}"
assert names==[want], names
print(f"   ok   master realm users = {names}")
print( "   ok   NO user carries is_temporary_admin — the console banner is gone")
PY
# Keycloak answers a bad password grant with HTTP 400 and error=invalid_grant, not 401 — 401 is for
# client authentication failures. Asserting 401 here failed a cutover that had actually succeeded,
# so assert what identifies a rejected credential: not-200, plus invalid_grant in the body.
c="$(token "$ADMIN_USERNAME" "$_d/pw-old" tok-dead)"
[ "$c" != 200 ] || die "the OLD bootstrap password still authenticates — it must not"
python3 - "$_d" <<'PY' || die "old password was rejected, but not as invalid_grant"
import json,sys
d=sys.argv[1]
r=json.load(open(f"{d}/tok-dead.json"))
assert r.get("error")=="invalid_grant", r
print(f"   ok   NEG: the old bootstrap password is rejected ({r['error']}: {r.get('error_description')})")
PY

printf '\nRESULT: PASS — permanent admin %s in place, temporary admin deleted, banner condition cleared,\n' "$ADMIN_USERNAME"
printf '        credential escrowed at %s and re-verified through the VSO-materialised Secret.\n' "$KV_ADMIN_PATH"
