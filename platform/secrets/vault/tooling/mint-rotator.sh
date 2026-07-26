#!/usr/bin/env bash
# Mint an INDEPENDENT orphan admin rotator token for the break-glass rotation (Option A).
# It logs in with the current break-glass password (stdin), creates an ORPHAN token that inherits
# the break-glass token's non-default policies (path `auth/token/create`, no parent -> a later
# path-revocation of auth/userpass/login/breakglass cannot revoke it), writes ONLY that token to a
# 0600 file (never printed), and revokes the break-glass login token it was minted from.
set -Eeuo pipefail
SHARED_KUBECONFIG=~/.kube/ok-shared.yaml
BG_LOGIN_PATH=auth/userpass/login/breakglass
ROTATOR_FILE=/tmp/rotator-token
cleanup(){ local rc=$?; trap - EXIT; set +e
  [[ -n "${BGT:-}" ]] && vx "$BGT" vault token revoke -self >/dev/null 2>&1
  unset BG BGT; exit "$rc"; }
trap cleanup EXIT
trap 'rc=$?; printf "ABORT: rc=%s at line %s\n" "$rc" "$LINENO" >&2; exit "$rc"' ERR
vx(){ local t="$1"; shift; printf '%s\n' "$t" | kubectl --kubeconfig "$SHARED_KUBECONFIG" -n vault exec -i vault-0 -- sh -c 'IFS= read -r VAULT_TOKEN; export VAULT_TOKEN; exec "$@"' sh "$@"; }

read -rsp 'Current break-glass password: ' BG; printf '\n'
BGT="$(printf '%s' "$BG" | jq -Rs '{password:.}' | kubectl --kubeconfig "$SHARED_KUBECONFIG" -n vault exec -i vault-0 -- sh -c '
  set -eu; umask 077; p="$(mktemp)"; trap "rm -f \"$p\"" EXIT; cat >"$p"; vault write -format=json '"$BG_LOGIN_PATH"' - <"$p"' | jq -er '.auth.client_token')"
unset BG; test -n "$BGT"; vx "$BGT" vault token lookup >/dev/null; echo "break-glass login OK"

# inherit the break-glass token's non-default policies for the orphan rotator
mapfile -t POLS < <(vx "$BGT" vault token lookup -format=json | jq -r '.data.policies[]? | select(. != "default")')
((${#POLS[@]})) || { echo "ABORT: break-glass token has no non-default policy to inherit" >&2; exit 1; }
POLARGS=(); for p in "${POLS[@]}"; do POLARGS+=("-policy=$p"); done
echo "orphan rotator will carry policies: ${POLS[*]}"

# create the orphan admin rotator (requires sudo on auth/token/create-orphan; break-glass admin has it)
ORPHAN_JSON="$(vx "$BGT" vault token create -orphan -ttl=30m -display-name=breakglass-rotator -format=json "${POLARGS[@]}")"
ORPHAN_TOK="$(jq -er '.auth.client_token' <<<"$ORPHAN_JSON")"
# verify independence: not from the break-glass login path, and truly orphan (no parent)
ROT_LK="$(vx "$ORPHAN_TOK" vault token lookup -format=json)"
ROT_PATH="$(jq -r '.data.path // ""' <<<"$ROT_LK")"
ROT_ORPHAN="$(jq -r '.data.orphan // false' <<<"$ROT_LK")"
[[ "$ROT_PATH" != "$BG_LOGIN_PATH" ]] || { echo "ABORT: rotator path == break-glass login path (not independent)" >&2; exit 1; }
[[ "$ROT_ORPHAN" == "true" ]] || { echo "ABORT: rotator token is not orphan (would cascade on parent revoke)" >&2; exit 1; }

umask 077; TMP="$(mktemp /tmp/rotator-token.XXXXXX)"; printf '%s' "$ORPHAN_TOK" > "$TMP"; mv "$TMP" "$ROTATOR_FILE"; chmod 600 "$ROTATOR_FILE"
echo "ROTATOR TOKEN WRITTEN -> $ROTATOR_FILE (0600). path=$ROT_PATH orphan=$ROT_ORPHAN policies=[${POLS[*]}]"
echo "Revoking the break-glass login token used to mint it (the orphan has no parent and survives)."
