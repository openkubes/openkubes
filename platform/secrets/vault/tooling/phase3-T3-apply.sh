#!/usr/bin/env bash
# Phase 3 / T3-apply (3C, hardened) — apply the first-ACTIVE Composition, identify exactly one
# new CompositionRevision, machine-verify snapshot==composition (fail-closed), show the
# readable T2->T3 inline-template diff for a HUMAN GATE, write /tmp/phase3-T3-gate.json atomically.
# NON-runtime-effective: no promote, no unpause. Precondition = proven T2 end-state.
set -Eeuo pipefail
cleanup(){ local rc=$?; trap - EXIT; set +e; [[ -n "${BGT:-}" ]] && declare -F vault_exec >/dev/null && vault_exec "$BGT" vault token revoke -self >/dev/null 2>&1 || true; unset BG BGT; exit "$rc"; }
trap cleanup EXIT
trap 'rc=$?; printf "ABORT: rc=%s at line %s\n" "$rc" "$LINENO" >&2; exit "$rc"' ERR

MGMT_KUBECONFIG=~/.kube/ok-mgmt.yaml; SHARED_KUBECONFIG=~/.kube/ok-shared.yaml
COMP=vaultconfig.platform.openkubes.ai
T3_FILE=~/temp/kubernauts/ok/openkubes/platform/secrets/vault/crossplane/vaultconfig-composition.T3.yaml
T2_GATE=/tmp/phase3-T2-gate.json
T2_DONE_FILE=/tmp/phase3-T2-done
GATE=/tmp/phase3-T3-gate.json
OLD_POLICY=ok-robotics-sa-obs; NEW_POLICY=okvc-ok-robotics-sa-obs
POLICY_RES=policies.vault.vault.upbound.io;              POLICY_MR=ok-robotics-ee43e699198c
ROLE_RES=authbackendroles.kubernetes.vault.upbound.io;   ROLE_MR=ok-robotics-6cae6fef03f6
CONF_RES=authbackendconfigs.kubernetes.vault.upbound.io; CONF_MR=ok-robotics-1cf8d3106f89
BACK_RES=backends.auth.vault.upbound.io;                 BACK_MR=ok-robotics-05b190692d43
export KUBECONFIG="$MGMT_KUBECONFIG"
vault_exec(){ local t="$1"; shift; printf '%s\n' "$t" | kubectl --kubeconfig "$SHARED_KUBECONFIG" -n vault exec -i vault-0 -- sh -c 'IFS= read -r VAULT_TOKEN; export VAULT_TOKEN; exec "$@"' sh "$@"; }
paused_confirmed(){ kubectl get "$@" -o json | jq -e '.metadata.annotations["crossplane.io/paused"]=="true" and any(.status.conditions[]?; .type=="Synced" and .status=="False" and .reason=="ReconcilePaused")' >/dev/null; }
creation_state(){ kubectl get "$1" "$2" -o json | jq -c '{pending:(.metadata.annotations["crossplane.io/external-create-pending"]//""),succeeded:(.metadata.annotations["crossplane.io/external-create-succeeded"]//""),failed:(.metadata.annotations["crossplane.io/external-create-failed"]//"")}'; }
creation_state_safe(){ jq -e '(.pending=="") or (([.succeeded,.failed]|max)!="" and ([.succeeded,.failed]|max) >= .pending)' >/dev/null; }

rm -f "$GATE"

# ── read T2 handoff (proven end-state) + chain-of-custody ──
test -s "$T2_GATE" || { echo "ABORT: T2 gate file missing (run T2 first)" >&2; exit 1; }
NEW_MR="$(jq -er '.newMR' "$T2_GATE")"; [[ -n "$NEW_MR" && "$NEW_MR" != "$POLICY_MR" ]] || { echo "ABORT: bad NEW_MR in T2 gate" >&2; exit 1; }
T2REV="$(jq -er '.newRevision' "$T2_GATE")"
T2_COMP_UID="$(jq -er '.compositionUID' "$T2_GATE")"
T2_REV_HASH="$(jq -er '.normalizedSpecSHA256' "$T2_GATE")"
[[ "$(kubectl get composition "$COMP" -o jsonpath='{.metadata.uid}')" == "$T2_COMP_UID" ]] || { echo "ABORT: Composition identity changed since T2" >&2; exit 1; }
[[ "$(kubectl get compositionrevision "$T2REV" -o json | jq -S '.spec|del(.revision)' | shasum -a256 | awk '{print $1}')" == "$T2_REV_HASH" ]] || { echo "ABORT: proven T2 revision content changed" >&2; exit 1; }
# T2 takeover actually EXECUTED (marker written only after full-management takeover proven)
test -s "$T2_DONE_FILE" || { echo "ABORT: successful T2 takeover handoff missing" >&2; exit 1; }
[[ "$(cat "$T2_DONE_FILE")" == "$NEW_MR" ]] || { echo "ABORT: T2 takeover handoff does not match NEW_MR" >&2; exit 1; }

