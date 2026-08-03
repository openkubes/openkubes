#!/usr/bin/env bash
# OK-81 step 5 — functional verification over port-forward.
# Accumulates failures (set -u, no -e) so every guarantee reports, exit code is the contract.
set -uo pipefail

: "${KUBECTL:?KUBECTL is required}"
: "${KUBECONFIG:?KUBECONFIG is required}"
: "${NAMESPACE:?NAMESPACE is required}"
: "${KC_ORIGIN:?KC_ORIGIN is required}"
: "${KC_RESOLVE:?KC_RESOLVE is required}"
: "${KC_CONNECT:?KC_CONNECT is required}"
: "${KC_CACERT:?KC_CACERT is required}"
: "${KC_EXPECTED_ISSUER:?KC_EXPECTED_ISSUER is required}"
: "${KEYCLOAK_ADMIN_USERNAME:?KEYCLOAK_ADMIN_USERNAME is required}"
KC="$KC_ORIGIN"
NS="$NAMESPACE"
REALM=ok-conformance
CLIENT=conformance-client
USER=conformance-user
FAILED=0
step() { printf '\n== %s\n' "$1"; }
ok()   { printf '   ok   %s\n' "$1"; }
fail() { printf '   FAIL %s\n' "$1" >&2; FAILED=1; }
kc_curl() { curl --resolve "$KC_RESOLVE" --connect-to "$KC_CONNECT" --cacert "$KC_CACERT" "$@"; }

_d=""; cleanup(){ [ -n "$_d" ] && rm -rf -- "$_d"; }
trap cleanup EXIT INT TERM
umask 077; _d="$(mktemp -d)"

"$KUBECTL" --kubeconfig "$KUBECONFIG" get secret keycloak-admin -n "$NS" -o jsonpath='{.data.password}' | base64 -d > "$_d/adminpw"
[ -s "$_d/adminpw" ] || { echo "ABORT: no admin password"; exit 2; }

step "1. discovery document advertises the stable HTTPS issuer"
kc_curl -sS -o "$_d/discovery" -w '%{http_code}' \
  "$KC/realms/master/.well-known/openid-configuration" > "$_d/discovery-code"
if [ "$(cat "$_d/discovery-code")" = 200 ]; then
  ISSUER=$(python3 -c "import json; print(json.load(open('$_d/discovery'))['issuer'])")
  EXPECTED_REALM_ISSUER="$KC_EXPECTED_ISSUER/realms/master"
  [ "$ISSUER" = "$EXPECTED_REALM_ISSUER" ] && ok "issuer=$ISSUER" \
    || fail "issuer=$ISSUER, expected $EXPECTED_REALM_ISSUER"
else
  fail "discovery http=$(cat "$_d/discovery-code")"
fi

step "2. admin token (password grant, admin-cli, password read from file not argv)"
kc_curl -sS -o "$_d/tok" -w '%{http_code}' \
  -d client_id=admin-cli -d grant_type=password -d "username=$KEYCLOAK_ADMIN_USERNAME" \
  --data-urlencode "password@$_d/adminpw" \
  "$KC/realms/master/protocol/openid-connect/token" > "$_d/code"
if [ "$(cat "$_d/code")" = 200 ]; then
  python3 -c "import json;open('$_d/at','w').write(json.load(open('$_d/tok'))['access_token'])"
  ok "admin authenticated"
else
  fail "admin token http=$(cat "$_d/code")"; cat "$_d/tok" >&2; exit 1
fi
python3 - "$_d" <<'PY'
import sys
d=sys.argv[1]
token=open(f"{d}/at").read()
open(f"{d}/auth.curl", "w").write(f'header = "Authorization: Bearer {token}"\n')
PY

api() { # api METHOD PATH [jsonfile]
  local m="$1" p="$2" f="${3:-}"
  if [ -n "$f" ]; then
    kc_curl -sS --config "$_d/auth.curl" -o "$_d/out" -w '%{http_code}' -X "$m" \
      -H 'Content-Type: application/json' --data-binary "@$f" "$KC$p"
  else
    kc_curl -sS --config "$_d/auth.curl" -o "$_d/out" -w '%{http_code}' -X "$m" "$KC$p"
  fi
}

step "3. conformance realm (neutral — deliberately NOT ok2-rmf)"
printf '{"realm":"%s","enabled":true}' "$REALM" > "$_d/realm.json"
c=$(api POST /admin/realms "$_d/realm.json")
case "$c" in 201) ok "realm $REALM created";; 409) ok "realm $REALM already present";; *) fail "realm create http=$c"; cat "$_d/out" >&2;; esac

