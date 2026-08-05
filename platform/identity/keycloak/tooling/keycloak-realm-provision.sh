#!/usr/bin/env bash
# Provision the platform realm, its groups, and one OIDC client per consuming cluster.
#
# WHY THIS IS CODE AND NOT A CONSOLE SESSION: realms live in the Keycloak database, and this
# capability's teardown destroys that database by design (the PVC is reclaim: Delete). A realm
# created by hand does not survive a rebuild, and nothing would tell you it was missing until an
# API server started rejecting every token.
#
# ONE realm, not one per consumer. Realms do not trust each other and each carries its own issuer
# and signing keys, so a realm per team would mean no single sign-on, a different issuer for every
# API server to trust, and group membership maintained N times — the fragmentation central OIDC
# (ADR-Platform-020) exists to remove. Separate realms are for separate tenants, which this estate
# does not have.
#
# PER-CLUSTER CLIENTS, though. The client id becomes the token's audience and each API server
# validates its own, so a token minted for one cluster cannot authenticate to another. ok-mgmt is
# the control plane that provisions every other cluster; that separation is worth the setup.
#
# Idempotent: re-running updates in place. Safe against a realm that already exists.
set -Eeuo pipefail

: "${KUBECTL:?KUBECTL is required}"
: "${KUBECONFIG:?KUBECONFIG is required}"
: "${NAMESPACE:?NAMESPACE is required}"
: "${KC_ORIGIN:?KC_ORIGIN is required}"
: "${KC_RESOLVE:?KC_RESOLVE is required}"
: "${KC_CONNECT:?KC_CONNECT is required}"
: "${KC_CACERT:?KC_CACERT is required}"
: "${KEYCLOAK_ADMIN_USERNAME:?KEYCLOAK_ADMIN_USERNAME is required}"
: "${VSO_ADMIN_SECRET:?VSO_ADMIN_SECRET is required}"
: "${PLATFORM_REALM:?PLATFORM_REALM is required}"
: "${PLATFORM_GROUPS:?PLATFORM_GROUPS is required}"
: "${PLATFORM_CLIENTS:?PLATFORM_CLIENTS is required}"

KC="$KC_ORIGIN"
NS="$NAMESPACE"
FAILED=0
step() { printf '\n== %s\n' "$1"; }
ok()   { printf '   ok   %s\n' "$1"; }
fail() { printf '   FAIL %s\n' "$1" >&2; FAILED=1; }
# --connect-to as well as --resolve: the canonical origin is :443 but the port-forward binds
# a local high port, and --resolve alone cannot redirect the port.
kc_curl() { curl --resolve "$KC_RESOLVE" --connect-to "$KC_CONNECT" --cacert "$KC_CACERT" "$@"; }

umask 077
_d="$(mktemp -d)"
keep() { echo "      work dir RETAINED (mode 700): $_d"; }
trap keep EXIT INT TERM

"$KUBECTL" --kubeconfig "$KUBECONFIG" get secret "$VSO_ADMIN_SECRET" -n "$NS" \
  -o jsonpath='{.data.password}' | base64 -d > "$_d/adminpw"
[ -s "$_d/adminpw" ] || { echo "ABORT: no admin password in $VSO_ADMIN_SECRET" >&2; exit 2; }

step "0. authenticate to the admin API"
c="$(kc_curl -sS -o "$_d/tok" -w '%{http_code}' \
  -d client_id=admin-cli -d grant_type=password -d "username=$KEYCLOAK_ADMIN_USERNAME" \
  --data-urlencode "password@$_d/adminpw" \
  "$KC/realms/master/protocol/openid-connect/token")"
[ "$c" = 200 ] || { echo "ABORT: admin token http=$c" >&2; cat "$_d/tok" >&2; exit 1; }
python3 -c "
import json,sys
print('header = \"Authorization: Bearer %s\"' % json.load(open(sys.argv[1]))['access_token'])" \
  "$_d/tok" > "$_d/auth.curl"
ok "authenticated as $KEYCLOAK_ADMIN_USERNAME"