# ── Manual XR + no Automatic XR on this Composition ──
[[ "$(kubectl get vaultconfig ok-robotics -o jsonpath='{.spec.compositionUpdatePolicy}')" == "Manual" ]] || { echo "ABORT: target XR is not explicitly Manual" >&2; exit 1; }
kubectl get vaultconfig -A -o json | jq -e --arg comp "$COMP" '[.items[]|select((.spec.compositionRef.name // "")==$comp and (.spec.compositionUpdatePolicy // "Automatic")!="Manual")]|length==0' >/dev/null || { echo "ABORT: an Automatic XR uses this Composition" >&2; exit 1; }

# ── XR must still be on the reviewed T2 revision and paused ──
[[ "$(kubectl get vaultconfig ok-robotics -o jsonpath='{.spec.compositionRevisionRef.name}')" == "$T2REV" ]] || { echo "ABORT: XR not on the proven T2 revision ($T2REV)" >&2; exit 1; }
paused_confirmed vaultconfig ok-robotics || { echo "ABORT: XR not ReconcilePaused" >&2; exit 1; }

# ── break-glass + Vault-side invariants ──
read -rsp 'Vault break-glass password: ' BG; printf '\n'
BGT="$(printf '%s' "$BG" | jq -Rs '{password: .}' | kubectl --kubeconfig "$SHARED_KUBECONFIG" -n vault exec -i vault-0 -- sh -c '
  set -eu; umask 077; p="$(mktemp)"; trap "rm -f \"$p\"" EXIT; cat >"$p"; vault write -format=json auth/userpass/login/breakglass - <"$p"' | jq -er '.auth.client_token')"
unset BG; test -n "$BGT"
vault_exec "$BGT" vault token lookup >/dev/null || { echo "ABORT: break-glass lookup failed" >&2; exit 1; }
echo "BREAK-GLASS TOKEN OK"
vault_exec "$BGT" vault read -format=json auth/kubernetes/ok-robotics/role/sa-obs | jq -e '.data.token_policies==["okvc-ok-robotics-sa-obs"]' >/dev/null || { echo "ABORT: role not okvc-" >&2; exit 1; }
POL="$(vault_exec "$BGT" vault policy list)"
grep -Fxq "$OLD_POLICY" <<<"$POL" || { echo "ABORT: old policy missing" >&2; exit 1; }
grep -Fxq "$NEW_POLICY" <<<"$POL" || { echo "ABORT: okvc policy missing" >&2; exit 1; }
vault_exec "$BGT" vault token revoke -self >/dev/null; unset BGT; echo "BREAK-GLASS TOKEN REVOKED"

# ── T2 end-state frozen precondition: 5 MRs paused; okvc- MR full mgmt; old MR legacy/["*"] ──
for pair in "$POLICY_RES $POLICY_MR" "$POLICY_RES $NEW_MR" "$ROLE_RES $ROLE_MR" "$CONF_RES $CONF_MR" "$BACK_RES $BACK_MR"; do set -- $pair
  paused_confirmed "$1" "$2" || { echo "ABORT: $2 not ReconcilePaused" >&2; exit 1; }; done
kubectl get "$POLICY_RES" "$POLICY_MR" -o json | jq -e --arg old "$OLD_POLICY" \
  '.metadata.annotations["crossplane.io/external-name"]==$old and .spec.forProvider.name==$old and .spec.managementPolicies==["*"]' >/dev/null \
  || { echo "ABORT: legacy Policy MR not on consistent OLD identity" >&2; exit 1; }
kubectl get "$POLICY_RES" "$NEW_MR" -o json | jq -e --arg new "$NEW_POLICY" \
  '.metadata.annotations["crossplane.io/external-name"]==$new and .spec.forProvider.name==$new and .spec.managementPolicies==["*"]' >/dev/null \
  || { echo "ABORT: okvc- MR not in full-management okvc- state" >&2; exit 1; }
creation_state "$POLICY_RES" "$NEW_MR" | creation_state_safe || { echo "ABORT: okvc- MR unsafe creation state" >&2; exit 1; }
REFS="$(kubectl get vaultconfig ok-robotics -o json | jq -r '.spec.resourceRefs[]|[.apiVersion,.kind,.name]|@tsv' | sort)"
EXP="$(printf '%s\n' \
  "auth.vault.upbound.io/v1alpha1"$'\t'"Backend"$'\t'"$BACK_MR" \
  "kubernetes.vault.upbound.io/v1alpha1"$'\t'"AuthBackendConfig"$'\t'"$CONF_MR" \
  "kubernetes.vault.upbound.io/v1alpha1"$'\t'"AuthBackendRole"$'\t'"$ROLE_MR" \
  "vault.vault.upbound.io/v1alpha1"$'\t'"Policy"$'\t'"$POLICY_MR" \
  "vault.vault.upbound.io/v1alpha1"$'\t'"Policy"$'\t'"$NEW_MR" | sort)"