step "4. confidential client with standard flow + service account"
cat > "$_d/client.json" <<JSON
{"clientId":"$CLIENT","enabled":true,"protocol":"openid-connect",
 "publicClient":false,"standardFlowEnabled":true,"serviceAccountsEnabled":true,
 "directAccessGrantsEnabled":false,
 "redirectUris":["$KC/callback"],"webOrigins":["+"],
 "attributes":{"pkce.code.challenge.method":"S256"}}
JSON
c=$(api POST "/admin/realms/$REALM/clients" "$_d/client.json")
case "$c" in 201|409) ok "client $CLIENT present (http=$c)";; *) fail "client create http=$c"; cat "$_d/out" >&2;; esac
api GET "/admin/realms/$REALM/clients?clientId=$CLIENT" >/dev/null
CLIENT_UUID=$(python3 -c "import json;d=json.load(open('$_d/out'));print(d[0]['id'] if d else '')")
[ -n "$CLIENT_UUID" ] || { fail "client id not found"; exit 1; }
if [ "$c" = 409 ]; then
  c=$(api PUT "/admin/realms/$REALM/clients/$CLIENT_UUID" "$_d/client.json")
  [ "$c" = 204 ] && ok "existing client updated for origin $KC" \
    || { fail "client update http=$c"; cat "$_d/out" >&2; }
fi
api GET "/admin/realms/$REALM/clients/$CLIENT_UUID/client-secret" >/dev/null
python3 -c "import json;open('$_d/csec','w').write(json.load(open('$_d/out'))['value'])"
[ -s "$_d/csec" ] && ok "client secret retrieved" || fail "no client secret"

step "5. test user"
cat > "$_d/user.json" <<JSON
{"username":"$USER","enabled":true,"emailVerified":true,
 "email":"conformance-user@ok-shared.internal","firstName":"Conformance","lastName":"User","requiredActions":[],
 "credentials":[{"type":"password","value":"$(openssl rand -base64 24 | tr -d '\n' | tee "$_d/userpw")","temporary":false}]}
JSON
c=$(api POST "/admin/realms/$REALM/users" "$_d/user.json")
case "$c" in 201|409) ok "user $USER present (http=$c)";; *) fail "user create http=$c"; cat "$_d/out" >&2;; esac
# 409 means the user survived from an earlier run, and on that path the password generated above was
# never applied — so step 5 would authenticate with a credential the account does not have. That is
# not a Keycloak fault and not a real regression: it made this suite pass only against a fresh
# database, and it failed for exactly this reason after a values change that was in fact harmless.
# Reset the existing account's password to the generated one so the suite is re-runnable.
if [ "$c" = 409 ]; then
  api GET "/admin/realms/$REALM/users?username=$USER&exact=true" >/dev/null
  USER_ID=$(python3 -c "import json;d=json.load(open('$_d/out'));print(d[0]['id'] if d else '')")
  if [ -z "$USER_ID" ]; then fail "existing user $USER could not be looked up"; else
    python3 - "$_d" <<'PY'
import json,sys
d=sys.argv[1]
json.dump({"type":"password","value":open(f"{d}/userpw").read(),"temporary":False},
          open(f"{d}/userpw.json","w"))
PY
    c=$(api PUT "/admin/realms/$REALM/users/$USER_ID/reset-password" "$_d/userpw.json")
    [ "$c" = 204 ] && ok "existing user's password reset to this run's value (suite is re-runnable)" \
      || { fail "reset-password http=$c"; cat "$_d/out" >&2; }
  fi
fi

