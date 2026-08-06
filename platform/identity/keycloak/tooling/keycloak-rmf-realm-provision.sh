#!/usr/bin/env bash
# Reconcile the application-specific RMF Web realm on the central Keycloak.
#
# Passwords arrive on inherited file descriptors rather than argv, the environment, or files:
#   fd 3 — central Keycloak master-realm administrator password
#   fd 4 — RMF Web built-in administrator password
# API bearer tokens and credential-bearing JSON remain in shell memory and are sent to curl on
# stdin or through an anonymous file descriptor. stdout is reserved for the signing public key.
set -Eeuo pipefail

case $- in *x*) set +x ;; esac

: "${KC_ORIGIN:?KC_ORIGIN is required}"
: "${KC_RESOLVE:?KC_RESOLVE is required}"
: "${KC_CONNECT:?KC_CONNECT is required}"
: "${KC_CACERT:?KC_CACERT is required}"
: "${KEYCLOAK_ADMIN_USERNAME:?KEYCLOAK_ADMIN_USERNAME is required}"
: "${RMF_WEB_ORIGIN:?RMF_WEB_ORIGIN is required}"
: "${RMF_REALM:=rmf-web}"

[[ "$RMF_WEB_ORIGIN" =~ ^https://[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?(:[0-9]{1,5})?$ ]] || {
  echo "ERROR: RMF_WEB_ORIGIN must be one canonical HTTPS origin with no path, query, wildcard, or trailing slash" >&2
  exit 2
}
[[ "$RMF_REALM" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || {
  echo "ERROR: RMF_REALM is not a safe realm name" >&2
  exit 2
}

KC_ADMIN_PASSWORD=$(cat <&3)
RMF_ADMIN_PASSWORD=$(cat <&4)
exec 3<&- 4<&-
[ -n "$KC_ADMIN_PASSWORD" ] || { echo "ERROR: central Keycloak admin password is empty" >&2; exit 2; }
[ -n "$RMF_ADMIN_PASSWORD" ] || { echo "ERROR: RMF Web admin password is empty" >&2; exit 2; }

ADMIN_TOKEN=''
API_BODY=''
API_CODE=''
CHANGES=0
KC_PUBLIC_ORIGIN=${KC_ORIGIN%:443}

clear_credentials() {
  unset KC_ADMIN_PASSWORD RMF_ADMIN_PASSWORD ADMIN_TOKEN API_BODY
}
trap clear_credentials EXIT INT TERM

log() { printf '%s\n' "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }
changed() { CHANGES=$((CHANGES + 1)); log "CHANGE: $*"; }
unchanged() { log "UNCHANGED: $*"; }

kc_curl() {
  curl --resolve "$KC_RESOLVE" --connect-to "$KC_CONNECT" --cacert "$KC_CACERT" "$@"
}

# api METHOD PATH [BODY]. BODY is a shell value, never a process argument; curl reads it on stdin.
api() {
  local method=$1 path=$2 body=${3-} raw
  if [ "$#" -eq 3 ]; then
    raw=$(printf '%s' "$body" | kc_curl -sS --config <(printf 'header = "Authorization: Bearer %s"\n' "$ADMIN_TOKEN") \
      -X "$method" -H 'Content-Type: application/json' --data-binary @- -w '\n%{http_code}' "$KC_ORIGIN$path") \
      || die "admin API transport failed for $method $path"
  else
    raw=$(kc_curl -sS --config <(printf 'header = "Authorization: Bearer %s"\n' "$ADMIN_TOKEN") \
      -X "$method" -w '\n%{http_code}' "$KC_ORIGIN$path") \
      || die "admin API transport failed for $method $path"
  fi
  API_CODE=${raw##*$'\n'}
  API_BODY=${raw%$'\n'*}
}

public_get() {
  local url=$1 raw
  raw=$(kc_curl -sS -w '\n%{http_code}' "$url") || die "public endpoint transport failed"
  API_CODE=${raw##*$'\n'}
  API_BODY=${raw%$'\n'*}
}

lookup_client() {
  local client_id=$1
  api GET "/admin/realms/$RMF_REALM/clients?clientId=$client_id"
  [ "$API_CODE" = 200 ] || die "client $client_id lookup returned HTTP $API_CODE"
  CLIENT_UUID=$(printf '%s' "$API_BODY" | jq -er --arg id "$client_id" \
    'map(select(.clientId == $id)) | if length == 1 then .[0].id else error("expected exactly one exact client match") end') \
    || die "client $client_id lookup was not unique"
}

log "Reconciling RMF Web realm $RMF_REALM for origin $RMF_WEB_ORIGIN"

token_response=$(printf '%s' "$KC_ADMIN_PASSWORD" | kc_curl -sS \
  -d client_id=admin-cli -d grant_type=password -d "username=$KEYCLOAK_ADMIN_USERNAME" \
  --data-urlencode password@- -w '\n%{http_code}' \
  "$KC_ORIGIN/realms/master/protocol/openid-connect/token") || die "admin authentication transport failed"
token_code=${token_response##*$'\n'}
token_body=${token_response%$'\n'*}
[ "$token_code" = 200 ] || die "central Keycloak admin authentication returned HTTP $token_code"
ADMIN_TOKEN=$(printf '%s' "$token_body" | jq -er .access_token) || die "admin token response had no access token"
unset KC_ADMIN_PASSWORD token_response token_body

# Realm: merge the two RMF-owned settings into the current representation so unrelated defaults
# and future realm policy remain intact.
api GET "/admin/realms/$RMF_REALM"
case "$API_CODE" in
  200)
    if printf '%s' "$API_BODY" | jq -e '.enabled == true and .ssoSessionMaxLifespan == 86400' >/dev/null; then
      unchanged "realm enabled=true, ssoSessionMaxLifespan=86400"
    else
      desired=$(printf '%s' "$API_BODY" | jq -c '.enabled=true | .ssoSessionMaxLifespan=86400')
      api PUT "/admin/realms/$RMF_REALM" "$desired"
      [ "$API_CODE" = 204 ] || die "realm update returned HTTP $API_CODE"
      changed "realm settings reconciled"
    fi
    ;;
  404)
    desired=$(jq -nc --arg realm "$RMF_REALM" '{realm:$realm,enabled:true,ssoSessionMaxLifespan:86400}')
    api POST /admin/realms "$desired"
    [ "$API_CODE" = 201 ] || die "realm creation returned HTTP $API_CODE"
    changed "realm created"
    ;;
  *) die "realm lookup returned HTTP $API_CODE" ;;
esac

# Browser client: the caller supplies one exact origin; the only wildcard is below that origin.
dashboard_desired=$(jq -nc --arg origin "$RMF_WEB_ORIGIN" \
  '{clientId:"dashboard",enabled:true,protocol:"openid-connect",publicClient:true,
    standardFlowEnabled:true,directAccessGrantsEnabled:true,serviceAccountsEnabled:false,
    rootUrl:$origin,redirectUris:[($origin+"/*")],webOrigins:[$origin]}')
api GET "/admin/realms/$RMF_REALM/clients?clientId=dashboard"
[ "$API_CODE" = 200 ] || die "dashboard client lookup returned HTTP $API_CODE"
dashboard_count=$(printf '%s' "$API_BODY" | jq '[.[] | select(.clientId == "dashboard")] | length')
case "$dashboard_count" in
  0)
    api POST "/admin/realms/$RMF_REALM/clients" "$dashboard_desired"
    [ "$API_CODE" = 201 ] || die "dashboard client creation returned HTTP $API_CODE"
    changed "dashboard client created"
    ;;
  1)
    dashboard_current=$(printf '%s' "$API_BODY" | jq -c '.[] | select(.clientId == "dashboard")')
    if printf '%s' "$dashboard_current" | jq -e --arg origin "$RMF_WEB_ORIGIN" \
      '.enabled == true and .protocol == "openid-connect" and .publicClient == true and
       .standardFlowEnabled == true and .directAccessGrantsEnabled == true and
       .serviceAccountsEnabled == false and .rootUrl == $origin and
       .redirectUris == [($origin+"/*")] and .webOrigins == [$origin]' >/dev/null; then
      unchanged "dashboard client"
    else
      desired=$(printf '%s' "$dashboard_current" | jq -c --argjson wanted "$dashboard_desired" '. * $wanted')
      dashboard_uuid=$(printf '%s' "$dashboard_current" | jq -er .id)
      api PUT "/admin/realms/$RMF_REALM/clients/$dashboard_uuid" "$desired"
      [ "$API_CODE" = 204 ] || die "dashboard client update returned HTTP $API_CODE"
      changed "dashboard client reconciled"
    fi
    ;;
  *) die "dashboard lookup returned $dashboard_count exact matches" ;;
esac
lookup_client dashboard
DASHBOARD_UUID=$CLIENT_UUID

smart_desired=$(jq -nc \
  '{clientId:"smart_cart",enabled:true,protocol:"openid-connect",publicClient:false,
    serviceAccountsEnabled:true,attributes:{"access.token.lifespan":"86400"}}')
api GET "/admin/realms/$RMF_REALM/clients?clientId=smart_cart"
[ "$API_CODE" = 200 ] || die "smart_cart client lookup returned HTTP $API_CODE"
smart_count=$(printf '%s' "$API_BODY" | jq '[.[] | select(.clientId == "smart_cart")] | length')
case "$smart_count" in
  0)
    api POST "/admin/realms/$RMF_REALM/clients" "$smart_desired"
    [ "$API_CODE" = 201 ] || die "smart_cart client creation returned HTTP $API_CODE"
    changed "smart_cart client created"
    ;;
  1)
    smart_current=$(printf '%s' "$API_BODY" | jq -c '.[] | select(.clientId == "smart_cart")')
    if printf '%s' "$smart_current" | jq -e \
      '.enabled == true and .protocol == "openid-connect" and .publicClient == false and
       .serviceAccountsEnabled == true and .attributes["access.token.lifespan"] == "86400"' >/dev/null; then
      unchanged "smart_cart client"
    else
      desired=$(printf '%s' "$smart_current" | jq -c --argjson wanted "$smart_desired" \
        '. * $wanted | .attributes = ((.attributes // {}) * $wanted.attributes)')
      smart_uuid=$(printf '%s' "$smart_current" | jq -er .id)
      api PUT "/admin/realms/$RMF_REALM/clients/$smart_uuid" "$desired"
      [ "$API_CODE" = 204 ] || die "smart_cart client update returned HTTP $API_CODE"
      changed "smart_cart client reconciled"
    fi
    ;;
  *) die "smart_cart lookup returned $smart_count exact matches" ;;
