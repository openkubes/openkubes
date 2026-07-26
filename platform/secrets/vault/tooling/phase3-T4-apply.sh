#!/usr/bin/env bash
# Phase 3 / T4-apply (3D-1, hardened) — apply the OLD-MR-retire Composition, identify exactly one
# new CompositionRevision, machine-verify snapshot==composition (fail-closed), show the readable
# T3->T4 inline-template diff for a HUMAN GATE, write /tmp/phase3-T4-gate.json atomically.
# NON-runtime-effective: no promote, no unpause. Precondition = proven 3C ACTIVE end-state.
set -Eeuo pipefail
cleanup(){ local rc=$?; trap - EXIT; set +e; [[ -n "${BGT:-}" ]] && declare -F vault_exec >/dev/null && vault_exec "$BGT" vault token revoke -self >/dev/null 2>&1 || true; unset BG BGT; exit "$rc"; }
trap cleanup EXIT
trap 'rc=$?; printf "ABORT: rc=%s at line %s\n" "$rc" "$LINENO" >&2; exit "$rc"' ERR

MGMT_KUBECONFIG=~/.kube/ok-mgmt.yaml; SHARED_KUBECONFIG=~/.kube/ok-shared.yaml
COMP=vaultconfig.platform.openkubes.ai
T4_FILE=~/temp/kubernauts/ok/openkubes/platform/secrets/vault/crossplane/vaultconfig-composition.T4-orphan.yaml
T3_GATE=/tmp/phase3-T3-gate.json
T3_DONE_FILE=/tmp/phase3-T3-done
GATE=/tmp/phase3-T4-gate.json
OLD_POLICY=ok-robotics-sa-obs; NEW_POLICY=okvc-ok-robotics-sa-obs
POLICY_RES=policies.vault.vault.upbound.io;              POLICY_MR=ok-robotics-ee43e699198c
ROLE_RES=authbackendroles.kubernetes.vault.upbound.io;   ROLE_MR=ok-robotics-6cae6fef03f6
CONF_RES=authbackendconfigs.kubernetes.vault.upbound.io; CONF_MR=ok-robotics-1cf8d3106f89
BACK_RES=backends.auth.vault.upbound.io;                 BACK_MR=ok-robotics-05b190692d43
export KUBECONFIG="$MGMT_KUBECONFIG"
vault_exec(){ local t="$1"; shift; printf '%s\n' "$t" | kubectl --kubeconfig "$SHARED_KUBECONFIG" -n vault exec -i vault-0 -- sh -c 'IFS= read -r VAULT_TOKEN; export VAULT_TOKEN; exec "$@"' sh "$@"; }
paused_confirmed(){ kubectl get "$@" -o json | jq -e '.metadata.annotations["crossplane.io/paused"]=="true" and any(.status.conditions[]?; .type=="Synced" and .status=="False" and .reason=="ReconcilePaused")' >/dev/null; }
mr_active_ok(){ kubectl get "$1" "$2" -o json | jq -e '(.metadata.annotations["crossplane.io/paused"]//"")!="true" and any(.status.conditions[]?; .type=="Synced" and .status=="True" and .reason=="ReconcileSuccess") and any(.status.conditions[]?; .type=="Ready" and .status=="True")' >/dev/null; }

rm -f "$GATE"

# ── read 3C handoff (proven ACTIVE end-state) + chain-of-custody ──
test -s "$T3_GATE" || { echo "ABORT: T3 gate file missing (run 3C first)" >&2; exit 1; }
test -s "$T3_DONE_FILE" || { echo "ABORT: successful 3C handoff missing" >&2; exit 1; }
NEW_MR="$(jq -er '.newMR' "$T3_GATE")"; [[ -n "$NEW_MR" && "$NEW_MR" != "$POLICY_MR" ]] || { echo "ABORT: bad NEW_MR in T3 gate" >&2; exit 1; }
[[ "$(cat "$T3_DONE_FILE")" == "$NEW_MR" ]] || { echo "ABORT: 3C handoff does not match NEW_MR" >&2; exit 1; }
T3REV="$(jq -er '.newRevision' "$T3_GATE")"
T3_COMP_UID="$(jq -er '.compositionUID' "$T3_GATE")"
T3_REV_HASH="$(jq -er '.normalizedSpecSHA256' "$T3_GATE")"
[[ "$(kubectl get composition "$COMP" -o jsonpath='{.metadata.uid}')" == "$T3_COMP_UID" ]] || { echo "ABORT: Composition identity changed since 3C" >&2; exit 1; }
[[ "$(kubectl get compositionrevision "$T3REV" -o json | jq -S '.spec|del(.revision)' | shasum -a256 | awk '{print $1}')" == "$T3_REV_HASH" ]] || { echo "ABORT: proven T3 revision content changed" >&2; exit 1; }

