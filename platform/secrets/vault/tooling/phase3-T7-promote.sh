#!/usr/bin/env bash
# Phase 3 / 3D-3b T7-promote — promote the canonical STEADY-STATE revision on the ACTIVE XR.
# Because it renders desired resources identical to T5, promoting is a no-op for Crossplane: prove
# exactly 4 resourceRefs, all 4 keep-set UIDs unchanged, NO MR created or terminating, okvc- policy
# unchanged, legacy still absent, role okvc-, XR+MRs active, VSO + consumer unchanged. Fail-closed
# with emergency freeze (XR + 4 MRs) on abort. No Vault mutation.
set -Eeuo pipefail
SUCCESS=0; PROMOTION_STATE="NOT_STARTED"; NEWREV=""
MGMT_KUBECONFIG=~/.kube/ok-mgmt.yaml; SHARED_KUBECONFIG=~/.kube/ok-shared.yaml
ROBOTICS_KUBECONFIG=~/.kube/ok-robotics.yaml; VSO_SECRET_NS=ok-observability; VSO_SECRET_NAME=ok-observability-credentials
OLD_POLICY=ok-robotics-sa-obs; NEW_POLICY=okvc-ok-robotics-sa-obs
POLICY_RES=policies.vault.vault.upbound.io;              POLICY_MR=ok-robotics-ee43e699198c
ROLE_RES=authbackendroles.kubernetes.vault.upbound.io;   ROLE_MR=ok-robotics-6cae6fef03f6
CONF_RES=authbackendconfigs.kubernetes.vault.upbound.io; CONF_MR=ok-robotics-1cf8d3106f89
BACK_RES=backends.auth.vault.upbound.io;                 BACK_MR=ok-robotics-05b190692d43
NEW_MR=ok-robotics-f3f5cd82a670
GATE=/tmp/phase3-T7-gate.json; T6_DONE=/tmp/phase3-T6-done; DONE_FILE=/tmp/phase3-T7-done
export KUBECONFIG="$MGMT_KUBECONFIG"
freeze_all(){
  kubectl annotate vaultconfig ok-robotics crossplane.io/paused=true --overwrite >/dev/null 2>&1 || true
  for ref in "$BACK_RES $BACK_MR" "$CONF_RES $CONF_MR" "$ROLE_RES $ROLE_MR" "$POLICY_RES $NEW_MR"; do set -- $ref
    kubectl annotate "$1" "$2" crossplane.io/paused=true --overwrite >/dev/null 2>&1 || true; done
}
cleanup(){ local rc=$?; trap - EXIT; set +e
  if ((rc!=0 && SUCCESS==0)); then
    case "$PROMOTION_STATE" in
      NOT_STARTED) echo "RECOVERY: PROMOTION_NOT_STARTED — no runtime change was attempted; NO freeze." >&2 ;;
      ATTEMPTED)
        echo "RECOVERY: PROMOTION_ATTEMPTED — outcome uncertain; inspecting XR revisionRef before deciding." >&2
        local cur
        if cur="$(kubectl get vaultconfig ok-robotics -o jsonpath='{.spec.compositionRevisionRef.name}' 2>/dev/null)"; then
          if [[ "$cur" == "$NEWREV" ]]; then echo "RECOVERY: NEWREV persisted -> freezing to hold state for inspection." >&2; freeze_all
          else echo "RECOVERY: XR still on '$cur' (not NEWREV) -> promotion did not persist; NOT freezing." >&2; fi
        else echo "RECOVERY: cannot read XR revisionRef -> state undeterminable; freezing conservatively." >&2; freeze_all; fi ;;
      CONFIRMED) echo "RECOVERY: PROMOTION_CONFIRMED — a post-check failed; freezing to hold state for inspection." >&2; freeze_all ;;
    esac
  fi
  [[ -n "${BGT:-}" ]] && declare -F vault_exec >/dev/null && vault_exec "$BGT" vault token revoke -self >/dev/null 2>&1 || true
  unset BG BGT; exit "$rc"; }
