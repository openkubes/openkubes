#!/usr/bin/env bash
# A6 Step 1 — ISOLATION test of the NARROWED ok-config-automation policy, WITHOUT touching the live
# policy. Creates a temporary test policy carrying the A6 target HCL + a test token with only that
# policy, then proves (as that token):
#   POSITIVE — it grants everything the reconciler needs (write okvc-*, manage kubernetes/<cluster>
#              auth mounts/roles/config, observe mounts, mint child tokens).
#   NEGATIVE — it denies admin reach: writing a NON-okvc policy, and touching its OWN ok-mgmt auth
#              mount / role (self-protection).
#   BODY SCOPING — whether "consumers are read-only" is ENFORCED or merely conventional. The A6 HCL
#              scopes policy NAMES (okvc-*); nothing scopes their CONTENTS. Reported separately and
#              does NOT block Step 2 — the narrowing is an improvement either way.
# Proves correctness BEFORE the live policy is narrowed. All temp objects are cleaned up. Fail-closed.
set -Eeuo pipefail
SHARED_KUBECONFIG=~/.kube/ok-shared.yaml
BG_LOGIN_PATH=auth/userpass/login/breakglass
TEST_POLICY=a6-automation-narrowed-test
PROBE_POLICY=okvc-a6-probe            # a legitimate okvc- name the narrowed policy MAY write
BAD_POLICY=a6-admin-attempt           # a non-okvc name the narrowed policy MUST NOT write
PROBE_HCL='path "secret/data/harmless-a6-probe" { capabilities = ["read"] }'
# Body-scoping probe: an okvc- name the narrowed policy MAY write, carrying a WRITE body it
# should not be able to confer. sys/policies/acl/okvc-* scopes the policy NAME; nothing in the
# A6 HCL scopes its CONTENTS, so this asks whether read-only is enforced or merely conventional.
ESC_POLICY=okvc-a6-escalation-probe
ESC_HCL='path "secret/data/a6-escalation-probe/*" { capabilities = ["create","update","read"] }'
ESC_MOUNT=kubernetes/a6-esc-probe     # throwaway auth mount, so no live mount is touched
ESC_ROLE=a6-esc-probe
FAILS=0
ESC_FINDINGS=0
ESC_INCONCLUSIVE=0
cleanup(){ local rc=$?; trap - EXIT; set +e
  [[ -n "${TESTTOK:-}" ]] && vx "$TESTTOK" vault token revoke -self >/dev/null 2>&1
  if [[ -n "${BGT:-}" ]]; then
    vx "$BGT" vault auth disable "$ESC_MOUNT"     >/dev/null 2>&1   # throwaway mount, before its policy
    vx "$BGT" vault policy delete "$ESC_POLICY"   >/dev/null 2>&1
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
for n in "$TEST_POLICY" "$PROBE_POLICY" "$BAD_POLICY" "$ESC_POLICY"; do
  vx "$BGT" vault policy list | grep -Fxq "$n" && { echo "ABORT: temp policy '$n' already exists — refusing to clobber" >&2; exit 1; }; done
vx "$BGT" vault auth list -format=json | jq -er --arg m "${ESC_MOUNT}/" 'has($m)' >/dev/null 2>&1 \
  && { echo "ABORT: temp auth mount '$ESC_MOUNT' already exists — refusing to clobber" >&2; exit 1; } || true

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

echo; echo "════════ BODY SCOPING — is consumer read-only ENFORCED, or only conventional? ════════"
# The A6 HCL scopes the reconciler to policy NAMES (sys/policies/acl/okvc-*). Nothing scopes a
# policy's CONTENTS. The composition emits capabilities=["read"], but that is a template choice,
# not a boundary. If the reconciler identity can author an okvc- policy carrying WRITE and then
# reference it from an auth role's token_policies, then "consumers are read-only" rests on the
# template — and anyone who can drive provider-vault, or any edit to the composition, changes it.
echo "  -- (1) write an okvc--named policy whose BODY grants KV write --"
if OUT="$(tok_policy_write "$TESTTOK" "$ESC_POLICY" "$ESC_HCL" 2>&1)"; then
  echo "  FINDING  okvc- name accepted a WRITE body — policy contents are NOT constrained"
  ESC_FINDINGS=$((ESC_FINDINGS+1))
  echo "  -- (2) mint a token carrying it directly (expected DENIED: parent-subset rule) --"
  if OUT2="$(vx "$TESTTOK" vault token create -ttl=1m -policy="$ESC_POLICY" -format=json 2>&1)"; then
    echo "  FINDING  direct token mint with $ESC_POLICY SUCCEEDED — no parent-subset restriction"
    ESC_FINDINGS=$((ESC_FINDINGS+1))
  elif grep -qiF 'child policies must be subset of parent' <<<"$OUT2"; then
    echo "  ok       direct token mint DENIED — the direct route is closed by the parent-subset rule"
  elif grep -qiE 'permission denied|403' <<<"$OUT2"; then
    echo "  ok       direct token mint DENIED (auth/token/create is subset-limited without sudo)"
  else
    echo "  INCONCLUSIVE  token mint failed for a non-permission reason — NOT a clean bill:"
    echo "                ${OUT2}"
    ESC_INCONCLUSIVE=$((ESC_INCONCLUSIVE+1))
  fi
  echo "  -- (3) confer it via an auth ROLE instead, on a throwaway mount --"
  # Do NOT collapse these failures into one message: "blocked" is a SECURITY conclusion, and
  # any non-permission error (mount name collision, plugin fault, typo) would otherwise be
  # reported as reassurance. Only an explicit permission denial means the chain is blocked;
  # anything else is INCONCLUSIVE and must be re-run. Same defect class as OK-124 in the gate.
  denied(){ grep -qiE 'permission denied|403' <<<"$1"; }
  if ! MOUT="$(vx "$TESTTOK" vault auth enable -path="$ESC_MOUNT" kubernetes 2>&1)"; then
    if denied "$MOUT"; then
      echo "  ok       DENIED creating the throwaway auth mount — chain is blocked at the mount"
    else
      echo "  INCONCLUSIVE  auth-mount creation failed for a non-permission reason — NOT a clean bill:"
      echo "                ${MOUT}"
      ESC_INCONCLUSIVE=$((ESC_INCONCLUSIVE+1))
    fi
  elif ! ROUT="$(vx "$TESTTOK" vault write "auth/${ESC_MOUNT}/role/${ESC_ROLE}" \
          bound_service_account_names=probe bound_service_account_namespaces=probe \
          token_policies="$ESC_POLICY" ttl=1m 2>&1)"; then
    if denied "$ROUT"; then
      echo "  ok       DENIED binding $ESC_POLICY to an auth role — chain is blocked at the role"
    else
      echo "  INCONCLUSIVE  role write failed for a non-permission reason — NOT a clean bill:"
      echo "                ${ROUT}"
      ESC_INCONCLUSIVE=$((ESC_INCONCLUSIVE+1))
    fi
  else
    GOT="$(vx "$BGT" vault read -format=json "auth/${ESC_MOUNT}/role/${ESC_ROLE}" 2>/dev/null | jq -r '.data.token_policies|join(",")')"
    if grep -qw "$ESC_POLICY" <<<"$GOT"; then
      echo "  FINDING  auth role now confers $ESC_POLICY (token_policies: $GOT)"
      echo "           => a bound ServiceAccount logging in here receives KV WRITE."
      echo "              Read-only is enforced by the composition template, not by the policy boundary."
      ESC_FINDINGS=$((ESC_FINDINGS+1))
    elif [ -z "$GOT" ]; then
      echo "  INCONCLUSIVE  role created but could not be read back — verdict unknown, re-run"
      ESC_INCONCLUSIVE=$((ESC_INCONCLUSIVE+1))
    else
      echo "  ok       role created but does not carry $ESC_POLICY (token_policies: $GOT)"
    fi
  fi
else
  echo "  ok       okvc- policy write with a WRITE body was refused: $OUT"
fi

echo; echo "════════ RESULT ════════"
if ((ESC_FINDINGS>0)); then
  echo "BODY-SCOPING FINDINGS: $ESC_FINDINGS. The narrowing is still an improvement, so this does NOT block Step 2,"
  echo "  but the live probe confirms consumer read-only is a property of the composition template"
  echo "  (capabilities=[\"read\"]), not of the reconciler's policy boundary. Closing the boundary means"
  echo "  scoping policy CONTENTS as well as names — e.g. a Vault-side admission/sentinel control, or accepting"
  echo "  and documenting that provider-vault is trusted to confer any KV capability within okvc-*."
elif ((ESC_INCONCLUSIVE==0)); then
  echo "BODY SCOPING: no findings — every step was explicitly DENIED, so the reconciler identity"
  echo "  cannot confer KV write. This is a clean bill."
fi
if ((ESC_INCONCLUSIVE>0)); then
  echo "BODY SCOPING: INCONCLUSIVE ($ESC_INCONCLUSIVE step(s) failed for non-permission reasons)."
  echo "  This is NOT evidence the chain is blocked. Re-run; if it persists, diagnose the error above"
  echo "  before drawing any security conclusion — a collapsed failure reading as 'clean' is the"
  echo "  defect this section exists to avoid (cf. OK-124)."
fi
if ((FAILS==0)); then echo "A6 NARROWED POLICY VALIDATED — grants all reconciler ops, denies admin reach. Safe to apply to the live ok-config-automation (Step 2)."
else echo "A6 POLICY TEST FAILED — $FAILS assertion(s) failed. Do NOT apply the narrowed policy yet." >&2; exit 1; fi
