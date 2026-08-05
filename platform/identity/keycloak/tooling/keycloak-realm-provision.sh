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
: "${KC_EXPECTED_ISSUER:?KC_EXPECTED_ISSUER is required}"
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
  # full.path=false is the platform naming decision: RoleBindings use leaf names such as
  # "openrmf-claim-editors" rather than full paths such as "/openrmf-claim-editors". Kubernetes
  # compares either form literally; leaf names would collide if nested groups later reuse a name.
  # id.token.claim=true because kubectl presents the ID token to the API server.
  cat > "$_d/mapper.json" <<'JSON'
{"name":"groups","protocol":"openid-connect","protocolMapper":"oidc-group-membership-mapper",
 "config":{"claim.name":"groups","full.path":"false",
           "id.token.claim":"true","access.token.claim":"true","userinfo.token.claim":"true"}}
JSON
  c=$(api POST "/admin/realms/$PLATFORM_REALM/clients/$uuid/protocol-mappers/models" "$_d/mapper.json")
  case "$c" in
    201) ok "client $cl: groups mapper created" ;;
    409)
      c=$(api GET "/admin/realms/$PLATFORM_REALM/clients/$uuid/protocol-mappers/models")
      if [ "$c" != 200 ]; then
        fail "client $cl mapper lookup http=$c"; cat "$_d/out" >&2; continue
      fi
      mapper_count=$(python3 -c "import json;d=json.load(open('$_d/out'));print(sum(m.get('name') == 'groups' for m in d))")
      if [ "$mapper_count" != 1 ]; then
        fail "client $cl has $mapper_count mappers named groups; expected exactly one"; continue
      fi
      mapper_id=$(python3 -c "import json;d=json.load(open('$_d/out'));print(next(m['id'] for m in d if m.get('name') == 'groups'))")
      mapper_type=$(python3 -c "import json;d=json.load(open('$_d/out'));print(next(m.get('protocolMapper','') for m in d if m.get('name') == 'groups'))")
      if [ "$mapper_type" = oidc-group-membership-mapper ]; then
        # PUT preserves the mapper id for anything that may reference it. Keycloak cannot change a
        # mapper's implementation type in place, so only a wrong-type name collision is recreated.
        python3 - "$_d/mapper.json" "$mapper_id" > "$_d/mapper-put.json" <<'PY2'
import json,sys
mapper=json.load(open(sys.argv[1])); mapper["id"]=sys.argv[2]
print(json.dumps(mapper))
PY2
        c=$(api PUT "/admin/realms/$PLATFORM_REALM/clients/$uuid/protocol-mappers/models/$mapper_id" "$_d/mapper-put.json")
        [ "$c" = 204 ] && ok "client $cl: groups mapper already present, settings reconciled" || fail "client $cl mapper update http=$c"
      else
        c=$(api DELETE "/admin/realms/$PLATFORM_REALM/clients/$uuid/protocol-mappers/models/$mapper_id")
        if [ "$c" != 204 ]; then
          fail "client $cl wrong-type mapper delete http=$c"; continue
        fi
        c=$(api POST "/admin/realms/$PLATFORM_REALM/clients/$uuid/protocol-mappers/models" "$_d/mapper.json")
        [ "$c" = 201 ] && ok "client $cl: wrong-type groups mapper replaced" || fail "client $cl mapper recreate http=$c"
      fi
      ;;
    *)   fail "client $cl mapper http=$c"; cat "$_d/out" >&2 ;;
  esac
done