trap cleanup EXIT
trap 'rc=$?; printf "ABORT: rc=%s at line %s\n" "$rc" "$LINENO" >&2; exit "$rc"' ERR

vault_exec(){ local t="$1"; shift; printf '%s\n' "$t" | kubectl --kubeconfig "$SHARED_KUBECONFIG" -n vault exec -i vault-0 -- sh -c 'IFS= read -r VAULT_TOKEN; export VAULT_TOKEN; exec "$@"' sh "$@"; }
new_policy_hash(){ vault_exec "$BGT" vault policy read "$NEW_POLICY" | shasum -a256 | awk '{print $1}'; }
mr_active_ok(){ kubectl get "$1" "$2" -o json | jq -e '(.metadata.annotations["crossplane.io/paused"]//"")!="true" and (.metadata.deletionTimestamp==null) and any(.status.conditions[]?; .type=="Synced" and .status=="True" and .reason=="ReconcileSuccess") and any(.status.conditions[]?; .type=="Ready" and .status=="True")' >/dev/null; }
xr_active_ok(){ kubectl get vaultconfig ok-robotics -o json | jq -e '(.metadata.annotations["crossplane.io/paused"]//"")!="true" and any(.status.conditions[]?; .type=="Synced" and .status=="True" and .reason=="ReconcileSuccess")' >/dev/null; }
legacy_absent(){ local out; if out="$(vault_exec "$BGT" vault policy read "$OLD_POLICY" 2>&1)"; then return 1; fi; grep -qiE 'no policy named|policy .* not found|policy .* does not exist' <<<"$out"; }
uid_of(){ kubectl get "$1" "$2" -o jsonpath='{.metadata.uid}'; }
en_of(){ kubectl get "$1" "$2" -o jsonpath='{.metadata.annotations.crossplane\.io/external-name}'; }
vso_hash(){ kubectl --kubeconfig "$ROBOTICS_KUBECONFIG" -n "$VSO_SECRET_NS" get secret "$VSO_SECRET_NAME" -o json | jq -S -c '.data' | shasum -a256 | awk '{print $1}'; }
vso_health_gate(){
  kubectl --kubeconfig "$ROBOTICS_KUBECONFIG" -n "$VSO_SECRET_NS" get vaultauth ok-robotics -o json | jq -e '.status.valid==true and (([.status.conditions[]?|select(.status=="True")|.type]) as $ok | (["Healthy","Ready"]-$ok)==[])' >/dev/null || return 1
  kubectl --kubeconfig "$ROBOTICS_KUBECONFIG" -n "$VSO_SECRET_NS" get vaultstaticsecret "$VSO_SECRET_NAME" -o json | jq -e '([.status.conditions[]?|select(.status=="True")|.type]) as $ok | (["SecretSynced","Healthy","Ready"]-$ok)==[]' >/dev/null || return 1
}
four_keep_refs(){ local got exp
  got="$(kubectl get vaultconfig ok-robotics -o json | jq -r '.spec.resourceRefs[]|[.apiVersion,.kind,.name]|@tsv' | sort)"
  exp="$(printf '%s\n' "auth.vault.upbound.io/v1alpha1"$'\t'"Backend"$'\t'"$BACK_MR" "kubernetes.vault.upbound.io/v1alpha1"$'\t'"AuthBackendConfig"$'\t'"$CONF_MR" "kubernetes.vault.upbound.io/v1alpha1"$'\t'"AuthBackendRole"$'\t'"$ROLE_MR" "vault.vault.upbound.io/v1alpha1"$'\t'"Policy"$'\t'"$NEW_MR" | sort)"
  [[ "$got" == "$exp" ]]; }
no_mr_terminating(){ for pair in "$BACK_RES $BACK_MR" "$CONF_RES $CONF_MR" "$ROLE_RES $ROLE_MR" "$POLICY_RES $NEW_MR"; do set -- $pair
  [[ -z "$(kubectl get "$1" "$2" -o jsonpath='{.metadata.deletionTimestamp}' 2>/dev/null)" ]] || return 1; done; }
