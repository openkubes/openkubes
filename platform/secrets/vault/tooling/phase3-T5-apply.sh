#!/usr/bin/env bash
# Phase 3 / T5-apply (3D-2, hardened) — apply the OLD-block-removal Composition, identify exactly
# one new CompositionRevision, machine-verify snapshot==composition (fail-closed), show the readable
# T4->T5 inline-template diff for a HUMAN GATE, write /tmp/phase3-T5-gate.json atomically.
# NON-runtime-effective: no promote. Precondition = proven 3D-1 end-state (OLD MR retired, NOT terminating).
set -Eeuo pipefail
cleanup(){ local rc=$?; trap - EXIT; set +e; [[ -n "${BGT:-}" ]] && declare -F vault_exec >/dev/null && vault_exec "$BGT" vault token revoke -self >/dev/null 2>&1 || true; unset BG BGT; exit "$rc"; }
trap cleanup EXIT
trap 'rc=$?; printf "ABORT: rc=%s at line %s\n" "$rc" "$LINENO" >&2; exit "$rc"' ERR

MGMT_KUBECONFIG=~/.kube/ok-mgmt.yaml; SHARED_KUBECONFIG=~/.kube/ok-shared.yaml
COMP=vaultconfig.platform.openkubes.ai
T5_FILE=~/temp/kubernauts/ok/openkubes/platform/secrets/vault/crossplane/vaultconfig-composition.T5.yaml
T4_GATE=/tmp/phase3-T4-gate.json
T4_DONE_FILE=/tmp/phase3-T4-done
GATE=/tmp/phase3-T5-gate.json
OLD_POLICY=ok-robotics-sa-obs; NEW_POLICY=okvc-ok-robotics-sa-obs
POLICY_RES=policies.vault.vault.upbound.io;              POLICY_MR=ok-robotics-ee43e699198c
ROLE_RES=authbackendroles.kubernetes.vault.upbound.io;   ROLE_MR=ok-robotics-6cae6fef03f6
CONF_RES=authbackendconfigs.kubernetes.vault.upbound.io; CONF_MR=ok-robotics-1cf8d3106f89
BACK_RES=backends.auth.vault.upbound.io;                 BACK_MR=ok-robotics-05b190692d43
export KUBECONFIG="$MGMT_KUBECONFIG"
vault_exec(){ local t="$1"; shift; printf '%s\n' "$t" | kubectl --kubeconfig "$SHARED_KUBECONFIG" -n vault exec -i vault-0 -- sh -c 'IFS= read -r VAULT_TOKEN; export VAULT_TOKEN; exec "$@"' sh "$@"; }
mr_active_ok(){ kubectl get "$1" "$2" -o json | jq -e '(.metadata.annotations["crossplane.io/paused"]//"")!="true" and any(.status.conditions[]?; .type=="Synced" and .status=="True" and .reason=="ReconcileSuccess") and any(.status.conditions[]?; .type=="Ready" and .status=="True")' >/dev/null; }

rm -f "$GATE"

# ── read 3D-1 handoff + chain-of-custody ──
test -s "$T4_GATE" || { echo "ABORT: T4 gate file missing (run 3D-1 first)" >&2; exit 1; }
test -s "$T4_DONE_FILE" || { echo "ABORT: successful 3D-1 handoff missing" >&2; exit 1; }
NEW_MR="$(jq -er '.newMR' "$T4_GATE")"; [[ -n "$NEW_MR" && "$NEW_MR" != "$POLICY_MR" ]] || { echo "ABORT: bad NEW_MR in T4 gate" >&2; exit 1; }
[[ "$(cat "$T4_DONE_FILE")" == "$NEW_MR" ]] || { echo "ABORT: 3D-1 handoff does not match NEW_MR" >&2; exit 1; }
T4REV="$(jq -er '.newRevision' "$T4_GATE")"
T4_COMP_UID="$(jq -er '.compositionUID' "$T4_GATE")"
T4_REV_HASH="$(jq -er '.normalizedSpecSHA256' "$T4_GATE")"
[[ "$(kubectl get composition "$COMP" -o jsonpath='{.metadata.uid}')" == "$T4_COMP_UID" ]] || { echo "ABORT: Composition identity changed since 3D-1" >&2; exit 1; }
[[ "$(kubectl get compositionrevision "$T4REV" -o json | jq -S '.spec|del(.revision)' | shasum -a256 | awk '{print $1}')" == "$T4_REV_HASH" ]] || { echo "ABORT: proven T4 revision content changed" >&2; exit 1; }

# ── Manual XR + no Automatic XR ──
[[ "$(kubectl get vaultconfig ok-robotics -o jsonpath='{.spec.compositionUpdatePolicy}')" == "Manual" ]] || { echo "ABORT: target XR is not explicitly Manual" >&2; exit 1; }
kubectl get vaultconfig -A -o json | jq -e --arg comp "$COMP" '[.items[]|select((.spec.compositionRef.name // "")==$comp and (.spec.compositionUpdatePolicy // "Automatic")!="Manual")]|length==0' >/dev/null || { echo "ABORT: an Automatic XR uses this Composition" >&2; exit 1; }

