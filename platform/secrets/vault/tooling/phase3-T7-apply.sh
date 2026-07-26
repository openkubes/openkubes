#!/usr/bin/env bash
# Phase 3 / 3D-3b T7-apply — apply the canonical STEADY-STATE Composition. Proves the new revision
# renders desired resources IDENTICAL to the live T5 revision (only comments differ; all
# composition-resource-name keys + functional lines byte-identical), so promoting it is a no-op for
# Crossplane (no identity migration). NON-runtime-effective: no promote. Precondition = 3D-3a end-state.
set -Eeuo pipefail
cleanup(){ local rc=$?; trap - EXIT; set +e; [[ -n "${BGT:-}" ]] && declare -F vault_exec >/dev/null && vault_exec "$BGT" vault token revoke -self >/dev/null 2>&1 || true; unset BG BGT; exit "$rc"; }
trap cleanup EXIT
trap 'rc=$?; printf "ABORT: rc=%s at line %s\n" "$rc" "$LINENO" >&2; exit "$rc"' ERR

MGMT_KUBECONFIG=~/.kube/ok-mgmt.yaml; SHARED_KUBECONFIG=~/.kube/ok-shared.yaml
ROBOTICS_KUBECONFIG=~/.kube/ok-robotics.yaml; VSO_SECRET_NS=ok-observability; VSO_SECRET_NAME=ok-observability-credentials
COMP=vaultconfig.platform.openkubes.ai
T7_FILE=~/temp/kubernauts/ok/openkubes/platform/secrets/vault/crossplane/vaultconfig-composition.T6-steady.yaml
T5_GATE=/tmp/phase3-T5-gate.json; T6_DONE=/tmp/phase3-T6-done; GATE=/tmp/phase3-T7-gate.json
OLD_POLICY=ok-robotics-sa-obs; NEW_POLICY=okvc-ok-robotics-sa-obs
POLICY_RES=policies.vault.vault.upbound.io;              POLICY_MR=ok-robotics-ee43e699198c
ROLE_RES=authbackendroles.kubernetes.vault.upbound.io;   ROLE_MR=ok-robotics-6cae6fef03f6
CONF_RES=authbackendconfigs.kubernetes.vault.upbound.io; CONF_MR=ok-robotics-1cf8d3106f89
BACK_RES=backends.auth.vault.upbound.io;                 BACK_MR=ok-robotics-05b190692d43
NEW_MR=ok-robotics-f3f5cd82a670
export KUBECONFIG="$MGMT_KUBECONFIG"
vault_exec(){ local t="$1"; shift; printf '%s\n' "$t" | kubectl --kubeconfig "$SHARED_KUBECONFIG" -n vault exec -i vault-0 -- sh -c 'IFS= read -r VAULT_TOKEN; export VAULT_TOKEN; exec "$@"' sh "$@"; }
new_policy_hash(){ vault_exec "$BGT" vault policy read "$NEW_POLICY" | shasum -a256 | awk '{print $1}'; }
mr_active_ok(){ kubectl get "$1" "$2" -o json | jq -e '(.metadata.annotations["crossplane.io/paused"]//"")!="true" and any(.status.conditions[]?; .type=="Synced" and .status=="True" and .reason=="ReconcileSuccess") and any(.status.conditions[]?; .type=="Ready" and .status=="True")' >/dev/null; }
xr_active_ok(){ kubectl get vaultconfig ok-robotics -o json | jq -e '(.metadata.annotations["crossplane.io/paused"]//"")!="true" and any(.status.conditions[]?; .type=="Synced" and .status=="True" and .reason=="ReconcileSuccess")' >/dev/null; }
legacy_absent(){ local out; if out="$(vault_exec "$BGT" vault policy read "$OLD_POLICY" 2>&1)"; then return 1; fi; grep -qiE 'no policy named|policy .* not found|policy .* does not exist' <<<"$out"; }
vso_health_gate(){
  kubectl --kubeconfig "$ROBOTICS_KUBECONFIG" -n "$VSO_SECRET_NS" get vaultauth ok-robotics -o json | jq -e '.status.valid==true and (([.status.conditions[]?|select(.status=="True")|.type]) as $ok | (["Healthy","Ready"]-$ok)==[])' >/dev/null || return 1
  kubectl --kubeconfig "$ROBOTICS_KUBECONFIG" -n "$VSO_SECRET_NS" get vaultstaticsecret "$VSO_SECRET_NAME" -o json | jq -e '([.status.conditions[]?|select(.status=="True")|.type]) as $ok | (["SecretSynced","Healthy","Ready"]-$ok)==[]' >/dev/null || return 1
}
four_keep_refs(){ local got exp
  got="$(kubectl get vaultconfig ok-robotics -o json | jq -r '.spec.resourceRefs[]|[.apiVersion,.kind,.name]|@tsv' | sort)"
  exp="$(printf '%s\n' "auth.vault.upbound.io/v1alpha1"$'\t'"Backend"$'\t'"$BACK_MR" "kubernetes.vault.upbound.io/v1alpha1"$'\t'"AuthBackendConfig"$'\t'"$CONF_MR" "kubernetes.vault.upbound.io/v1alpha1"$'\t'"AuthBackendRole"$'\t'"$ROLE_MR" "vault.vault.upbound.io/v1alpha1"$'\t'"Policy"$'\t'"$NEW_MR" | sort)"
  [[ "$got" == "$exp" ]]; }
