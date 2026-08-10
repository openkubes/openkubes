#!/usr/bin/env bash
set -Eeuo pipefail
case $- in *x*) set +x ;; esac

: "${KC_ORIGIN:?KC_ORIGIN is required}"
: "${KC_RESOLVE:?KC_RESOLVE is required}"
: "${KC_CACERT:?KC_CACERT is required}"
: "${KEYCLOAK_ADMIN_USERNAME:?KEYCLOAK_ADMIN_USERNAME is required}"
: "${PLATFORM_REALM:=openkubes}"
: "${CLIENT_ID:=registry-default}"
: "${REDIRECT_URI:?REDIRECT_URI is required}"
: "${REGISTRY_ORIGIN:?REGISTRY_ORIGIN is required}"
: "${WRITER_GROUP:=registry-writers}"
: "${READER_GROUP:=registry-readers}"
: "${KUBECTL:=kubectl}"
: "${KUBECONFIG:?KUBECONFIG is required}"
: "${NAMESPACE:=zot}"
: "${OIDC_SECRET:=zot-oidc}"

admin_password=$(cat <&3)
writer_password=$(cat <&4)
reader_password=$(cat <&5)
exec 3<&- 4<&- 5<&-
[ -n "$admin_password" ] && [ -n "$writer_password" ] && [ -n "$reader_password" ] || {
  echo "ERROR: an inherited credential descriptor was empty" >&2; exit 2;
}

token=''
body=''
code=''
cleanup() { unset admin_password writer_password reader_password token body client_secret; }
trap cleanup EXIT INT TERM
die() { echo "ERROR: $*" >&2; exit 1; }

kc_curl() {
  curl --resolve "$KC_RESOLVE" --cacert "$KC_CACERT" "$@"
}

