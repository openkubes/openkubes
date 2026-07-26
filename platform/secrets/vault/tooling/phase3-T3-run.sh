#!/usr/bin/env bash
# Phase 3 / T3-run (3C, hardened) — the FIRST ACTIVE step. Promote T3 (paused XR), then
# controlled-unpause XR + the 4 keep-set MRs (Backend/Config/Role/okvc- Policy), prove each
# reaches a FRESH ReconcileSuccess, the OLD Policy MR stays paused, all 5 UIDs + external-name
# stable, and the consumer VSO Secret is unchanged. Then run a REAL drift test on the okvc-
# policy (inert deny stanza) and prove Crossplane restores the desired HCL. END STATE: XR +
# keep-set ACTIVE, old MR paused (its removal is 3D). Fail-closed with emergency re-freeze AND
# emergency policy-restore (so an abort mid-drift never leaves the policy mutated).
set -Eeuo pipefail
SUCCESS=0; DRIFT_APPLIED=0; DRIFT_RESTORED=0
MGMT_KUBECONFIG=~/.kube/ok-mgmt.yaml; SHARED_KUBECONFIG=~/.kube/ok-shared.yaml

# ── consumer VSO Secret coordinates on ok-robotics — CONFIRM before running ──
ROBOTICS_KUBECONFIG=~/.kube/ok-robotics.yaml
VSO_SECRET_NS=ok-observability
VSO_SECRET_NAME=ok-observability-credentials

OLD_POLICY=ok-robotics-sa-obs; NEW_POLICY=okvc-ok-robotics-sa-obs
POLICY_RES=policies.vault.vault.upbound.io;              POLICY_MR=ok-robotics-ee43e699198c
ROLE_RES=authbackendroles.kubernetes.vault.upbound.io;   ROLE_MR=ok-robotics-6cae6fef03f6
CONF_RES=authbackendconfigs.kubernetes.vault.upbound.io; CONF_MR=ok-robotics-1cf8d3106f89
BACK_RES=backends.auth.vault.upbound.io;                 BACK_MR=ok-robotics-05b190692d43
GATE=/tmp/phase3-T3-gate.json
T2_DONE_FILE=/tmp/phase3-T2-done
DONE_FILE=/tmp/phase3-T3-done
BASELINE_FILE=""
export KUBECONFIG="$MGMT_KUBECONFIG"
NEW_MR=""

