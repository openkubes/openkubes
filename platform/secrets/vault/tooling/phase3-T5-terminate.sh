#!/usr/bin/env bash
# Phase 3 / T5-terminate (3D-2, hardened) — the ONLY step that deletes a K8s MR object.
# Promote T5 (OLD block removed) on the ACTIVE XR; the paused OLD MR is expected to become
# TERMINATING (deletionTimestamp) but NOT finalize (finalizer held by the pause-check). Prove
# that + both Vault policies still present/hash-equal. Then explicitly UNPAUSE the terminating
# OLD MR so its managed reconciler releases the finalizer under Observe + Orphan — deleting the
# K8s object while PRESERVING the external Vault policy. Wait until the MR is gone, then re-prove
# refs 5->4, old Vault policy present+hash-equal, okvc- hash-equal, keep-set + consumer healthy.
# Fail-closed. On abort the emergency path freezes XR + keep-set, but handles the OLD MR by its
# LIVE state: a terminating OLD MR is deliberately kept UNPAUSED so its finalizer can still
# release under Observe + Orphan (external Vault policy stays safe); a not-yet-terminating OLD MR
# is paused. So an abort mid-termination does not strand the MR paused.
set -Eeuo pipefail
SUCCESS=0
MGMT_KUBECONFIG=~/.kube/ok-mgmt.yaml; SHARED_KUBECONFIG=~/.kube/ok-shared.yaml

# ── consumer VSO Secret coordinates on ok-robotics (confirmed in 3C) ──
ROBOTICS_KUBECONFIG=~/.kube/ok-robotics.yaml
VSO_SECRET_NS=ok-observability
VSO_SECRET_NAME=ok-observability-credentials

OLD_POLICY=ok-robotics-sa-obs; NEW_POLICY=okvc-ok-robotics-sa-obs
POLICY_RES=policies.vault.vault.upbound.io;              POLICY_MR=ok-robotics-ee43e699198c
ROLE_RES=authbackendroles.kubernetes.vault.upbound.io;   ROLE_MR=ok-robotics-6cae6fef03f6
CONF_RES=authbackendconfigs.kubernetes.vault.upbound.io; CONF_MR=ok-robotics-1cf8d3106f89
BACK_RES=backends.auth.vault.upbound.io;                 BACK_MR=ok-robotics-05b190692d43
GATE=/tmp/phase3-T5-gate.json
T4_DONE_FILE=/tmp/phase3-T4-done
DONE_FILE=/tmp/phase3-T5-done
export KUBECONFIG="$MGMT_KUBECONFIG"
NEW_MR=""
# XR + keep-set may always be frozen. The OLD MR must NOT be re-paused once it is terminating,
# or its finalizer would stay held forever — so it is handled by its live state instead.
freeze_keep_set(){
  kubectl annotate vaultconfig ok-robotics crossplane.io/paused=true --overwrite >/dev/null 2>&1 || true
  for ref in "$BACK_RES $BACK_MR" "$CONF_RES $CONF_MR" "$ROLE_RES $ROLE_MR"; do set -- $ref
    kubectl annotate "$1" "$2" crossplane.io/paused=true --overwrite >/dev/null 2>&1 || true; done
  # NEW_MR may still be empty (e.g. abort before the gate is read) — handle it separately so
  # `set -u` never trips on an unset positional in the loop's split.
  if [[ -n "$NEW_MR" ]]; then
    kubectl annotate "$POLICY_RES" "$NEW_MR" crossplane.io/paused=true --overwrite >/dev/null 2>&1 || true
  fi
}
handle_old_mr_on_abort(){ local js
  if js="$(kubectl get "$POLICY_RES" "$POLICY_MR" -o json 2>/dev/null)"; then
    if jq -e '.metadata.deletionTimestamp != null' >/dev/null <<<"$js"; then
      echo "EMERGENCY: OLD MR is terminating; ensuring it remains UNPAUSED so the finalizer can release" >&2
      kubectl annotate "$POLICY_RES" "$POLICY_MR" crossplane.io/paused- >/dev/null 2>&1 || true
    else
      echo "EMERGENCY: OLD MR not terminating; pausing it" >&2
      kubectl annotate "$POLICY_RES" "$POLICY_MR" crossplane.io/paused=true --overwrite >/dev/null 2>&1 || true
    fi
  else
    echo "EMERGENCY: OLD MR absent or unreadable; not modifying it" >&2
  fi
}
cleanup(){ local rc=$?; trap - EXIT; set +e
  if ((rc!=0 && SUCCESS==0)); then echo "EMERGENCY FREEZE: pausing XR and keep-set" >&2; freeze_keep_set; handle_old_mr_on_abort; fi
  [[ -n "${BGT:-}" ]] && declare -F vault_exec >/dev/null && vault_exec "$BGT" vault token revoke -self >/dev/null 2>&1 || true
  [[ -n "${OLD_MR_BEFORE:-}" && "$SUCCESS" == "1" ]] && rm -f "$OLD_MR_BEFORE"
  unset BG BGT; exit "$rc"; }