api() {
  local method=$1 path=$2 payload=${3-} raw
  if [ "$#" -eq 3 ]; then
    raw=$(printf '%s' "$payload" | kc_curl -sS --config <(printf 'header = "Authorization: Bearer %s"\n' "$token") \
      -X "$method" -H 'Content-Type: application/json' --data-binary @- -w '\n%{http_code}' "$KC_ORIGIN$path") || die "$method $path transport failed"
  else
    raw=$(kc_curl -sS --config <(printf 'header = "Authorization: Bearer %s"\n' "$token") \
      -X "$method" -w '\n%{http_code}' "$KC_ORIGIN$path") || die "$method $path transport failed"
  fi
  code=${raw##*$'\n'}
  body=${raw%$'\n'*}
}

raw=$(printf '%s' "$admin_password" | kc_curl -sS -d client_id=admin-cli -d grant_type=password \
  -d "username=$KEYCLOAK_ADMIN_USERNAME" --data-urlencode password@- -w '\n%{http_code}' \
  "$KC_ORIGIN/realms/master/protocol/openid-connect/token") || die "admin authentication transport failed"
code=${raw##*$'\n'}; body=${raw%$'\n'*}
[ "$code" = 200 ] || die "admin authentication returned HTTP $code"
token=$(printf '%s' "$body" | jq -er .access_token) || die "admin token missing"
unset admin_password raw body

reconcile_group() {
  local name=$1 count gid payload
  api GET "/admin/realms/$PLATFORM_REALM/groups?search=$name&exact=true"
  [ "$code" = 200 ] || die "group $name lookup returned HTTP $code"
  count=$(printf '%s' "$body" | jq --arg n "$name" '[.[]|select(.name==$n)]|length')
  if [ "$count" = 0 ]; then
    payload=$(jq -nc --arg n "$name" '{name:$n}')
    api POST "/admin/realms/$PLATFORM_REALM/groups" "$payload"
    [ "$code" = 201 ] || die "group $name creation returned HTTP $code"
    api GET "/admin/realms/$PLATFORM_REALM/groups?search=$name&exact=true"
  elif [ "$count" != 1 ]; then
    die "group $name lookup returned $count exact matches"
  fi
  gid=$(printf '%s' "$body" | jq -er --arg n "$name" '.[]|select(.name==$n)|.id') || die "group $name id missing"
  printf '%s' "$gid"
}

writer_gid=$(reconcile_group "$WRITER_GROUP")
reader_gid=$(reconcile_group "$READER_GROUP")

desired=$(jq -nc --arg id "$CLIENT_ID" --arg origin "$REGISTRY_ORIGIN" --arg redirect "$REDIRECT_URI" \
  '{clientId:$id,name:"registry-default (zot)",enabled:true,protocol:"openid-connect",publicClient:false,
    standardFlowEnabled:true,directAccessGrantsEnabled:true,serviceAccountsEnabled:false,
    rootUrl:$origin,baseUrl:$origin,redirectUris:[$redirect],webOrigins:[$origin]}')
api GET "/admin/realms/$PLATFORM_REALM/clients?clientId=$CLIENT_ID"
[ "$code" = 200 ] || die "client lookup returned HTTP $code"
count=$(printf '%s' "$body" | jq --arg id "$CLIENT_ID" '[.[]|select(.clientId==$id)]|length')
if [ "$count" = 0 ]; then
  api POST "/admin/realms/$PLATFORM_REALM/clients" "$desired"
  [ "$code" = 201 ] || die "client creation returned HTTP $code"
  api GET "/admin/realms/$PLATFORM_REALM/clients?clientId=$CLIENT_ID"
elif [ "$count" = 1 ]; then
  current=$(printf '%s' "$body" | jq -c --arg id "$CLIENT_ID" '.[]|select(.clientId==$id)')
  client_uuid=$(printf '%s' "$current" | jq -er .id)
  merged=$(printf '%s' "$current" | jq -c --argjson wanted "$desired" '. * $wanted')
  api PUT "/admin/realms/$PLATFORM_REALM/clients/$client_uuid" "$merged"
  [ "$code" = 204 ] || die "client update returned HTTP $code"
  api GET "/admin/realms/$PLATFORM_REALM/clients?clientId=$CLIENT_ID"
else
  die "client lookup returned $count exact matches"
fi
client_uuid=$(printf '%s' "$body" | jq -er --arg id "$CLIENT_ID" '.[]|select(.clientId==$id)|.id') || die "client id missing"

mapper_name=registry-groups
mapper=$(jq -nc --arg name "$mapper_name" \
  '{name:$name,protocol:"openid-connect",protocolMapper:"oidc-group-membership-mapper",
    consentRequired:false,config:{"full.path":"false","id.token.claim":"true","access.token.claim":"true",
      "userinfo.token.claim":"true","claim.name":"groups","jsonType.label":"String","multivalued":"true"}}')
api GET "/admin/realms/$PLATFORM_REALM/clients/$client_uuid/protocol-mappers/models"
[ "$code" = 200 ] || die "mapper lookup returned HTTP $code"
mapper_count=$(printf '%s' "$body" | jq --arg n "$mapper_name" '[.[]|select(.name==$n)]|length')
if [ "$mapper_count" = 0 ]; then
  api POST "/admin/realms/$PLATFORM_REALM/clients/$client_uuid/protocol-mappers/models" "$mapper"
  [ "$code" = 201 ] || die "groups mapper creation returned HTTP $code"
elif [ "$mapper_count" = 1 ]; then
  mapper_id=$(printf '%s' "$body" | jq -er --arg n "$mapper_name" '.[]|select(.name==$n)|.id')
  mapper=$(printf '%s' "$mapper" | jq -c --arg id "$mapper_id" '.id=$id')
  api PUT "/admin/realms/$PLATFORM_REALM/clients/$client_uuid/protocol-mappers/models/$mapper_id" "$mapper"
  [ "$code" = 204 ] || die "groups mapper update returned HTTP $code"
else
  die "groups mapper lookup returned $mapper_count exact matches"
fi

reconcile_user() {
  local username=$1 password=$2 gid=$3 email payload uid memberships
  email="$username@openkubes.internal"
  api GET "/admin/realms/$PLATFORM_REALM/users?username=$username&exact=true"
  [ "$code" = 200 ] || die "user $username lookup returned HTTP $code"
  count=$(printf '%s' "$body" | jq --arg u "$username" '[.[]|select(.username==$u)]|length')
  if [ "$count" = 0 ]; then
    payload=$(jq -nc --arg u "$username" --arg e "$email" \
      '{username:$u,email:$e,firstName:"Zot",lastName:"Conformance",emailVerified:true,enabled:true}')
    api POST "/admin/realms/$PLATFORM_REALM/users" "$payload"
    [ "$code" = 201 ] || die "user $username creation returned HTTP $code"
    api GET "/admin/realms/$PLATFORM_REALM/users?username=$username&exact=true"
  elif [ "$count" != 1 ]; then
    die "user $username lookup returned $count exact matches"
  fi
  uid=$(printf '%s' "$body" | jq -er --arg u "$username" '.[]|select(.username==$u)|.id')
  payload=$(printf '%s' "$password" | jq -Rsc '{type:"password",temporary:false,value:.}')
  api PUT "/admin/realms/$PLATFORM_REALM/users/$uid/reset-password" "$payload"
  [ "$code" = 204 ] || die "user $username password reset returned HTTP $code"
  unset payload
  api GET "/admin/realms/$PLATFORM_REALM/users/$uid/groups"
  [ "$code" = 200 ] || die "user $username group lookup returned HTTP $code"
  memberships=$body
  if ! printf '%s' "$memberships" | jq -e --arg id "$gid" 'any(.[];.id==$id)' >/dev/null; then
    api PUT "/admin/realms/$PLATFORM_REALM/users/$uid/groups/$gid"
    [ "$code" = 204 ] || die "user $username group join returned HTTP $code"
  fi
}

writer_user=zot-writer
reader_user=zot-reader
reconcile_user "$writer_user" "$writer_password" "$writer_gid"
reconcile_user "$reader_user" "$reader_password" "$reader_gid"

api GET "/admin/realms/$PLATFORM_REALM/clients/$client_uuid/client-secret"
[ "$code" = 200 ] || die "client secret read returned HTTP $code"
client_secret=$(printf '%s' "$body" | jq -er .value) || die "client secret missing"

token_response=$(printf '%s' "$writer_password" | kc_curl -sS \
  --config <(printf 'data-urlencode = "client_secret=%s"\n' "$client_secret") \
  -d "client_id=$CLIENT_ID" -d grant_type=password -d "username=$writer_user" \
  --data-urlencode password@- -w '\n%{http_code}' \
  "$KC_ORIGIN/realms/$PLATFORM_REALM/protocol/openid-connect/token") || die "writer token transport failed"
code=${token_response##*$'\n'}; body=${token_response%$'\n'*}
[ "$code" = 200 ] || die "writer token returned HTTP $code"
access_token=$(printf '%s' "$body" | jq -er .access_token) || die "writer access token missing"
claims=$(printf '%s' "$access_token" | cut -d. -f2 | tr '_-' '/+' | awk '{l=length($0)%4; if(l==2)$0=$0"=="; else if(l==3)$0=$0"="; print}' | base64 -d 2>/dev/null)
printf '%s' "$claims" | jq -e --arg g "$WRITER_GROUP" '.groups|index($g)!=null' >/dev/null || die "issued writer token has no $WRITER_GROUP groups claim"
printf 'TOKEN_CLAIMS: '
printf '%s' "$claims" | jq -c '{preferred_username,groups}'
unset access_token token_response claims

if "$KUBECTL" --kubeconfig "$KUBECONFIG" get secret "$OIDC_SECRET" -n "$NAMESPACE" >/dev/null 2>&1; then
  session_keys=$("$KUBECTL" --kubeconfig "$KUBECONFIG" get secret "$OIDC_SECRET" -n "$NAMESPACE" -o jsonpath='{.data.session-keys\.json}' | base64 -d)
  printf '%s' "$session_keys" | jq -e '.hashKey and .encryptKey' >/dev/null || die "existing session keys are invalid"
else
  hash_key=$(openssl rand -base64 48 | tr -d '\n' | cut -c1-64)
  encrypt_key=$(openssl rand -base64 24 | tr -d '\n' | cut -c1-32)
  session_keys=$(printf '{"hashKey":"%s","encryptKey":"%s"}' "$hash_key" "$encrypt_key")
  unset hash_key encrypt_key
fi
credentials=$(printf '{"clientid":"%s","clientsecret":"%s"}' "$CLIENT_ID" "$client_secret")
{
  printf 'apiVersion: v1\nkind: Secret\nmetadata:\n  name: %s\n  namespace: %s\ntype: Opaque\ndata:\n' "$OIDC_SECRET" "$NAMESPACE"
  printf '  credentials.json: %s\n' "$(printf '%s' "$credentials" | base64 | tr -d '\n')"
  printf '  session-keys.json: %s\n' "$(printf '%s' "$session_keys" | base64 | tr -d '\n')"
} | "$KUBECTL" --kubeconfig "$KUBECONFIG" apply -f - >/dev/null
unset client_secret credentials session_keys writer_password reader_password
echo "RESULT: PASS — central client, groups mapper, profile groups, users, issued groups claim, and namespace Secret reconciled"
