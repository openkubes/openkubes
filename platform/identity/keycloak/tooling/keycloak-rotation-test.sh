#!/usr/bin/env bash
# OK-81 step 5.8 — exercise both credential rotations, including the asymmetry between them.
#
# The claim under test is the one the deployment document makes: Vault owns the DESIRED value, but
# it is not the runtime authority for the Keycloak admin account, while it IS the effective source
# for the database role because CNPG reconciles spec.managed.roles[].passwordSecret. Those are
# opposite behaviours from the same Vault write, so each direction is asserted explicitly rather
# than described.
#
# Part A — admin account:
#   A1 rotate in Keycloak       -> new works, old refused
#   A2 Vault is now STALE       -> the Vault-materialised value no longer authenticates
#   A3 write Vault ALONE        -> Keycloak is unmoved: still the Keycloak-set password
#   A4 converge                 -> escrow the real value, materialise, re-verify
# Part B — database role:
#   B1 write Vault              -> Secret updates, CNPG passwordStatus advances, psql accepts new
#   B2 old value refused
#   B3 restart Keycloak         -> comes back Ready against the rotated credential
set -Eeuo pipefail

: "${KUBECTL:?KUBECTL is required}"
: "${KUBECONFIG:?KUBECONFIG is required}"
: "${NAMESPACE:?NAMESPACE is required}"
: "${KC_PORT:?KC_PORT is required}"
: "${ADMIN_USERNAME:?ADMIN_USERNAME is required}"
: "${VSO_ADMIN_SECRET:?VSO_ADMIN_SECRET is required}"
: "${VSO_DB_SECRET:?VSO_DB_SECRET is required}"
: "${KV_ADMIN_PATH:?KV_ADMIN_PATH is required}"
: "${KV_DB_PATH:?KV_DB_PATH is required}"
: "${CNPG_CLUSTER:?CNPG_CLUSTER is required}"
: "${DB_NAME:?DB_NAME is required}"
: "${DB_USERNAME:?DB_USERNAME is required}"
: "${KEYCLOAK_STATEFULSET:?KEYCLOAK_STATEFULSET is required}"
: "${KV_PUT_SCRIPT:?KV_PUT_SCRIPT is required}"
: "${WAIT_SECRET_SCRIPT:?WAIT_SECRET_SCRIPT is required}"
CA="$1"

KC="http://localhost:$KC_PORT"
NS="$NAMESPACE"
KC_POD="$KEYCLOAK_STATEFULSET-0"
DB_POD="$CNPG_CLUSTER-1"
step() { printf '\n== %s\n' "$1"; }
ok()   { printf '   ok   %s\n' "$1"; }
die()  { printf '   FAIL %s\n' "$1" >&2; exit 1; }

umask 077
_d="$(mktemp -d)"
# Work dir retained on purpose: it holds every password this run generates, and a failure part-way
# through a rotation is exactly when you need them.
keep() { echo "      work dir RETAINED (mode 700, contains plaintext credentials): $_d"; }
trap keep EXIT INT TERM
echo "      work dir: $_d"