old_mr_gone(){ local out; if ! out="$(kubectl get "$POLICY_RES" "$POLICY_MR" --ignore-not-found -o name 2>/dev/null)"; then echo "ERROR: cannot determine whether legacy MR exists" >&2; return 2; fi; [[ -z "$out" ]]; }

# ── gate + chain-of-custody ──
test -s "$GATE" || { echo "ABORT: T7 gate missing" >&2; exit 1; }
test -s "$T6_DONE" || { echo "ABORT: 3D-3a handoff missing" >&2; exit 1; }
COMP="$(jq -er '.composition' "$GATE")"; EXP_UID="$(jq -er '.compositionUID' "$GATE")"; OLDREV="$(jq -er '.oldRevision' "$GATE")"; NEWREV="$(jq -er '.newRevision' "$GATE")"; EXP_HASH="$(jq -er '.normalizedSpecSHA256' "$GATE")"; EXP_OKVC="$(jq -er '.okvcPolicySHA256' "$GATE")"
# chain-of-custody across script runs: validate the 3D-3a handoff and bind the T7 gate's okvc-
# baseline to it (the T7 gate's okvcPolicySHA256 must equal the T6 done marker's remainingPolicySHA256)
jq -e '.deletedPolicy=="ok-robotics-sa-obs" and .remainingPolicy=="okvc-ok-robotics-sa-obs" and .noReferencesProven==true and .crossplaneMRAbsent==true' "$T6_DONE" >/dev/null || { echo "ABORT: invalid 3D-3a handoff (T6 done marker)" >&2; exit 1; }
[[ "$(jq -er '.remainingPolicySHA256' "$T6_DONE")" == "$EXP_OKVC" ]] || { echo "ABORT: T7 gate is not bound to the T6 policy baseline" >&2; exit 1; }
[[ "$(kubectl get vaultconfig ok-robotics -o jsonpath='{.spec.compositionUpdatePolicy}')" == "Manual" ]] || { echo "ABORT: XR not Manual" >&2; exit 1; }
[[ "$(kubectl get composition "$COMP" -o jsonpath='{.metadata.uid}')" == "$EXP_UID" ]] || { echo "ABORT: composition identity changed" >&2; exit 1; }
[[ "$(kubectl get vaultconfig ok-robotics -o jsonpath='{.spec.compositionRevisionRef.name}')" == "$OLDREV" ]] || { echo "ABORT: XR not on reviewed T5 revision" >&2; exit 1; }
[[ "$(kubectl get vaultconfig ok-robotics -o jsonpath='{.metadata.annotations.crossplane\.io/paused}')" != "true" ]] || { echo "ABORT: XR paused — expected ACTIVE" >&2; exit 1; }
[[ "$(kubectl get compositionrevision "$NEWREV" -o json | jq -S '.spec|del(.revision)' | shasum -a256 | awk '{print $1}')" == "$EXP_HASH" ]] || { echo "ABORT: reviewed T7 revision content changed" >&2; exit 1; }

# ── break-glass ──
read -rsp 'Vault break-glass password: ' BG; printf '\n'
BGT="$(printf '%s' "$BG" | jq -Rs '{password: .}' | kubectl --kubeconfig "$SHARED_KUBECONFIG" -n vault exec -i vault-0 -- sh -c '
  set -eu; umask 077; p="$(mktemp)"; trap "rm -f \"$p\"" EXIT; cat >"$p"; vault write -format=json auth/userpass/login/breakglass - <"$p"' | jq -er '.auth.client_token')"
unset BG; test -n "$BGT"; vault_exec "$BGT" vault token lookup >/dev/null; echo "BREAK-GLASS TOKEN OK"

# ── PRECONDITION (3D-3a end-state) + baselines ──
xr_active_ok || { echo "ABORT: XR not active before promote" >&2; exit 1; }
four_keep_refs || { echo "ABORT: resourceRefs != 4 keep MRs" >&2; exit 1; }
no_mr_terminating || { echo "ABORT: a keep-set MR is already terminating" >&2; exit 1; }
old_mr_gone || { echo "ABORT: legacy Crossplane MR present or unreadable before promote" >&2; exit 1; }
for pair in "$BACK_RES $BACK_MR" "$CONF_RES $CONF_MR" "$ROLE_RES $ROLE_MR" "$POLICY_RES $NEW_MR"; do set -- $pair
  mr_active_ok "$1" "$2" || { echo "ABORT: keep-set MR not active before promote: $2" >&2; exit 1; }; done