old_mr_gone(){ local out; if ! out="$(kubectl get "$POLICY_RES" "$POLICY_MR" --ignore-not-found -o name 2>/dev/null)"; then echo "ERROR: cannot determine whether legacy MR exists" >&2; return 2; fi; [[ -z "$out" ]]; }
rev_template(){ kubectl get compositionrevision "$1" -o json | jq -r '.spec.pipeline[]|select(.step=="render")|.input.inline.template'; }
# normalize to FUNCTIONAL content: drop ONLY full-line comments + blanks. Do NOT strip inline
# "#..." — a '#' can be payload inside a YAML block scalar / Go-template string, so stripping it
# could hide a real change and fail OPEN. Our actual change is full-line comments only.
norm_template(){ sed -E -e '/^[[:space:]]*#/d' -e '/^[[:space:]]*$/d'; }

rm -f "$GATE"

# ── chain-of-custody: T5 revision + 3D-3a (legacy deleted) handoff ──
test -s "$T5_GATE" || { echo "ABORT: T5 gate missing" >&2; exit 1; }
test -s "$T6_DONE" || { echo "ABORT: 3D-3a handoff (T6 done) missing" >&2; exit 1; }
jq -e '.deletedPolicy=="ok-robotics-sa-obs" and .noReferencesProven==true and .crossplaneMRAbsent==true' "$T6_DONE" >/dev/null || { echo "ABORT: 3D-3a handoff not a clean legacy-delete record" >&2; exit 1; }
T5REV="$(jq -er '.newRevision' "$T5_GATE")"; T5_COMP_UID="$(jq -er '.compositionUID' "$T5_GATE")"; T5_REV_HASH="$(jq -er '.normalizedSpecSHA256' "$T5_GATE")"
EXP_NEW_POLICY_SHA="$(jq -er '.remainingPolicySHA256' "$T6_DONE")"
[[ "$(kubectl get composition "$COMP" -o jsonpath='{.metadata.uid}')" == "$T5_COMP_UID" ]] || { echo "ABORT: Composition identity changed since T5" >&2; exit 1; }
[[ "$(kubectl get compositionrevision "$T5REV" -o json | jq -S '.spec|del(.revision)' | shasum -a256 | awk '{print $1}')" == "$T5_REV_HASH" ]] || { echo "ABORT: proven T5 revision content changed" >&2; exit 1; }

# ── Manual XR + on T5 + active ──
[[ "$(kubectl get vaultconfig ok-robotics -o jsonpath='{.spec.compositionUpdatePolicy}')" == "Manual" ]] || { echo "ABORT: XR not Manual" >&2; exit 1; }
kubectl get vaultconfig -A -o json | jq -e --arg comp "$COMP" '[.items[]|select((.spec.compositionRef.name // "")==$comp and (.spec.compositionUpdatePolicy // "Automatic")!="Manual")]|length==0' >/dev/null || { echo "ABORT: an Automatic XR uses this Composition" >&2; exit 1; }
[[ "$(kubectl get vaultconfig ok-robotics -o jsonpath='{.spec.compositionRevisionRef.name}')" == "$T5REV" ]] || { echo "ABORT: XR not on T5 revision" >&2; exit 1; }
[[ "$(kubectl get vaultconfig ok-robotics -o jsonpath='{.metadata.annotations.crossplane\.io/paused}')" != "true" ]] || { echo "ABORT: XR paused — expected ACTIVE 3D-3a end-state" >&2; exit 1; }
xr_active_ok || { echo "ABORT: XR not active/ReconcileSuccess" >&2; exit 1; }

# ── break-glass: 3D-3a end-state Vault invariants ──
read -rsp 'Vault break-glass password: ' BG; printf '\n'
BGT="$(printf '%s' "$BG" | jq -Rs '{password: .}' | kubectl --kubeconfig "$SHARED_KUBECONFIG" -n vault exec -i vault-0 -- sh -c '
  set -eu; umask 077; p="$(mktemp)"; trap "rm -f \"$p\"" EXIT; cat >"$p"; vault write -format=json auth/userpass/login/breakglass - <"$p"' | jq -er '.auth.client_token')"
