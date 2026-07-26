#!/usr/bin/env bash
# Phase 3 / T1-import (hardened) — promote T1 (paused XR), render+verify identities,
# re-pause XR, unpause ONLY the new okvc- Policy MR, prove Observe-only import, re-pause it.
# XR + all 5 MRs remain paused at the end. Full management (Observe->"*") is T2. Fail-closed.
set -Eeuo pipefail
SUCCESS=0
MGMT_KUBECONFIG=~/.kube/ok-mgmt.yaml; SHARED_KUBECONFIG=~/.kube/ok-shared.yaml
OLD_POLICY=ok-robotics-sa-obs; NEW_POLICY=okvc-ok-robotics-sa-obs
POLICY_RES=policies.vault.vault.upbound.io;              POLICY_MR=ok-robotics-ee43e699198c
ROLE_RES=authbackendroles.kubernetes.vault.upbound.io;   ROLE_MR=ok-robotics-6cae6fef03f6
CONF_RES=authbackendconfigs.kubernetes.vault.upbound.io; CONF_MR=ok-robotics-1cf8d3106f89
BACK_RES=backends.auth.vault.upbound.io;                 BACK_MR=ok-robotics-05b190692d43
GATE=/tmp/phase3-T1-gate.json
export KUBECONFIG="$MGMT_KUBECONFIG"
NEW_MR=""
freeze_all(){
  kubectl annotate vaultconfig ok-robotics crossplane.io/paused=true --overwrite >/dev/null 2>&1 || true
  for ref in "$POLICY_RES $POLICY_MR" "$ROLE_RES $ROLE_MR" "$CONF_RES $CONF_MR" "$BACK_RES $BACK_MR"; do set -- $ref
    kubectl annotate "$1" "$2" crossplane.io/paused=true --overwrite >/dev/null 2>&1 || true; done
  [[ -n "$NEW_MR" ]] && kubectl annotate "$POLICY_RES" "$NEW_MR" crossplane.io/paused=true --overwrite >/dev/null 2>&1 || true
}
cleanup(){ local rc=$?; trap - EXIT; set +e
  if ((rc!=0 && SUCCESS==0)); then echo "EMERGENCY FREEZE: re-pausing XR and all T1 MRs" >&2; freeze_all; fi
  [[ -n "${BGT:-}" ]] && declare -F vault_exec >/dev/null && vault_exec "$BGT" vault token revoke -self >/dev/null 2>&1 || true
  unset BG BGT; exit "$rc"; }
trap cleanup EXIT
trap 'rc=$?; printf "ABORT: rc=%s at line %s\n" "$rc" "$LINENO" >&2; exit "$rc"' ERR

vault_exec(){ local t="$1"; shift; printf '%s\n' "$t" | kubectl --kubeconfig "$SHARED_KUBECONFIG" -n vault exec -i vault-0 -- sh -c 'IFS= read -r VAULT_TOKEN; export VAULT_TOKEN; exec "$@"' sh "$@"; }
mr_ready(){ kubectl get "$1" "$2" -o json | jq -e 'any(.status.conditions[]?; .type=="Synced" and .status=="True" and .reason=="ReconcileSuccess") and any(.status.conditions[]?; .type=="Ready" and .status=="True")' >/dev/null; }
en_of(){ kubectl get "$1" "$2" -o jsonpath='{.metadata.annotations.crossplane\.io/external-name}'; }
uid_of(){ kubectl get "$1" "$2" -o jsonpath='{.metadata.uid}'; }
paused_confirmed(){ kubectl get "$@" -o json | jq -e '.metadata.annotations["crossplane.io/paused"]=="true" and any(.status.conditions[]?; .type=="Synced" and .status=="False" and .reason=="ReconcilePaused")' >/dev/null; }
creation_state(){ kubectl get "$1" "$2" -o json | jq -c '{pending:(.metadata.annotations["crossplane.io/external-create-pending"]//""),succeeded:(.metadata.annotations["crossplane.io/external-create-succeeded"]//""),failed:(.metadata.annotations["crossplane.io/external-create-failed"]//"")}'; }
creation_state_safe(){ jq -e '(.pending=="") or (([.succeeded,.failed]|max)!="" and ([.succeeded,.failed]|max) >= .pending)' >/dev/null; }
policy_hash(){ vault_exec "$BGT" vault policy read "$NEW_POLICY" | shasum -a256 | awk '{print $1}'; }
discover_okvc_policy_mrs(){ local name
  while IFS= read -r name; do [[ -n "$name" ]] || continue
    [[ "$(en_of "$POLICY_RES" "$name")" == "$NEW_POLICY" ]] && printf '%s\n' "$name"
  done < <(kubectl get vaultconfig ok-robotics -o json | jq -r '.spec.resourceRefs[]|select(.apiVersion=="vault.vault.upbound.io/v1alpha1" and .kind=="Policy")|.name'); }