legacy_absent || { echo "ABORT: legacy policy present/undeterminable before promote" >&2; exit 1; }
[[ "$(new_policy_hash)" == "$EXP_OKVC" ]] || { echo "ABORT: okvc- policy hash != 3D-3a baseline" >&2; exit 1; }
vault_exec "$BGT" vault read -format=json auth/kubernetes/ok-robotics/role/sa-obs | jq -e '.data.token_policies==["okvc-ok-robotics-sa-obs"]' >/dev/null || { echo "ABORT: role not okvc-only" >&2; exit 1; }
vso_health_gate || { echo "ABORT: VSO not healthy before promote" >&2; exit 1; }
B_UID="$(uid_of "$BACK_RES" "$BACK_MR")"; C_UID="$(uid_of "$CONF_RES" "$CONF_MR")"; R_UID="$(uid_of "$ROLE_RES" "$ROLE_MR")"; N_UID="$(uid_of "$POLICY_RES" "$NEW_MR")"
for u in "$B_UID" "$C_UID" "$R_UID" "$N_UID"; do [[ -n "$u" ]] || { echo "ABORT: missing keep-set UID" >&2; exit 1; }; done
VSO_BEFORE="$(vso_hash)"
echo "3D-3b PRECONDITION RECONFIRMED (3D-3a end-state; 4 refs; 4 UIDs; legacy absent; okvc- baseline; VSO healthy)"

# ── PROMOTE on the active XR — take the baseline resourceVersion ATOMICALLY from the patch response
#    (a later reconcile between patch and a separate GET could otherwise be captured as the baseline,
#    making the fresh-reconcile wait time out on a healthy state and freeze unnecessarily). ──
PROMOTION_STATE="ATTEMPTED"
PATCH_JSON="$(kubectl patch vaultconfig ok-robotics --type=merge -p "{\"spec\":{\"compositionRevisionRef\":{\"name\":\"$NEWREV\"}}}" -o json)"
jq -e --arg rev "$NEWREV" '.spec.compositionRevisionRef.name==$rev and (.metadata.resourceVersion|type=="string")' <<<"$PATCH_JSON" >/dev/null || { echo "ABORT: patch response does not confirm NEWREV" >&2; exit 1; }
PATCHED_RV="$(jq -er '.metadata.resourceVersion' <<<"$PATCH_JSON")"
[[ "$(jq -r '.metadata.annotations["crossplane.io/paused"] // ""' <<<"$PATCH_JSON")" != "true" ]] || { echo "ABORT: XR unexpectedly paused in patch response" >&2; exit 1; }
PROMOTION_STATE="CONFIRMED"
echo "STEADY REVISION PROMOTED (XR active; NEWREV persisted; baseline rv=$PATCHED_RV)"

# ── wait for a GENUINELY NEW reconciliation of the promoted revision (resourceVersion must advance
#    past the patch-response baseline, so a stale pre-existing Synced=True is not mistaken for it) ──
deadline=$((SECONDS+120)); RECONCILED=0
while ((SECONDS<deadline)); do
  XR_JSON="$(kubectl get vaultconfig ok-robotics -o json)"
  CUR_RV="$(jq -r '.metadata.resourceVersion' <<<"$XR_JSON")"
  if [[ "$CUR_RV" != "$PATCHED_RV" ]] && jq -e --arg rev "$NEWREV" '.spec.compositionRevisionRef.name==$rev and any(.status.conditions[]?; .type=="Synced" and .status=="True" and .reason=="ReconcileSuccess")' <<<"$XR_JSON" >/dev/null; then RECONCILED=1; break; fi
  sleep 3
