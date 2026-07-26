#!/usr/bin/env bash
# Phase 3 / T2-apply (hardened) — apply T2 (Takeover) Composition, identify exactly one
# new CompositionRevision, machine-verify snapshot==composition (fail-closed), show the
# semantic T1->T2 diff for a HUMAN GATE, write /tmp/phase3-T2-gate.json atomically.
# NON-runtime-effective: no promote, no unpause. Precondition = proven T1 end-state.
set -Eeuo pipefail
cleanup(){ local rc=$?; trap - EXIT; set +e; [[ -n "${BGT:-}" ]] && declare -F vault_exec >/dev/null && vault_exec "$BGT" vault token revoke -self >/dev/null 2>&1 || true; unset BG BGT; exit "$rc"; }
trap cleanup EXIT
trap 'rc=$?; printf "ABORT: rc=%s at line %s\n" "$rc" "$LINENO" >&2; exit "$rc"' ERR

MGMT_KUBECONFIG=~/.kube/ok-mgmt.yaml; SHARED_KUBECONFIG=~/.kube/ok-shared.yaml
COMP=vaultconfig.platform.openkubes.ai
T2_FILE=~/temp/kubernauts/ok/openkubes/platform/secrets/vault/crossplane/vaultconfig-composition.T2.yaml
T1_GATE=/tmp/phase3-T1-gate.json
T1_NEWMR_FILE=/tmp/phase3-T1-newmr
GATE=/tmp/phase3-T2-gate.json
OLD_POLICY=ok-robotics-sa-obs; NEW_POLICY=okvc-ok-robotics-sa-obs
POLICY_RES=policies.vault.vault.upbound.io;              POLICY_MR=ok-robotics-ee43e699198c
ROLE_RES=authbackendroles.kubernetes.vault.upbound.io;   ROLE_MR=ok-robotics-6cae6fef03f6
CONF_RES=authbackendconfigs.kubernetes.vault.upbound.io; CONF_MR=ok-robotics-1cf8d3106f89
BACK_RES=backends.auth.vault.upbound.io;                 BACK_MR=ok-robotics-05b190692d43
export KUBECONFIG="$MGMT_KUBECONFIG"
vault_exec(){ local t="$1"; shift; printf '%s\n' "$t" | kubectl --kubeconfig "$SHARED_KUBECONFIG" -n vault exec -i vault-0 -- sh -c 'IFS= read -r VAULT_TOKEN; export VAULT_TOKEN; exec "$@"' sh "$@"; }
paused_confirmed(){ kubectl get "$@" -o json | jq -e '.metadata.annotations["crossplane.io/paused"]=="true" and any(.status.conditions[]?; .type=="Synced" and .status=="False" and .reason=="ReconcilePaused")' >/dev/null; }
en_of(){ kubectl get "$1" "$2" -o jsonpath='{.metadata.annotations.crossplane\.io/external-name}'; }
creation_state(){ kubectl get "$1" "$2" -o json | jq -c '{pending:(.metadata.annotations["crossplane.io/external-create-pending"]//""),succeeded:(.metadata.annotations["crossplane.io/external-create-succeeded"]//""),failed:(.metadata.annotations["crossplane.io/external-create-failed"]//"")}'; }
creation_state_safe(){ jq -e '(.pending=="") or (([.succeeded,.failed]|max)!="" and ([.succeeded,.failed]|max) >= .pending)' >/dev/null; }

rm -f "$GATE"

# ── read T1 handoff (proven end-state) ──
test -s "$T1_GATE"      || { echo "ABORT: T1 gate file missing (run T1 first)" >&2; exit 1; }
test -s "$T1_NEWMR_FILE" || { echo "ABORT: T1 new-MR handoff missing (run T1 import first)" >&2; exit 1; }
NEW_MR="$(cat "$T1_NEWMR_FILE")"; [[ -n "$NEW_MR" && "$NEW_MR" != "$POLICY_MR" ]] || { echo "ABORT: bad NEW_MR handoff: '$NEW_MR'" >&2; exit 1; }
T1REV="$(jq -er '.newRevision' "$T1_GATE")"
T1_COMP_UID="$(jq -er '.compositionUID' "$T1_GATE")"
T1_REV_HASH="$(jq -er '.normalizedSpecSHA256' "$T1_GATE")"