# ── XR ACTIVE on the reviewed T4 revision ──
[[ "$(kubectl get vaultconfig ok-robotics -o jsonpath='{.spec.compositionRevisionRef.name}')" == "$T4REV" ]] || { echo "ABORT: XR not on the proven T4 revision ($T4REV)" >&2; exit 1; }
[[ "$(kubectl get vaultconfig ok-robotics -o jsonpath='{.metadata.annotations.crossplane\.io/paused}')" != "true" ]] || { echo "ABORT: XR paused — expected ACTIVE 3D-1 end-state" >&2; exit 1; }
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

# ── 3D-1 end-state: keep-set active; OLD MR retired (Observe+Orphan+paused, NOT terminating) ──
for pair in "$BACK_RES $BACK_MR" "$CONF_RES $CONF_MR" "$ROLE_RES $ROLE_MR" "$POLICY_RES $NEW_MR"; do set -- $pair
  mr_active_ok "$1" "$2" || { echo "ABORT: keep-set MR not active/ReconcileSuccess: $2" >&2; exit 1; }; done
kubectl get "$POLICY_RES" "$POLICY_MR" -o json | jq -e --arg old "$OLD_POLICY" \
  '.metadata.deletionTimestamp==null and .metadata.annotations["crossplane.io/paused"]=="true" and .metadata.annotations["crossplane.io/external-name"]==$old and .spec.forProvider.name==$old and .spec.managementPolicies==["Observe"] and .spec.deletionPolicy=="Orphan" and any(.status.conditions[]?; .type=="Synced" and .status=="False" and .reason=="ReconcilePaused")' >/dev/null \
  || { echo "ABORT: OLD Policy MR not in retired (Observe+Orphan+paused, not-terminating) state" >&2; exit 1; }
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
[[ "$REFS" == "$EXP" ]] || { echo "ABORT: unexpected resourceRefs pre-T5" >&2; printf '%s\n' "$REFS" >&2; exit 1; }
echo "PRECONDITION OK (3D-1 end-state; keep-set active; OLD MR retired, not terminating)"

# ── APPLY T5 + exactly one new revision ──
COMP_UID="$(kubectl get composition "$COMP" -o jsonpath='{.metadata.uid}')"
OLDREV="$(kubectl get vaultconfig ok-robotics -o jsonpath='{.spec.compositionRevisionRef.name}')"
[[ "$OLDREV" == "$T4REV" ]] || { echo "ABORT: XR revision drifted from T4 revision" >&2; exit 1; }
OLD_MAX="$(kubectl get compositionrevision -l "crossplane.io/composition-name=$COMP" -o json | jq --arg u "$COMP_UID" '[.items[]|select(any(.metadata.ownerReferences[]?;.uid==$u))|.spec.revision]|max // 0')"
kubectl apply -f "$T5_FILE"
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
kubectl get composition "$COMP" -o json | jq -S '.spec' > /tmp/t5-composition-spec.json
kubectl get compositionrevision "$NEWREV" -o json | jq -S '.spec|del(.revision)' > /tmp/t5-revision-spec.json
if ! diff -u /tmp/t5-composition-spec.json /tmp/t5-revision-spec.json; then echo "ABORT: revision snapshot differs from Composition" >&2; exit 1; fi
echo "(a) SNAPSHOT == COMPOSITION"

# ── (b) readable T4->T5 inline-template diff (HUMAN GATE) ──
echo "── (b) T4 -> T5 inline-template diff (HUMAN GATE) ──"
kubectl get compositionrevision "$OLDREV" -o json | jq -r '.spec.pipeline[]|select(.step=="render")|.input.inline.template' > /tmp/t5-old-template.yaml
kubectl get compositionrevision "$NEWREV" -o json | jq -r '.spec.pipeline[]|select(.step=="render")|.input.inline.template' > /tmp/t5-new-template.yaml
diff -u /tmp/t5-old-template.yaml /tmp/t5-new-template.yaml || true
echo

# ── atomic gate file ──
NEWREV_HASH="$(kubectl get compositionrevision "$NEWREV" -o json | jq -S '.spec|del(.revision)' | shasum -a256 | awk '{print $1}')"
GATE_TMP="$(mktemp /tmp/phase3-T5-gate.XXXXXX)"
jq -n --arg comp "$COMP" --arg compUID "$COMP_UID" --arg oldrev "$OLDREV" --arg newrev "$NEWREV" --arg hash "$NEWREV_HASH" --arg newmr "$NEW_MR" \
  '{composition:$comp,compositionUID:$compUID,oldRevision:$oldrev,newRevision:$newrev,normalizedSpecSHA256:$hash,newMR:$newmr}' > "$GATE_TMP"
mv "$GATE_TMP" "$GATE"
cat "$GATE"; echo
cat <<'GATE'
===================================================================
HUMAN GATE — the (b) inline-template diff must show ONLY the DELETION of the
OLD Policy MR block (its 3D-1 comment + the whole policy-<role> Policy MR + one
"---" separator). Nothing added, nothing else changed.
Everything else byte-identical to T4:
    okvc- MR (policy-okvc-<role>): now the FIRST per-role resource; external-name okvc-,
      name okvc-, managementPolicies ["*"] (unchanged)
    Backend / AuthBackendConfig / AuthBackendRole (unchanged)
    Role tokenPolicies: okvc- only (unchanged)
    No other change (SA bindings / TTL / ProviderConfig / mount / okvc- comment)

If the diff shows anything beyond removing the OLD-MR block -> STOP (do NOT terminate).
Nothing promoted yet. If it matches -> run phase3-T5-terminate.
===================================================================
GATE