secret_pw() { # secret_pw <secret> <outfile>
  "$KUBECTL" --kubeconfig "$KUBECONFIG" get secret "$1" -n "$NS" \
    -o jsonpath='{.data.password}' | base64 -d > "$2"
  [ -s "$2" ] || die "no password in Secret $1"
}
token() { # token <password-file> <out-prefix> ; prints http code
  curl -sS -o "$_d/$2.json" -w '%{http_code}' \
    -d client_id=admin-cli -d grant_type=password -d "username=$ADMIN_USERNAME" \
    --data-urlencode "password@$1" \
    "$KC/realms/master/protocol/openid-connect/token"
}
assert_login()  { # assert_login <password-file> <label>
  local c; c="$(token "$1" "tok-$2")"
  [ "$c" = 200 ] || { cat "$_d/tok-$2.json" >&2; die "$2: expected the password to work, http=$c"; }
}
assert_refused() { # assert_refused <password-file> <label>
  local c; c="$(token "$1" "tok-$2")"
  [ "$c" != 200 ] || die "$2: expected the password to be REFUSED, but it authenticated"
  python3 - "$_d" "$2" <<'PY' || die "$2: refused, but not with invalid_grant"
import json,sys
d,label=sys.argv[1],sys.argv[2]
r=json.load(open(f"{d}/tok-{label}.json"))
assert r.get("error")=="invalid_grant", r
PY
}
clear_lockout() { # clear_lockout <currently-valid-password-file>
  # Brute-force protection counts THIS TEST'S deliberate failures against the very account it then
  # has to log in as. With failureFactor=5 the third or fourth negative check locks `admin` out, the
  # next positive assertion fails for a reason that has nothing to do with rotation, and the run dies
  # between "write a throwaway value to Vault" and "converge" — leaving Vault holding the throwaway
  # while Keycloak holds the real password. That happened once and needed a manual re-escrow.
  #
  # So reset the counter after every negative, while it is still below the threshold and a token can
  # still be obtained. Clearing per-negative is what keeps this safe; clearing once at the end would
  # be too late by construction.
  local c
  c="$(token "$1" tok-clear)" || true
  [ "$c" = 200 ] || { printf '   ..   lockout clear skipped (no token, http=%s)\n' "$c"; return 0; }
  python3 -c "
import json,sys
print('header = \"Authorization: Bearer %s\"' % json.load(open(sys.argv[1]))['access_token'])" \
    "$_d/tok-clear.json" > "$_d/clear.curl"
  c="$(curl -sS --config "$_d/clear.curl" -o /dev/null -w '%{http_code}' -X DELETE \
    "$KC/admin/realms/master/attack-detection/brute-force/users/$ADMIN_ID")"
  case "$c" in 204|200) printf '   ..   brute-force counter cleared for %s\n' "$ADMIN_USERNAME" ;;
    *) printf '   ..   brute-force clear returned http=%s (continuing)\n' "$c" ;;
  esac
}
db_login() { # db_login <password-file> ; prints "AUTH_OK" or "AUTH_FAIL <psql message>"
  # The CNPG container filesystem is read-only, so psql's stderr cannot be spooled to a file there.
  # It is captured into a variable instead and returned on the AUTH_FAIL line ON PURPOSE: a bare
  # pass/fail would make "wrong password" and "cannot reach the server" indistinguishable, and the
  # negative assertion below would then pass for the wrong reason.
  "$KUBECTL" --kubeconfig "$KUBECONFIG" exec -i -n "$NS" "$DB_POD" -c postgres -- \
    env "PGHOST=$CNPG_CLUSTER-rw" PGPORT=5432 "PGUSER=$DB_USERNAME" "PGDATABASE=$DB_NAME" \
    sh -c 'read -r p; export PGPASSWORD="$p";
           if err="$(psql -w -tAc "select 1" 2>&1 >/dev/null)"; then echo AUTH_OK;
           else printf "AUTH_FAIL %s\n" "$(echo "$err" | tr "\n" " ")"; fi' \
    < "$1"
}
db_password_rv() {
  "$KUBECTL" --kubeconfig "$KUBECONFIG" get cluster.postgresql.cnpg.io "$CNPG_CLUSTER" -n "$NS" \
    -o "jsonpath={.status.managedRolesStatus.passwordStatus.$DB_USERNAME.resourceVersion}"
}

# ============================================================ PART A — the admin account
step "A0. baseline: the credential in $VSO_ADMIN_SECRET authenticates"
secret_pw "$VSO_ADMIN_SECRET" "$_d/pw-a"
assert_login "$_d/pw-a" a
ok "current escrowed admin credential works"

python3 -c "
import json,sys
print('header = \"Authorization: Bearer %s\"' % json.load(open(sys.argv[1]))['access_token'])" \
  "$_d/tok-a.json" > "$_d/auth.curl"
c="$(curl -sS --config "$_d/auth.curl" -o "$_d/uid" -w '%{http_code}' \
  "$KC/admin/realms/master/users?username=$ADMIN_USERNAME&exact=true")"
[ "$c" = 200 ] || die "user lookup http=$c"
ADMIN_ID="$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))[0]['id'])" "$_d/uid")"
ok "admin id=$ADMIN_ID"

