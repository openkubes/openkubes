#!/usr/bin/env bash
# A6 Step 1 — ISOLATION test of the NARROWED ok-config-automation policy, WITHOUT touching the live
# policy. Creates a temporary test policy carrying the A6 target HCL + a test token with only that
# policy, then proves (as that token):
#   POSITIVE — it grants everything the reconciler needs (write okvc-*, manage kubernetes/<cluster>
#              auth mounts/roles/config, observe mounts, mint child tokens).
#   NEGATIVE — it denies admin reach: writing a NON-okvc policy, and touching its OWN ok-mgmt auth
#              mount / role (self-protection).
# Proves correctness BEFORE the live policy is narrowed. All temp objects are cleaned up. Fail-closed.
set -Eeuo pipefail
SHARED_KUBECONFIG=~/.kube/ok-shared.yaml
BG_LOGIN_PATH=auth/userpass/login/breakglass
TEST_POLICY=a6-automation-narrowed-test
PROBE_POLICY=okvc-a6-probe            # a legitimate okvc- name the narrowed policy MAY write
BAD_POLICY=a6-admin-attempt           # a non-okvc name the narrowed policy MUST NOT write
PROBE_HCL='path "secret/data/harmless-a6-probe" { capabilities = ["read"] }'
FAILS=0
cleanup(){ local rc=$?; trap - EXIT; set +e
  [[ -n "${TESTTOK:-}" ]] && vx "$TESTTOK" vault token revoke -self >/dev/null 2>&1
  if [[ -n "${BGT:-}" ]]; then
    vx "$BGT" vault policy delete "$PROBE_POLICY" >/dev/null 2>&1
    vx "$BGT" vault policy delete "$BAD_POLICY"   >/dev/null 2>&1   # only exists if the test FAILED
    vx "$BGT" vault policy delete "$TEST_POLICY"  >/dev/null 2>&1
    vx "$BGT" vault token revoke -self >/dev/null 2>&1
  fi
  unset BG BGT TESTTOK; exit "$rc"; }