# ── T1 chain-of-custody: don't trust just a /tmp filename — bind to the exact proven T1 ──
[[ "$(kubectl get composition "$COMP" -o jsonpath='{.metadata.uid}')" == "$T1_COMP_UID" ]] || { echo "ABORT: Composition identity changed since T1" >&2; exit 1; }
[[ "$(kubectl get compositionrevision "$T1REV" -o json | jq -S '.spec|del(.revision)' | shasum -a256 | awk '{print $1}')" == "$T1_REV_HASH" ]] || { echo "ABORT: proven T1 revision content changed" >&2; exit 1; }

# ── Manual XR + no Automatic XR on this Composition ──
[[ "$(kubectl get vaultconfig ok-robotics -o jsonpath='{.spec.compositionUpdatePolicy}')" == "Manual" ]] || { echo "ABORT: target XR is not explicitly Manual" >&2; exit 1; }
kubectl get vaultconfig -A -o json | jq -e --arg comp "$COMP" '[.items[]|select((.spec.compositionRef.name // "")==$comp and (.spec.compositionUpdatePolicy // "Automatic")!="Manual")]|length==0' >/dev/null || { echo "ABORT: an Automatic XR uses this Composition" >&2; exit 1; }

# ── XR must still be on the reviewed T1 revision and paused ──
[[ "$(kubectl get vaultconfig ok-robotics -o jsonpath='{.spec.compositionRevisionRef.name}')" == "$T1REV" ]] || { echo "ABORT: XR not on the proven T1 revision ($T1REV)" >&2; exit 1; }
paused_confirmed vaultconfig ok-robotics || { echo "ABORT: XR not ReconcilePaused" >&2; exit 1; }

# ── break-glass + Vault-side invariants (unchanged since T1) ──
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

# ── T1 end-state frozen precondition: 5 MRs paused ──
for pair in "$POLICY_RES $POLICY_MR" "$POLICY_RES $NEW_MR" "$ROLE_RES $ROLE_MR" "$CONF_RES $CONF_MR" "$BACK_RES $BACK_MR"; do set -- $pair
  paused_confirmed "$1" "$2" || { echo "ABORT: $2 not ReconcilePaused" >&2; exit 1; }; done
# legacy Policy MR: reverted to OLD identity (external-name & desired name old), full mgmt, no ForceNew diff
kubectl get "$POLICY_RES" "$POLICY_MR" -o json | jq -e --arg old "$OLD_POLICY" \
  '.metadata.annotations["crossplane.io/external-name"]==$old and .spec.forProvider.name==$old and .spec.managementPolicies==["*"]' >/dev/null \
  || { echo "ABORT: legacy Policy MR not on consistent OLD identity" >&2; exit 1; }
# imported okvc- MR: Observe, external-name & desired name okvc-, no dangling create
kubectl get "$POLICY_RES" "$NEW_MR" -o json | jq -e --arg new "$NEW_POLICY" \
  '.metadata.annotations["crossplane.io/external-name"]==$new and .spec.forProvider.name==$new and .spec.managementPolicies==["Observe"]' >/dev/null \
  || { echo "ABORT: imported okvc- MR not in proven Observe state" >&2; exit 1; }
creation_state "$POLICY_RES" "$NEW_MR" | creation_state_safe || { echo "ABORT: imported okvc- MR has unsafe creation state" >&2; exit 1; }
# XR references exactly the 5 known MRs
REFS="$(kubectl get vaultconfig ok-robotics -o json | jq -r '.spec.resourceRefs[]|[.apiVersion,.kind,.name]|@tsv' | sort)"
EXP="$(printf '%s\n' \
  "auth.vault.upbound.io/v1alpha1"$'\t'"Backend"$'\t'"$BACK_MR" \
  "kubernetes.vault.upbound.io/v1alpha1"$'\t'"AuthBackendConfig"$'\t'"$CONF_MR" \
  "kubernetes.vault.upbound.io/v1alpha1"$'\t'"AuthBackendRole"$'\t'"$ROLE_MR" \
  "vault.vault.upbound.io/v1alpha1"$'\t'"Policy"$'\t'"$POLICY_MR" \
  "vault.vault.upbound.io/v1alpha1"$'\t'"Policy"$'\t'"$NEW_MR" | sort)"
