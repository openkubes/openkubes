#!/usr/bin/env bash
# Rotate the exposed break-glass (userpass) password AND revoke all tokens ever issued via its login
# path. Uses an INDEPENDENT ephemeral orphan rotator (minted by mint-rotator.sh -> /tmp/rotator-token,
# path auth/token/create, no parent) so the path-revocation cannot revoke the rotator mid-operation.
# Passwords are read via stdin only (never argv/history/logs). No automatic rollback to the exposed
# password. Five-state model governs recovery. Nothing secret is written to the done marker.
#
# Preconditions (confirmed by probe-breakglass-rotation.sh on 2026-07-26):
#   - rotator path = auth/token/create, orphan, policy ok-admin, has update+sudo on the user path
#     and on sys/leases/revoke-prefix/auth/userpass/login/breakglass
#   - failed userpass login signature = HTTP "Code: 400" + "invalid username or password"
set -Eeuo pipefail
SHARED_KUBECONFIG=~/.kube/ok-shared.yaml
BG_LOGIN_PATH=auth/userpass/login/breakglass
BG_USER_PATH=auth/userpass/users/breakglass
ROTATOR_FILE=/tmp/rotator-token
DONE_FILE=/tmp/rotate-breakglass-done
ROTATION_STATE="ROTATION_NOT_STARTED"
OLD_TOK=""; NEW_TOK=""; FINAL_TOK=""

vx(){ local t="$1"; shift; printf '%s\n' "$t" | kubectl --kubeconfig "$SHARED_KUBECONFIG" -n vault exec -i vault-0 -- sh -c 'IFS= read -r VAULT_TOKEN; export VAULT_TOKEN; exec "$@"' sh "$@"; }
bg_login_json(){ printf '%s' "$1" | jq -Rs '{password: .}' | kubectl --kubeconfig "$SHARED_KUBECONFIG" -n vault exec -i vault-0 -- sh -c '
  set -eu; umask 077; p="$(mktemp)"; trap "rm -f \"$p\"" EXIT; cat >"$p"; vault write -format=json '"$BG_LOGIN_PATH"' - <"$p"'; }
# $1 = new password (stdin, secret), $2 = token_policies JSON array (argv, NOT secret) — written
# alongside the password so an update can never clobber the user's authorization.
rotator_set_password(){ { printf '%s\n' "$ROT_TOK"; printf '%s' "$1" | jq -Rs --argjson pol "$2" '{password: ., token_policies: $pol}'; } | kubectl --kubeconfig "$SHARED_KUBECONFIG" -n vault exec -i vault-0 -- sh -c '
  set -eu; IFS= read -r VAULT_TOKEN; export VAULT_TOKEN; umask 077; p="$(mktemp)"; trap "rm -f \"$p\"" EXIT; cat >"$p"; vault write '"$BG_USER_PATH"' - <"$p"' >/dev/null; }
rotator_alive(){ vx "$ROT_TOK" vault token lookup >/dev/null 2>&1; }
# LOGIN_RESULT in {SUCCESS, INVALID_CREDS, ERROR}; on SUCCESS sets LOGIN_TOKEN
login_attempt(){ local out; LOGIN_TOKEN=""
  if out="$(bg_login_json "$1" 2>&1)"; then
    LOGIN_TOKEN="$(jq -er '.auth.client_token' <<<"$out" 2>/dev/null || true)"
    [[ -n "$LOGIN_TOKEN" ]] && LOGIN_RESULT=SUCCESS || LOGIN_RESULT=ERROR
  else
    if grep -qiE 'invalid username or password' <<<"$out" && grep -qE 'Code: 400' <<<"$out"; then LOGIN_RESULT=INVALID_CREDS; else LOGIN_RESULT=ERROR; fi
  fi; }
# prove the old password is rejected NOW, guarded by rotator liveness before+after (so an outage is
# not misread as a rejection)
assert_old_rejected(){
  rotator_alive || { echo "ABORT: rotator not reachable before negative test" >&2; exit 1; }
  login_attempt "$OLD_PW"
  rotator_alive || { echo "ABORT: rotator not reachable after negative test (outage — cannot trust the result)" >&2; exit 1; }
  case "$LOGIN_RESULT" in
    INVALID_CREDS) : ;;
    SUCCESS) echo "ABORT: OLD password STILL VALID (rotation not effective) — revoking that token" >&2; [[ -n "$LOGIN_TOKEN" ]] && vx "$LOGIN_TOKEN" vault token revoke -self >/dev/null 2>&1; exit 1 ;;
    *) echo "ABORT: old-password login gave an unexpected (non-invalid-creds) result; cannot confirm rejection" >&2; exit 1 ;;
  esac; }