check_five_refs(){ local got exp
  got="$(kubectl get vaultconfig ok-robotics -o json | jq -r '.spec.resourceRefs[]|[.apiVersion,.kind,.name]|@tsv' | sort)"
  exp="$(printf '%s\n' \
    "auth.vault.upbound.io/v1alpha1"$'\t'"Backend"$'\t'"$BACK_MR" \
    "kubernetes.vault.upbound.io/v1alpha1"$'\t'"AuthBackendConfig"$'\t'"$CONF_MR" \
    "kubernetes.vault.upbound.io/v1alpha1"$'\t'"AuthBackendRole"$'\t'"$ROLE_MR" \
    "vault.vault.upbound.io/v1alpha1"$'\t'"Policy"$'\t'"$POLICY_MR" \
    "vault.vault.upbound.io/v1alpha1"$'\t'"Policy"$'\t'"$NEW_MR" | sort)"
  [[ "$got" == "$exp" ]] || { echo "ABORT: unexpected resourceRefs" >&2; echo "--expected--" >&2; printf '%s\n' "$exp" >&2; echo "--actual--" >&2; printf '%s\n' "$got" >&2; return 1; }; }

# ── gate file present + clear stale T2 handoff ──
test -s "$GATE" || { echo "ABORT: T1 gate file missing or empty" >&2; exit 1; }
NEWMR_FILE=/tmp/phase3-T1-newmr; rm -f "$NEWMR_FILE"

# ── Manual re-check (another XR may have appeared) ──
COMP="$(jq -er '.composition' "$GATE")"
[[ "$(kubectl get vaultconfig ok-robotics -o jsonpath='{.spec.compositionUpdatePolicy}')" == "Manual" ]] || { echo "ABORT: XR not Manual" >&2; exit 1; }
kubectl get vaultconfig -A -o json | jq -e --arg comp "$COMP" '[.items[]|select((.spec.compositionRef.name // "")==$comp and (.spec.compositionUpdatePolicy // "Automatic")!="Manual")]|length==0' >/dev/null || { echo "ABORT: an Automatic XR uses this Composition" >&2; exit 1; }

# ── break-glass ──
read -rsp 'Vault break-glass password: ' BG; printf '\n'
BGT="$(printf '%s' "$BG" | jq -Rs '{password: .}' | kubectl --kubeconfig "$SHARED_KUBECONFIG" -n vault exec -i vault-0 -- sh -c '
  set -eu; umask 077; p="$(mktemp)"; trap "rm -f \"$p\"" EXIT; cat >"$p"; vault write -format=json auth/userpass/login/breakglass - <"$p"' | jq -er '.auth.client_token')"
unset BG; test -n "$BGT"
vault_exec "$BGT" vault token lookup >/dev/null || { echo "ABORT: break-glass lookup failed" >&2; exit 1; }
echo "BREAK-GLASS TOKEN OK"

# ── PRECONDITION + PROMOTE ──
EXP_UID="$(jq -er '.compositionUID' "$GATE")"; OLDREV="$(jq -er '.oldRevision' "$GATE")"; NEWREV="$(jq -er '.newRevision' "$GATE")"; EXP_HASH="$(jq -er '.normalizedSpecSHA256' "$GATE")"
[[ "$(kubectl get composition "$COMP" -o jsonpath='{.metadata.uid}')" == "$EXP_UID" ]] || { echo "ABORT: composition identity changed" >&2; exit 1; }
[[ "$(kubectl get vaultconfig ok-robotics -o jsonpath='{.spec.compositionRevisionRef.name}')" == "$OLDREV" ]] || { echo "ABORT: XR not on reviewed old revision" >&2; exit 1; }
paused_confirmed vaultconfig ok-robotics || { echo "ABORT: XR not ReconcilePaused" >&2; exit 1; }
[[ "$(kubectl get compositionrevision "$NEWREV" -o json | jq -S '.spec|del(.revision)' | shasum -a256 | awk '{print $1}')" == "$EXP_HASH" ]] || { echo "ABORT: reviewed revision content changed" >&2; exit 1; }