[[ "$REFS" == "$EXP" ]] || { echo "ABORT: unexpected resourceRefs pre-T3" >&2; printf '%s\n' "$REFS" >&2; exit 1; }
echo "PRECONDITION OK (T2 end-state; 5 MRs paused; okvc- full-mgmt; old MR legacy/paused)"

# ── APPLY T3 + exactly one new revision ──
COMP_UID="$(kubectl get composition "$COMP" -o jsonpath='{.metadata.uid}')"
OLDREV="$(kubectl get vaultconfig ok-robotics -o jsonpath='{.spec.compositionRevisionRef.name}')"
[[ "$OLDREV" == "$T2REV" ]] || { echo "ABORT: XR revision drifted from T2 revision" >&2; exit 1; }
OLD_MAX="$(kubectl get compositionrevision -l "crossplane.io/composition-name=$COMP" -o json | jq --arg u "$COMP_UID" '[.items[]|select(any(.metadata.ownerReferences[]?;.uid==$u))|.spec.revision]|max // 0')"
kubectl apply -f "$T3_FILE"
deadline=$((SECONDS+120)); NEWREV=""
while ((SECONDS<deadline)); do
  mapfile -t NR < <(kubectl get compositionrevision -l "crossplane.io/composition-name=$COMP" -o json \
    | jq -r --arg u "$COMP_UID" --argjson old "$OLD_MAX" '.items[]|select(.spec.revision>$old and any(.metadata.ownerReferences[]?;.uid==$u))|[.spec.revision,.metadata.name]|@tsv')
  ((${#NR[@]}==1)) && { IFS=$'\t' read -r _ NEWREV <<<"${NR[0]}"; break; }
  ((${#NR[@]}>1)) && { echo "ABORT: multiple new revisions" >&2; printf '%s\n' "${NR[@]}" >&2; exit 1; }
  sleep 2
done
[[ -n "$NEWREV" ]] || { echo "ABORT: no new revision (unchanged apply?)" >&2; exit 1; }
echo "OLDREV=$OLDREV"; echo "NEWREV=$NEWREV"

# ── (a) snapshot == composition (fail-closed) ──
kubectl get composition "$COMP" -o json | jq -S '.spec' > /tmp/t3-composition-spec.json
kubectl get compositionrevision "$NEWREV" -o json | jq -S '.spec|del(.revision)' > /tmp/t3-revision-spec.json
if ! diff -u /tmp/t3-composition-spec.json /tmp/t3-revision-spec.json; then echo "ABORT: revision snapshot differs from Composition" >&2; exit 1; fi
echo "(a) SNAPSHOT == COMPOSITION"

# ── (b) readable T2->T3 inline-template diff (HUMAN GATE) ──
echo "── (b) T2 -> T3 inline-template diff (HUMAN GATE) ──"
kubectl get compositionrevision "$OLDREV" -o json | jq -r '.spec.pipeline[]|select(.step=="render")|.input.inline.template' > /tmp/t3-old-template.yaml
kubectl get compositionrevision "$NEWREV" -o json | jq -r '.spec.pipeline[]|select(.step=="render")|.input.inline.template' > /tmp/t3-new-template.yaml
diff -u /tmp/t3-old-template.yaml /tmp/t3-new-template.yaml || true
echo

# ── atomic gate file ──
NEWREV_HASH="$(kubectl get compositionrevision "$NEWREV" -o json | jq -S '.spec|del(.revision)' | shasum -a256 | awk '{print $1}')"
GATE_TMP="$(mktemp /tmp/phase3-T3-gate.XXXXXX)"
jq -n --arg comp "$COMP" --arg compUID "$COMP_UID" --arg oldrev "$OLDREV" --arg newrev "$NEWREV" --arg hash "$NEWREV_HASH" --arg newmr "$NEW_MR" \
  '{composition:$comp,compositionUID:$compUID,oldRevision:$oldrev,newRevision:$newrev,normalizedSpecSHA256:$hash,newMR:$newmr}' > "$GATE_TMP"
mv "$GATE_TMP" "$GATE"
cat "$GATE"; echo
cat <<'GATE'
===================================================================
HUMAN GATE — the (b) inline-template diff must show ONLY four deleted lines:
four `crossplane.io/paused: "true"` annotations, one each on:
    Backend, AuthBackendConfig, okvc- Policy MR (policy-okvc-<role>), AuthBackendRole

The OLD Policy MR (policy-<role>) MUST KEEP its `crossplane.io/paused: "true"`
(it stays frozen through 3C; its Orphan/removal is 3D). Everything else byte-identical:
    okvc- MR: external-name okvc-, name okvc-, managementPolicies ["*"] (unchanged)
    old MR: legacy name, ["*"], paused (unchanged)
    Role tokenPolicies: okvc- only (unchanged)
    No other change (SA bindings / TTL / ProviderConfig / mount / comments)

If the diff shows anything beyond those four deletions -> STOP (do NOT run 3C).
Nothing promoted or unpaused yet. If it matches -> run phase3-T3-run.
===================================================================
GATE