unset BG; test -n "$BGT"; vault_exec "$BGT" vault token lookup >/dev/null; echo "BREAK-GLASS TOKEN OK"
legacy_absent || { echo "ABORT: legacy policy is present/undeterminable (3D-3a not complete?)" >&2; exit 1; }
[[ "$(new_policy_hash)" == "$EXP_NEW_POLICY_SHA" ]] || { echo "ABORT: okvc- policy hash != 3D-3a baseline" >&2; exit 1; }
vault_exec "$BGT" vault read -format=json auth/kubernetes/ok-robotics/role/sa-obs | jq -e '.data.token_policies==["okvc-ok-robotics-sa-obs"]' >/dev/null || { echo "ABORT: role not okvc-only" >&2; exit 1; }
vault_exec "$BGT" vault token revoke -self >/dev/null; unset BGT; echo "BREAK-GLASS TOKEN REVOKED"

# ── keep-set + refs (3D-3a end-state) ──
old_mr_gone || { echo "ABORT: legacy Crossplane MR present or unreadable" >&2; exit 1; }
four_keep_refs || { echo "ABORT: resourceRefs != 4 keep MRs" >&2; exit 1; }
for pair in "$BACK_RES $BACK_MR" "$CONF_RES $CONF_MR" "$ROLE_RES $ROLE_MR" "$POLICY_RES $NEW_MR"; do set -- $pair
  mr_active_ok "$1" "$2" || { echo "ABORT: keep-set MR not active: $2" >&2; exit 1; }; done
vso_health_gate || { echo "ABORT: VSO not healthy" >&2; exit 1; }
echo "PRECONDITION OK (3D-3a end-state; legacy absent; okvc- baseline; 4 refs active; VSO healthy)"

