#!/usr/bin/env bash
# Phase 3 / T4-promote (3D-1, hardened) — promote the OLD-MR-retire revision on the ACTIVE XR.
# The OLD MR is paused, so promoting only rewrites its desired spec: managementPolicies ["Observe"]
# + deletionPolicy Orphan. Proves the OLD MR converges (no external action), the keep set stays
# active/ReconcileSuccess with all 5 UIDs stable, and NOTHING changes in Vault or the consumer.
# No Vault mutation here. Fail-closed with emergency freeze (XR + all 5 MRs) on abort.
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
GATE=/tmp/phase3-T4-gate.json
T3_DONE_FILE=/tmp/phase3-T3-done
DONE_FILE=/tmp/phase3-T4-done
export KUBECONFIG="$MGMT_KUBECONFIG"
NEW_MR=""
freeze_all(){
  kubectl annotate vaultconfig ok-robotics crossplane.io/paused=true --overwrite >/dev/null 2>&1 || true
  for ref in "$POLICY_RES $POLICY_MR" "$ROLE_RES $ROLE_MR" "$CONF_RES $CONF_MR" "$BACK_RES $BACK_MR"; do set -- $ref
    kubectl annotate "$1" "$2" crossplane.io/paused=true --overwrite >/dev/null 2>&1 || true; done
  [[ -n "$NEW_MR" ]] && kubectl annotate "$POLICY_RES" "$NEW_MR" crossplane.io/paused=true --overwrite >/dev/null 2>&1 || true
}
cleanup(){ local rc=$?; trap - EXIT; set +e
  if ((rc!=0 && SUCCESS==0)); then echo "EMERGENCY FREEZE: re-pausing XR and all 5 MRs" >&2; freeze_all; fi
  [[ -n "${BGT:-}" ]] && declare -F vault_exec >/dev/null && vault_exec "$BGT" vault token revoke -self >/dev/null 2>&1 || true
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
old_mr_retired(){ kubectl get "$POLICY_RES" "$POLICY_MR" -o json | jq -e --arg old "$OLD_POLICY" '
  .metadata.deletionTimestamp==null
  and .metadata.annotations["crossplane.io/paused"]=="true"
  and .metadata.annotations["crossplane.io/external-name"]==$old
  and .spec.forProvider.name==$old
  and .spec.managementPolicies==["Observe"]
  and .spec.deletionPolicy=="Orphan"
  and any(.status.conditions[]?; .type=="Synced" and .status=="False" and .reason=="ReconcilePaused")' >/dev/null; }
check_five_refs(){ local got exp
  got="$(kubectl get vaultconfig ok-robotics -o json | jq -r '.spec.resourceRefs[]|[.apiVersion,.kind,.name]|@tsv' | sort)"
  exp="$(printf '%s\n' \
    "auth.vault.upbound.io/v1alpha1"$'\t'"Backend"$'\t'"$BACK_MR" \
    "kubernetes.vault.upbound.io/v1alpha1"$'\t'"AuthBackendConfig"$'\t'"$CONF_MR" \
    "kubernetes.vault.upbound.io/v1alpha1"$'\t'"AuthBackendRole"$'\t'"$ROLE_MR" \
    "vault.vault.upbound.io/v1alpha1"$'\t'"Policy"$'\t'"$POLICY_MR" \
    "vault.vault.upbound.io/v1alpha1"$'\t'"Policy"$'\t'"$NEW_MR" | sort)"
  [[ "$got" == "$exp" ]] || { echo "ABORT: unexpected resourceRefs" >&2; echo "--expected--" >&2; printf '%s\n' "$exp" >&2; echo "--actual--" >&2; printf '%s\n' "$got" >&2; return 1; }; }

# ── gate + chain-of-custody + 3C handoff ──
test -s "$GATE" || { echo "ABORT: T4 gate file missing or empty" >&2; exit 1; }
NEW_MR="$(jq -er '.newMR' "$GATE")"; [[ -n "$NEW_MR" && "$NEW_MR" != "$POLICY_MR" ]] || { echo "ABORT: bad NEW_MR in gate" >&2; exit 1; }
test -s "$T3_DONE_FILE" || { echo "ABORT: successful 3C handoff missing" >&2; exit 1; }
[[ "$(cat "$T3_DONE_FILE")" == "$NEW_MR" ]] || { echo "ABORT: 3C handoff does not match NEW_MR" >&2; exit 1; }
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

# ── PRECONDITION (3C ACTIVE end-state) ──
EXP_UID="$(jq -er '.compositionUID' "$GATE")"; OLDREV="$(jq -er '.oldRevision' "$GATE")"; NEWREV="$(jq -er '.newRevision' "$GATE")"; EXP_HASH="$(jq -er '.normalizedSpecSHA256' "$GATE")"
[[ "$(kubectl get composition "$COMP" -o jsonpath='{.metadata.uid}')" == "$EXP_UID" ]] || { echo "ABORT: composition identity changed" >&2; exit 1; }
[[ "$(kubectl get vaultconfig ok-robotics -o jsonpath='{.spec.compositionRevisionRef.name}')" == "$OLDREV" ]] || { echo "ABORT: XR not on reviewed T3 revision" >&2; exit 1; }
[[ "$(kubectl get vaultconfig ok-robotics -o jsonpath='{.metadata.annotations.crossplane\.io/paused}')" != "true" ]] || { echo "ABORT: XR paused — expected ACTIVE" >&2; exit 1; }
[[ "$(kubectl get compositionrevision "$NEWREV" -o json | jq -S '.spec|del(.revision)' | shasum -a256 | awk '{print $1}')" == "$EXP_HASH" ]] || { echo "ABORT: reviewed T4 revision content changed" >&2; exit 1; }
for pair in "$BACK_RES $BACK_MR" "$CONF_RES $CONF_MR" "$ROLE_RES $ROLE_MR" "$POLICY_RES $NEW_MR"; do set -- $pair
  mr_active_ok "$1" "$2" || { echo "ABORT: keep-set MR not active before 3D-1: $2" >&2; exit 1; }; done
paused_confirmed "$POLICY_RES" "$POLICY_MR" || { echo "ABORT: OLD MR not paused before 3D-1" >&2; exit 1; }
kubectl get "$POLICY_RES" "$POLICY_MR" -o json | jq -e --arg old "$OLD_POLICY" '.metadata.deletionTimestamp==null and .metadata.annotations["crossplane.io/external-name"]==$old and .spec.forProvider.name==$old and .spec.managementPolicies==["*"]' >/dev/null || { echo "ABORT: OLD MR is terminating or not on legacy/full-mgmt identity" >&2; exit 1; }
kubectl get "$POLICY_RES" "$NEW_MR" -o json | jq -e --arg new "$NEW_POLICY" '.metadata.annotations["crossplane.io/external-name"]==$new and .spec.forProvider.name==$new and .spec.managementPolicies==["*"]' >/dev/null || { echo "ABORT: okvc- MR not full-mgmt okvc-" >&2; exit 1; }
vault_exec "$BGT" vault read -format=json auth/kubernetes/ok-robotics/role/sa-obs | jq -e '.data.token_policies==["okvc-ok-robotics-sa-obs"]' >/dev/null || { echo "ABORT: Vault role not okvc-only" >&2; exit 1; }
POL="$(vault_exec "$BGT" vault policy list)"
grep -Fxq "$OLD_POLICY" <<<"$POL" || { echo "ABORT: old Vault policy missing" >&2; exit 1; }
grep -Fxq "$NEW_POLICY" <<<"$POL" || { echo "ABORT: okvc Vault policy missing" >&2; exit 1; }
check_five_refs || { echo "ABORT: pre-3D-1 resource set not exactly 5" >&2; exit 1; }
vso_health_gate || { echo "ABORT: VSO not healthy before 3D-1" >&2; exit 1; }
echo "3D-1 PRECONDITION RECONFIRMED (3C ACTIVE end-state; VSO healthy)"

# capture identities + immutable baselines
P_UID="$(uid_of "$POLICY_RES" "$POLICY_MR")"; R_UID="$(uid_of "$ROLE_RES" "$ROLE_MR")"; C_UID="$(uid_of "$CONF_RES" "$CONF_MR")"; B_UID="$(uid_of "$BACK_RES" "$BACK_MR")"; N_UID="$(uid_of "$POLICY_RES" "$NEW_MR")"
for u in "$P_UID" "$R_UID" "$C_UID" "$B_UID" "$N_UID"; do [[ -n "$u" ]] || { echo "ABORT: missing UID in precondition" >&2; exit 1; }; done
VSO_BEFORE="$(vso_hash)"
OLD_POLICY_HASH_BEFORE="$(old_policy_hash)"; NEW_POLICY_HASH_BEFORE="$(new_policy_hash)"
[[ -n "$OLD_POLICY_HASH_BEFORE" && -n "$NEW_POLICY_HASH_BEFORE" ]] || { echo "ABORT: could not capture both policy baselines" >&2; exit 1; }

# ── PROMOTE on the active XR ──
kubectl patch vaultconfig ok-robotics --type=merge -p "{\"spec\":{\"compositionRevisionRef\":{\"name\":\"$NEWREV\"}}}"
[[ "$(kubectl get vaultconfig ok-robotics -o jsonpath='{.spec.compositionRevisionRef.name}')" == "$NEWREV" ]] || { echo "ABORT: promotion not persisted" >&2; exit 1; }
[[ "$(kubectl get vaultconfig ok-robotics -o jsonpath='{.metadata.annotations.crossplane\.io/paused}')" != "true" ]] || { echo "ABORT: XR unexpectedly paused after promote" >&2; exit 1; }
echo "T4 REVISION PROMOTED (XR active)"

# ── OLD MR converges to Observe+Orphan (still paused, no external action) ──
deadline=$((SECONDS+180)); until old_mr_retired; do (( SECONDS>=deadline )) && { echo "ABORT: OLD MR did not converge to Observe+Orphan+paused" >&2; exit 1; }; sleep 3; done
xr_active_ok || { echo "ABORT: XR not active/ReconcileSuccess after T4 promotion" >&2; exit 1; }
echo "OLD MR RETIRED (Observe + Orphan; still paused; legacy name; XR active/ReconcileSuccess)"

# ── keep-set undisturbed; all 5 UIDs stable; 5 refs; okvc- + role unchanged ──
for pair in "$BACK_RES $BACK_MR" "$CONF_RES $CONF_MR" "$ROLE_RES $ROLE_MR" "$POLICY_RES $NEW_MR"; do set -- $pair
  mr_active_ok "$1" "$2" || { echo "ABORT: keep-set MR not active after promote: $2" >&2; exit 1; }; done
[[ "$(uid_of "$POLICY_RES" "$POLICY_MR")" == "$P_UID" && "$(uid_of "$ROLE_RES" "$ROLE_MR")" == "$R_UID" && "$(uid_of "$CONF_RES" "$CONF_MR")" == "$C_UID" && "$(uid_of "$BACK_RES" "$BACK_MR")" == "$B_UID" && "$(uid_of "$POLICY_RES" "$NEW_MR")" == "$N_UID" ]] || { echo "ABORT: an MR identity changed during 3D-1" >&2; exit 1; }
[[ "$(en_of "$POLICY_RES" "$NEW_MR")" == "$NEW_POLICY" ]] || { echo "ABORT: okvc- external-name drifted" >&2; exit 1; }
kubectl get "$POLICY_RES" "$NEW_MR" -o json | jq -e '.spec.managementPolicies==["*"]' >/dev/null || { echo "ABORT: okvc- MR not full-management" >&2; exit 1; }
check_five_refs || { echo "ABORT: resource set changed during 3D-1" >&2; exit 1; }
vault_exec "$BGT" vault read -format=json auth/kubernetes/ok-robotics/role/sa-obs | jq -e '.data.token_policies==["okvc-ok-robotics-sa-obs"]' >/dev/null || { echo "ABORT: role drifted off okvc-" >&2; exit 1; }
echo "KEEP-SET UNDISTURBED (5 UIDs stable; 5 refs; okvc- full-mgmt; role okvc-)"

# ── nothing changed in Vault or the consumer ──
POL2="$(vault_exec "$BGT" vault policy list)"
grep -Fxq "$OLD_POLICY" <<<"$POL2" || { echo "ABORT: old Vault policy disappeared during 3D-1" >&2; exit 1; }
grep -Fxq "$NEW_POLICY" <<<"$POL2" || { echo "ABORT: okvc Vault policy disappeared during 3D-1" >&2; exit 1; }
[[ "$(old_policy_hash)" == "$OLD_POLICY_HASH_BEFORE" ]] || { echo "ABORT: legacy Vault policy content changed during 3D-1" >&2; exit 1; }
[[ "$(new_policy_hash)" == "$NEW_POLICY_HASH_BEFORE" ]] || { echo "ABORT: okvc- Vault policy content changed during 3D-1" >&2; exit 1; }
vso_health_gate || { echo "ABORT: VSO unhealthy after 3D-1" >&2; exit 1; }
[[ "$(vso_hash)" == "$VSO_BEFORE" ]] || { echo "ABORT: consumer Secret changed during 3D-1" >&2; exit 1; }
echo "VAULT + CONSUMER UNCHANGED (both policy hashes stable; both policies present; VSO intact)"

vault_exec "$BGT" vault token revoke -self >/dev/null; unset BGT; echo "BREAK-GLASS TOKEN REVOKED"
DONE_TMP="$(mktemp /tmp/phase3-T4-done.XXXXXX)"; printf '%s' "$NEW_MR" > "$DONE_TMP"; mv "$DONE_TMP" "$DONE_FILE"
SUCCESS=1
echo "PHASE 3 3D-1 DONE (OLD MR prepared: Observe+Orphan+paused; ready for the controlled 3D-2 termination-and-unpause protocol; nothing deleted). NEW_MR=$NEW_MR"