esac
lookup_client smart_cart
SMART_UUID=$CLIENT_UUID

# The service-account identity is generated by Keycloak when service accounts are enabled.
api GET "/admin/realms/$RMF_REALM/clients/$SMART_UUID/service-account-user"
[ "$API_CODE" = 200 ] || die "smart_cart service-account lookup returned HTTP $API_CODE"
SMART_SA_UUID=$(printf '%s' "$API_BODY" | jq -er 'select(.username == "service-account-smart_cart") | .id') \
  || die "smart_cart service-account user has the wrong identity"
lookup_client realm-management
REALM_MANAGEMENT_UUID=$CLIENT_UUID
api GET "/admin/realms/$RMF_REALM/clients/$REALM_MANAGEMENT_UUID/roles/view-users"
[ "$API_CODE" = 200 ] || die "realm-management view-users role lookup returned HTTP $API_CODE"
VIEW_USERS_ROLE=$API_BODY
api GET "/admin/realms/$RMF_REALM/users/$SMART_SA_UUID/role-mappings/clients/$REALM_MANAGEMENT_UUID"
[ "$API_CODE" = 200 ] || die "smart_cart role mapping lookup returned HTTP $API_CODE"
if printf '%s' "$API_BODY" | jq -e 'any(.[]; .name == "view-users")' >/dev/null; then
  unchanged "smart_cart service account has realm-management/view-users"