# ── APPLY T6-steady + exactly one new revision ──
COMP_UID="$(kubectl get composition "$COMP" -o jsonpath='{.metadata.uid}')"
OLDREV="$(kubectl get vaultconfig ok-robotics -o jsonpath='{.spec.compositionRevisionRef.name}')"
[[ "$OLDREV" == "$T5REV" ]] || { echo "ABORT: XR revision drifted from T5" >&2; exit 1; }
OLD_MAX="$(kubectl get compositionrevision -l "crossplane.io/composition-name=$COMP" -o json | jq --arg u "$COMP_UID" '[.items[]|select(any(.metadata.ownerReferences[]?;.uid==$u))|.spec.revision]|max // 0')"
kubectl apply -f "$T7_FILE"
deadline=$((SECONDS+120)); NEWREV=""
while ((SECONDS<deadline)); do
  mapfile -t NR < <(kubectl get compositionrevision -l "crossplane.io/composition-name=$COMP" -o json | jq -r --arg u "$COMP_UID" --argjson old "$OLD_MAX" '.items[]|select(.spec.revision>$old and any(.metadata.ownerReferences[]?;.uid==$u))|[.spec.revision,.metadata.name]|@tsv')
  ((${#NR[@]}==1)) && { IFS=$'\t' read -r _ NEWREV <<<"${NR[0]}"; break; }
  ((${#NR[@]}>1)) && { echo "ABORT: multiple new revisions" >&2; printf '%s\n' "${NR[@]}" >&2; exit 1; }
  sleep 2
done
[[ -n "$NEWREV" ]] || { echo "ABORT: no new revision (unchanged apply?)" >&2; exit 1; }
echo "OLDREV=$OLDREV"; echo "NEWREV=$NEWREV"

# ── (a) snapshot == composition ──
kubectl get composition "$COMP" -o json | jq -S '.spec' > /tmp/t7-composition-spec.json
kubectl get compositionrevision "$NEWREV" -o json | jq -S '.spec|del(.revision)' > /tmp/t7-revision-spec.json
if ! diff -u /tmp/t7-composition-spec.json /tmp/t7-revision-spec.json; then echo "ABORT: revision snapshot differs from Composition" >&2; exit 1; fi
echo "(a) SNAPSHOT == COMPOSITION"

# ── (b) RENDER-EQUIVALENCE PROOF: normalized templates byte-identical + keys identical ──
rev_template "$OLDREV" > /tmp/t7-old.tpl; rev_template "$NEWREV" > /tmp/t7-new.tpl
norm_template < /tmp/t7-old.tpl > /tmp/t7-old.norm; norm_template < /tmp/t7-new.tpl > /tmp/t7-new.norm
if ! diff -u /tmp/t7-old.norm /tmp/t7-new.norm; then echo "ABORT: functional template DIFFERS — not a comments-only change" >&2; exit 1; fi
echo "(b1) FUNCTIONAL TEMPLATE IDENTICAL (comments-only source diff; rendered desired resources unchanged)"
diff <(grep 'composition-resource-name' /tmp/t7-old.tpl) <(grep 'composition-resource-name' /tmp/t7-new.tpl) >/dev/null || { echo "ABORT: composition-resource-name keys changed (would force an identity migration)" >&2; exit 1; }
echo "(b2) composition-resource-name KEYS IDENTICAL (no identity migration)"
# (b3) MACHINE-ENFORCED comments-only: every raw +/- diff line must be a full-line '#' comment.
# Capture the OUTPUT (not the pipeline exit) — under pipefail `diff` returns 1 on any difference,
# which would otherwise make an `if <pipeline>` gate fail OPEN. `|| true` guards the diff-exit.
NONCOMMENT_DIFF="$(diff -U0 /tmp/t7-old.tpl /tmp/t7-new.tpl | grep -E '^[+-][^+-]' | grep -Ev '^[+-][[:space:]]*#' || true)"
if [[ -n "$NONCOMMENT_DIFF" ]]; then echo "ABORT: raw template diff contains a NON-comment change:" >&2; printf '%s\n' "$NONCOMMENT_DIFF" >&2; exit 1; fi
echo "(b3) RAW DIFF IS COMMENTS-ONLY (machine-checked; not just the visual gate)"
# (b0) FULL functional-spec compare: bind EVERY composition/pipeline field (mode, compositeTypeRef,
# functionRefs, pipeline order, ready step, ...) to T5 — not just the rendered resources. Replace
# only the render template with its comment-stripped form, then diff the entire revision specs.
for rev in "$OLDREV" "$NEWREV"; do
  kubectl get compositionrevision "$rev" -o json | jq -e '[.spec.pipeline[]|select(.step=="render")]|length==1' >/dev/null \
    || { echo "ABORT: revision $rev does not contain exactly one render step" >&2; exit 1; }
done
kubectl get compositionrevision "$OLDREV" -o json | jq -S --rawfile tpl /tmp/t7-old.norm '.spec|del(.revision)|(.pipeline[]|select(.step=="render")|.input.inline.template)=$tpl' > /tmp/t7-old-functional-spec.json
kubectl get compositionrevision "$NEWREV" -o json | jq -S --rawfile tpl /tmp/t7-new.norm '.spec|del(.revision)|(.pipeline[]|select(.step=="render")|.input.inline.template)=$tpl' > /tmp/t7-new-functional-spec.json
if ! diff -u /tmp/t7-old-functional-spec.json /tmp/t7-new-functional-spec.json; then echo "ABORT: CompositionRevision specs differ outside comments" >&2; exit 1; fi
echo "(b0) FULL FUNCTIONAL REVISION SPEC IDENTICAL (all composition/pipeline fields bound to T5)"
echo "── (c) raw template diff (HUMAN GATE: comments only) ──"
diff -u /tmp/t7-old.tpl /tmp/t7-new.tpl || true
echo

# ── atomic gate file ──
NEWREV_HASH="$(kubectl get compositionrevision "$NEWREV" -o json | jq -S '.spec|del(.revision)' | shasum -a256 | awk '{print $1}')"
GATE_TMP="$(mktemp /tmp/phase3-T7-gate.XXXXXX)"
jq -n --arg comp "$COMP" --arg compUID "$COMP_UID" --arg oldrev "$OLDREV" --arg newrev "$NEWREV" --arg hash "$NEWREV_HASH" --arg newmr "$NEW_MR" --arg okvcsha "$EXP_NEW_POLICY_SHA" \
  '{composition:$comp,compositionUID:$compUID,oldRevision:$oldrev,newRevision:$newrev,normalizedSpecSHA256:$hash,newMR:$newmr,okvcPolicySHA256:$okvcsha}' > "$GATE_TMP"
mv "$GATE_TMP" "$GATE"
cat "$GATE"; echo
cat <<'GATE'
===================================================================
HUMAN GATE — the (c) raw template diff must show ONLY comment (#) lines changed.
Machine gates already enforced:
  (b1) functional template (comments stripped) is BYTE-IDENTICAL to the live T5 revision
  (b2) every composition-resource-name key is unchanged (no identity migration)
So promoting this revision re-renders the SAME 4 desired resources: no MR is created,
updated, or terminated. If the (c) diff shows any non-comment line -> STOP (do NOT promote).
Nothing promoted yet. If it matches -> run phase3-T7-promote.
===================================================================
GATE