trap cleanup EXIT
trap 'rc=$?; printf "ABORT: rc=%s at line %s\n" "$rc" "$LINENO" >&2; exit "$rc"' ERR

vault_exec(){ local t="$1"; shift; printf '%s\n' "$t" | kubectl --kubeconfig "$SHARED_KUBECONFIG" -n vault exec -i vault-0 -- sh -c 'IFS= read -r VAULT_TOKEN; export VAULT_TOKEN; exec "$@"' sh "$@"; }
old_policy_hash(){ vault_exec "$BGT" vault policy read "$OLD_POLICY" | shasum -a256 | awk '{print $1}'; }
new_policy_hash(){ vault_exec "$BGT" vault policy read "$NEW_POLICY" | shasum -a256 | awk '{print $1}'; }
mr_active_ok(){ kubectl get "$1" "$2" -o json | jq -e '(.metadata.annotations["crossplane.io/paused"]//"")!="true" and any(.status.conditions[]?; .type=="Synced" and .status=="True" and .reason=="ReconcileSuccess") and any(.status.conditions[]?; .type=="Ready" and .status=="True")' >/dev/null; }
xr_active_ok(){ kubectl get vaultconfig ok-robotics -o json | jq -e '(.metadata.annotations["crossplane.io/paused"]//"")!="true" and any(.status.conditions[]?; .type=="Synced" and .status=="True" and .reason=="ReconcileSuccess")' >/dev/null; }
paused_confirmed(){ kubectl get "$@" -o json | jq -e '.metadata.annotations["crossplane.io/paused"]=="true" and any(.status.conditions[]?; .type=="Synced" and .status=="False" and .reason=="ReconcilePaused")' >/dev/null; }
uid_of(){ kubectl get "$1" "$2" -o jsonpath='{.metadata.uid}'; }
en_of(){ kubectl get "$1" "$2" -o jsonpath='{.metadata.annotations.crossplane\.io/external-name}'; }
vso_hash(){ kubectl --kubeconfig "$ROBOTICS_KUBECONFIG" -n "$VSO_SECRET_NS" get secret "$VSO_SECRET_NAME" -o json | jq -S -c '.data' | shasum -a256 | awk '{print $1}'; }
vso_health_gate(){
  kubectl --kubeconfig "$ROBOTICS_KUBECONFIG" -n "$VSO_SECRET_NS" get vaultauth ok-robotics -o json | jq -e '
    .status.valid==true and (([.status.conditions[]?|select(.status=="True")|.type]) as $ok | (["Healthy","Ready"]-$ok)==[])' >/dev/null || return 1
  kubectl --kubeconfig "$ROBOTICS_KUBECONFIG" -n "$VSO_SECRET_NS" get vaultstaticsecret "$VSO_SECRET_NAME" -o json | jq -e '
    ([.status.conditions[]?|select(.status=="True")|.type]) as $ok | (["SecretSynced","Healthy","Ready"]-$ok)==[]' >/dev/null || return 1
}
# SAME OLD MR, terminating, finalizer HELD, still paused, and still Observe+Orphan/legacy.
# Uses OLD_UID + OLD_FINALIZERS captured before the promote.
old_mr_terminating(){ local js; js="$(kubectl get "$POLICY_RES" "$POLICY_MR" -o json 2>/dev/null)" || return 1
  jq -e --arg uid "$OLD_UID" --arg old "$OLD_POLICY" --argjson finalizers "$OLD_FINALIZERS" '
    .metadata.uid==$uid
    and .metadata.deletionTimestamp!=null
    and .metadata.finalizers==$finalizers
    and ((.metadata.finalizers|length)>0)
    and .metadata.annotations["crossplane.io/paused"]=="true"
    and .metadata.annotations["crossplane.io/external-name"]==$old
    and .spec.forProvider.name==$old
    and .spec.managementPolicies==["Observe"]
    and .spec.deletionPolicy=="Orphan"' >/dev/null <<<"$js"; }
# Only a SUCCESSFUL API call with an empty result means gone; any API error returns 2.
old_mr_gone(){ local out
  if ! out="$(kubectl get "$POLICY_RES" "$POLICY_MR" --ignore-not-found -o name 2>/dev/null)"; then
    echo "ERROR: could not determine whether OLD MR exists" >&2; return 2; fi
  [[ -z "$out" ]]; }
refs_count(){ kubectl get vaultconfig ok-robotics -o json | jq '.spec.resourceRefs|length'; }
# During termination resourceRefs must be EXACTLY one of two known sets: keep-set+old (5) or keep-set (4).
refs_are_expected_during_termination(){ local got exp4 exp5
  got="$(kubectl get vaultconfig ok-robotics -o json | jq -r '.spec.resourceRefs[]|[.apiVersion,.kind,.name]|@tsv' | sort)"
  exp4="$(printf '%s\n' \
    "auth.vault.upbound.io/v1alpha1"$'\t'"Backend"$'\t'"$BACK_MR" \
    "kubernetes.vault.upbound.io/v1alpha1"$'\t'"AuthBackendConfig"$'\t'"$CONF_MR" \
    "kubernetes.vault.upbound.io/v1alpha1"$'\t'"AuthBackendRole"$'\t'"$ROLE_MR" \
    "vault.vault.upbound.io/v1alpha1"$'\t'"Policy"$'\t'"$NEW_MR" | sort)"
  exp5="$({ printf '%s\n' "$exp4"; printf '%s\n' "vault.vault.upbound.io/v1alpha1"$'\t'"Policy"$'\t'"$POLICY_MR"; } | sort)"
  [[ "$got" == "$exp4" || "$got" == "$exp5" ]]; }
four_keep_refs(){ local got exp
  got="$(kubectl get vaultconfig ok-robotics -o json | jq -r '.spec.resourceRefs[]|[.apiVersion,.kind,.name]|@tsv' | sort)"
  exp="$(printf '%s\n' \
    "auth.vault.upbound.io/v1alpha1"$'\t'"Backend"$'\t'"$BACK_MR" \
    "kubernetes.vault.upbound.io/v1alpha1"$'\t'"AuthBackendConfig"$'\t'"$CONF_MR" \
    "kubernetes.vault.upbound.io/v1alpha1"$'\t'"AuthBackendRole"$'\t'"$ROLE_MR" \
    "vault.vault.upbound.io/v1alpha1"$'\t'"Policy"$'\t'"$NEW_MR" | sort)"
  [[ "$got" == "$exp" ]]; }

# ── gate + chain-of-custody + 3D-1 handoff ──
test -s "$GATE" || { echo "ABORT: T5 gate file missing or empty" >&2; exit 1; }
NEW_MR="$(jq -er '.newMR' "$GATE")"; [[ -n "$NEW_MR" && "$NEW_MR" != "$POLICY_MR" ]] || { echo "ABORT: bad NEW_MR in gate" >&2; exit 1; }
test -s "$T4_DONE_FILE" || { echo "ABORT: successful 3D-1 handoff missing" >&2; exit 1; }
[[ "$(cat "$T4_DONE_FILE")" == "$NEW_MR" ]] || { echo "ABORT: 3D-1 handoff does not match NEW_MR" >&2; exit 1; }
rm -f "$DONE_FILE"
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

# ── PRECONDITION (3D-1 end-state) + baselines ──
EXP_UID="$(jq -er '.compositionUID' "$GATE")"; OLDREV="$(jq -er '.oldRevision' "$GATE")"; NEWREV="$(jq -er '.newRevision' "$GATE")"; EXP_HASH="$(jq -er '.normalizedSpecSHA256' "$GATE")"
[[ "$(kubectl get composition "$COMP" -o jsonpath='{.metadata.uid}')" == "$EXP_UID" ]] || { echo "ABORT: composition identity changed" >&2; exit 1; }
[[ "$(kubectl get vaultconfig ok-robotics -o jsonpath='{.spec.compositionRevisionRef.name}')" == "$OLDREV" ]] || { echo "ABORT: XR not on reviewed T4 revision" >&2; exit 1; }
[[ "$(kubectl get vaultconfig ok-robotics -o jsonpath='{.metadata.annotations.crossplane\.io/paused}')" != "true" ]] || { echo "ABORT: XR paused — expected ACTIVE" >&2; exit 1; }
[[ "$(kubectl get compositionrevision "$NEWREV" -o json | jq -S '.spec|del(.revision)' | shasum -a256 | awk '{print $1}')" == "$EXP_HASH" ]] || { echo "ABORT: reviewed T5 revision content changed" >&2; exit 1; }
for pair in "$BACK_RES $BACK_MR" "$CONF_RES $CONF_MR" "$ROLE_RES $ROLE_MR" "$POLICY_RES $NEW_MR"; do set -- $pair
  mr_active_ok "$1" "$2" || { echo "ABORT: keep-set MR not active before 3D-2: $2" >&2; exit 1; }; done
kubectl get "$POLICY_RES" "$POLICY_MR" -o json | jq -e --arg old "$OLD_POLICY" \
  '.metadata.deletionTimestamp==null and .metadata.annotations["crossplane.io/paused"]=="true" and .metadata.annotations["crossplane.io/external-name"]==$old and .spec.forProvider.name==$old and .spec.managementPolicies==["Observe"] and .spec.deletionPolicy=="Orphan"' >/dev/null \
  || { echo "ABORT: OLD MR not in retired (Observe+Orphan+paused, not-terminating) state before 3D-2" >&2; exit 1; }
vault_exec "$BGT" vault read -format=json auth/kubernetes/ok-robotics/role/sa-obs | jq -e '.data.token_policies==["okvc-ok-robotics-sa-obs"]' >/dev/null || { echo "ABORT: Vault role not okvc-only" >&2; exit 1; }
POL="$(vault_exec "$BGT" vault policy list)"
grep -Fxq "$OLD_POLICY" <<<"$POL" || { echo "ABORT: old Vault policy missing" >&2; exit 1; }
grep -Fxq "$NEW_POLICY" <<<"$POL" || { echo "ABORT: okvc Vault policy missing" >&2; exit 1; }
[[ "$(refs_count)" == "5" ]] || { echo "ABORT: expected exactly 5 resourceRefs before 3D-2" >&2; exit 1; }
refs_are_expected_during_termination || { echo "ABORT: resourceRefs are not the exact known keep-set+old set before 3D-2" >&2; exit 1; }
vso_health_gate || { echo "ABORT: VSO not healthy before 3D-2" >&2; exit 1; }
echo "3D-2 PRECONDITION RECONFIRMED (3D-1 end-state; 5 refs; VSO healthy)"

B_UID="$(uid_of "$BACK_RES" "$BACK_MR")"; C_UID="$(uid_of "$CONF_RES" "$CONF_MR")"; R_UID="$(uid_of "$ROLE_RES" "$ROLE_MR")"; N_UID="$(uid_of "$POLICY_RES" "$NEW_MR")"
for u in "$B_UID" "$C_UID" "$R_UID" "$N_UID"; do [[ -n "$u" ]] || { echo "ABORT: missing keep-set UID" >&2; exit 1; }; done
OLD_HASH_BEFORE="$(old_policy_hash)"; NEW_HASH_BEFORE="$(new_policy_hash)"; VSO_BEFORE="$(vso_hash)"
[[ -n "$OLD_HASH_BEFORE" && -n "$NEW_HASH_BEFORE" && -n "$VSO_BEFORE" ]] || { echo "ABORT: could not capture baselines" >&2; exit 1; }
# archive the OLD MR identity + finalizer set so phase 1 can prove "same MR, finalizer held"
OLD_MR_BEFORE="$(mktemp /tmp/phase3-T5-old-mr-before.XXXXXX)"
kubectl get "$POLICY_RES" "$POLICY_MR" -o json > "$OLD_MR_BEFORE"
OLD_UID="$(jq -er '.metadata.uid' "$OLD_MR_BEFORE")"
OLD_FINALIZERS="$(jq -c '.metadata.finalizers // []' "$OLD_MR_BEFORE")"
jq -e '(.metadata.finalizers // [])|length>0' "$OLD_MR_BEFORE" >/dev/null || { echo "ABORT: OLD MR has no finalizer before termination" >&2; exit 1; }

# ── PROMOTE T5 (active XR renders; OLD block removed) ──
kubectl patch vaultconfig ok-robotics --type=merge -p "{\"spec\":{\"compositionRevisionRef\":{\"name\":\"$NEWREV\"}}}"
[[ "$(kubectl get vaultconfig ok-robotics -o jsonpath='{.spec.compositionRevisionRef.name}')" == "$NEWREV" ]] || { echo "ABORT: promotion not persisted" >&2; exit 1; }
[[ "$(kubectl get vaultconfig ok-robotics -o jsonpath='{.metadata.annotations.crossplane\.io/paused}')" != "true" ]] || { echo "ABORT: XR unexpectedly paused after promote" >&2; exit 1; }
echo "T5 REVISION PROMOTED (XR active)"

# ── Phase 1: OLD MR becomes TERMINATING but does NOT finalize (still paused) ──
deadline=$((SECONDS+120)); until old_mr_terminating; do (( SECONDS>=deadline )) && { echo "ABORT: OLD MR did not enter terminating+paused+finalizer-held state after promote" >&2; exit 1; }; sleep 3; done
refs_are_expected_during_termination || { echo "ABORT: unexpected resourceRefs during OLD MR termination" >&2; exit 1; }
echo "OLD MR TERMINATING (same UID; deletionTimestamp set; finalizer held; still paused; Observe+Orphan). resourceRefs now=$(refs_count)"
# nothing in Vault changed while it lingers
POL2="$(vault_exec "$BGT" vault policy list)"
grep -Fxq "$OLD_POLICY" <<<"$POL2" || { echo "ABORT: old Vault policy vanished during phase 1" >&2; exit 1; }
grep -Fxq "$NEW_POLICY" <<<"$POL2" || { echo "ABORT: okvc Vault policy vanished during phase 1" >&2; exit 1; }
[[ "$(old_policy_hash)" == "$OLD_HASH_BEFORE" ]] || { echo "ABORT: legacy policy content changed during phase 1" >&2; exit 1; }
[[ "$(new_policy_hash)" == "$NEW_HASH_BEFORE" ]] || { echo "ABORT: okvc- policy content changed during phase 1" >&2; exit 1; }
for pair in "$BACK_RES $BACK_MR" "$CONF_RES $CONF_MR" "$ROLE_RES $ROLE_MR" "$POLICY_RES $NEW_MR"; do set -- $pair
  mr_active_ok "$1" "$2" || { echo "ABORT: keep-set MR not active in phase 1: $2" >&2; exit 1; }; done
xr_active_ok || { echo "ABORT: XR not active/ReconcileSuccess in phase 1" >&2; exit 1; }

# ── Phase 2: UNPAUSE the terminating OLD MR -> managed reconciler releases finalizer (Orphan) ──
kubectl annotate "$POLICY_RES" "$POLICY_MR" crossplane.io/paused-
set +e; old_mr_gone; rc=$?; set -e
case "$rc" in
  0) : ;;  # already gone — fine
  1) [[ "$(kubectl get "$POLICY_RES" "$POLICY_MR" -o jsonpath='{.metadata.annotations.crossplane\.io/paused}')" != "true" ]] || { echo "ABORT: terminating OLD MR is still paused" >&2; exit 1; } ;;
  *) echo "ABORT: API error while confirming OLD MR unpause" >&2; exit 1 ;;