api() { # api METHOD PATH [jsonfile] ; prints http code, body in $_d/out
  local m="$1" p="$2" f="${3:-}"
  if [ -n "$f" ]; then
    kc_curl -sS --config "$_d/auth.curl" -o "$_d/out" -w '%{http_code}' -X "$m" \
      -H 'Content-Type: application/json' --data-binary "@$f" "$KC$p"
  else
    kc_curl -sS --config "$_d/auth.curl" -o "$_d/out" -w '%{http_code}' -X "$m" "$KC$p"
  fi
}

step "1. realm $PLATFORM_REALM"
# bruteForceProtected mirrors what master already enforces; a platform realm holding real humans
# should not be weaker than the admin realm.
cat > "$_d/realm.json" <<JSON
{"realm":"$PLATFORM_REALM","enabled":true,
 "displayName":"OpenKubes platform identity",
 "bruteForceProtected":true,"failureFactor":5,"permanentLockout":false,
 "waitIncrementSeconds":60,"maxFailureWaitSeconds":900}
JSON
c=$(api POST /admin/realms "$_d/realm.json")
case "$c" in
  201) ok "realm created" ;;
  409) c=$(api PUT "/admin/realms/$PLATFORM_REALM" "$_d/realm.json")
       [ "$c" = 204 ] && ok "realm already present, settings reconciled" || fail "realm update http=$c" ;;
  *)   fail "realm create http=$c"; cat "$_d/out" >&2 ;;
esac

step "2. groups — these become Kubernetes groups in the token"
for g in $PLATFORM_GROUPS; do
  printf '{"name":"%s"}' "$g" > "$_d/group.json"
  c=$(api POST "/admin/realms/$PLATFORM_REALM/groups" "$_d/group.json")
  case "$c" in 201) ok "group $g created";; 409) ok "group $g already present";; *) fail "group $g http=$c";; esac
done

step "3. one public client per cluster — the client id IS the audience"
for cl in $PLATFORM_CLIENTS; do
  # publicClient: kubectl cannot keep a secret, so this is a public client and PKCE is mandatory
  # rather than optional. Redirect URIs cover the loopback ports kubectl OIDC helpers bind.
  cat > "$_d/client.json" <<JSON
{"clientId":"$cl","enabled":true,"protocol":"openid-connect",
 "publicClient":true,"standardFlowEnabled":true,"directAccessGrantsEnabled":false,
 "serviceAccountsEnabled":false,
 "redirectUris":["http://localhost:8000","http://localhost:8000/*","http://localhost:18000","http://localhost:18000/*"],
 "webOrigins":["+"],
 "attributes":{"pkce.code.challenge.method":"S256"}}
JSON
  c=$(api POST "/admin/realms/$PLATFORM_REALM/clients" "$_d/client.json")
  case "$c" in 201) ok "client $cl created";; 409) ok "client $cl already present";; *) fail "client $cl http=$c"; cat "$_d/out" >&2; continue;; esac

  api GET "/admin/realms/$PLATFORM_REALM/clients?clientId=$cl" >/dev/null
  uuid=$(python3 -c "import json;d=json.load(open('$_d/out'));print(d[0]['id'] if d else '')")
  [ -n "$uuid" ] || { fail "client $cl has no id"; continue; }
  if [ "$c" = 409 ]; then
    c=$(api PUT "/admin/realms/$PLATFORM_REALM/clients/$uuid" "$_d/client.json")
    [ "$c" = 204 ] || fail "client $cl update http=$c"
  fi

  # THE MAPPER IS THE WHOLE POINT. Without it the token carries no groups claim, every RoleBinding
  # to a group matches nobody, and nothing errors anywhere — the failure mode is silence.
  # full.path=false so groups arrive as "openrmf-claim-editors", not "/openrmf-claim-editors";
  # Kubernetes compares the claim value literally against the RoleBinding subject.
  # id.token.claim=true because kubectl presents the ID token to the API server.
  cat > "$_d/mapper.json" <<'JSON'
{"name":"groups","protocol":"openid-connect","protocolMapper":"oidc-group-membership-mapper",
 "config":{"claim.name":"groups","full.path":"false",
           "id.token.claim":"true","access.token.claim":"true","userinfo.token.claim":"true"}}