step "A1. rotate the admin password IN KEYCLOAK (its own API is the only thing that can)"
openssl rand -base64 32 | tr -d '\n' > "$_d/pw-b"
python3 - "$_d" <<'PY'
import json,sys
d=sys.argv[1]
json.dump({"type":"password","value":open(f"{d}/pw-b").read(),"temporary":False},
          open(f"{d}/reset.json","w"))
PY
c="$(curl -sS --config "$_d/auth.curl" -o "$_d/out" -w '%{http_code}' -X PUT \
  -H 'Content-Type: application/json' --data-binary "@$_d/reset.json" \
  "$KC/admin/realms/master/users/$ADMIN_ID/reset-password")"
[ "$c" = 204 ] || { cat "$_d/out" >&2; die "reset-password http=$c"; }
assert_login "$_d/pw-b" b
ok "the new password authenticates"
assert_refused "$_d/pw-a" a-dead
ok "NEG: the previous password is refused (invalid_grant)"
clear_lockout "$_d/pw-b"

step "A2. Vault is now STALE — and that is the asymmetry, not a bug"
secret_pw "$VSO_ADMIN_SECRET" "$_d/pw-secret-now"
cmp -s "$_d/pw-secret-now" "$_d/pw-a" || die "the Secret changed on its own; nothing should have touched Vault"
ok "$VSO_ADMIN_SECRET still holds the OLD value: a Keycloak-side rotation does not write to Vault"
assert_refused "$_d/pw-secret-now" secret-stale
ok "NEG: the Vault-materialised credential no longer authenticates — escrow is now out of date"
clear_lockout "$_d/pw-b"

step "A3. write Vault ALONE and prove Keycloak does not move"
openssl rand -base64 32 | tr -d '\n' > "$_d/pw-c"
python3 - "$_d" "$ADMIN_USERNAME" <<'PY'
import json,sys
d,name=sys.argv[1],sys.argv[2]
json.dump({"username":name,"password":open(f"{d}/pw-c").read()}, open(f"{d}/kv-c.json","w"))
PY
bash "$KV_PUT_SCRIPT" "$CA" "$KV_ADMIN_PATH" "$_d/kv-c.json"
bash "$WAIT_SECRET_SCRIPT" "$VSO_ADMIN_SECRET" password "$_d/pw-c" 180
assert_refused "$_d/pw-c" vault-only
ok "NEG: the value written to Vault does NOT authenticate against Keycloak"
clear_lockout "$_d/pw-b"
assert_login "$_d/pw-b" b-still
ok "Keycloak still accepts only what its own API set — Vault is not the runtime authority here"

step "A4. converge: escrow the real password and re-verify through the Secret"
python3 - "$_d" "$ADMIN_USERNAME" <<'PY'
import json,sys
d,name=sys.argv[1],sys.argv[2]
json.dump({"username":name,"password":open(f"{d}/pw-b").read()}, open(f"{d}/kv-b.json","w"))
PY
bash "$KV_PUT_SCRIPT" "$CA" "$KV_ADMIN_PATH" "$_d/kv-b.json"
bash "$WAIT_SECRET_SCRIPT" "$VSO_ADMIN_SECRET" password "$_d/pw-b" 180
secret_pw "$VSO_ADMIN_SECRET" "$_d/pw-final"
assert_login "$_d/pw-final" final
ok "Vault, the Secret and Keycloak agree again; admin rotation complete"

# ============================================================ PART B — the database role
step "B0. baseline: the current database credential authenticates to PostgreSQL"
secret_pw "$VSO_DB_SECRET" "$_d/db-a"
r="$(db_login "$_d/db-a")"
[ "$r" = AUTH_OK ] || die "baseline database login failed ($r)"
ok "role $DB_USERNAME authenticates with the current escrowed password"
RV_BEFORE="$(db_password_rv)"
ok "CNPG passwordStatus.$DB_USERNAME.resourceVersion before = $RV_BEFORE"

