#!/usr/bin/env bash
# A6 Step 2 — narrow the LIVE ok-config-automation policy to the reserved-prefix least-privilege set,
# and PROVE the reconciler still writes okvc- policies with it (Vault evaluates ACL policies by name
# at request time, so the provider's existing token gets the narrowed rights immediately — no restart).
# Fail-closed with AUTOMATIC ROLLBACK: if the reconciler cannot restore an injected okvc- drift with
# the narrowed policy, the original (archived) policy is re-applied and the okvc- policy restored.
set -Eeuo pipefail
SUCCESS=0; NARROW_STATE="NOT_APPLIED"; DRIFT_APPLIED=0; DRIFT_RESTORED=0; BROAD_ARCHIVE=""; BASELINE_HCL=""
MGMT_KUBECONFIG=~/.kube/ok-mgmt.yaml; SHARED_KUBECONFIG=~/.kube/ok-shared.yaml
BG_LOGIN_PATH=auth/userpass/login/breakglass
AUTOMATION_POLICY=ok-config-automation
OKVC_POLICY=okvc-ok-robotics-sa-obs
POLICY_RES=policies.vault.vault.upbound.io;              NEW_MR=ok-robotics-f3f5cd82a670
ROLE_RES=authbackendroles.kubernetes.vault.upbound.io;   ROLE_MR=ok-robotics-6cae6fef03f6
CONF_RES=authbackendconfigs.kubernetes.vault.upbound.io; CONF_MR=ok-robotics-1cf8d3106f89
BACK_RES=backends.auth.vault.upbound.io;                 BACK_MR=ok-robotics-05b190692d43
DONE_FILE=/tmp/a6-apply-narrow-done
export KUBECONFIG="$MGMT_KUBECONFIG"