step "6. AUTHORIZATION CODE + PKCE (the guarantee that justifies a central IdP)"
python3 - "$_d" <<'PY'
import os,sys,base64,hashlib
d=sys.argv[1]
v=base64.urlsafe_b64encode(os.urandom(40)).decode().rstrip('=')
c=base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).decode().rstrip('=')
open(f"{d}/verifier","w").write(v); open(f"{d}/challenge","w").write(c)
PY
VER=$(cat "$_d/verifier"); CHAL=$(cat "$_d/challenge")
REDIRECT_URI="$KC/callback"
REDIRECT_ENCODED=$(python3 -c 'import sys,urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$REDIRECT_URI")
AUTH="$KC/realms/$REALM/protocol/openid-connect/auth?client_id=$CLIENT&response_type=code&scope=openid&redirect_uri=$REDIRECT_ENCODED&state=xyz&code_challenge=$CHAL&code_challenge_method=S256"
kc_curl -sS -c "$_d/jar" -o "$_d/login.html" "$AUTH"
ACTION=$(python3 -c "
import re,html
s=open('$_d/login.html').read()
m=re.search(r'action=\"([^\"]+)\"',s)
print(html.unescape(m.group(1)) if m else '')")
if [ -z "$ACTION" ]; then fail "no login form returned"; else
  kc_curl -sS -b "$_d/jar" -c "$_d/jar" -o /dev/null -D "$_d/hdr" \
    -d "username=$USER" --data-urlencode "password@$_d/userpw" -d credentialId= "$ACTION"
  CODE=$(python3 -c "
import re
s=open('$_d/hdr').read()
m=re.search(r'[Ll]ocation:.*?[?&]code=([^&\s]+)',s)
print(m.group(1) if m else '')")
  if [ -z "$CODE" ]; then fail "no authorization code in redirect"; grep -i '^location' "$_d/hdr" >&2 || true; else
    ok "authorization code obtained via browser-style login"
    kc_curl -sS -o "$_d/tokens" -w '%{http_code}' \
      -d grant_type=authorization_code -d "client_id=$CLIENT" \
      --data-urlencode "client_secret@$_d/csec" -d "code=$CODE" \
      -d "redirect_uri=$REDIRECT_URI" -d "code_verifier=$VER" \
      "$KC/realms/$REALM/protocol/openid-connect/token" > "$_d/tc"
    if [ "$(cat "$_d/tc")" = 200 ]; then ok "code+verifier exchanged for tokens"; else
      fail "token exchange http=$(cat "$_d/tc")"; cat "$_d/tokens" >&2; fi
  fi
fi

step "7. verify the token signature against the advertised JWKS (real crypto, not trust)"
kc_curl -sS -o "$_d/jwks" "$KC/realms/$REALM/protocol/openid-connect/certs"
if python3 - "$_d" "$KC_EXPECTED_ISSUER/realms/$REALM" <<'PY'
import json,sys,jwt
from jwt import PyJWKClient
d,iss=sys.argv[1],sys.argv[2]
t=json.load(open(f"{d}/tokens"))
jwks=json.load(open(f"{d}/jwks"))
hdr=jwt.get_unverified_header(t["access_token"])
key=[k for k in jwks["keys"] if k["kid"]==hdr["kid"]]
if not key: print("   FAIL kid not present in JWKS"); sys.exit(1)
pk=jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(key[0]))
c=jwt.decode(t["access_token"], pk, algorithms=[hdr["alg"]], options={"verify_aud":False}, issuer=iss)
print(f"   ok   access token signature VERIFIED (alg={hdr['alg']}, kid={hdr['kid'][:12]}…)")
print(f"   ok   issuer={c['iss']} sub={c['sub'][:8]}… preferred_username={c.get('preferred_username')}")
idc=jwt.decode(t["id_token"], pk, algorithms=[hdr["alg"]], options={"verify_aud":False}, issuer=iss)
print(f"   ok   id_token verified, aud={idc['aud']}")
print(f"   ok   refresh token present: {bool(t.get('refresh_token'))}")
PY
then
  :
else
  fail "signature verification"
fi

step "8. client-credentials grant (machine identity)"
kc_curl -sS -o "$_d/cc" -w '%{http_code}' -d grant_type=client_credentials -d "client_id=$CLIENT" \
  --data-urlencode "client_secret@$_d/csec" \
  "$KC/realms/$REALM/protocol/openid-connect/token" > "$_d/ccc"
[ "$(cat "$_d/ccc")" = 200 ] && ok "client-credentials token issued" || { fail "client-credentials http=$(cat "$_d/ccc")"; cat "$_d/cc" >&2; }

step "9. NEGATIVE: wrong client secret must be rejected"
printf 'not-the-secret' > "$_d/bad"
c=$(kc_curl -sS -o /dev/null -w '%{http_code}' -d grant_type=client_credentials -d "client_id=$CLIENT" \
  --data-urlencode "client_secret@$_d/bad" "$KC/realms/$REALM/protocol/openid-connect/token")
[ "$c" = 401 ] && ok "wrong secret denied (401)" || fail "wrong secret got http=$c, expected 401"

printf '\n'
if [ "$FAILED" -eq 0 ]; then echo "STEP 5: PASS"; trap - EXIT INT TERM; cleanup; exit 0
else echo "STEP 5: FAIL" >&2; trap - EXIT INT TERM; cleanup; exit 1; fi