step "B1. rotate in Vault — here Vault IS effective, because CNPG reconciles managed.roles"
openssl rand -base64 32 | tr -d '\n' > "$_d/db-b"
python3 - "$_d" "$DB_USERNAME" <<'PY'
import json,sys
d,u=sys.argv[1],sys.argv[2]
json.dump({"username":u,"password":open(f"{d}/db-b").read()}, open(f"{d}/kv-db.json","w"))
PY
bash "$KV_PUT_SCRIPT" "$CA" "$KV_DB_PATH" "$_d/kv-db.json"
bash "$WAIT_SECRET_SCRIPT" "$VSO_DB_SECRET" password "$_d/db-b" 180

echo "      waiting for CNPG to reconcile the role against the new Secret"
for i in $(seq 1 90); do
  rv="$(db_password_rv)"
  [ -n "$rv" ] && [ "$rv" != "$RV_BEFORE" ] && break
  sleep 2
done
rv="$(db_password_rv)"
[ "$rv" != "$RV_BEFORE" ] || die "CNPG passwordStatus.resourceVersion never advanced from $RV_BEFORE"
ok "CNPG reconciled: passwordStatus.$DB_USERNAME.resourceVersion $RV_BEFORE -> $rv"

for i in $(seq 1 60); do
  r="$(db_login "$_d/db-b")"
  [ "$r" = AUTH_OK ] && break
  sleep 2
done
[ "$r" = AUTH_OK ] || die "the rotated database password never became valid in PostgreSQL ($r)"
ok "PostgreSQL accepts the new password — the Vault write reached the role"

step "B2. NEG: the previous database password must be refused"
r="$(db_login "$_d/db-a")"
case "$r" in
  AUTH_OK) die "the OLD database password still authenticates" ;;
  AUTH_FAIL*"password authentication failed"*) ok "NEG: the previous database password is refused by PostgreSQL" ;;
  *) die "old password did not authenticate, but not because it was rejected: $r" ;;
esac

step "B3. restart Keycloak so it picks the rotated credential out of its environment"
# Secret-backed env vars do not change inside a running container, so until this restart Keycloak is
# still holding connections authenticated with the old value. The restart is what proves the rotated
# credential actually works for the consumer, not just for psql.
"$KUBECTL" --kubeconfig "$KUBECONFIG" delete pod "$KC_POD" -n "$NS" --wait=true
"$KUBECTL" --kubeconfig "$KUBECONFIG" rollout status "statefulset/$KEYCLOAK_STATEFULSET" -n "$NS" \
  --timeout="${KEYCLOAK_WAIT_TIMEOUT:-5m}"
ok "StatefulSet $KEYCLOAK_STATEFULSET is Ready again after the database credential rotation"

# The caller's port-forward was bound to the pod that has just been deleted, so it is gone — a
# port-forward does not follow a StatefulSet to a new pod. Re-establish one here. The port must be
# the same $KC_PORT: KC_HOSTNAME pins the origin, so asserting over a different port would fail for
# a reason that has nothing to do with rotation.
OWN_PF=''
for i in $(seq 1 45); do
  c="$(curl -sS -o /dev/null -w '%{http_code}' "$KC/realms/master/.well-known/openid-configuration" || true)"
  [ "$c" = 200 ] && break
  if [ -z "$OWN_PF" ] || ! kill -0 "$OWN_PF" 2>/dev/null; then
    "$KUBECTL" --kubeconfig "$KUBECONFIG" port-forward -n "$NS" "statefulset/$KEYCLOAK_STATEFULSET" \
      "$KC_PORT:8080" --address=127.0.0.1 > "$_d/pf-restart.log" 2>&1 &
    OWN_PF=$!
    trap 'kill "$OWN_PF" 2>/dev/null || true; keep' EXIT INT TERM
  fi
  sleep 2
done
[ "$c" = 200 ] || { cat "$_d/pf-restart.log" >&2; die "Keycloak did not serve the discovery document after restart (http=$c)"; }
ok "discovery document served after restart"
assert_login "$_d/pw-final" post-restart
ok "admin login works after restart — Keycloak is running on the rotated database credential"

printf '\nRESULT: PASS — admin rotation and database-role rotation both verified, including the\n'
printf '        asymmetry: Vault alone cannot change the Keycloak account, but Vault alone DOES\n'
printf '        rotate the PostgreSQL role through CNPG managed.roles.\n'
