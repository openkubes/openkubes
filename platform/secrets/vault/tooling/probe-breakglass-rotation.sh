#!/usr/bin/env bash
# READ-ONLY preflight for the break-glass password rotation. Resolves the two unknowns GPT flagged
# BEFORE we finalize/execute rotate-breakglass.sh:
#   (1) the exact INVALID-CREDENTIALS signature of a failed userpass login in this Vault version;
#   (2) whether an INDEPENDENT rotator authority exists (a token NOT issued via the break-glass
#       login path, with the capabilities to update the user + path-revoke its tokens).
# It also confirms the environment (userpass mount, breakglass user, the exact login path).
# NO mutation. It logs in twice (old password + deliberately-wrong password) only to observe, and
# revokes the resulting test tokens. Passwords are read via stdin, never argv/history.
set -Eeuo pipefail
SHARED_KUBECONFIG=~/.kube/ok-shared.yaml
BG_LOGIN_PATH=auth/userpass/login/breakglass
BG_USER_PATH=auth/userpass/users/breakglass
EXPECTED_LOGIN_PATH=auth/userpass/login/breakglass

cleanup(){ local rc=$?; trap - EXIT; set +e
  [[ -n "${OLD_TOK:-}" ]] && vx "$OLD_TOK" vault token revoke -self >/dev/null 2>&1
  unset OLD_PW OLD_TOK ROT_TOK; exit "$rc"; }
trap cleanup EXIT
trap 'rc=$?; printf "ABORT: rc=%s at line %s\n" "$rc" "$LINENO" >&2; exit "$rc"' ERR

# token via stdin, args via argv; never the password in argv
vx(){ local t="$1"; shift; printf '%s\n' "$t" | kubectl --kubeconfig "$SHARED_KUBECONFIG" -n vault exec -i vault-0 -- sh -c 'IFS= read -r VAULT_TOKEN; export VAULT_TOKEN; exec "$@"' sh "$@"; }
# userpass login with the password delivered over stdin as JSON; prints login JSON on success
bg_login_json(){ printf '%s' "$1" | jq -Rs '{password: .}' | kubectl --kubeconfig "$SHARED_KUBECONFIG" -n vault exec -i vault-0 -- sh -c '
  set -eu; umask 077; p="$(mktemp)"; trap "rm -f \"$p\"" EXIT; cat >"$p"; vault write -format=json '"$BG_LOGIN_PATH"' - <"$p"'; }
# capture combined output + rc without tripping the ERR trap
cap(){ local __o="$1" __r="$2" __c __s; shift 2
  if __c="$("$@" 2>&1)"; then __s=0; else __s=$?; fi
  printf -v "$__o" '%s' "$__c"; printf -v "$__r" '%s' "$__s"; }

echo "════════ break-glass rotation PREFLIGHT (read-only) ════════"

# ── ROTATOR token (independent authority) — read from the 0600 file minted by mint-rotator.sh ──
ROTATOR_FILE=/tmp/rotator-token
test -s "$ROTATOR_FILE" || { echo "ABORT: rotator token file $ROTATOR_FILE missing — run mint-rotator.sh first" >&2; exit 1; }
ROT_TOK="$(cat "$ROTATOR_FILE")"; [[ -n "$ROT_TOK" ]] || { echo "ABORT: empty rotator token file" >&2; exit 1; }
ROT_LOOKUP="$(vx "$ROT_TOK" vault token lookup -format=json)"
ROT_PATH="$(jq -r '.data.path // ""' <<<"$ROT_LOOKUP")"
echo "  rotator token .data.path = [${ROT_PATH:-<root/none>}]"
echo "  rotator policies          = $(jq -rc '.data.policies // []' <<<"$ROT_LOOKUP")"
if [[ "$ROT_PATH" == "$BG_LOGIN_PATH" ]]; then
  echo "  >>> WARNING: rotator token IS from the break-glass login path — NOT independent. Path-revocation would revoke it mid-operation. Use a root/generate-root/other-admin token instead." >&2
else
  echo "  rotator independence: OK (not from $BG_LOGIN_PATH)"
fi
echo "  rotator capability on $BG_USER_PATH : $(vx "$ROT_TOK" vault token capabilities "$BG_USER_PATH" 2>&1 || true)"
echo "  rotator capability on sys/leases/revoke-prefix/$BG_LOGIN_PATH : $(vx "$ROT_TOK" vault token capabilities "sys/leases/revoke-prefix/$BG_LOGIN_PATH" 2>&1 || true)"

# ── environment: userpass mount + breakglass user exist (read via rotator) ──
echo "── environment ──"
vx "$ROT_TOK" vault auth list -format=json | jq -e '."userpass/".type=="userpass"' >/dev/null && echo "  userpass/ mount: enabled (type userpass)" || echo "  >>> userpass/ mount NOT found as expected" >&2
if vx "$ROT_TOK" vault read -format=json "$BG_USER_PATH" >/dev/null 2>&1; then echo "  user 'breakglass': exists"; else echo "  >>> user 'breakglass' NOT readable at $BG_USER_PATH" >&2; fi

# ── (1) prove old password + confirm the exact login path ──
echo "── old-password login (proves current password + exact login path) ──"
read -rsp 'Current (exposed) break-glass password: ' OLD_PW; printf '\n'
OLD_LOGIN="$(bg_login_json "$OLD_PW")"
OLD_TOK="$(jq -er '.auth.client_token' <<<"$OLD_LOGIN")"
OLD_TOK_PATH="$(vx "$OLD_TOK" vault token lookup -format=json | jq -r '.data.path // ""')"
echo "  old-password login: SUCCESS; issued-token .data.path = [$OLD_TOK_PATH]"
[[ "$OLD_TOK_PATH" == "$EXPECTED_LOGIN_PATH" ]] && echo "  login path matches expected ($EXPECTED_LOGIN_PATH) ✓" || echo "  >>> login path MISMATCH (expected $EXPECTED_LOGIN_PATH)" >&2

# ── (2) capture the exact INVALID-CREDENTIALS signature (deliberately wrong password) ──
echo "── invalid-credentials signature (deliberately wrong password; read-only) ──"
cap WRONG_OUT WRONG_RC bg_login_json "definitely-not-the-password-$RANDOM$RANDOM"
echo "  wrong-password login rc = $WRONG_RC"
echo "  wrong-password output (this is the signature the rotation script must match):"
printf '%s\n' "$WRONG_OUT" | sed 's/^/    | /'

# ── revoke the old-password test token (cleanup handles it too) ──
vx "$OLD_TOK" vault token revoke -self >/dev/null 2>&1 || true; OLD_TOK=""
echo "════════ PREFLIGHT COMPLETE (nothing changed) ════════"
echo "Report back: (a) the rotator .data.path + independence, (b) the exact wrong-password signature line,"
echo "so rotate-breakglass.sh can hard-code the accepted invalid-credentials pattern and confirm the rotator."