else
  role_array=$(printf '%s' "$VIEW_USERS_ROLE" | jq -c '[.]')
  api POST "/admin/realms/$RMF_REALM/users/$SMART_SA_UUID/role-mappings/clients/$REALM_MANAGEMENT_UUID" "$role_array"
  [ "$API_CODE" = 204 ] || die "view-users role assignment returned HTTP $API_CODE"
  changed "smart_cart service account granted realm-management/view-users"
fi

# RMF Web hardcodes builtin_admin=admin. It authenticates this user through dashboard, so a real
# password grant lets a rerun distinguish an unchanged credential from one that needs resetting.
#
# The profile fields are not cosmetic. This realm's user profile marks email, firstName and
# lastName as required for role `user`, so a username-only account authenticates with
# "invalid_grant: Account is not fully set up" — the password is accepted and the login still
# fails. That is the wall a human hits as the browser's "complete your profile" step; a
# service-owned account has nobody to complete it, so it is set here and the account is
# reproducible. emailVerified is asserted because nothing can deliver mail to this address.
RMF_ADMIN_EMAIL="admin@${RMF_WEB_ORIGIN#https://}"
admin_profile=$(jq -nc --arg email "$RMF_ADMIN_EMAIL" \
  '{username:"admin",enabled:true,emailVerified:true,firstName:"RMF",lastName:"Administrator",email:$email}')