JSON
  c=$(api POST "/admin/realms/$PLATFORM_REALM/clients/$uuid/protocol-mappers/models" "$_d/mapper.json")
  case "$c" in
    201) ok "client $cl: groups mapper created" ;;
    409) ok "client $cl: groups mapper already present" ;;
    *)   fail "client $cl mapper http=$c"; cat "$_d/out" >&2 ;;
  esac
done

step "4. PROVE the groups claim actually lands in a token"
# A 201 on the mapper proves it was created, not that it works. The failure this guards against is
# silent: no groups claim means every RoleBinding to a group matches nobody, with no error anywhere.
# Keycloak can render the exact ID token a given user would receive, so this asserts the real output
# rather than the configuration that is supposed to produce it. Probe user is created and removed.
PROBE_USER="claim-probe-$$"
PROBE_GROUP="$(printf '%s' "$PLATFORM_GROUPS" | awk '{print $1}')"
PROBE_CLIENT="$(printf '%s' "$PLATFORM_CLIENTS" | awk '{print $1}')"
probe_id=""
cleanup_probe() {
  [ -n "$probe_id" ] || return 0
  api DELETE "/admin/realms/$PLATFORM_REALM/users/$probe_id" >/dev/null 2>&1 || true
}
trap 'cleanup_probe; keep' EXIT INT TERM

printf '{"username":"%s","enabled":true,"groups":["%s"]}' "$PROBE_USER" "$PROBE_GROUP" > "$_d/probe.json"
c=$(api POST "/admin/realms/$PLATFORM_REALM/users" "$_d/probe.json")
if [ "$c" != 201 ]; then
  fail "probe user create http=$c"; cat "$_d/out" >&2
else
  api GET "/admin/realms/$PLATFORM_REALM/users?username=$PROBE_USER&exact=true" >/dev/null
  probe_id=$(python3 -c "import json;d=json.load(open('$_d/out'));print(d[0]['id'] if d else '')")
  api GET "/admin/realms/$PLATFORM_REALM/clients?clientId=$PROBE_CLIENT" >/dev/null
  probe_client_uuid=$(python3 -c "import json;d=json.load(open('$_d/out'));print(d[0]['id'] if d else '')")
  c=$(api GET "/admin/realms/$PLATFORM_REALM/clients/$probe_client_uuid/evaluate-scopes/generate-example-id-token?userId=$probe_id&scope=openid")
  if [ "$c" != 200 ]; then
    fail "example id-token http=$c"; cat "$_d/out" >&2
  else
    python3 - "$_d/out" "$PROBE_GROUP" "$PROBE_CLIENT" <<'PY2' || fail "groups claim assertion failed"
import json,sys
tok=json.load(open(sys.argv[1])); want,client=sys.argv[2],sys.argv[3]
groups=tok.get("groups")
assert groups is not None, "no 'groups' claim in the ID token — the mapper is not producing it"
assert want in groups, f"groups={groups!r} does not contain {want!r}"
aud=tok.get("aud")
auds=aud if isinstance(aud,list) else [aud]
assert client in auds, f"aud={aud!r} is not the per-cluster client {client!r}"
print(f"   ok   ID token carries groups={groups} and aud={aud}")
PY2
  fi
fi

step "5. report the issuer each API server must be pointed at"
c=$(api GET "/realms/$PLATFORM_REALM/.well-known/openid-configuration")
if [ "$c" = 200 ]; then
  python3 -c "import json;d=json.load(open('$_d/out'));print('   ok   issuer=%s' % d['issuer'])"
else
  fail "discovery http=$c"
fi

printf '\n'
if [ "$FAILED" -eq 0 ]; then
  echo "RESULT: PASS — realm $PLATFORM_REALM, groups [$PLATFORM_GROUPS], clients [$PLATFORM_CLIENTS]"
  echo "        Each cluster's API server uses oidc-client-id=<its own client id>."
else
  echo "RESULT: FAIL" >&2; exit 1
fi