esac
echo "OLD MR UNPAUSED OR ALREADY GONE (finalizer release under Observe + Orphan)"

# ── Phase 3: wait until the K8s MR object is GONE (API error != gone) ──
deadline=$((SECONDS+300))
while true; do
  set +e; old_mr_gone; rc=$?; set -e
  if ((rc==0)); then break; fi
  if ((rc==2)); then echo "ABORT: API error while checking OLD MR termination" >&2; exit 1; fi
  if ((SECONDS>=deadline)); then echo "ABORT: OLD MR object did not terminate within deadline" >&2; exit 1; fi
  sleep 5
done
echo "OLD MR OBJECT GONE (finalizer released; K8s object deleted)"

# ── Phase 4: final proof — refs 4, old Vault policy PRESERVED, everything else stable ──
four_keep_refs || { echo "ABORT: resourceRefs not exactly the 4 keep MRs after termination" >&2; exit 1; }
old_mr_gone || { echo "ABORT: OLD MR reappeared" >&2; exit 1; }
POL3="$(vault_exec "$BGT" vault policy list)"
grep -Fxq "$OLD_POLICY" <<<"$POL3" || { echo "ABORT: legacy Vault policy was DELETED (Orphan failed!)" >&2; exit 1; }
grep -Fxq "$NEW_POLICY" <<<"$POL3" || { echo "ABORT: okvc Vault policy missing after termination" >&2; exit 1; }
[[ "$(old_policy_hash)" == "$OLD_HASH_BEFORE" ]] || { echo "ABORT: legacy Vault policy content changed across termination" >&2; exit 1; }
[[ "$(new_policy_hash)" == "$NEW_HASH_BEFORE" ]] || { echo "ABORT: okvc- Vault policy content changed across termination" >&2; exit 1; }
[[ "$(uid_of "$BACK_RES" "$BACK_MR")" == "$B_UID" && "$(uid_of "$CONF_RES" "$CONF_MR")" == "$C_UID" && "$(uid_of "$ROLE_RES" "$ROLE_MR")" == "$R_UID" && "$(uid_of "$POLICY_RES" "$NEW_MR")" == "$N_UID" ]] || { echo "ABORT: a keep-set MR identity changed during 3D-2" >&2; exit 1; }
[[ "$(en_of "$POLICY_RES" "$NEW_MR")" == "$NEW_POLICY" ]] || { echo "ABORT: okvc- external-name drifted" >&2; exit 1; }
kubectl get "$POLICY_RES" "$NEW_MR" -o json | jq -e '.spec.managementPolicies==["*"]' >/dev/null || { echo "ABORT: okvc- MR not full-management" >&2; exit 1; }
for pair in "$BACK_RES $BACK_MR" "$CONF_RES $CONF_MR" "$ROLE_RES $ROLE_MR" "$POLICY_RES $NEW_MR"; do set -- $pair
  mr_active_ok "$1" "$2" || { echo "ABORT: keep-set MR not active at final checkpoint: $2" >&2; exit 1; }; done