# ── full frozen precondition RE-CONFIRMED (time may have passed since T1-apply/review) ──
for pair in "$POLICY_RES $POLICY_MR" "$ROLE_RES $ROLE_MR" "$CONF_RES $CONF_MR" "$BACK_RES $BACK_MR"; do set -- $pair
  paused_confirmed "$1" "$2" || { echo "ABORT: existing MR not ReconcilePaused before T1: $2" >&2; exit 1; }; done
vault_exec "$BGT" vault read -format=json auth/kubernetes/ok-robotics/role/sa-obs | jq -e '.data.token_policies==["okvc-ok-robotics-sa-obs"]' >/dev/null || { echo "ABORT: Vault role no longer okvc-only" >&2; exit 1; }
POL="$(vault_exec "$BGT" vault policy list)"
grep -Fxq "$OLD_POLICY" <<<"$POL" || { echo "ABORT: old Vault policy missing before T1" >&2; exit 1; }
grep -Fxq "$NEW_POLICY" <<<"$POL" || { echo "ABORT: okvc Vault policy missing before T1" >&2; exit 1; }
kubectl get "$POLICY_RES" "$POLICY_MR" -o json | jq -e --arg old "$OLD_POLICY" --arg new "$NEW_POLICY" \
  '.metadata.annotations["crossplane.io/paused"]=="true" and .metadata.annotations["crossplane.io/external-name"]==$old and .spec.forProvider.name==$new and any(.status.conditions[]?; .type=="LastAsyncOperation" and .reason=="AsyncUpdateFailure")' >/dev/null \
  || { echo "ABORT: legacy Policy MR state changed since T1 review" >&2; exit 1; }
PRE_REFS="$(kubectl get vaultconfig ok-robotics -o json | jq -r '.spec.resourceRefs[]|[.apiVersion,.kind,.name]|@tsv' | sort)"
EXP_PRE_REFS="$(printf '%s\n' \
  "auth.vault.upbound.io/v1alpha1"$'\t'"Backend"$'\t'"$BACK_MR" \
  "kubernetes.vault.upbound.io/v1alpha1"$'\t'"AuthBackendConfig"$'\t'"$CONF_MR" \
  "kubernetes.vault.upbound.io/v1alpha1"$'\t'"AuthBackendRole"$'\t'"$ROLE_MR" \
  "vault.vault.upbound.io/v1alpha1"$'\t'"Policy"$'\t'"$POLICY_MR" | sort)"
[[ "$PRE_REFS" == "$EXP_PRE_REFS" ]] || { echo "ABORT: pre-T1 resource set changed since review" >&2; exit 1; }
echo "T1 IMPORT PRECONDITION RECONFIRMED"

P_UID="$(uid_of "$POLICY_RES" "$POLICY_MR")"; R_UID="$(uid_of "$ROLE_RES" "$ROLE_MR")"; C_UID="$(uid_of "$CONF_RES" "$CONF_MR")"; B_UID="$(uid_of "$BACK_RES" "$BACK_MR")"
POLICY_HASH_BEFORE="$(policy_hash)"
kubectl patch vaultconfig ok-robotics --type=merge -p "{\"spec\":{\"compositionRevisionRef\":{\"name\":\"$NEWREV\"}}}"
[[ "$(kubectl get vaultconfig ok-robotics -o jsonpath='{.spec.compositionRevisionRef.name}')" == "$NEWREV" ]] || { echo "ABORT: promotion not persisted" >&2; exit 1; }
paused_confirmed vaultconfig ok-robotics || { echo "ABORT: XR unexpectedly unpaused after promote" >&2; exit 1; }
echo "T1 REVISION PROMOTED (XR still paused)"