# ── Manual XR + no Automatic XR ──
[[ "$(kubectl get vaultconfig ok-robotics -o jsonpath='{.spec.compositionUpdatePolicy}')" == "Manual" ]] || { echo "ABORT: target XR is not explicitly Manual" >&2; exit 1; }
kubectl get vaultconfig -A -o json | jq -e --arg comp "$COMP" '[.items[]|select((.spec.compositionRef.name // "")==$comp and (.spec.compositionUpdatePolicy // "Automatic")!="Manual")]|length==0' >/dev/null || { echo "ABORT: an Automatic XR uses this Composition" >&2; exit 1; }

# ── XR ACTIVE on the reviewed T3 revision ──
[[ "$(kubectl get vaultconfig ok-robotics -o jsonpath='{.spec.compositionRevisionRef.name}')" == "$T3REV" ]] || { echo "ABORT: XR not on the proven T3 revision ($T3REV)" >&2; exit 1; }
[[ "$(kubectl get vaultconfig ok-robotics -o jsonpath='{.metadata.annotations.crossplane\.io/paused}')" != "true" ]] || { echo "ABORT: XR is paused — expected ACTIVE 3C end-state" >&2; exit 1; }
kubectl get vaultconfig ok-robotics -o json | jq -e 'any(.status.conditions[]?; .type=="Synced" and .status=="True" and .reason=="ReconcileSuccess")' >/dev/null || { echo "ABORT: XR not ReconcileSuccess" >&2; exit 1; }

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

# ── 3C ACTIVE end-state: keep-set active; OLD MR paused/legacy/["*"]; okvc- full-mgmt ──
for pair in "$BACK_RES $BACK_MR" "$CONF_RES $CONF_MR" "$ROLE_RES $ROLE_MR" "$POLICY_RES $NEW_MR"; do set -- $pair
  mr_active_ok "$1" "$2" || { echo "ABORT: keep-set MR not active/ReconcileSuccess: $2" >&2; exit 1; }; done
paused_confirmed "$POLICY_RES" "$POLICY_MR" || { echo "ABORT: OLD Policy MR not paused" >&2; exit 1; }
kubectl get "$POLICY_RES" "$POLICY_MR" -o json | jq -e --arg old "$OLD_POLICY" \
  '.metadata.deletionTimestamp==null and .metadata.annotations["crossplane.io/external-name"]==$old and .spec.forProvider.name==$old and .spec.managementPolicies==["*"]' >/dev/null \
  || { echo "ABORT: OLD Policy MR is terminating or not on legacy/full-mgmt identity" >&2; exit 1; }
kubectl get "$POLICY_RES" "$NEW_MR" -o json | jq -e --arg new "$NEW_POLICY" \
  '.metadata.annotations["crossplane.io/external-name"]==$new and .spec.forProvider.name==$new and .spec.managementPolicies==["*"]' >/dev/null \
  || { echo "ABORT: okvc- MR not full-management okvc-" >&2; exit 1; }
REFS="$(kubectl get vaultconfig ok-robotics -o json | jq -r '.spec.resourceRefs[]|[.apiVersion,.kind,.name]|@tsv' | sort)"
EXP="$(printf '%s\n' \
  "auth.vault.upbound.io/v1alpha1"$'\t'"Backend"$'\t'"$BACK_MR" \
  "kubernetes.vault.upbound.io/v1alpha1"$'\t'"AuthBackendConfig"$'\t'"$CONF_MR" \
  "kubernetes.vault.upbound.io/v1alpha1"$'\t'"AuthBackendRole"$'\t'"$ROLE_MR" \
  "vault.vault.upbound.io/v1alpha1"$'\t'"Policy"$'\t'"$POLICY_MR" \
  "vault.vault.upbound.io/v1alpha1"$'\t'"Policy"$'\t'"$NEW_MR" | sort)"
