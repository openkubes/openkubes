#!/usr/bin/env bash
# Phase 3 / T2-import (hardened) — promote T2 (paused XR), render+verify (new okvc- MR now
# ["*"], all 5 UIDs stable), re-pause XR, unpause ONLY the okvc- Policy MR, prove the TAKEOVER
# (full management: a FRESH ReconcileSuccess, no create, no external mutation, no Async/replace
# error, policy content unchanged), re-pause it. XR + all 5 MRs remain paused at the end.
# 3C does the real drift cycle. Fail-closed.
set -Eeuo pipefail
SUCCESS=0
MGMT_KUBECONFIG=~/.kube/ok-mgmt.yaml; SHARED_KUBECONFIG=~/.kube/ok-shared.yaml
OLD_POLICY=ok-robotics-sa-obs; NEW_POLICY=okvc-ok-robotics-sa-obs
POLICY_RES=policies.vault.vault.upbound.io;              POLICY_MR=ok-robotics-ee43e699198c
ROLE_RES=authbackendroles.kubernetes.vault.upbound.io;   ROLE_MR=ok-robotics-6cae6fef03f6
CONF_RES=authbackendconfigs.kubernetes.vault.upbound.io; CONF_MR=ok-robotics-1cf8d3106f89
BACK_RES=backends.auth.vault.upbound.io;                 BACK_MR=ok-robotics-05b190692d43
GATE=/tmp/phase3-T2-gate.json
DONE_FILE=/tmp/phase3-T2-done
export KUBECONFIG="$MGMT_KUBECONFIG"
NEW_MR=""
freeze_all(){
  kubectl annotate vaultconfig ok-robotics crossplane.io/paused=true --overwrite >/dev/null 2>&1 || true
  for ref in "$POLICY_RES $POLICY_MR" "$ROLE_RES $ROLE_MR" "$CONF_RES $CONF_MR" "$BACK_RES $BACK_MR"; do set -- $ref
    kubectl annotate "$1" "$2" crossplane.io/paused=true --overwrite >/dev/null 2>&1 || true; done
  [[ -n "$NEW_MR" ]] && kubectl annotate "$POLICY_RES" "$NEW_MR" crossplane.io/paused=true --overwrite >/dev/null 2>&1 || true
}
cleanup(){ local rc=$?; trap - EXIT; set +e
  if ((rc!=0 && SUCCESS==0)); then echo "EMERGENCY FREEZE: re-pausing XR and all T2 MRs" >&2; freeze_all; fi
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
# Prove a FRESH full-management reconcile: exactly one Synced=True/ReconcileSuccess with a
# NEW lastTransitionTime (!= the paused one captured in SYNCED_BEFORE), Ready=True, and the
# explicit ABSENCE of a failed LastAsyncOperation or any replace/rename message.
takeover_ready(){ kubectl get "$POLICY_RES" "$NEW_MR" -o json | jq -e --arg before "$SYNCED_BEFORE" '
  ([.status.conditions[]?|select(.type=="Synced")]) as $s
  | ($s|length)==1
  and $s[0].status=="True" and $s[0].reason=="ReconcileSuccess" and $s[0].lastTransitionTime!=$before
  and any(.status.conditions[]?; .type=="Ready" and .status=="True")
  and ((any(.status.conditions[]?; .type=="LastAsyncOperation" and .status=="False"))|not)
  and ((any(.status.conditions[]?;
        ((.reason//"")=="AsyncUpdateFailure")
        or ((.message//"")|test("requires replacing|cannot change the value of the argument.*name";"i"))
      ))|not)
' >/dev/null; }
check_five_refs(){ local got exp
  got="$(kubectl get vaultconfig ok-robotics -o json | jq -r '.spec.resourceRefs[]|[.apiVersion,.kind,.name]|@tsv' | sort)"
  exp="$(printf '%s\n' \
    "auth.vault.upbound.io/v1alpha1"$'\t'"Backend"$'\t'"$BACK_MR" \
    "kubernetes.vault.upbound.io/v1alpha1"$'\t'"AuthBackendConfig"$'\t'"$CONF_MR" \
    "kubernetes.vault.upbound.io/v1alpha1"$'\t'"AuthBackendRole"$'\t'"$ROLE_MR" \
    "vault.vault.upbound.io/v1alpha1"$'\t'"Policy"$'\t'"$POLICY_MR" \
    "vault.vault.upbound.io/v1alpha1"$'\t'"Policy"$'\t'"$NEW_MR" | sort)"
  [[ "$got" == "$exp" ]] || { echo "ABORT: unexpected resourceRefs" >&2; echo "--expected--" >&2; printf '%s\n' "$exp" >&2; echo "--actual--" >&2; printf '%s\n' "$got" >&2; return 1; }; }

# ── gate file present ──
test -s "$GATE" || { echo "ABORT: T2 gate file missing or empty" >&2; exit 1; }
NEW_MR="$(jq -er '.newMR' "$GATE")"; [[ -n "$NEW_MR" && "$NEW_MR" != "$POLICY_MR" ]] || { echo "ABORT: bad NEW_MR in gate" >&2; exit 1; }
rm -f "$DONE_FILE"

# ── Manual re-check ──
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

# ── PRECONDITION (T1 end-state) + PROMOTE ──
EXP_UID="$(jq -er '.compositionUID' "$GATE")"; OLDREV="$(jq -er '.oldRevision' "$GATE")"; NEWREV="$(jq -er '.newRevision' "$GATE")"; EXP_HASH="$(jq -er '.normalizedSpecSHA256' "$GATE")"
[[ "$(kubectl get composition "$COMP" -o jsonpath='{.metadata.uid}')" == "$EXP_UID" ]] || { echo "ABORT: composition identity changed" >&2; exit 1; }
[[ "$(kubectl get vaultconfig ok-robotics -o jsonpath='{.spec.compositionRevisionRef.name}')" == "$OLDREV" ]] || { echo "ABORT: XR not on reviewed T1 revision" >&2; exit 1; }
paused_confirmed vaultconfig ok-robotics || { echo "ABORT: XR not ReconcilePaused" >&2; exit 1; }
[[ "$(kubectl get compositionrevision "$NEWREV" -o json | jq -S '.spec|del(.revision)' | shasum -a256 | awk '{print $1}')" == "$EXP_HASH" ]] || { echo "ABORT: reviewed T2 revision content changed" >&2; exit 1; }

# 5 MRs frozen; legacy on OLD identity; okvc- MR imported Observe
for pair in "$POLICY_RES $POLICY_MR" "$POLICY_RES $NEW_MR" "$ROLE_RES $ROLE_MR" "$CONF_RES $CONF_MR" "$BACK_RES $BACK_MR"; do set -- $pair
  paused_confirmed "$1" "$2" || { echo "ABORT: MR not ReconcilePaused before T2: $2" >&2; exit 1; }; done
vault_exec "$BGT" vault read -format=json auth/kubernetes/ok-robotics/role/sa-obs | jq -e '.data.token_policies==["okvc-ok-robotics-sa-obs"]' >/dev/null || { echo "ABORT: Vault role no longer okvc-only" >&2; exit 1; }
POL="$(vault_exec "$BGT" vault policy list)"
grep -Fxq "$OLD_POLICY" <<<"$POL" || { echo "ABORT: old Vault policy missing before T2" >&2; exit 1; }
grep -Fxq "$NEW_POLICY" <<<"$POL" || { echo "ABORT: okvc Vault policy missing before T2" >&2; exit 1; }
kubectl get "$POLICY_RES" "$POLICY_MR" -o json | jq -e --arg old "$OLD_POLICY" \
  '.metadata.annotations["crossplane.io/paused"]=="true" and .metadata.annotations["crossplane.io/external-name"]==$old and .spec.forProvider.name==$old and .spec.managementPolicies==["*"]' >/dev/null \
  || { echo "ABORT: legacy Policy MR not on consistent OLD identity" >&2; exit 1; }
kubectl get "$POLICY_RES" "$NEW_MR" -o json | jq -e --arg new "$NEW_POLICY" \
  '.metadata.annotations["crossplane.io/paused"]=="true" and .metadata.annotations["crossplane.io/external-name"]==$new and .spec.forProvider.name==$new and .spec.managementPolicies==["Observe"]' >/dev/null \
  || { echo "ABORT: okvc- MR not in proven Observe state before T2" >&2; exit 1; }
creation_state "$POLICY_RES" "$NEW_MR" | creation_state_safe || { echo "ABORT: okvc- MR unsafe creation state before T2" >&2; exit 1; }
check_five_refs || { echo "ABORT: pre-T2 resource set not exactly 5" >&2; exit 1; }
echo "T2 TAKEOVER PRECONDITION RECONFIRMED"

# capture ALL five identities + policy content (nothing must be recreated in T2)
P_UID="$(uid_of "$POLICY_RES" "$POLICY_MR")"; R_UID="$(uid_of "$ROLE_RES" "$ROLE_MR")"; C_UID="$(uid_of "$CONF_RES" "$CONF_MR")"; B_UID="$(uid_of "$BACK_RES" "$BACK_MR")"; N_UID="$(uid_of "$POLICY_RES" "$NEW_MR")"
for u in "$P_UID" "$R_UID" "$C_UID" "$B_UID" "$N_UID"; do [[ -n "$u" ]] || { echo "ABORT: missing UID in precondition" >&2; exit 1; }; done
POLICY_HASH_BEFORE="$(policy_hash)"
NEW_CREATE_BEFORE="$(creation_state "$POLICY_RES" "$NEW_MR")"

kubectl patch vaultconfig ok-robotics --type=merge -p "{\"spec\":{\"compositionRevisionRef\":{\"name\":\"$NEWREV\"}}}"
[[ "$(kubectl get vaultconfig ok-robotics -o jsonpath='{.spec.compositionRevisionRef.name}')" == "$NEWREV" ]] || { echo "ABORT: promotion not persisted" >&2; exit 1; }
paused_confirmed vaultconfig ok-robotics || { echo "ABORT: XR unexpectedly unpaused after promote" >&2; exit 1; }
echo "T2 REVISION PROMOTED (XR still paused)"

# ── XR unpause -> render -> verify (okvc- MR now ["*"], all else unchanged) -> re-pause ──
kubectl annotate vaultconfig ok-robotics crossplane.io/paused-
deadline=$((SECONDS+120))
until
  kubectl get "$POLICY_RES" "$NEW_MR"  -o json | jq -e '.metadata.annotations["crossplane.io/paused"]=="true" and .spec.managementPolicies==["*"] and .spec.forProvider.name=="okvc-ok-robotics-sa-obs"' >/dev/null \
  && kubectl get "$POLICY_RES" "$POLICY_MR" -o json | jq -e '.metadata.annotations["crossplane.io/paused"]=="true" and .spec.managementPolicies==["*"] and .spec.forProvider.name=="ok-robotics-sa-obs"' >/dev/null \
  && kubectl get "$ROLE_RES" "$ROLE_MR"   -o json | jq -e '.metadata.annotations["crossplane.io/paused"]=="true" and .spec.forProvider.tokenPolicies==["okvc-ok-robotics-sa-obs"]' >/dev/null
do (( SECONDS>=deadline )) && { echo "ABORT: T2 render did not converge" >&2; exit 1; }; sleep 2; done
check_five_refs || { echo "ABORT: T2 render changed the resource set" >&2; exit 1; }
echo "RENDER PROVEN (okvc- MR now [\"*\"]; legacy unchanged; role okvc-; 5 refs)"
# ALL five identities stable — nothing recreated by the managementPolicies flip
[[ "$(uid_of "$POLICY_RES" "$POLICY_MR")" == "$P_UID" && "$(uid_of "$ROLE_RES" "$ROLE_MR")" == "$R_UID" && "$(uid_of "$CONF_RES" "$CONF_MR")" == "$C_UID" && "$(uid_of "$BACK_RES" "$BACK_MR")" == "$B_UID" && "$(uid_of "$POLICY_RES" "$NEW_MR")" == "$N_UID" ]] \
  || { echo "ABORT: an MR identity changed during T2 render" >&2; exit 1; }
[[ "$(en_of "$POLICY_RES" "$NEW_MR")" == "$NEW_POLICY" ]] || { echo "ABORT: okvc- MR external-name drifted" >&2; exit 1; }
echo "IDENTITIES OK (all 5 UIDs stable; okvc- external-name intact)"
kubectl annotate vaultconfig ok-robotics crossplane.io/paused=true --overwrite
deadline=$((SECONDS+90)); until paused_confirmed vaultconfig ok-robotics; do (( SECONDS>=deadline )) && { echo "ABORT: XR re-pause not confirmed" >&2; exit 1; }; sleep 2; done
echo "XR CONFIRMED RE-PAUSED"

# ── TAKEOVER: unpause ONLY the okvc- MR, prove a fresh full-management reconcile (no create, no external mutation, content unchanged) ──
deadline=$((SECONDS+90)); until paused_confirmed "$POLICY_RES" "$NEW_MR"; do (( SECONDS>=deadline )) && { echo "ABORT: okvc- MR not ReconcilePaused pre-takeover" >&2; exit 1; }; sleep 2; done
creation_state "$POLICY_RES" "$NEW_MR" | creation_state_safe || { echo "ABORT: unsafe creation state before takeover" >&2; exit 1; }
# baseline Synced transition-time (while paused) so we can prove a genuinely fresh reconcile
SYNCED_BEFORE="$(kubectl get "$POLICY_RES" "$NEW_MR" -o json | jq -er '[.status.conditions[]?|select(.type=="Synced")]|if length==1 then .[0].lastTransitionTime else error("expected exactly one Synced condition") end')"
kubectl annotate "$POLICY_RES" "$NEW_MR" crossplane.io/paused-
[[ -z "$(kubectl get "$POLICY_RES" "$NEW_MR" -o jsonpath='{.metadata.annotations.crossplane\.io/paused}')" ]] || { echo "ABORT: okvc- MR still paused" >&2; exit 1; }
deadline=$((SECONDS+300)); until takeover_ready; do (( SECONDS>=deadline )) && { echo "ABORT: fresh full-management reconcile not proven (no new ReconcileSuccess, or Async/replace error)" >&2; exit 1; }; sleep 5; done
kubectl get "$POLICY_RES" "$NEW_MR" -o json | jq -e '.spec.managementPolicies==["*"]' >/dev/null || { echo "ABORT: okvc- MR not in full management after takeover" >&2; exit 1; }
[[ "$(en_of "$POLICY_RES" "$NEW_MR")" == "$NEW_POLICY" ]] || { echo "ABORT: okvc- MR external-name drifted during takeover" >&2; exit 1; }
NEW_CREATE_AFTER="$(creation_state "$POLICY_RES" "$NEW_MR")"
creation_state_safe <<<"$NEW_CREATE_AFTER" || { echo "ABORT: unsafe creation state after takeover: $NEW_CREATE_AFTER" >&2; exit 1; }
[[ "$NEW_CREATE_AFTER" == "$NEW_CREATE_BEFORE" ]] || { echo "ABORT: create attempted during takeover (before=$NEW_CREATE_BEFORE after=$NEW_CREATE_AFTER)" >&2; exit 1; }
[[ "$(policy_hash)" == "$POLICY_HASH_BEFORE" ]] || { echo "ABORT: okvc- policy content changed during takeover" >&2; exit 1; }
echo "TAKEOVER PROVEN (fresh full-management ReconcileSuccess; no create; no external mutation; policy hash unchanged)"

# ── re-pause okvc- MR ──
kubectl annotate "$POLICY_RES" "$NEW_MR" crossplane.io/paused=true --overwrite
deadline=$((SECONDS+90)); until paused_confirmed "$POLICY_RES" "$NEW_MR"; do (( SECONDS>=deadline )) && { echo "ABORT: okvc- MR re-pause not confirmed" >&2; exit 1; }; sleep 2; done
echo "OKVC- MR RE-PAUSED"

# ── FINAL FREEZE PROOF: exactly 5 refs + XR + 5 MRs ReconcilePaused ──
check_five_refs || { echo "ABORT: T2 resource set changed before final checkpoint" >&2; exit 1; }
echo "T2 RESOURCE SET STILL EXACTLY 5"
paused_confirmed vaultconfig ok-robotics || { echo "ABORT: XR not paused at checkpoint" >&2; exit 1; }
for ref in "$POLICY_RES $POLICY_MR" "$POLICY_RES $NEW_MR" "$ROLE_RES $ROLE_MR" "$CONF_RES $CONF_MR" "$BACK_RES $BACK_MR"; do set -- $ref
  paused_confirmed "$1" "$2" || { echo "ABORT: $2 not ReconcilePaused at checkpoint" >&2; exit 1; }; done
echo "FINAL T2 FREEZE CONFIRMED (XR + 5 MRs ReconcilePaused)"

vault_exec "$BGT" vault token revoke -self >/dev/null; unset BGT; echo "BREAK-GLASS TOKEN REVOKED"
DONE_TMP="$(mktemp /tmp/phase3-T2-done.XXXXXX)"; printf '%s' "$NEW_MR" > "$DONE_TMP"; mv "$DONE_TMP" "$DONE_FILE"
SUCCESS=1
echo "PHASE 3 T2 DONE (okvc- MR now full management; XR + all MRs paused). NEW_MR=$NEW_MR"
