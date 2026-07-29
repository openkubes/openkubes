#!/usr/bin/env bash
# OK-115 acceptance test — authenticate only as the dedicated owner seeding
# ServiceAccount, prove create+update in its derived KV v2 subtree, and prove
# real API operations are denied everywhere else. No break-glass token is used.
#
# The positive probe uses CAS=0 as an atomic pre-existence guard, then CAS=1 to
# prove update. A write-only identity cannot remove the resulting value; the
# trap reports the exact path for a separately authorised metadata-delete step.
# Delete is deliberately not granted merely to make this test self-cleaning.
set -Eeuo pipefail

usage() {
  cat <<'EOF'
Usage:
  ok115-scoped-seed-test.sh \
    --consumer-kubeconfig PATH --shared-kubeconfig PATH \
    --cluster DNS_LABEL --app DNS_LABEL --role DNS_LABEL \
    --service-account DNS_LABEL --namespace DNS_LABEL \
    [--max-ttl-seconds 600] [--vault-pod vault-0]

The consumer kubeconfig is used only to mint a bounded token for the dedicated
seeding ServiceAccount. The shared kubeconfig execs the Vault CLI in the Vault
pod. JWTs and Vault tokens travel over stdin and never in process arguments.
The Kubernetes TokenRequest duration is fixed at its 600-second API minimum;
--max-ttl-seconds controls the independently bounded Vault token lease.
EOF
}

CONSUMER_KUBECONFIG=
SHARED_KUBECONFIG=
CLUSTER=
APP=
ROLE=
SERVICE_ACCOUNT=
SERVICE_ACCOUNT_NAMESPACE=
MAX_TTL_SECONDS=600
KUBERNETES_TOKEN_SECONDS=600
VAULT_POD=vault-0
VAULT_NAMESPACE=vault

while (($#)); do
  case "$1" in
    --consumer-kubeconfig) CONSUMER_KUBECONFIG="${2:?missing value}"; shift 2 ;;
    --shared-kubeconfig) SHARED_KUBECONFIG="${2:?missing value}"; shift 2 ;;
    --cluster) CLUSTER="${2:?missing value}"; shift 2 ;;
    --app) APP="${2:?missing value}"; shift 2 ;;
    --role) ROLE="${2:?missing value}"; shift 2 ;;
    --service-account) SERVICE_ACCOUNT="${2:?missing value}"; shift 2 ;;
    --namespace) SERVICE_ACCOUNT_NAMESPACE="${2:?missing value}"; shift 2 ;;
    --max-ttl-seconds) MAX_TTL_SECONDS="${2:?missing value}"; shift 2 ;;
    --vault-pod) VAULT_POD="${2:?missing value}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: unknown argument '$1'" >&2; usage >&2; exit 2 ;;
  esac
done

for required in CONSUMER_KUBECONFIG SHARED_KUBECONFIG CLUSTER APP ROLE SERVICE_ACCOUNT SERVICE_ACCOUNT_NAMESPACE; do
  [[ -n "${!required}" ]] || { echo "ERROR: --$(tr '[:upper:]_' '[:lower:]-' <<<"$required") is required" >&2; exit 2; }
done
[[ "$MAX_TTL_SECONDS" =~ ^[0-9]+$ ]] && ((MAX_TTL_SECONDS >= 60 && MAX_TTL_SECONDS <= 600)) \
  || { echo "ERROR: --max-ttl-seconds must be 60..600" >&2; exit 2; }