vx(){ local t="$1"; shift; printf '%s\n' "$t" | kubectl --kubeconfig "$SHARED_KUBECONFIG" -n vault exec -i vault-0 -- sh -c 'IFS= read -r VAULT_TOKEN; export VAULT_TOKEN; exec "$@"' sh "$@"; }
bg_policy_write(){ local name="$1" file="$2"; { printf '%s\n' "$BGT"; cat "$file"; } | kubectl --kubeconfig "$SHARED_KUBECONFIG" -n vault exec -i vault-0 -- sh -c '
  set -eu; IFS= read -r VAULT_TOKEN; export VAULT_TOKEN; umask 077; p="$(mktemp)"; trap "rm -f \"$p\"" EXIT; cat >"$p"; vault policy write "$1" "$p"' sh "$name" >/dev/null; }
pol_read(){ vx "$BGT" vault policy read "$1"; }
okvc_hash(){ pol_read "$OKVC_POLICY" | shasum -a256 | awk '{print $1}'; }
mr_ok(){ kubectl get "$1" "$2" -o json | jq -e 'any(.status.conditions[]?; .type=="Synced" and .status=="True" and .reason=="ReconcileSuccess") and any(.status.conditions[]?; .type=="Ready" and .status=="True")' >/dev/null; }
mr_bad(){ kubectl get "$1" "$2" -o json | jq -e 'any(.status.conditions[]?; (.reason//"")=="AsyncUpdateFailure" or ((.message//"")|test("permission denied|403";"i")))' >/dev/null; }
xr_ok(){ kubectl get vaultconfig ok-robotics -o json | jq -e 'any(.status.conditions[]?; .type=="Synced" and .status=="True" and .reason=="ReconcileSuccess")' >/dev/null; }
keepset_ok(){ for pr in "$BACK_RES $BACK_MR" "$CONF_RES $CONF_MR" "$ROLE_RES $ROLE_MR" "$POLICY_RES $NEW_MR"; do set -- $pr; mr_ok "$1" "$2" || return 1; done; }

rollback_policy(){ [[ -n "${BROAD_ARCHIVE:-}" && -s "$BROAD_ARCHIVE" && -n "${BGT:-}" ]] || return 1
  echo "ROLLBACK: re-applying the original ok-config-automation policy" >&2
  bg_policy_write "$AUTOMATION_POLICY" "$BROAD_ARCHIVE" && [[ "$(pol_read "$AUTOMATION_POLICY" | shasum -a256 | awk '{print $1}')" == "$BROAD_SHA" ]]; }
cleanup(){ local rc=$?; trap - EXIT; set +e
  # 1) if we injected a drift into the okvc- policy and it wasn't restored, put it back from baseline
  if ((DRIFT_APPLIED==1 && DRIFT_RESTORED==0)) && [[ -n "${BGT:-}" && -s "${BASELINE_HCL:-}" ]]; then
    echo "EMERGENCY: restoring okvc- policy from baseline" >&2
    bg_policy_write "$OKVC_POLICY" "$BASELINE_HCL" && [[ "$(okvc_hash)" == "$OKVC_SHA" ]] && echo "  okvc- restored" >&2 || echo "  CRITICAL: okvc- restore not verified — restore from $BASELINE_HCL" >&2
  fi
  # 2) if we narrowed the policy but did not confirm the write path, roll the policy back to original
  if ((rc!=0 && SUCCESS==0)) && [[ "$NARROW_STATE" == "APPLIED" ]]; then
    if rollback_policy; then echo "ROLLBACK OK: automation policy restored to original; reconciler authority intact." >&2
    else echo "CRITICAL: automation policy rollback NOT verified — manually restore $AUTOMATION_POLICY from $BROAD_ARCHIVE" >&2; fi
  fi
  [[ -n "${BGT:-}" ]] && vx "$BGT" vault token revoke -self >/dev/null 2>&1
  unset BG BGT; exit "$rc"; }
trap cleanup EXIT
trap 'rc=$?; printf "ABORT: rc=%s at line %s\n" "$rc" "$LINENO" >&2; exit "$rc"' ERR

# ── A6 narrowed target policy ──
NARROW_HCL="$(mktemp /tmp/a6-narrowed.XXXXXX)"; cat > "$NARROW_HCL" <<'HCL'
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

# ── R0 baseline (archive current policy + confirm reconciler healthy) ──
vx "$BGT" vault read -format=json auth/kubernetes/ok-mgmt/role/provider-vault | jq -e '.data.token_policies==["ok-config-automation"]' >/dev/null || { echo "ABORT: reconciler role not bound to ok-config-automation" >&2; exit 1; }
BROAD_ARCHIVE="$(mktemp /tmp/ok-config-automation.orig.XXXXXX)"; ( umask 077; pol_read "$AUTOMATION_POLICY" > "$BROAD_ARCHIVE" ); test -s "$BROAD_ARCHIVE" || { echo "ABORT: could not archive current policy" >&2; exit 1; }
BROAD_SHA="$(shasum -a256 "$BROAD_ARCHIVE" | awk '{print $1}')"
BASELINE_HCL="$(mktemp /tmp/okvc-baseline.XXXXXX)"; ( umask 077; pol_read "$OKVC_POLICY" > "$BASELINE_HCL" ); OKVC_SHA="$(okvc_hash)"
keepset_ok || { echo "ABORT: keep-set not all ReconcileSuccess at baseline" >&2; exit 1; }
xr_ok || { echo "ABORT: XR not ReconcileSuccess at baseline" >&2; exit 1; }
grep -q 'sys/policies/acl/\*' "$BROAD_ARCHIVE" && echo "R0 BASELINE OK (current policy is the BROAD seed; archived $BROAD_ARCHIVE; reconciler healthy)" || echo "R0 BASELINE OK (current policy archived $BROAD_ARCHIVE; reconciler healthy)"

# ── R1 apply the narrowed policy ──
NARROW_STATE="APPLIED"
bg_policy_write "$AUTOMATION_POLICY" "$NARROW_HCL"
pol_read "$AUTOMATION_POLICY" | grep -q 'sys/policies/acl/okvc-\*' || { echo "ABORT: narrowed policy not present after write" >&2; exit 1; }
pol_read "$AUTOMATION_POLICY" | grep -q 'sys/policies/acl/\*"' && { echo "ABORT: broad sys/policies/acl/* still present after narrowing" >&2; exit 1; } || true
echo "R1 NARROWED POLICY APPLIED (ok-config-automation -> okvc-* scoped; broad grant removed)"

# ── R2 LIVE write-path proof: inject an okvc- drift, the reconciler (narrowed policy) must restore it ──
DRIFT_FILE="$(mktemp /tmp/okvc-drift.XXXXXX)"; ( umask 077; cat "$BASELINE_HCL" > "$DRIFT_FILE"; printf '\npath "okvc-a6-live-drift/inert" { capabilities = ["deny"] }\n' >> "$DRIFT_FILE" )
bg_policy_write "$OKVC_POLICY" "$DRIFT_FILE"; DRIFT_APPLIED=1; rm -f "$DRIFT_FILE"
[[ "$(okvc_hash)" != "$OKVC_SHA" ]] || { echo "ABORT: drift write did not change the policy (test invalid)" >&2; exit 1; }
echo "R2 DRIFT INJECTED (okvc- policy changed; triggering reconcile)"
kubectl annotate "$POLICY_RES" "$NEW_MR" openkubes.ai/a6-drift-probe-at="$(date -u +%FT%TZ)" --overwrite >/dev/null
deadline=$((SECONDS+300))
until [[ "$(okvc_hash)" == "$OKVC_SHA" ]] && mr_ok "$POLICY_RES" "$NEW_MR"; do
  if mr_bad "$POLICY_RES" "$NEW_MR"; then echo "ABORT: okvc- MR hit permission-denied/AsyncUpdateFailure with the narrowed policy" >&2; exit 1; fi
  (( SECONDS>=deadline )) && { echo "ABORT: reconciler did not restore okvc- drift within deadline (narrowed policy insufficient?)" >&2; exit 1; }; sleep 5; done
DRIFT_RESTORED=1
kubectl annotate "$POLICY_RES" "$NEW_MR" openkubes.ai/a6-drift-probe-at- >/dev/null 2>&1 || true
keepset_ok || { echo "ABORT: a keep-set MR not ReconcileSuccess after the narrowed-policy reconcile" >&2; exit 1; }
xr_ok || { echo "ABORT: XR not ReconcileSuccess after narrowing" >&2; exit 1; }
NARROW_STATE="WRITE_PROVEN"
echo "R2 WRITE PATH PROVEN (reconciler restored the okvc- drift using the NARROWED policy; 4 MRs + XR ReconcileSuccess)"

# ── success ──
vx "$BGT" vault token revoke -self >/dev/null; unset BGT
DONE_TMP="$(mktemp /tmp/a6-apply-narrow-done.XXXXXX)"
jq -n --arg at "$(date -u +%FT%TZ)" --arg sha "$(shasum -a256 "$NARROW_HCL" | awk '{print $1}')" \
  '{policy:"ok-config-automation",narrowedAt:$at,narrowedHCL_SHA256:$sha,scope:"sys/policies/acl/okvc-* + kubernetes/* (self ok-mgmt denied)",reconcilerWriteProven:true,fourMRsReconcileSuccess:true}' > "$DONE_TMP"
mv "$DONE_TMP" "$DONE_FILE"
SUCCESS=1
echo "A6 STEP 2 DONE — ok-config-automation narrowed to least-privilege okvc-* scope; live reconciler write path proven; automation identity can no longer reach admin policies or its own auth mount. Done marker: $DONE_FILE"