done
((RECONCILED==1)) || { echo "ABORT: XR did not show a fresh ReconcileSuccess for the promoted revision (resourceVersion did not advance)" >&2; exit 1; }
echo "XR RECONCILED FRESH (resourceVersion advanced past the patch; on NEWREV; ReconcileSuccess)"
four_keep_refs || { echo "ABORT: resourceRefs changed after promote" >&2; exit 1; }
no_mr_terminating || { echo "ABORT: a keep-set MR started terminating after promote" >&2; exit 1; }
old_mr_gone || { echo "ABORT: a legacy Crossplane MR reappeared or is unreadable after promote" >&2; exit 1; }
[[ "$(uid_of "$BACK_RES" "$BACK_MR")" == "$B_UID" && "$(uid_of "$CONF_RES" "$CONF_MR")" == "$C_UID" && "$(uid_of "$ROLE_RES" "$ROLE_MR")" == "$R_UID" && "$(uid_of "$POLICY_RES" "$NEW_MR")" == "$N_UID" ]] || { echo "ABORT: a keep-set MR identity changed (unexpected recreate)" >&2; exit 1; }
[[ "$(en_of "$POLICY_RES" "$NEW_MR")" == "$NEW_POLICY" ]] || { echo "ABORT: okvc- external-name drifted" >&2; exit 1; }
kubectl get "$POLICY_RES" "$NEW_MR" -o json | jq -e '.spec.managementPolicies==["*"]' >/dev/null || { echo "ABORT: okvc- MR not full-management" >&2; exit 1; }
for pair in "$BACK_RES $BACK_MR" "$CONF_RES $CONF_MR" "$ROLE_RES $ROLE_MR" "$POLICY_RES $NEW_MR"; do set -- $pair
  mr_active_ok "$1" "$2" || { echo "ABORT: keep-set MR not active after promote: $2" >&2; exit 1; }; done
echo "KEEP-SET UNCHANGED (4 refs; 4 UIDs stable; none terminating; okvc- external-name + full-mgmt intact)"

# ── Vault + consumer untouched ──
legacy_absent || { echo "ABORT: legacy policy reappeared after promote" >&2; exit 1; }
[[ "$(new_policy_hash)" == "$EXP_OKVC" ]] || { echo "ABORT: okvc- policy content changed after promote" >&2; exit 1; }
vault_exec "$BGT" vault read -format=json auth/kubernetes/ok-robotics/role/sa-obs | jq -e '.data.token_policies==["okvc-ok-robotics-sa-obs"]' >/dev/null || { echo "ABORT: role drifted off okvc- after promote" >&2; exit 1; }
vso_health_gate || { echo "ABORT: VSO unhealthy after promote" >&2; exit 1; }
[[ "$(vso_hash)" == "$VSO_BEFORE" ]] || { echo "ABORT: consumer Secret changed after promote" >&2; exit 1; }
echo "VAULT + CONSUMER UNCHANGED (legacy absent; okvc- hash-equal; role okvc-; VSO intact; Secret bytes unchanged)"

vault_exec "$BGT" vault token revoke -self >/dev/null; unset BGT; echo "BREAK-GLASS TOKEN REVOKED"
DONE_TMP="$(mktemp /tmp/phase3-T7-done.XXXXXX)"
jq -n --arg steadyRevision "$NEWREV" --arg compositionUID "$EXP_UID" --arg normalizedSpecSHA256 "$EXP_HASH" --arg remainingPolicySHA256 "$EXP_OKVC" \
  '{steadyRevision:$steadyRevision,compositionUID:$compositionUID,normalizedSpecSHA256:$normalizedSpecSHA256,resourceRefs:4,resourceUIDsStable:true,legacyPolicyAbsent:true,remainingPolicySHA256:$remainingPolicySHA256,consumerSecretUnchanged:true}' > "$DONE_TMP"
mv "$DONE_TMP" "$DONE_FILE"
SUCCESS=1
echo "PHASE 3 3D-3b DONE (steady-state composition promoted; render identical; nothing created/terminated; A6 migration fully closed). steadyRevision=$NEWREV"