api GET "/admin/realms/$RMF_REALM/users?username=admin&exact=true"
[ "$API_CODE" = 200 ] || die "RMF admin user lookup returned HTTP $API_CODE"
admin_count=$(printf '%s' "$API_BODY" | jq '[.[] | select(.username == "admin")] | length')
case "$admin_count" in
  0)
    api POST "/admin/realms/$RMF_REALM/users" "$admin_profile"
    [ "$API_CODE" = 201 ] || die "RMF admin user creation returned HTTP $API_CODE"
    changed "RMF admin user created, profile complete"
    ;;
  1)
    admin_current=$(printf '%s' "$API_BODY" | jq -c '.[] | select(.username == "admin")')
    if printf '%s' "$admin_current" | jq -e --argjson w "$admin_profile" \
        '(.enabled == $w.enabled) and (.emailVerified == $w.emailVerified)
         and (.firstName == $w.firstName) and (.lastName == $w.lastName) and (.email == $w.email)' \
        >/dev/null; then
      unchanged "RMF admin user enabled with a complete profile"
    else
      admin_uuid=$(printf '%s' "$admin_current" | jq -er .id)
      desired=$(printf '%s' "$admin_current" | jq -c --argjson w "$admin_profile" '. * $w')
      api PUT "/admin/realms/$RMF_REALM/users/$admin_uuid" "$desired"
      [ "$API_CODE" = 204 ] || die "RMF admin user profile update returned HTTP $API_CODE"
      changed "RMF admin user profile reconciled"
    fi
    ;;
  *) die "RMF admin user lookup returned $admin_count exact matches" ;;
esac
api GET "/admin/realms/$RMF_REALM/users?username=admin&exact=true"
RMF_ADMIN_UUID=$(printf '%s' "$API_BODY" | jq -er \
  'map(select(.username == "admin")) | if length == 1 then .[0].id else error("not unique") end') \
  || die "RMF admin user is not unique"

password_probe=$(printf '%s' "$RMF_ADMIN_PASSWORD" | kc_curl -sS \
  -d client_id=dashboard -d grant_type=password -d username=admin --data-urlencode password@- \
  -w '\n%{http_code}' "$KC_ORIGIN/realms/$RMF_REALM/protocol/openid-connect/token") \
  || die "RMF admin password probe transport failed"
password_probe_code=${password_probe##*$'\n'}
unset password_probe
case "$password_probe_code" in
  200) unchanged "RMF admin password already matches the application credential" ;;
  400|401)
    password_json=$(printf '%s' "$RMF_ADMIN_PASSWORD" | jq -Rsc '{type:"password",value:.,temporary:false}')
    api PUT "/admin/realms/$RMF_REALM/users/$RMF_ADMIN_UUID/reset-password" "$password_json"
    unset password_json
    [ "$API_CODE" = 204 ] || die "RMF admin password reset returned HTTP $API_CODE"
    changed "RMF admin password reconciled"
    ;;
  *) die "RMF admin password probe returned unexpected HTTP $password_probe_code" ;;
esac