DNS_LABEL_RE='^[a-z0-9]([-a-z0-9]*[a-z0-9])?$'
for value_name in CLUSTER APP ROLE SERVICE_ACCOUNT SERVICE_ACCOUNT_NAMESPACE; do
  value="${!value_name}"
  [[ ${#value} -le 63 && "$value" =~ $DNS_LABEL_RE ]] \
    || { echo "ERROR: $value_name must be a DNS label (1..63 characters)" >&2; exit 2; }
done
for command in kubectl jq grep; do
  command -v "$command" >/dev/null || { echo "ERROR: required command '$command' not found" >&2; exit 1; }
done
[[ -r "$CONSUMER_KUBECONFIG" ]] || { echo "ERROR: cannot read consumer kubeconfig" >&2; exit 1; }
[[ -r "$SHARED_KUBECONFIG" ]] || { echo "ERROR: cannot read shared kubeconfig" >&2; exit 1; }

EXPECTED_POLICY="okvc-${CLUSTER}-${APP}-seed"
NONCE="$(tr -d '-' </proc/sys/kernel/random/uuid | cut -c1-12)"
PROBE_NAME="ok115-probe-${NONCE}"
PROBE_PATH="secret/${CLUSTER}/${APP}/${PROBE_NAME}"
OTHER_APP_PATH="secret/${CLUSTER}/ok115-other-app-${NONCE}/probe"
OTHER_CLUSTER_PATH="secret/ok115-other-cluster-${NONCE}/${APP}/probe"
ROLE_PROBE="ok115-role-${NONCE}"
USER_PROBE="ok115-user-${NONCE}"
ENTITY_PROBE="$(tr -d '\n' </proc/sys/kernel/random/uuid)"
FAILS=0
CLEANUP_PATHS=()
SEED_TOKEN=
SA_JWT=

# The token is delivered as the first stdin line, stripped inside the pod, and
# exported only for the lifetime of the Vault CLI process.
vault_as_seed() {
  { printf '%s\n' "$SEED_TOKEN"; } |
    kubectl --kubeconfig "$SHARED_KUBECONFIG" -n "$VAULT_NAMESPACE" exec -i "$VAULT_POD" -- \
      sh -c 'set -eu; IFS= read -r VAULT_TOKEN; export VAULT_TOKEN; exec "$@"' sh "$@"
}

vault_as_seed_input() {
  local input="$1"
  shift
  { printf '%s\n' "$SEED_TOKEN"; printf '%s' "$input"; } |
    kubectl --kubeconfig "$SHARED_KUBECONFIG" -n "$VAULT_NAMESPACE" exec -i "$VAULT_POD" -- \
      sh -c 'set -eu; IFS= read -r VAULT_TOKEN; export VAULT_TOKEN; exec "$@"' sh "$@"
}

cleanup() {
  local rc=$?
  trap - EXIT ERR
  set +e
  if ((${#CLEANUP_PATHS[@]})); then
    printf '\nCLEANUP REQUIRED (separately authorised; not granted to the seeder):\n' >&2
    for path in "${CLEANUP_PATHS[@]}"; do
      printf '  vault kv metadata delete %s\n' "$path" >&2
    done
  fi
  if [[ -n "$SEED_TOKEN" ]]; then
    # tokenNoDefaultPolicy removes auth/token/revoke-self too. Try, but rely on
    # the role's <=10-minute explicit max TTL if Vault correctly denies it.
    vault_as_seed vault token revoke -self >/dev/null 2>&1
  fi
  unset SA_JWT SEED_TOKEN
  exit "$rc"
}
trap cleanup EXIT
trap 'rc=$?; printf "ABORT: rc=%s at line %s\n" "$rc" "$LINENO" >&2; exit "$rc"' ERR

denial_signature() {
  grep -qiE 'permission denied|code: 403|response code: 403|errors:[[:space:]]*permission denied' <<<"$1"
}

expect_denied() {
  local label="$1" out
  shift
  if out="$(vault_as_seed "$@" 2>&1)"; then
    printf 'NEG FAIL %-42s ALLOWED\n' "$label" >&2
    FAILS=$((FAILS + 1))
  elif denial_signature "$out"; then
    printf 'NEG ok   %-42s denied\n' "$label"
  else
    printf 'NEG FAIL %-42s non-permission failure: %s\n' "$label" "$out" >&2
    FAILS=$((FAILS + 1))
  fi
}

expect_denied_input() {
  local label="$1" input="$2" cleanup_path="$3" out
  shift 3
  if out="$(vault_as_seed_input "$input" "$@" 2>&1)"; then
    printf 'NEG FAIL %-42s ALLOWED\n' "$label" >&2
    CLEANUP_PATHS+=("$cleanup_path")
    FAILS=$((FAILS + 1))
  elif denial_signature "$out"; then
    printf 'NEG ok   %-42s denied\n' "$label"
  else
    printf 'NEG FAIL %-42s non-permission failure: %s\n' "$label" "$out" >&2
    FAILS=$((FAILS + 1))
  fi
}

echo "Minting a ${KUBERNETES_TOKEN_SECONDS}s Kubernetes token for ${SERVICE_ACCOUNT_NAMESPACE}/${SERVICE_ACCOUNT} (Vault TTL ceiling: ${MAX_TTL_SECONDS}s)..."
if ! SA_JWT="$(kubectl --kubeconfig "$CONSUMER_KUBECONFIG" -n "$SERVICE_ACCOUNT_NAMESPACE" \
  create token "$SERVICE_ACCOUNT" --duration="${KUBERNETES_TOKEN_SECONDS}s")"; then
  echo "ERROR: Kubernetes TokenRequest failed; no ServiceAccount token was minted" >&2
  exit 1
fi
[[ -n "$SA_JWT" ]] \
  || { echo "ERROR: Kubernetes TokenRequest succeeded but returned an empty ServiceAccount token" >&2; exit 1; }

# jwt=- makes the Vault CLI read the credential from stdin; neither JWT nor
# resulting Vault token appears in argv or output.
LOGIN_JSON="$(
  printf '%s' "$SA_JWT" |
    kubectl --kubeconfig "$SHARED_KUBECONFIG" -n "$VAULT_NAMESPACE" exec -i "$VAULT_POD" -- \
      vault write -format=json "auth/kubernetes/${CLUSTER}/login" role="$ROLE" jwt=-
)"
unset SA_JWT
SEED_TOKEN="$(jq -er '.auth.client_token' <<<"$LOGIN_JSON")"
LEASE_SECONDS="$(jq -er '.auth.lease_duration' <<<"$LOGIN_JSON")"
POLICIES="$(jq -er '.auth.policies | sort | join(",")' <<<"$LOGIN_JSON")"
unset LOGIN_JSON

[[ "$POLICIES" == "$EXPECTED_POLICY" ]] \
  || { echo "ERROR: token policies '$POLICIES', expected only '$EXPECTED_POLICY' (no default policy)" >&2; exit 1; }
((LEASE_SECONDS > 0 && LEASE_SECONDS <= MAX_TTL_SECONDS)) \
  || { echo "ERROR: token lease ${LEASE_SECONDS}s exceeds ${MAX_TTL_SECONDS}s ceiling" >&2; exit 1; }
printf 'AUTH ok   policies=[%s] ttl=%ss (ceiling=%ss)\n' "$POLICIES" "$LEASE_SECONDS" "$MAX_TTL_SECONDS"

echo
echo "POSITIVE — create then update inside the derived cluster/app subtree"
CREATE_JSON="$(vault_as_seed_input "first-${NONCE}" vault kv put -format=json -cas=0 "$PROBE_PATH" marker=-)"
jq -e '.data.version == 1' <<<"$CREATE_JSON" >/dev/null \
  || { echo "ERROR: CAS=0 write did not create version 1" >&2; exit 1; }
CLEANUP_PATHS+=("$PROBE_PATH")
echo "POS ok   create ${PROBE_PATH} (CAS=0, version=1)"

UPDATE_JSON="$(vault_as_seed_input "second-${NONCE}" vault kv put -format=json -cas=1 "$PROBE_PATH" marker=-)"
jq -e '.data.version == 2' <<<"$UPDATE_JSON" >/dev/null \
  || { echo "ERROR: CAS=1 write did not create version 2" >&2; exit 1; }
echo "POS ok   update ${PROBE_PATH} (CAS=1, version=2)"
unset CREATE_JSON UPDATE_JSON

echo
echo "NEGATIVE — real API operations must return permission denied"
# CAS=0 is an atomic pre-existence guard: even if a probe name collides, it
# cannot overwrite an existing value. Success is still a security failure.
expect_denied_input "other app in same cluster" "deny-${NONCE}" "$OTHER_APP_PATH" \
  vault kv put -format=json -cas=0 "$OTHER_APP_PATH" marker=-
expect_denied_input "other cluster" "deny-${NONCE}" "$OTHER_CLUSTER_PATH" \
  vault kv put -format=json -cas=0 "$OTHER_CLUSTER_PATH" marker=-

expect_denied "KV read-after-write" vault kv get "$PROBE_PATH"
expect_denied "KV delete" vault kv delete "$PROBE_PATH"
expect_denied "KV undelete" vault kv undelete -versions=2 "$PROBE_PATH"
expect_denied "KV destroy" vault kv destroy -versions=2 "$PROBE_PATH"
expect_denied "KV metadata delete" vault kv metadata delete "$PROBE_PATH"

# These are safe real reads of existing administrative endpoints (or unique,
# UUID-suffixed probe names). Unlike token-capabilities, they exercise Vault's
# API authorizer without risking modification if the assertion is wrong.
expect_denied "sys/mounts" vault read sys/mounts
expect_denied "sys/policies/acl/ok-admin" vault read sys/policies/acl/ok-admin
expect_denied "sys/policies/acl/ok-config-automation" vault read sys/policies/acl/ok-config-automation
expect_denied "sys/auth" vault read sys/auth
expect_denied "sys/auth/kubernetes/<cluster>" vault read "sys/auth/kubernetes/${CLUSTER}"
expect_denied "auth/kubernetes/<cluster>/config" vault read "auth/kubernetes/${CLUSTER}/config"
expect_denied "auth/kubernetes/<cluster>/role/<probe>" vault read "auth/kubernetes/${CLUSTER}/role/${ROLE_PROBE}"
expect_denied "auth/userpass/users/<probe>" vault read "auth/userpass/users/${USER_PROBE}"
expect_denied "auth/token/create" vault token create -ttl=1s -explicit-max-ttl=1s -format=json
expect_denied "identity/entity" vault read "identity/entity/id/${ENTITY_PROBE}"
expect_denied "sys/audit" vault read sys/audit

echo
if ((FAILS == 0)); then
  echo "RESULT: PASS — scoped owner can create/update only its derived KV data subtree; all negative operations were denied."
  exit 0
else
  echo "RESULT: FAIL — ${FAILS} negative assertion(s) failed. Do not deploy this seed role." >&2
  exit 1
fi