trap cleanup EXIT
trap 'rc=$?; printf "ABORT: rc=%s at line %s\n" "$rc" "$LINENO" >&2; exit "$rc"' ERR
vx(){ local t="$1"; shift; printf '%s\n' "$t" | kubectl --kubeconfig "$SHARED_KUBECONFIG" -n vault exec -i vault-0 -- sh -c 'IFS= read -r VAULT_TOKEN; export VAULT_TOKEN; exec "$@"' sh "$@"; }
# write a policy AS a given token, HCL over stdin, name as remote arg (no secret; policy content is not secret)
tok_policy_write(){ local tok="$1" name="$2" hcl="$3"; { printf '%s\n' "$tok"; printf '%s' "$hcl"; } | kubectl --kubeconfig "$SHARED_KUBECONFIG" -n vault exec -i vault-0 -- sh -c '
  set -eu; IFS= read -r VAULT_TOKEN; export VAULT_TOKEN; umask 077; p="$(mktemp)"; trap "rm -f \"$p\"" EXIT; cat >"$p"; vault policy write "$1" "$p"' sh "$name"; }
caps(){ vx "$TESTTOK" vault token capabilities "$1" 2>/dev/null; }
assert_can(){ local p="$1" c="$2" got; got="$(caps "$p")"; if grep -qw "$c" <<<"$got"; then echo "  POS ok   [$c] on $p  (caps: $got)"; else echo "  POS FAIL missing [$c] on $p  (caps: $got)"; FAILS=$((FAILS+1)); fi; }
assert_deny(){ local p="$1" got; got="$(caps "$p")"; if [[ "$(tr -d '[:space:]' <<<"$got")" == "deny" ]]; then echo "  NEG ok   deny on $p"; else echo "  NEG FAIL not denied on $p  (caps: $got)"; FAILS=$((FAILS+1)); fi; }

# ── A6 target policy (from the ADR-025 amendment) ──
read -r -d '' A6_HCL <<'HCL' || true
path "sys/auth"                      { capabilities = ["read"] }
path "sys/auth/kubernetes/*"         { capabilities = ["create","read","update","delete","sudo"] }
path "sys/auth/kubernetes/ok-mgmt"   { capabilities = ["deny"] }
path "sys/auth/kubernetes/ok-mgmt/*" { capabilities = ["deny"] }
path "auth/kubernetes/ok-mgmt"       { capabilities = ["deny"] }
path "auth/kubernetes/ok-mgmt/*"     { capabilities = ["deny"] }
path "sys/mounts/auth/kubernetes/*"  { capabilities = ["read"] }
path "sys/policies/acl/okvc-*"       { capabilities = ["create","read","update","delete","list"] }
path "auth/kubernetes/*"             { capabilities = ["create","read","update","delete","list"] }
path "auth/token/create"             { capabilities = ["create","update"] }
HCL

read -rsp 'break-glass password (rotated): ' BG; printf '\n'
BGT="$(printf '%s' "$BG" | jq -Rs '{password:.}' | kubectl --kubeconfig "$SHARED_KUBECONFIG" -n vault exec -i vault-0 -- sh -c '
  set -eu; umask 077; p="$(mktemp)"; trap "rm -f \"$p\"" EXIT; cat >"$p"; vault write -format=json '"$BG_LOGIN_PATH"' - <"$p"' | jq -er '.auth.client_token')"
unset BG; test -n "$BGT"; vx "$BGT" vault token lookup >/dev/null; echo "break-glass login OK"

# safety: none of the temp names must pre-exist
for n in "$TEST_POLICY" "$PROBE_POLICY" "$BAD_POLICY"; do
  vx "$BGT" vault policy list | grep -Fxq "$n" && { echo "ABORT: temp policy '$n' already exists — refusing to clobber" >&2; exit 1; }; done

# ── create the temp NARROWED test policy + a token carrying only it ──
tok_policy_write "$BGT" "$TEST_POLICY" "$A6_HCL" >/dev/null
TESTTOK="$(vx "$BGT" vault token create -orphan -ttl=10m -display-name=a6-policy-test -policy="$TEST_POLICY" -format=json | jq -er '.auth.client_token')"
echo "test token minted (policies: default + $TEST_POLICY)"

echo; echo "════════ POSITIVE — narrowed policy grants what the reconciler needs ════════"
assert_can "sys/policies/acl/$PROBE_POLICY"          create
assert_can "sys/policies/acl/$PROBE_POLICY"          update
assert_can "sys/policies/acl/okvc-ok-robotics-sa-obs" read
assert_can "sys/mounts/auth/kubernetes/ok-robotics"  read
assert_can "sys/auth/kubernetes/ok-robotics"         create
assert_can "auth/kubernetes/ok-robotics/role/sa-obs" update
assert_can "auth/kubernetes/ok-robotics/config"      update
assert_can "auth/token/create"                       create
echo "  -- real write of a legitimate okvc- policy (as the test token) --"
tok_policy_write "$TESTTOK" "$PROBE_POLICY" "$PROBE_HCL" >/dev/null && echo "  POS ok   real write of $PROBE_POLICY SUCCEEDED"
vx "$BGT" vault policy read "$PROBE_POLICY" >/dev/null && echo "  POS ok   $PROBE_POLICY exists"
vx "$BGT" vault policy delete "$PROBE_POLICY" >/dev/null; echo "  (cleanup: $PROBE_POLICY deleted)"

echo; echo "════════ NEGATIVE — narrowed policy denies admin reach ════════"
assert_deny "sys/policies/acl/$BAD_POLICY"                 # non-okvc policy name
assert_deny "sys/policies/acl/ok-config-automation"       # cannot edit the automation policy itself
assert_deny "sys/policies/acl/okvc"                        # 'okvc' without dash must NOT match okvc-*
assert_deny "sys/auth/kubernetes/ok-mgmt"                  # self mount lifecycle
assert_deny "sys/auth/kubernetes/ok-mgmt/tune"
assert_deny "auth/kubernetes/ok-mgmt/role/provider-vault"  # self auth role
assert_deny "sys/auth/approle"                             # non-kubernetes auth type
echo "  -- real write of a NON-okvc policy (as the test token) MUST be denied --"
if OUT="$(tok_policy_write "$TESTTOK" "$BAD_POLICY" "$PROBE_HCL" 2>&1)"; then
  echo "  NEG FAIL real write of $BAD_POLICY was ALLOWED — deleting it" >&2; vx "$BGT" vault policy delete "$BAD_POLICY" >/dev/null 2>&1; FAILS=$((FAILS+1))
elif grep -qiE 'permission denied|403|1 error occurred' <<<"$OUT"; then
  echo "  NEG ok   real write of $BAD_POLICY DENIED (permission denied)"
else
  echo "  NEG FAIL $BAD_POLICY write failed but not with permission-denied: $OUT" >&2; FAILS=$((FAILS+1))
fi

echo; echo "════════ RESULT ════════"
if ((FAILS==0)); then echo "A6 NARROWED POLICY VALIDATED — grants all reconciler ops, denies admin reach. Safe to apply to the live ok-config-automation (Step 2)."
else echo "A6 POLICY TEST FAILED — $FAILS assertion(s) failed. Do NOT apply the narrowed policy yet." >&2; exit 1; fi