# Client scope and audience mapper are reconciled independently; deleting the scope would change
# its UUID and momentarily detach it from both clients.
api GET "/admin/realms/$RMF_REALM/client-scopes"
[ "$API_CODE" = 200 ] || die "client-scope lookup returned HTTP $API_CODE"
scope_count=$(printf '%s' "$API_BODY" | jq '[.[] | select(.name == "dashboard")] | length')
case "$scope_count" in
  0)
    api POST "/admin/realms/$RMF_REALM/client-scopes" \
      '{"name":"dashboard","protocol":"openid-connect","description":"RMF dashboard audience"}'
    [ "$API_CODE" = 201 ] || die "dashboard client-scope creation returned HTTP $API_CODE"
    changed "dashboard client scope created"
    ;;
  1)
    scope_current=$(printf '%s' "$API_BODY" | jq -c '.[] | select(.name == "dashboard")')
    if printf '%s' "$scope_current" | jq -e '.protocol == "openid-connect"' >/dev/null; then
      unchanged "dashboard client scope"
    else
      scope_uuid=$(printf '%s' "$scope_current" | jq -er .id)
      desired=$(printf '%s' "$scope_current" | jq -c '.protocol="openid-connect"')
      api PUT "/admin/realms/$RMF_REALM/client-scopes/$scope_uuid" "$desired"
      [ "$API_CODE" = 204 ] || die "dashboard client-scope update returned HTTP $API_CODE"
      changed "dashboard client scope reconciled"
    fi
    ;;
  *) die "dashboard client-scope lookup returned $scope_count exact matches" ;;
esac
api GET "/admin/realms/$RMF_REALM/client-scopes"
DASHBOARD_SCOPE_UUID=$(printf '%s' "$API_BODY" | jq -er \
  'map(select(.name == "dashboard")) | if length == 1 then .[0].id else error("not unique") end') \
  || die "dashboard client scope is not unique"

mapper_desired='{"name":"rmf-audience","protocol":"openid-connect","protocolMapper":"oidc-audience-mapper","config":{"included.client.audience":"dashboard","access.token.claim":"true","id.token.claim":"false"}}'
api GET "/admin/realms/$RMF_REALM/client-scopes/$DASHBOARD_SCOPE_UUID/protocol-mappers/models"
[ "$API_CODE" = 200 ] || die "audience mapper lookup returned HTTP $API_CODE"
mapper_count=$(printf '%s' "$API_BODY" | jq '[.[] | select(.name == "rmf-audience")] | length')
case "$mapper_count" in
  0)
    api POST "/admin/realms/$RMF_REALM/client-scopes/$DASHBOARD_SCOPE_UUID/protocol-mappers/models" "$mapper_desired"
    [ "$API_CODE" = 201 ] || die "audience mapper creation returned HTTP $API_CODE"
    changed "rmf-audience mapper created"
    ;;
  1)
    mapper_current=$(printf '%s' "$API_BODY" | jq -c '.[] | select(.name == "rmf-audience")')
    if printf '%s' "$mapper_current" | jq -e \
      '.protocol == "openid-connect" and .protocolMapper == "oidc-audience-mapper" and
       .config["included.client.audience"] == "dashboard" and
       .config["access.token.claim"] == "true" and .config["id.token.claim"] == "false"' >/dev/null; then
      unchanged "rmf-audience mapper"
    else
      mapper_uuid=$(printf '%s' "$mapper_current" | jq -er .id)
      if printf '%s' "$mapper_current" | jq -e '.protocolMapper == "oidc-audience-mapper"' >/dev/null; then
        desired=$(printf '%s' "$mapper_current" | jq -c --argjson wanted "$mapper_desired" '. * $wanted')
        api PUT "/admin/realms/$RMF_REALM/client-scopes/$DASHBOARD_SCOPE_UUID/protocol-mappers/models/$mapper_uuid" "$desired"
        [ "$API_CODE" = 204 ] || die "audience mapper update returned HTTP $API_CODE"
        changed "rmf-audience mapper reconciled"
      else
        api DELETE "/admin/realms/$RMF_REALM/client-scopes/$DASHBOARD_SCOPE_UUID/protocol-mappers/models/$mapper_uuid"
        [ "$API_CODE" = 204 ] || die "wrong-type audience mapper deletion returned HTTP $API_CODE"
        api POST "/admin/realms/$RMF_REALM/client-scopes/$DASHBOARD_SCOPE_UUID/protocol-mappers/models" "$mapper_desired"
        [ "$API_CODE" = 201 ] || die "audience mapper recreation returned HTTP $API_CODE"
        changed "wrong-type rmf-audience mapper replaced"
      fi
    fi
    ;;
  *) die "audience mapper lookup returned $mapper_count exact matches" ;;