cleanup(){ local rc=$?; trap - EXIT; set +e
  for t in "$OLD_TOK" "$NEW_TOK" "$FINAL_TOK"; do [[ -n "$t" ]] && vx "$t" vault token revoke -self >/dev/null 2>&1; done
  if ((rc!=0)) && [[ "$ROTATION_STATE" != "FINAL_LOGIN_CONFIRMED" ]]; then
    case "$ROTATION_STATE" in
      ROTATION_NOT_STARTED) echo "RECOVERY: ROTATION_NOT_STARTED — nothing changed." >&2 ;;
      PASSWORD_UPDATE_ATTEMPTED) echo "RECOVERY: PASSWORD_UPDATE_ATTEMPTED — password state uncertain. Test BOTH passwords manually; do NOT blindly retry. Rotator kept at $ROTATOR_FILE for manual completion." >&2 ;;
      PASSWORD_UPDATE_CONFIRMED) echo "RECOVERY: PASSWORD_UPDATE_CONFIRMED — new password valid + old rejected, but existing break-glass tokens may still be live. Run manually with the rotator: vault token revoke -mode=path $BG_LOGIN_PATH. Session NOT safe yet." >&2 ;;
      TOKENS_REVOKED) echo "RECOVERY: TOKENS_REVOKED — path tokens revoked but final login not confirmed. Verify a new-password login manually." >&2 ;;
    esac
    echo "RECOVERY: no automatic rollback to the exposed password was performed. Rotator not auto-revoked (kept for manual completion)." >&2
  fi
  unset OLD_PW NEW1 NEW2 NEW_PW ROT_TOK; exit "$rc"; }
trap cleanup EXIT
trap 'rc=$?; printf "ABORT: rc=%s at line %s\n" "$rc" "$LINENO" >&2; exit "$rc"' ERR

rm -f "$DONE_FILE"

# ── R0 preflight (independent rotator) ──
test -s "$ROTATOR_FILE" || { echo "ABORT: rotator token file $ROTATOR_FILE missing — run mint-rotator.sh first" >&2; exit 1; }
ROT_TOK="$(cat "$ROTATOR_FILE")"; [[ -n "$ROT_TOK" ]] || { echo "ABORT: empty rotator token" >&2; exit 1; }
ROT_LK="$(vx "$ROT_TOK" vault token lookup -format=json)"
[[ "$(jq -r '.data.path // ""' <<<"$ROT_LK")" != "$BG_LOGIN_PATH" ]] || { echo "ABORT: rotator is from the break-glass login path (not independent)" >&2; exit 1; }
[[ "$(jq -r '.data.orphan // false' <<<"$ROT_LK")" == "true" ]] || { echo "ABORT: rotator is not orphan (would cascade on path revoke)" >&2; exit 1; }
grep -qwE 'update|sudo' <<<"$(vx "$ROT_TOK" vault token capabilities "$BG_USER_PATH")" || { echo "ABORT: rotator lacks update/sudo on $BG_USER_PATH" >&2; exit 1; }
grep -qwE 'update|sudo' <<<"$(vx "$ROT_TOK" vault token capabilities "sys/leases/revoke-prefix/$BG_LOGIN_PATH")" || { echo "ABORT: rotator lacks update/sudo on the revoke-prefix path" >&2; exit 1; }
vx "$ROT_TOK" vault auth list -format=json | jq -e '."userpass/".type=="userpass"' >/dev/null || { echo "ABORT: userpass/ mount not present" >&2; exit 1; }
USER_POLICIES_BEFORE="$(vx "$ROT_TOK" vault read -format=json "$BG_USER_PATH" | jq -c '.data.token_policies // []')"
echo "R0 PREFLIGHT OK (independent orphan rotator; caps present; userpass user policies=$USER_POLICIES_BEFORE)"

# ── R1 prove the old password + exact login path ──
read -rsp 'Current (exposed) break-glass password: ' OLD_PW; printf '\n'; [[ -n "$OLD_PW" ]] || { echo "ABORT: empty old password" >&2; exit 1; }
login_attempt "$OLD_PW"; [[ "$LOGIN_RESULT" == "SUCCESS" ]] || { echo "ABORT: current password did not authenticate ($LOGIN_RESULT)" >&2; exit 1; }
OLD_TOK="$LOGIN_TOKEN"
[[ "$(vx "$OLD_TOK" vault token lookup -format=json | jq -r '.data.path // ""')" == "$BG_LOGIN_PATH" ]] || { echo "ABORT: old-token login path mismatch" >&2; exit 1; }
echo "R1 OLD PASSWORD PROVEN (login path = $BG_LOGIN_PATH)"