[[ "$REFS" == "$EXP" ]] || { echo "ABORT: unexpected resourceRefs pre-T4" >&2; printf '%s\n' "$REFS" >&2; exit 1; }
echo "PRECONDITION OK (3C ACTIVE end-state; keep-set active; OLD MR paused/legacy/[*])"

# ── APPLY T4 + exactly one new revision ──
COMP_UID="$(kubectl get composition "$COMP" -o jsonpath='{.metadata.uid}')"
OLDREV="$(kubectl get vaultconfig ok-robotics -o jsonpath='{.spec.compositionRevisionRef.name}')"
[[ "$OLDREV" == "$T3REV" ]] || { echo "ABORT: XR revision drifted from T3 revision" >&2; exit 1; }
OLD_MAX="$(kubectl get compositionrevision -l "crossplane.io/composition-name=$COMP" -o json | jq --arg u "$COMP_UID" '[.items[]|select(any(.metadata.ownerReferences[]?;.uid==$u))|.spec.revision]|max // 0')"
kubectl apply -f "$T4_FILE"
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
kubectl get composition "$COMP" -o json | jq -S '.spec' > /tmp/t4-composition-spec.json
kubectl get compositionrevision "$NEWREV" -o json | jq -S '.spec|del(.revision)' > /tmp/t4-revision-spec.json
if ! diff -u /tmp/t4-composition-spec.json /tmp/t4-revision-spec.json; then echo "ABORT: revision snapshot differs from Composition" >&2; exit 1; fi
echo "(a) SNAPSHOT == COMPOSITION"

# ── (b) readable T3->T4 inline-template diff (HUMAN GATE) ──
echo "── (b) T3 -> T4 inline-template diff (HUMAN GATE) ──"
kubectl get compositionrevision "$OLDREV" -o json | jq -r '.spec.pipeline[]|select(.step=="render")|.input.inline.template' > /tmp/t4-old-template.yaml
kubectl get compositionrevision "$NEWREV" -o json | jq -r '.spec.pipeline[]|select(.step=="render")|.input.inline.template' > /tmp/t4-new-template.yaml
diff -u /tmp/t4-old-template.yaml /tmp/t4-new-template.yaml || true
echo

# ── atomic gate file ──
NEWREV_HASH="$(kubectl get compositionrevision "$NEWREV" -o json | jq -S '.spec|del(.revision)' | shasum -a256 | awk '{print $1}')"
GATE_TMP="$(mktemp /tmp/phase3-T4-gate.XXXXXX)"
jq -n --arg comp "$COMP" --arg compUID "$COMP_UID" --arg oldrev "$OLDREV" --arg newrev "$NEWREV" --arg hash "$NEWREV_HASH" --arg newmr "$NEW_MR" \
  '{composition:$comp,compositionUID:$compUID,oldRevision:$oldrev,newRevision:$newrev,normalizedSpecSHA256:$hash,newMR:$newmr}' > "$GATE_TMP"
mv "$GATE_TMP" "$GATE"
cat "$GATE"; echo
cat <<'GATE'
===================================================================
HUMAN GATE — the (b) inline-template diff must show ONLY changes to the
OLD Policy MR block (composition-resource-name policy-<role>):
    * its header comment updated to the 3D-1 wording
    * managementPolicies ["*"] -> ["Observe"]
    * + deletionPolicy: Orphan   (new line)
The OLD MR MUST KEEP `crossplane.io/paused: "true"` and its legacy name.
Everything else byte-identical to T3:
    okvc- MR: external-name okvc-, name okvc-, managementPolicies ["*"] (unchanged)
    Backend / AuthBackendConfig / AuthBackendRole (unchanged; already unpaused in T3)
    Role tokenPolicies: okvc- only (unchanged)
    No other change (SA bindings / TTL / ProviderConfig / mount)

If the diff shows anything beyond the OLD-MR block -> STOP (do NOT promote).
Nothing promoted yet. If it matches -> run phase3-T4-promote.
===================================================================
GATE