[[ "$REFS" == "$EXP" ]] || { echo "ABORT: unexpected resourceRefs pre-T2" >&2; printf '%s\n' "$REFS" >&2; exit 1; }
echo "PRECONDITION OK (T1 end-state; 5 MRs paused; okvc- imported Observe)"

# ── APPLY T2 + exactly one new revision ──
COMP_UID="$(kubectl get composition "$COMP" -o jsonpath='{.metadata.uid}')"
OLDREV="$(kubectl get vaultconfig ok-robotics -o jsonpath='{.spec.compositionRevisionRef.name}')"
[[ "$OLDREV" == "$T1REV" ]] || { echo "ABORT: XR revision drifted from T1 revision" >&2; exit 1; }
OLD_MAX="$(kubectl get compositionrevision -l "crossplane.io/composition-name=$COMP" -o json | jq --arg u "$COMP_UID" '[.items[]|select(any(.metadata.ownerReferences[]?;.uid==$u))|.spec.revision]|max // 0')"
kubectl apply -f "$T2_FILE"
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
kubectl get composition "$COMP" -o json | jq -S '.spec' > /tmp/t2-composition-spec.json
kubectl get compositionrevision "$NEWREV" -o json | jq -S '.spec|del(.revision)' > /tmp/t2-revision-spec.json
if ! diff -u /tmp/t2-composition-spec.json /tmp/t2-revision-spec.json; then echo "ABORT: revision snapshot differs from Composition" >&2; exit 1; fi
echo "(a) SNAPSHOT == COMPOSITION"

# ── (b) semantic T1->T2 diff (HUMAN GATE) — extract the inline render template so the
#     diff is human-readable (one line), not a single-line JSON blob. ──
echo "── (b) T1 -> T2 inline-template diff (HUMAN GATE) ──"
kubectl get compositionrevision "$OLDREV" -o json | jq -r '.spec.pipeline[]|select(.step=="render")|.input.inline.template' > /tmp/t2-old-template.yaml
kubectl get compositionrevision "$NEWREV" -o json | jq -r '.spec.pipeline[]|select(.step=="render")|.input.inline.template' > /tmp/t2-new-template.yaml
diff -u /tmp/t2-old-template.yaml /tmp/t2-new-template.yaml || true
echo

# ── atomic gate file ──
NEWREV_HASH="$(kubectl get compositionrevision "$NEWREV" -o json | jq -S '.spec|del(.revision)' | shasum -a256 | awk '{print $1}')"
GATE_TMP="$(mktemp /tmp/phase3-T2-gate.XXXXXX)"
jq -n --arg comp "$COMP" --arg compUID "$COMP_UID" --arg oldrev "$OLDREV" --arg newrev "$NEWREV" --arg hash "$NEWREV_HASH" --arg newmr "$NEW_MR" \
  '{composition:$comp,compositionUID:$compUID,oldRevision:$oldrev,newRevision:$newrev,normalizedSpecSHA256:$hash,newMR:$newmr}' > "$GATE_TMP"
mv "$GATE_TMP" "$GATE"
cat "$GATE"; echo
cat <<'GATE'
===================================================================
HUMAN GATE — the (b) inline-template diff must show EXACTLY ONE changed line
(on the okvc- Policy MR, i.e. the block whose external-name is okvc-<cluster>-<role>):

    -              managementPolicies: ["Observe"]
    +              managementPolicies: ["*"]

  Everything else byte-identical to T1 (including every template comment):
    old Policy MR: legacy name, ["*"], paused (unchanged)
    new okvc MR: external-name okvc-, name okvc-, paused (unchanged)
    Backend / AuthBackendConfig / AuthBackendRole: paused (unchanged)
    Role tokenPolicies: okvc- only (unchanged)
    No other change (SA bindings / TTL / ProviderConfig / mount / comments)

If the diff shows anything beyond that single line -> STOP (do NOT import).
Nothing promoted or unpaused. If it matches -> run phase3-T2-import.
===================================================================
GATE