# ── XR unpause -> render -> verify -> re-pause ──
kubectl annotate vaultconfig ok-robotics crossplane.io/paused-
deadline=$((SECONDS+120))
until
  kubectl get "$POLICY_RES" "$POLICY_MR" -o json | jq -e '.metadata.annotations["crossplane.io/paused"]=="true" and (.spec.forProvider.name=="ok-robotics-sa-obs")' >/dev/null \
  && kubectl get "$ROLE_RES" "$ROLE_MR" -o json | jq -e '.metadata.annotations["crossplane.io/paused"]=="true" and (.spec.forProvider.tokenPolicies==["okvc-ok-robotics-sa-obs"])' >/dev/null \
  && { mapfile -t OKVC_MRS < <(discover_okvc_policy_mrs); ((${#OKVC_MRS[@]}==1)); }
do (( SECONDS>=deadline )) && { echo "ABORT: T1 render did not converge uniquely" >&2; exit 1; }; sleep 2; done
NEW_MR="${OKVC_MRS[0]}"
[[ "$NEW_MR" != "$POLICY_MR" ]] || { echo "ABORT: new Policy MR collides with legacy MR" >&2; exit 1; }
echo "RENDER PROVEN (old reverted+paused; unique new okvc- MR $NEW_MR)"
# legacy MR fully consistent on the OLD identity (resolves the prior ForceNew conflict declaratively)
kubectl get "$POLICY_RES" "$POLICY_MR" -o json | jq -e --arg old "$OLD_POLICY" \
  '.metadata.annotations["crossplane.io/paused"]=="true" and .metadata.annotations["crossplane.io/external-name"]==$old and .spec.managementPolicies==["*"] and .spec.forProvider.name==$old' >/dev/null \
  || { echo "ABORT: legacy Policy MR did not return to a consistent old identity" >&2; exit 1; }
echo "LEGACY POLICY MR CONSISTENT (external-name and desired name old; ForceNew diff removed)"
# exactly the five expected resourceRefs, nothing extra
check_five_refs || { echo "ABORT: T1 resource set verification failed" >&2; exit 1; }
echo "T1 RESOURCE SET CONFIRMED (exactly 5 expected MRs)"
kubectl get "$POLICY_RES" "$NEW_MR" -o json | jq -e '.metadata.annotations["crossplane.io/paused"]=="true" and .spec.managementPolicies==["Observe"] and .spec.forProvider.name=="okvc-ok-robotics-sa-obs"' >/dev/null || { echo "ABORT: new MR not paused/Observe/okvc-" >&2; exit 1; }
[[ "$(en_of "$POLICY_RES" "$NEW_MR")" == "$NEW_POLICY" ]] || { echo "ABORT: new MR external-name != okvc-" >&2; exit 1; }
# identities: 4 existing unchanged; new UID distinct from all
[[ "$(uid_of "$POLICY_RES" "$POLICY_MR")" == "$P_UID" && "$(uid_of "$ROLE_RES" "$ROLE_MR")" == "$R_UID" && "$(uid_of "$CONF_RES" "$CONF_MR")" == "$C_UID" && "$(uid_of "$BACK_RES" "$BACK_MR")" == "$B_UID" ]] || { echo "ABORT: existing MR identity changed" >&2; exit 1; }
NEW_UID="$(uid_of "$POLICY_RES" "$NEW_MR")"; [[ -n "$NEW_UID" ]] || { echo "ABORT: new MR has no UID" >&2; exit 1; }
for u in "$P_UID" "$R_UID" "$C_UID" "$B_UID"; do [[ "$NEW_UID" != "$u" ]] || { echo "ABORT: new MR UID collides" >&2; exit 1; }; done
echo "IDENTITIES OK (4 existing UIDs stable; new MR distinct UID $NEW_UID)"
kubectl annotate vaultconfig ok-robotics crossplane.io/paused=true --overwrite
deadline=$((SECONDS+90)); until paused_confirmed vaultconfig ok-robotics; do (( SECONDS>=deadline )) && { echo "ABORT: XR re-pause not confirmed" >&2; exit 1; }; sleep 2; done
echo "XR CONFIRMED RE-PAUSED"

# ── Observe-import: prove the new MR's initial freeze was processed, then unpause ONLY it ──
deadline=$((SECONDS+90)); until paused_confirmed "$POLICY_RES" "$NEW_MR"; do (( SECONDS>=deadline )) && { echo "ABORT: new Policy MR never reached ReconcilePaused" >&2; exit 1; }; sleep 2; done
echo "NEW POLICY MR INITIAL FREEZE CONFIRMED"
NEW_CREATE_BEFORE="$(creation_state "$POLICY_RES" "$NEW_MR")"
creation_state_safe <<<"$NEW_CREATE_BEFORE" || { echo "ABORT: unsafe creation state before import: $NEW_CREATE_BEFORE" >&2; exit 1; }
kubectl annotate "$POLICY_RES" "$NEW_MR" crossplane.io/paused-
[[ -z "$(kubectl get "$POLICY_RES" "$NEW_MR" -o jsonpath='{.metadata.annotations.crossplane\.io/paused}')" ]] || { echo "ABORT: new MR still paused" >&2; exit 1; }
deadline=$((SECONDS+300)); until mr_ready "$POLICY_RES" "$NEW_MR"; do (( SECONDS>=deadline )) && { echo "ABORT: new MR not ReconcileSuccess/Ready (Observe import)" >&2; exit 1; }; sleep 5; done
[[ "$(en_of "$POLICY_RES" "$NEW_MR")" == "$NEW_POLICY" ]] || { echo "ABORT: new MR external-name drifted" >&2; exit 1; }
NEW_CREATE_AFTER="$(creation_state "$POLICY_RES" "$NEW_MR")"
creation_state_safe <<<"$NEW_CREATE_AFTER" || { echo "ABORT: unsafe creation state after import: $NEW_CREATE_AFTER" >&2; exit 1; }
[[ "$NEW_CREATE_AFTER" == "$NEW_CREATE_BEFORE" ]] || { echo "ABORT: create attempted during Observe import (before=$NEW_CREATE_BEFORE after=$NEW_CREATE_AFTER)" >&2; exit 1; }
[[ "$(policy_hash)" == "$POLICY_HASH_BEFORE" ]] || { echo "ABORT: okvc- policy content changed during import" >&2; exit 1; }
echo "OBSERVE IMPORT PROVEN (ReconcileSuccess, external-name okvc-, no create, policy hash unchanged)"

# ── re-pause new MR ──
kubectl annotate "$POLICY_RES" "$NEW_MR" crossplane.io/paused=true --overwrite
deadline=$((SECONDS+90)); until paused_confirmed "$POLICY_RES" "$NEW_MR"; do (( SECONDS>=deadline )) && { echo "ABORT: new MR re-pause not confirmed" >&2; exit 1; }; sleep 2; done
echo "NEW MR RE-PAUSED"

# ── FINAL FREEZE PROOF: exactly 5 refs + XR + 5 MRs ReconcilePaused ──
check_five_refs || { echo "ABORT: T1 resource set changed before final checkpoint" >&2; exit 1; }
echo "T1 RESOURCE SET STILL EXACTLY 5"
paused_confirmed vaultconfig ok-robotics || { echo "ABORT: XR not paused at checkpoint" >&2; exit 1; }
for ref in "$POLICY_RES $POLICY_MR" "$POLICY_RES $NEW_MR" "$ROLE_RES $ROLE_MR" "$CONF_RES $CONF_MR" "$BACK_RES $BACK_MR"; do set -- $ref
  paused_confirmed "$1" "$2" || { echo "ABORT: $2 not ReconcilePaused at checkpoint" >&2; exit 1; }; done
echo "FINAL T1 FREEZE CONFIRMED (XR + 5 MRs ReconcilePaused)"

vault_exec "$BGT" vault token revoke -self >/dev/null; unset BGT; echo "BREAK-GLASS TOKEN REVOKED"
NEWMR_TMP="$(mktemp /tmp/phase3-T1-newmr.XXXXXX)"; printf '%s' "$NEW_MR" > "$NEWMR_TMP"; mv "$NEWMR_TMP" "$NEWMR_FILE"
SUCCESS=1
echo "PHASE 3 T1 DONE (okvc- imported Observe-only; XR + all MRs paused). NEW_MR=$NEW_MR"
