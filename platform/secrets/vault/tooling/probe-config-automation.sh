#!/usr/bin/env bash
# READ-ONLY: show the LIVE state needed to plan the A6 policy tightening + negative test.
#   - the current ok-config-automation policy HCL (is it the broad seed or already narrowed?)
#   - the reconciler role binding (auth/kubernetes/ok-mgmt/role/provider-vault -> token_policies)
#   - the kubernetes auth mounts that exist (what the reconciler manages vs its own ok-mgmt mount)
#   - the okvc- policies currently present (what the reconciler owns)
# No mutation. Logs in with the (rotated) break-glass password over stdin; revokes the token at end.
set -Eeuo pipefail
SHARED_KUBECONFIG=~/.kube/ok-shared.yaml
BG_LOGIN_PATH=auth/userpass/login/breakglass
cleanup(){ local rc=$?; trap - EXIT; set +e; [[ -n "${BGT:-}" ]] && vx "$BGT" vault token revoke -self >/dev/null 2>&1; unset BG BGT; exit "$rc"; }
trap cleanup EXIT
trap 'rc=$?; printf "ABORT: rc=%s at line %s\n" "$rc" "$LINENO" >&2; exit "$rc"' ERR
vx(){ local t="$1"; shift; printf '%s\n' "$t" | kubectl --kubeconfig "$SHARED_KUBECONFIG" -n vault exec -i vault-0 -- sh -c 'IFS= read -r VAULT_TOKEN; export VAULT_TOKEN; exec "$@"' sh "$@"; }

read -rsp 'break-glass password (rotated): ' BG; printf '\n'
BGT="$(printf '%s' "$BG" | jq -Rs '{password:.}' | kubectl --kubeconfig "$SHARED_KUBECONFIG" -n vault exec -i vault-0 -- sh -c '
  set -eu; umask 077; p="$(mktemp)"; trap "rm -f \"$p\"" EXIT; cat >"$p"; vault write -format=json '"$BG_LOGIN_PATH"' - <"$p"' | jq -er '.auth.client_token')"
unset BG; test -n "$BGT"; vx "$BGT" vault token lookup >/dev/null; echo "break-glass login OK"

echo; echo "════════ (1) LIVE ok-config-automation policy HCL ════════"
vx "$BGT" vault policy read ok-config-automation
echo; echo "  >>> Is 'sys/policies/acl/*' present (BROAD seed) or 'sys/policies/acl/okvc-*' (NARROWED)?"

echo; echo "════════ (2) reconciler role binding ════════"
vx "$BGT" vault read -format=json auth/kubernetes/ok-mgmt/role/provider-vault \
  | jq '{token_policies:.data.token_policies, bound_sa_names:.data.bound_service_account_names, bound_sa_ns:.data.bound_service_account_namespaces, token_ttl:.data.token_ttl}'

echo; echo "════════ (3) kubernetes auth mounts (reconciler manages non-ok-mgmt ones) ════════"
vx "$BGT" vault auth list -format=json | jq -r 'to_entries[] | select(.value.type=="kubernetes") | "  \(.key)  accessor=\(.value.accessor)"'

echo; echo "════════ (4) okvc- policies present (reconciler-owned) ════════"
vx "$BGT" vault policy list | grep -E '^okvc-' || echo "  (none)"

echo; echo "════════ (5) any NON-okvc reconciler-looking policies (should be none after migration) ════════"
vx "$BGT" vault policy list | grep -E 'ok-robotics|sa-obs' | grep -vE '^okvc-' || echo "  (none — clean)"

vx "$BGT" vault token revoke -self >/dev/null; unset BGT
echo; echo "════════ PROBE COMPLETE (read-only; nothing changed) ════════"
echo "Report (1) [broad vs narrowed], (2) token_policies, (3) the kubernetes mounts, (4) the okvc- policy list."