esac

for client_pair in "dashboard:$DASHBOARD_UUID" "smart_cart:$SMART_UUID"; do
  client_name=${client_pair%%:*}
  client_uuid=${client_pair#*:}
  api GET "/admin/realms/$RMF_REALM/clients/$client_uuid/default-client-scopes"
  [ "$API_CODE" = 200 ] || die "$client_name default-scope lookup returned HTTP $API_CODE"
  if printf '%s' "$API_BODY" | jq -e --arg id "$DASHBOARD_SCOPE_UUID" 'any(.[]; .id == $id)' >/dev/null; then
    unchanged "$client_name has dashboard as a default client scope"
  else
    api PUT "/admin/realms/$RMF_REALM/clients/$client_uuid/default-client-scopes/$DASHBOARD_SCOPE_UUID"
    [ "$API_CODE" = 204 ] || die "$client_name default-scope assignment returned HTTP $API_CODE"
    changed "$client_name assigned dashboard as a default client scope"
  fi
done

# Re-read the acceptance-critical Admin API representations and parse every assertion structurally.
api GET "/admin/realms/$RMF_REALM"
[ "$API_CODE" = 200 ] && printf '%s' "$API_BODY" | jq -e \
  '.enabled == true and .ssoSessionMaxLifespan == 86400' >/dev/null || die "realm verification failed"
lookup_client dashboard
api GET "/admin/realms/$RMF_REALM/clients/$CLIENT_UUID"
printf '%s' "$API_BODY" | jq -e --arg origin "$RMF_WEB_ORIGIN" \
  '.publicClient == true and .serviceAccountsEnabled == false and .rootUrl == $origin and
   .redirectUris == [($origin+"/*")] and .webOrigins == [$origin]' >/dev/null || die "dashboard verification failed"
lookup_client smart_cart
api GET "/admin/realms/$RMF_REALM/clients/$CLIENT_UUID"
printf '%s' "$API_BODY" | jq -e \
  '.publicClient == false and .serviceAccountsEnabled == true and
   .attributes["access.token.lifespan"] == "86400"' >/dev/null || die "smart_cart verification failed"
api GET "/admin/realms/$RMF_REALM/client-scopes/$DASHBOARD_SCOPE_UUID/protocol-mappers/models"
printf '%s' "$API_BODY" | jq -e \
  '[.[] | select(.name == "rmf-audience" and .protocolMapper == "oidc-audience-mapper" and
    .config["included.client.audience"] == "dashboard" and
    .config["access.token.claim"] == "true" and .config["id.token.claim"] == "false")] | length == 1' \
  >/dev/null || die "audience mapper verification failed"