step "4. PROVE every client renders every configured group in its token"
# A 201 on the mapper proves it was created, not that it works. The failure this guards against is
# silent: no groups claim means every RoleBinding to a group matches nobody, with no error anywhere.
# Keycloak can render the exact ID token a given user would receive, so this asserts mapper output
# rather than the configuration that is supposed to produce it. One realm user is sufficient for
# every client evaluation; creating one per client would add cleanup risk without changing scope.
PROBE_USER="claim-probe-$$"
probe_id=""
probe_cleanup_done=0
cleanup_probe() {
  local c id remaining cleanup_failed=0
  [ "$probe_cleanup_done" = 0 ] || return 0
  c=$(api GET "/admin/realms/$PLATFORM_REALM/users?username=$PROBE_USER&exact=true")
  if [ "$c" != 200 ]; then
    fail "probe user cleanup lookup http=$c"
    return 1
  fi
  for id in $(python3 -c "import json;print(' '.join(u['id'] for u in json.load(open('$_d/out'))))"); do
    c=$(api DELETE "/admin/realms/$PLATFORM_REALM/users/$id")
    if [ "$c" != 204 ]; then
      fail "probe user $PROBE_USER delete http=$c"
      cleanup_failed=1
    fi
  done
  c=$(api GET "/admin/realms/$PLATFORM_REALM/users?username=$PROBE_USER&exact=true")
  if [ "$c" != 200 ]; then
    fail "probe user cleanup verification http=$c"
    return 1
  fi
  remaining=$(python3 -c "import json;print(len(json.load(open('$_d/out'))))")
  if [ "$remaining" != 0 ]; then
    fail "probe user $PROBE_USER remains after cleanup"
    return 1
  fi
  probe_cleanup_done=1
  [ "$cleanup_failed" = 0 ] || return 1
  ok "probe user $PROBE_USER is absent after verified cleanup"
}
on_exit() {
  local rc=$?
  trap - EXIT INT TERM
  cleanup_probe || rc=1
  keep
  exit "$rc"
}
trap on_exit EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

python3 - "$PROBE_USER" "$PLATFORM_GROUPS" > "$_d/probe.json" <<'PY2'
import json,sys
print(json.dumps({"username":sys.argv[1], "enabled":True, "groups":sys.argv[2].split()}))
PY2
c=$(api POST "/admin/realms/$PLATFORM_REALM/users" "$_d/probe.json")
if [ "$c" != 201 ]; then
  fail "probe user create http=$c"; cat "$_d/out" >&2
else
  c=$(api GET "/admin/realms/$PLATFORM_REALM/users?username=$PROBE_USER&exact=true")
  [ "$c" = 200 ] || fail "probe user lookup http=$c"
  probe_id=$(python3 -c "import json;d=json.load(open('$_d/out'));print(d[0]['id'] if len(d) == 1 else '')")
  if [ -z "$probe_id" ]; then
    fail "probe user lookup did not return exactly one user"
  else
    for probe_client in $PLATFORM_CLIENTS; do
      c=$(api GET "/admin/realms/$PLATFORM_REALM/clients?clientId=$probe_client")
      if [ "$c" != 200 ]; then
        fail "client $probe_client probe lookup http=$c"; continue
      fi
      probe_client_uuid=$(python3 -c "import json;d=json.load(open('$_d/out'));print(d[0]['id'] if len(d) == 1 else '')")
      if [ -z "$probe_client_uuid" ]; then
        fail "client $probe_client probe lookup did not return exactly one client"; continue
      fi
      c=$(api GET "/admin/realms/$PLATFORM_REALM/clients/$probe_client_uuid/evaluate-scopes/generate-example-id-token?userId=$probe_id&scope=openid")
      if [ "$c" != 200 ]; then
        fail "client $probe_client example id-token http=$c"; cat "$_d/out" >&2; continue
      fi
      python3 - "$_d/out" "$PLATFORM_GROUPS" "$probe_client" <<'PY3' || fail "client $probe_client groups/audience assertion failed"
import json,sys
tok=json.load(open(sys.argv[1])); wants,client=sys.argv[2].split(),sys.argv[3]
groups=tok.get("groups")
assert groups is not None, "no 'groups' claim in the ID token — the mapper is not producing it"
missing=[want for want in wants if want not in groups]
assert not missing, f"groups={groups!r} is missing configured groups {missing!r}"
aud=tok.get("aud")
auds=aud if isinstance(aud,list) else [aud]
assert client in auds, f"aud={aud!r} is not the per-cluster client {client!r}"
print(f"   ok   client {client}: ID token carries every group {groups} and aud={aud}")
PY3
    done
  fi
fi
if ! cleanup_probe; then :; fi

step "5. assert the issuer each API server will trust"
c=$(api GET "/realms/$PLATFORM_REALM/.well-known/openid-configuration")
if [ "$c" = 200 ]; then
  python3 - "$_d/out" "$KC_EXPECTED_ISSUER" <<'PY2' || fail "discovery issuer assertion failed"
import json,sys
issuer=json.load(open(sys.argv[1])).get("issuer")
assert issuer == sys.argv[2], f"issuer={issuer!r}, expected {sys.argv[2]!r}"
print(f"   ok   issuer={issuer}")
PY2
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