# ── R2 capture the new password (twice, stdin only) ──
read -rsp 'New break-glass password: ' NEW1; printf '\n'
read -rsp 'Repeat new break-glass password: ' NEW2; printf '\n'
[[ -n "$NEW1" && "$NEW1" == "$NEW2" ]] || { echo "ABORT: new passwords empty or do not match" >&2; exit 1; }
[[ "$NEW1" != "$OLD_PW" ]] || { echo "ABORT: new password must differ from the exposed one" >&2; exit 1; }
NEW_PW="$NEW1"; unset NEW1 NEW2

# ── R3 update the password (via the independent rotator) ──
ROTATION_STATE="PASSWORD_UPDATE_ATTEMPTED"
rotator_set_password "$NEW_PW" "$USER_POLICIES_BEFORE"
echo "R3 PASSWORD UPDATE ISSUED (via rotator; state=ATTEMPTED)"

# ── R4 positive + negative verification (with rotator liveness guarding the negative test) ──
login_attempt "$NEW_PW"; [[ "$LOGIN_RESULT" == "SUCCESS" ]] || { echo "ABORT: NEW password did not authenticate after update ($LOGIN_RESULT)" >&2; exit 1; }
NEW_TOK="$LOGIN_TOKEN"
assert_old_rejected
[[ "$(vx "$ROT_TOK" vault read -format=json "$BG_USER_PATH" | jq -c '.data.token_policies // []')" == "$USER_POLICIES_BEFORE" ]] || { echo "ABORT: break-glass user policies changed during the update" >&2; exit 1; }
vx "$NEW_TOK" vault token revoke -self >/dev/null 2>&1 || true; NEW_TOK=""
ROTATION_STATE="PASSWORD_UPDATE_CONFIRMED"
echo "R4 VERIFIED (new password valid; old password rejected with the expected 400 invalid-credentials signature; user policies unchanged; state=CONFIRMED)"

# ── R5 revoke ALL tokens issued via the break-glass login path ──
[[ "$BG_LOGIN_PATH" == "auth/userpass/login/breakglass" ]] || { echo "ABORT: refusing to revoke an unexpected path" >&2; exit 1; }
vx "$ROT_TOK" vault token revoke -mode=path "$BG_LOGIN_PATH" >/dev/null
OLD_TOK=""   # just revoked along with every other break-glass-path token
ROTATION_STATE="TOKENS_REVOKED"
echo "R5 PATH TOKENS REVOKED ($BG_LOGIN_PATH; state=TOKENS_REVOKED)"

# ── R6 final proof after revocation, then revoke the ephemeral rotator ──
login_attempt "$NEW_PW"; [[ "$LOGIN_RESULT" == "SUCCESS" ]] || { echo "ABORT: NEW password login failed after path-revocation ($LOGIN_RESULT)" >&2; exit 1; }
FINAL_TOK="$LOGIN_TOKEN"
vx "$FINAL_TOK" vault token lookup >/dev/null || { echo "ABORT: final new-password token not valid" >&2; exit 1; }
assert_old_rejected
vx "$FINAL_TOK" vault token revoke -self >/dev/null; FINAL_TOK=""
vx "$ROT_TOK" vault token revoke -self >/dev/null 2>&1 || true   # ephemeral rotator: done
rm -f "$ROTATOR_FILE"
ROTATION_STATE="FINAL_LOGIN_CONFIRMED"

DONE_TMP="$(mktemp /tmp/rotate-breakglass-done.XXXXXX)"
jq -n --arg at "$(date -u +%FT%TZ)" \
  '{user:"breakglass",authPath:"auth/userpass/login/breakglass",rotatedAt:$at,oldPasswordRejected:true,loginPathTokensRevoked:true,newPasswordLoginAfterRevocation:true,generatedTokensRevoked:true}' > "$DONE_TMP"
mv "$DONE_TMP" "$DONE_FILE"
unset OLD_PW NEW_PW ROT_TOK
echo "R6 FINAL LOGIN CONFIRMED — break-glass password rotated; all break-glass-path tokens revoked; ephemeral rotator revoked. Done marker: $DONE_FILE"