freeze_all(){
  kubectl annotate vaultconfig ok-robotics crossplane.io/paused=true --overwrite >/dev/null 2>&1 || true
  for ref in "$POLICY_RES $POLICY_MR" "$ROLE_RES $ROLE_MR" "$CONF_RES $CONF_MR" "$BACK_RES $BACK_MR"; do set -- $ref
    kubectl annotate "$1" "$2" crossplane.io/paused=true --overwrite >/dev/null 2>&1 || true; done
  [[ -n "$NEW_MR" ]] && kubectl annotate "$POLICY_RES" "$NEW_MR" crossplane.io/paused=true --overwrite >/dev/null 2>&1 || true
}
vault_exec(){ local t="$1"; shift; printf '%s\n' "$t" | kubectl --kubeconfig "$SHARED_KUBECONFIG" -n vault exec -i vault-0 -- sh -c 'IFS= read -r VAULT_TOKEN; export VAULT_TOKEN; exec "$@"' sh "$@"; }
vault_policy_write(){ local name="$1" file="$2"; { printf '%s\n' "$BGT"; cat "$file"; } | kubectl --kubeconfig "$SHARED_KUBECONFIG" -n vault exec -i vault-0 -- sh -c '
  set -eu; IFS= read -r VAULT_TOKEN; export VAULT_TOKEN; umask 077; p="$(mktemp)"; trap "rm -f \"$p\"" EXIT; cat >"$p"; vault policy write "$1" "$p"' sh "$name" >/dev/null; }
vault_policy_read(){ vault_exec "$BGT" vault policy read "$NEW_POLICY"; }
policy_hash(){ vault_policy_read | shasum -a256 | awk '{print $1}'; }

cleanup(){ local rc=$?; trap - EXIT; set +e
  # emergency policy-restore FIRST (independent of MR state), while the break-glass token is still valid
  if ((DRIFT_APPLIED==1 && DRIFT_RESTORED==0)) && [[ -n "${BGT:-}" && -s "${BASELINE_FILE:-}" ]]; then
    echo "EMERGENCY RESTORE: rewriting okvc- policy to baseline HCL" >&2
    if vault_policy_write "$NEW_POLICY" "$BASELINE_FILE" && [[ "$(policy_hash)" == "$POLICY_HASH_BEFORE" ]]; then
      DRIFT_RESTORED=1; echo "EMERGENCY RESTORE CONFIRMED (policy hash back to baseline)" >&2
    else
      echo "CRITICAL: emergency restore NOT verified — restore $NEW_POLICY manually from $BASELINE_FILE" >&2
    fi
  fi
  if ((rc!=0 && SUCCESS==0)); then echo "EMERGENCY FREEZE: re-pausing XR and all 5 MRs" >&2; freeze_all; fi
  [[ -n "${BGT:-}" ]] && vault_exec "$BGT" vault token revoke -self >/dev/null 2>&1 || true
  [[ -n "${BASELINE_FILE:-}" && "$SUCCESS" == "1" ]] && rm -f "$BASELINE_FILE"
  unset BG BGT; exit "$rc"; }
trap cleanup EXIT
trap 'rc=$?; printf "ABORT: rc=%s at line %s\n" "$rc" "$LINENO" >&2; exit "$rc"' ERR

mr_active_ok(){ kubectl get "$1" "$2" -o json | jq -e '(.metadata.annotations["crossplane.io/paused"]//"")!="true" and any(.status.conditions[]?; .type=="Synced" and .status=="True" and .reason=="ReconcileSuccess") and any(.status.conditions[]?; .type=="Ready" and .status=="True")' >/dev/null; }
fresh_ok(){ kubectl get "$1" "$2" -o json | jq -e --arg before "$3" '
  ([.status.conditions[]?|select(.type=="Synced")]) as $s
  | ($s|length)==1 and $s[0].status=="True" and $s[0].reason=="ReconcileSuccess" and $s[0].lastTransitionTime!=$before
  and any(.status.conditions[]?; .type=="Ready" and .status=="True")
  and ((any(.status.conditions[]?; .type=="LastAsyncOperation" and .status=="False"))|not)
  and ((any(.status.conditions[]?; ((.reason//"")=="AsyncUpdateFailure") or ((.message//"")|test("requires replacing|cannot change the value of the argument.*name";"i"))))|not)
' >/dev/null; }
synced_time(){ kubectl get "$1" "$2" -o json | jq -er '[.status.conditions[]?|select(.type=="Synced")]|if length==1 then .[0].lastTransitionTime else error("expected exactly one Synced condition") end'; }
# Drift-restore health WITHOUT a lastTransitionTime requirement: a Condition need not bump its
# timestamp on every reconcile, so the real drift proof is the policy hash returning to baseline
# (below). This gate only asserts the MR is currently healthy and error-free.
reconcile_healthy(){ kubectl get "$1" "$2" -o json | jq -e '
  any(.status.conditions[]?; .type=="Synced" and .status=="True" and .reason=="ReconcileSuccess")
  and any(.status.conditions[]?; .type=="Ready" and .status=="True")
  and ((any(.status.conditions[]?; .type=="LastAsyncOperation" and .status=="False"))|not)
  and ((any(.status.conditions[]?; ((.reason//"")=="AsyncUpdateFailure") or ((.message//"")|test("requires replacing|cannot change the value of the argument.*name";"i"))))|not)
' >/dev/null; }
uid_of(){ kubectl get "$1" "$2" -o jsonpath='{.metadata.uid}'; }
en_of(){ kubectl get "$1" "$2" -o jsonpath='{.metadata.annotations.crossplane\.io/external-name}'; }
paused_confirmed(){ kubectl get "$@" -o json | jq -e '.metadata.annotations["crossplane.io/paused"]=="true" and any(.status.conditions[]?; .type=="Synced" and .status=="False" and .reason=="ReconcilePaused")' >/dev/null; }
creation_state(){ kubectl get "$1" "$2" -o json | jq -c '{pending:(.metadata.annotations["crossplane.io/external-create-pending"]//""),succeeded:(.metadata.annotations["crossplane.io/external-create-succeeded"]//""),failed:(.metadata.annotations["crossplane.io/external-create-failed"]//"")}'; }
creation_state_safe(){ jq -e '(.pending=="") or (([.succeeded,.failed]|max)!="" and ([.succeeded,.failed]|max) >= .pending)' >/dev/null; }
vso_hash(){ kubectl --kubeconfig "$ROBOTICS_KUBECONFIG" -n "$VSO_SECRET_NS" get secret "$VSO_SECRET_NAME" -o json | jq -S -c '.data' | shasum -a256 | awk '{print $1}'; }
# Proven Phase-2 VSO gate: the auth binding AND the sync object must be healthy, not just the
# materialised Secret bytes. VaultAuth valid + Healthy/Ready; VaultStaticSecret SecretSynced/Healthy/Ready.
vso_health_gate(){
  kubectl --kubeconfig "$ROBOTICS_KUBECONFIG" -n "$VSO_SECRET_NS" get vaultauth ok-robotics -o json | jq -e '
    .status.valid==true and (([.status.conditions[]?|select(.status=="True")|.type]) as $ok | (["Healthy","Ready"]-$ok)==[])' >/dev/null || return 1
  kubectl --kubeconfig "$ROBOTICS_KUBECONFIG" -n "$VSO_SECRET_NS" get vaultstaticsecret "$VSO_SECRET_NAME" -o json | jq -e '
    ([.status.conditions[]?|select(.status=="True")|.type]) as $ok | (["SecretSynced","Healthy","Ready"]-$ok)==[]' >/dev/null || return 1
}
check_five_refs(){ local got exp
  got="$(kubectl get vaultconfig ok-robotics -o json | jq -r '.spec.resourceRefs[]|[.apiVersion,.kind,.name]|@tsv' | sort)"
  exp="$(printf '%s\n' \
    "auth.vault.upbound.io/v1alpha1"$'\t'"Backend"$'\t'"$BACK_MR" \
    "kubernetes.vault.upbound.io/v1alpha1"$'\t'"AuthBackendConfig"$'\t'"$CONF_MR" \
    "kubernetes.vault.upbound.io/v1alpha1"$'\t'"AuthBackendRole"$'\t'"$ROLE_MR" \
    "vault.vault.upbound.io/v1alpha1"$'\t'"Policy"$'\t'"$POLICY_MR" \
    "vault.vault.upbound.io/v1alpha1"$'\t'"Policy"$'\t'"$NEW_MR" | sort)"
  [[ "$got" == "$exp" ]] || { echo "ABORT: unexpected resourceRefs" >&2; echo "--expected--" >&2; printf '%s\n' "$exp" >&2; echo "--actual--" >&2; printf '%s\n' "$got" >&2; return 1; }; }

# ── gate file + chain-of-custody ──
test -s "$GATE" || { echo "ABORT: T3 gate file missing or empty" >&2; exit 1; }
NEW_MR="$(jq -er '.newMR' "$GATE")"; [[ -n "$NEW_MR" && "$NEW_MR" != "$POLICY_MR" ]] || { echo "ABORT: bad NEW_MR in gate" >&2; exit 1; }
# T2 takeover actually EXECUTED (guards against a rendered-but-never-taken-over T2 state)
test -s "$T2_DONE_FILE" || { echo "ABORT: successful T2 takeover handoff missing" >&2; exit 1; }
[[ "$(cat "$T2_DONE_FILE")" == "$NEW_MR" ]] || { echo "ABORT: T2 takeover handoff does not match NEW_MR" >&2; exit 1; }
rm -f "$DONE_FILE"
COMP="$(jq -er '.composition' "$GATE")"
[[ "$(kubectl get vaultconfig ok-robotics -o jsonpath='{.spec.compositionUpdatePolicy}')" == "Manual" ]] || { echo "ABORT: XR not Manual" >&2; exit 1; }
kubectl get vaultconfig -A -o json | jq -e --arg comp "$COMP" '[.items[]|select((.spec.compositionRef.name // "")==$comp and (.spec.compositionUpdatePolicy // "Automatic")!="Manual")]|length==0' >/dev/null || { echo "ABORT: an Automatic XR uses this Composition" >&2; exit 1; }

# ── consumer secret reachable (fail-closed if VSO coordinates are wrong) ──
kubectl --kubeconfig "$ROBOTICS_KUBECONFIG" -n "$VSO_SECRET_NS" get secret "$VSO_SECRET_NAME" >/dev/null 2>&1 || { echo "ABORT: consumer VSO Secret $VSO_SECRET_NS/$VSO_SECRET_NAME not reachable — confirm ROBOTICS_KUBECONFIG / NS / NAME at top of script" >&2; exit 1; }

# ── break-glass (kept alive through the whole active + drift phase) ──
read -rsp 'Vault break-glass password: ' BG; printf '\n'
BGT="$(printf '%s' "$BG" | jq -Rs '{password: .}' | kubectl --kubeconfig "$SHARED_KUBECONFIG" -n vault exec -i vault-0 -- sh -c '
  set -eu; umask 077; p="$(mktemp)"; trap "rm -f \"$p\"" EXIT; cat >"$p"; vault write -format=json auth/userpass/login/breakglass - <"$p"' | jq -er '.auth.client_token')"
unset BG; test -n "$BGT"
vault_exec "$BGT" vault token lookup >/dev/null || { echo "ABORT: break-glass lookup failed" >&2; exit 1; }
echo "BREAK-GLASS TOKEN OK"

# ── PRECONDITION (T2 end-state) + promote ──
EXP_UID="$(jq -er '.compositionUID' "$GATE")"; OLDREV="$(jq -er '.oldRevision' "$GATE")"; NEWREV="$(jq -er '.newRevision' "$GATE")"; EXP_HASH="$(jq -er '.normalizedSpecSHA256' "$GATE")"
[[ "$(kubectl get composition "$COMP" -o jsonpath='{.metadata.uid}')" == "$EXP_UID" ]] || { echo "ABORT: composition identity changed" >&2; exit 1; }
[[ "$(kubectl get vaultconfig ok-robotics -o jsonpath='{.spec.compositionRevisionRef.name}')" == "$OLDREV" ]] || { echo "ABORT: XR not on reviewed T2 revision" >&2; exit 1; }
paused_confirmed vaultconfig ok-robotics || { echo "ABORT: XR not ReconcilePaused" >&2; exit 1; }
[[ "$(kubectl get compositionrevision "$NEWREV" -o json | jq -S '.spec|del(.revision)' | shasum -a256 | awk '{print $1}')" == "$EXP_HASH" ]] || { echo "ABORT: reviewed T3 revision content changed" >&2; exit 1; }
for pair in "$POLICY_RES $POLICY_MR" "$POLICY_RES $NEW_MR" "$ROLE_RES $ROLE_MR" "$CONF_RES $CONF_MR" "$BACK_RES $BACK_MR"; do set -- $pair
  paused_confirmed "$1" "$2" || { echo "ABORT: MR not ReconcilePaused before T3: $2" >&2; exit 1; }; done
vault_exec "$BGT" vault read -format=json auth/kubernetes/ok-robotics/role/sa-obs | jq -e '.data.token_policies==["okvc-ok-robotics-sa-obs"]' >/dev/null || { echo "ABORT: Vault role no longer okvc-only" >&2; exit 1; }
kubectl get "$POLICY_RES" "$POLICY_MR" -o json | jq -e --arg old "$OLD_POLICY" '.metadata.annotations["crossplane.io/paused"]=="true" and .metadata.annotations["crossplane.io/external-name"]==$old and .spec.forProvider.name==$old and .spec.managementPolicies==["*"]' >/dev/null || { echo "ABORT: legacy Policy MR not on consistent OLD identity" >&2; exit 1; }
kubectl get "$POLICY_RES" "$NEW_MR" -o json | jq -e --arg new "$NEW_POLICY" '.metadata.annotations["crossplane.io/external-name"]==$new and .spec.forProvider.name==$new and .spec.managementPolicies==["*"]' >/dev/null || { echo "ABORT: okvc- MR not full-mgmt okvc- before T3" >&2; exit 1; }
# both Vault policies must still exist right before we go active (time may have passed since apply)
POL="$(vault_exec "$BGT" vault policy list)"
grep -Fxq "$OLD_POLICY" <<<"$POL" || { echo "ABORT: old Vault policy missing before 3C" >&2; exit 1; }
grep -Fxq "$NEW_POLICY" <<<"$POL" || { echo "ABORT: okvc Vault policy missing before 3C" >&2; exit 1; }
check_five_refs || { echo "ABORT: pre-T3 resource set not exactly 5" >&2; exit 1; }
# VSO stack must be healthy BEFORE we touch anything
vso_health_gate || { echo "ABORT: VSO not healthy before 3C (VaultAuth/VaultStaticSecret)" >&2; exit 1; }
echo "3C PRECONDITION RECONFIRMED (T2 end-state; both policies present; VSO healthy)"

# capture identities, VSO hash, policy baseline, and paused Synced-times for freshness proofs
P_UID="$(uid_of "$POLICY_RES" "$POLICY_MR")"; R_UID="$(uid_of "$ROLE_RES" "$ROLE_MR")"; C_UID="$(uid_of "$CONF_RES" "$CONF_MR")"; B_UID="$(uid_of "$BACK_RES" "$BACK_MR")"; N_UID="$(uid_of "$POLICY_RES" "$NEW_MR")"
for u in "$P_UID" "$R_UID" "$C_UID" "$B_UID" "$N_UID"; do [[ -n "$u" ]] || { echo "ABORT: missing UID in precondition" >&2; exit 1; }; done
VSO_BEFORE="$(vso_hash)"; [[ -n "$VSO_BEFORE" ]] || { echo "ABORT: could not hash consumer Secret" >&2; exit 1; }
POLICY_HASH_BEFORE="$(policy_hash)"
CREATE_BEFORE="$(creation_state "$POLICY_RES" "$NEW_MR")"; creation_state_safe <<<"$CREATE_BEFORE" || { echo "ABORT: unsafe okvc- creation state before 3C: $CREATE_BEFORE" >&2; exit 1; }
BASELINE_FILE="$(mktemp /tmp/phase3-T3-baseline.XXXXXX)"; ( umask 077; vault_policy_read > "$BASELINE_FILE" ); test -s "$BASELINE_FILE" || { echo "ABORT: could not capture policy baseline" >&2; exit 1; }
SB_BACK="$(synced_time "$BACK_RES" "$BACK_MR")"; SB_CONF="$(synced_time "$CONF_RES" "$CONF_MR")"; SB_ROLE="$(synced_time "$ROLE_RES" "$ROLE_MR")"; SB_OKVC="$(synced_time "$POLICY_RES" "$NEW_MR")"

kubectl patch vaultconfig ok-robotics --type=merge -p "{\"spec\":{\"compositionRevisionRef\":{\"name\":\"$NEWREV\"}}}"
[[ "$(kubectl get vaultconfig ok-robotics -o jsonpath='{.spec.compositionRevisionRef.name}')" == "$NEWREV" ]] || { echo "ABORT: promotion not persisted" >&2; exit 1; }
paused_confirmed vaultconfig ok-robotics || { echo "ABORT: XR unexpectedly unpaused after promote" >&2; exit 1; }
echo "T3 REVISION PROMOTED (XR still paused)"

# ── controlled unpause: XR first (renders T3), then the 4 keep-set MRs ──
kubectl annotate vaultconfig ok-robotics crossplane.io/paused-
deadline=$((SECONDS+120)); until kubectl get vaultconfig ok-robotics -o json | jq -e 'any(.status.conditions[]?; .type=="Synced" and .status=="True" and .reason=="ReconcileSuccess")' >/dev/null; do (( SECONDS>=deadline )) && { echo "ABORT: XR did not reach ReconcileSuccess after unpause" >&2; exit 1; }; sleep 3; done
check_five_refs || { echo "ABORT: XR render changed the resource set" >&2; exit 1; }
for ref in "$BACK_RES $BACK_MR" "$CONF_RES $CONF_MR" "$ROLE_RES $ROLE_MR" "$POLICY_RES $NEW_MR"; do set -- $ref
  kubectl annotate "$1" "$2" crossplane.io/paused- >/dev/null 2>&1 || true; done
echo "XR ACTIVE + keep-set unpaused"

# ── each keep-set MR reaches a FRESH ReconcileSuccess; OLD MR stays paused ──
deadline=$((SECONDS+300))
until fresh_ok "$BACK_RES" "$BACK_MR" "$SB_BACK" && fresh_ok "$CONF_RES" "$CONF_MR" "$SB_CONF" && fresh_ok "$ROLE_RES" "$ROLE_MR" "$SB_ROLE" && fresh_ok "$POLICY_RES" "$NEW_MR" "$SB_OKVC"; do
  (( SECONDS>=deadline )) && { echo "ABORT: keep-set did not all reach fresh ReconcileSuccess" >&2; exit 1; }; sleep 5; done
paused_confirmed "$POLICY_RES" "$POLICY_MR" || { echo "ABORT: OLD Policy MR must stay paused during 3C" >&2; exit 1; }
echo "KEEP-SET ACTIVE (fresh ReconcileSuccess x4; OLD MR still paused)"

# ── steady-state invariants: identities, external-name, role, no create ──
[[ "$(uid_of "$POLICY_RES" "$POLICY_MR")" == "$P_UID" && "$(uid_of "$ROLE_RES" "$ROLE_MR")" == "$R_UID" && "$(uid_of "$CONF_RES" "$CONF_MR")" == "$C_UID" && "$(uid_of "$BACK_RES" "$BACK_MR")" == "$B_UID" && "$(uid_of "$POLICY_RES" "$NEW_MR")" == "$N_UID" ]] || { echo "ABORT: an MR identity changed during 3C activation" >&2; exit 1; }
[[ "$(en_of "$POLICY_RES" "$NEW_MR")" == "$NEW_POLICY" ]] || { echo "ABORT: okvc- external-name drifted" >&2; exit 1; }
kubectl get "$POLICY_RES" "$NEW_MR" -o json | jq -e '.spec.managementPolicies==["*"]' >/dev/null || { echo "ABORT: okvc- MR not full-management" >&2; exit 1; }
vault_exec "$BGT" vault read -format=json auth/kubernetes/ok-robotics/role/sa-obs | jq -e '.data.token_policies==["okvc-ok-robotics-sa-obs"]' >/dev/null || { echo "ABORT: role drifted off okvc-" >&2; exit 1; }
CREATE_ACTIVE="$(creation_state "$POLICY_RES" "$NEW_MR")"; creation_state_safe <<<"$CREATE_ACTIVE" || { echo "ABORT: unsafe okvc- creation state after activation: $CREATE_ACTIVE" >&2; exit 1; }
[[ "$CREATE_ACTIVE" == "$CREATE_BEFORE" ]] || { echo "ABORT: create annotations changed during activation (before=$CREATE_BEFORE after=$CREATE_ACTIVE)" >&2; exit 1; }
[[ "$(policy_hash)" == "$POLICY_HASH_BEFORE" ]] || { echo "ABORT: okvc- policy content changed on activation" >&2; exit 1; }
vso_health_gate || { echo "ABORT: VSO unhealthy after activation" >&2; exit 1; }
[[ "$(vso_hash)" == "$VSO_BEFORE" ]] || { echo "ABORT: consumer Secret changed on activation" >&2; exit 1; }
echo "STEADY ACTIVE STATE OK (5 UIDs stable; external-name okvc-; role okvc-; no create vs baseline; policy + consumer Secret unchanged; VSO healthy)"

# ── REAL DRIFT TEST: inert deny stanza -> Crossplane restores desired HCL ──
DRIFT_FILE="$(mktemp /tmp/phase3-T3-drift.XXXXXX)"; ( umask 077; cat "$BASELINE_FILE" > "$DRIFT_FILE"; printf '\npath "okvc-drift-probe/inert" { capabilities = ["deny"] }\n' >> "$DRIFT_FILE" )
vault_policy_write "$NEW_POLICY" "$DRIFT_FILE"; DRIFT_APPLIED=1; rm -f "$DRIFT_FILE"
[[ "$(policy_hash)" != "$POLICY_HASH_BEFORE" ]] || { echo "ABORT: drift write did not change the policy (test invalid)" >&2; exit 1; }
echo "DRIFT INJECTED (inert deny stanza; policy hash now differs)"
kubectl annotate "$POLICY_RES" "$NEW_MR" openkubes.ai/drift-probe-at="$(date -u +%FT%TZ)" --overwrite >/dev/null
# The authoritative drift proof is the Vault policy hash returning to baseline WITHOUT any
# break-glass restore on this main path; reconcile_healthy just confirms the MR stayed error-free.
deadline=$((SECONDS+300))
until [[ "$(policy_hash)" == "$POLICY_HASH_BEFORE" ]] && reconcile_healthy "$POLICY_RES" "$NEW_MR"; do
  (( SECONDS>=deadline )) && { echo "ABORT: Crossplane did not restore the okvc- policy after drift" >&2; exit 1; }; sleep 5; done
DRIFT_RESTORED=1
[[ "$(en_of "$POLICY_RES" "$NEW_MR")" == "$NEW_POLICY" ]] || { echo "ABORT: okvc- external-name drifted during restore" >&2; exit 1; }
CREATE_POSTDRIFT="$(creation_state "$POLICY_RES" "$NEW_MR")"; creation_state_safe <<<"$CREATE_POSTDRIFT" || { echo "ABORT: unsafe creation state after restore: $CREATE_POSTDRIFT" >&2; exit 1; }
[[ "$CREATE_POSTDRIFT" == "$CREATE_BEFORE" ]] || { echo "ABORT: create annotations changed across drift cycle (baseline=$CREATE_BEFORE after=$CREATE_POSTDRIFT)" >&2; exit 1; }
kubectl annotate "$POLICY_RES" "$NEW_MR" openkubes.ai/drift-probe-at- >/dev/null 2>&1 || true
echo "DRIFT RECONCILED (Crossplane restored desired HCL; MR healthy/ReconcileSuccess; no create; external-name okvc-)"

# ── consumer stayed healthy throughout ──
vso_health_gate || { echo "ABORT: VSO unhealthy after drift cycle" >&2; exit 1; }
[[ "$(vso_hash)" == "$VSO_BEFORE" ]] || { echo "ABORT: consumer Secret changed across the drift cycle" >&2; exit 1; }
echo "CONSUMER VSO INTACT (VaultAuth+VaultStaticSecret healthy; Secret bytes unchanged across activation + drift)"

# ── final active-state proof ──
check_five_refs || { echo "ABORT: resource set changed at final checkpoint" >&2; exit 1; }
mr_active_ok "$BACK_RES" "$BACK_MR" && mr_active_ok "$CONF_RES" "$CONF_MR" && mr_active_ok "$ROLE_RES" "$ROLE_MR" && mr_active_ok "$POLICY_RES" "$NEW_MR" || { echo "ABORT: a keep-set MR not active/ReconcileSuccess at checkpoint" >&2; exit 1; }
paused_confirmed "$POLICY_RES" "$POLICY_MR" || { echo "ABORT: OLD MR not paused at checkpoint" >&2; exit 1; }
[[ "$(kubectl get vaultconfig ok-robotics -o jsonpath='{.metadata.annotations.crossplane\.io/paused}')" != "true" ]] || { echo "ABORT: XR unexpectedly paused at checkpoint" >&2; exit 1; }
echo "FINAL 3C STATE CONFIRMED (XR + keep-set ACTIVE; OLD MR paused; 5 refs)"

vault_exec "$BGT" vault token revoke -self >/dev/null; unset BGT; echo "BREAK-GLASS TOKEN REVOKED"
DONE_TMP="$(mktemp /tmp/phase3-T3-done.XXXXXX)"; printf '%s' "$NEW_MR" > "$DONE_TMP"; mv "$DONE_TMP" "$DONE_FILE"
SUCCESS=1
echo "PHASE 3 3C DONE (active steady state proven; drift reconciled; consumer intact; OLD MR paused pending 3D). NEW_MR=$NEW_MR"