for client_pair in "dashboard:$DASHBOARD_UUID" "smart_cart:$SMART_UUID"; do
  client_name=${client_pair%%:*}; client_uuid=${client_pair#*:}
  api GET "/admin/realms/$RMF_REALM/clients/$client_uuid/default-client-scopes"
  printf '%s' "$API_BODY" | jq -e --arg id "$DASHBOARD_SCOPE_UUID" 'any(.[]; .id == $id)' >/dev/null \
    || die "$client_name default client-scope verification failed"
done
api GET "/admin/realms/$RMF_REALM/users/$SMART_SA_UUID/role-mappings/clients/$REALM_MANAGEMENT_UUID"
printf '%s' "$API_BODY" | jq -e 'any(.[]; .name == "view-users")' >/dev/null \
  || die "smart_cart view-users verification failed"
log "ASSERT: Admin API realm, clients, audience mapper, default scopes, and view-users mapping match"

# Discover the real token endpoint, use it for a real password grant, and inspect the resulting JWT.
public_get "$KC_ORIGIN/realms/$RMF_REALM/.well-known/openid-configuration"
[ "$API_CODE" = 200 ] || die "RMF discovery returned HTTP $API_CODE"
TOKEN_ENDPOINT=$(printf '%s' "$API_BODY" | jq -er .token_endpoint) || die "discovery has no token endpoint"
JWKS_URI=$(printf '%s' "$API_BODY" | jq -er .jwks_uri) || die "discovery has no JWKS URI"
DISCOVERY_ISSUER=$(printf '%s' "$API_BODY" | jq -er .issuer) || die "discovery has no issuer"
expected_issuer="$KC_PUBLIC_ORIGIN/realms/$RMF_REALM"
[ "$DISCOVERY_ISSUER" = "$expected_issuer" ] || die "discovery issuer does not match the canonical RMF realm"
expected_token_endpoint="$KC_PUBLIC_ORIGIN/realms/$RMF_REALM/protocol/openid-connect/token"
[ "$TOKEN_ENDPOINT" = "$expected_token_endpoint" ] || die "discovery token endpoint does not match the canonical RMF realm"
token_response=$(printf '%s' "$RMF_ADMIN_PASSWORD" | kc_curl -sS \
  -d client_id=dashboard -d grant_type=password -d username=admin --data-urlencode password@- \
  -w '\n%{http_code}' "$TOKEN_ENDPOINT") || die "dashboard token transport failed"
token_code=${token_response##*$'\n'}
token_body=${token_response%$'\n'*}
[ "$token_code" = 200 ] || die "dashboard token request returned HTTP $token_code"
DASHBOARD_TOKEN=$(printf '%s' "$token_body" | jq -er .access_token) || die "dashboard token response had no access token"
unset RMF_ADMIN_PASSWORD token_response token_body
jwt_header=${DASHBOARD_TOKEN%%.*}
case $((${#jwt_header} % 4)) in 2) jwt_header+='==' ;; 3) jwt_header+='=' ;; 1) die "invalid JWT header length" ;; esac
jwt_header_json=$(printf '%s' "$jwt_header" | tr '_-' '/+' | base64 -d) || die "dashboard JWT header is not base64url"
TOKEN_KID=$(printf '%s' "$jwt_header_json" | jq -er .kid) || die "dashboard JWT header has no signing kid"
unset jwt_header jwt_header_json
jwt_payload=${DASHBOARD_TOKEN#*.}; jwt_payload=${jwt_payload%%.*}
unset DASHBOARD_TOKEN
case $((${#jwt_payload} % 4)) in 2) jwt_payload+='==' ;; 3) jwt_payload+='=' ;; 1) die "invalid JWT payload length" ;; esac
jwt_claims=$(printf '%s' "$jwt_payload" | tr '_-' '/+' | base64 -d) || die "dashboard JWT payload is not base64url"
unset jwt_payload
printf '%s' "$jwt_claims" | jq -e '.aud as $aud | if ($aud|type) == "array" then any($aud[]; . == "dashboard") else $aud == "dashboard" end' \
  >/dev/null || die "dashboard access token lacks aud=dashboard"
observed_aud=$(printf '%s' "$jwt_claims" | jq -c .aud)
unset jwt_claims
log "ASSERT: discovery token endpoint issued dashboard access token with aud=$observed_aud"

# The signing certificate and derived public key are public data. stdout remains exactly this PEM.
public_get "$JWKS_URI"
[ "$API_CODE" = 200 ] || die "RMF JWKS returned HTTP $API_CODE"
SIGNING_X5C=$(printf '%s' "$API_BODY" | jq -er --arg kid "$TOKEN_KID" \
  '[.keys[] | select(.kid == $kid and .use == "sig" and (.x5c | length > 0))] |
   if length == 1 then .[0].x5c[0] else error("token signing kid did not resolve uniquely") end') \
  || die "JWKS has no unique signing certificate for the dashboard token kid"
PUBLIC_KEY=$(printf '%s\n%s\n%s\n' '-----BEGIN CERTIFICATE-----' "$SIGNING_X5C" '-----END CERTIFICATE-----' \
  | openssl x509 -pubkey -noout) || die "signing certificate did not yield a public key"
printf '%s\n' "$PUBLIC_KEY" | openssl pkey -pubin -noout >/dev/null \
  || die "derived signing public key did not parse"

if [ "$CHANGES" -eq 0 ]; then
  log "RESULT: PASS — no changes; RMF Web realm is already reconciled"
else
  log "RESULT: PASS — $CHANGES change(s); RMF Web realm reconciled"
fi
printf '%s\n' "$PUBLIC_KEY"