xr_active_ok || { echo "ABORT: XR not active/ReconcileSuccess at final checkpoint" >&2; exit 1; }
vault_exec "$BGT" vault read -format=json auth/kubernetes/ok-robotics/role/sa-obs | jq -e '.data.token_policies==["okvc-ok-robotics-sa-obs"]' >/dev/null || { echo "ABORT: role drifted off okvc-" >&2; exit 1; }
vso_health_gate || { echo "ABORT: VSO unhealthy after 3D-2" >&2; exit 1; }
[[ "$(vso_hash)" == "$VSO_BEFORE" ]] || { echo "ABORT: consumer Secret changed during 3D-2" >&2; exit 1; }
echo "3D-2 FINAL PROOF OK (4 refs; OLD MR gone; legacy Vault policy PRESERVED + hash-equal; okvc- hash-equal; keep-set + role + consumer healthy)"

vault_exec "$BGT" vault token revoke -self >/dev/null; unset BGT; echo "BREAK-GLASS TOKEN REVOKED"
DONE_TMP="$(mktemp /tmp/phase3-T5-done.XXXXXX)"
jq -n --arg removedMR "$POLICY_MR" --arg removedUID "$OLD_UID" --arg remainingMR "$NEW_MR" \
  --arg oldPolicySHA256 "$OLD_HASH_BEFORE" --arg newPolicySHA256 "$NEW_HASH_BEFORE" \
  '{removedMR:$removedMR,removedUID:$removedUID,remainingMR:$remainingMR,oldPolicyPreserved:true,oldPolicySHA256:$oldPolicySHA256,newPolicySHA256:$newPolicySHA256}' > "$DONE_TMP"
mv "$DONE_TMP" "$DONE_FILE"
SUCCESS=1
echo "PHASE 3 3D-2 DONE (OLD MR object removed; legacy Vault policy orphaned + preserved; keep-set active). Ready for 3D-3 (delete legacy Vault policy after no-reference proof). NEW_MR=$NEW_MR"
