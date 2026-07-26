#!/usr/bin/env bash
# Phase 3 / T1-apply (hardened) — apply T1 transition Composition, identify exactly one
# new CompositionRevision, machine-verify snapshot==composition (fail-closed), show the
# semantic OLD->NEW diff for a HUMAN GATE, write /tmp/phase3-T1-gate.json atomically.
# NON-runtime-effective: no promote, no unpause. Requires Manual XR + no Automatic XR.
set -Eeuo pipefail
cleanup(){ local rc=$?; trap - EXIT; set +e; [[ -n "${BGT:-}" ]] && declare -F vault_exec >/dev/null && vault_exec "$BGT" vault token revoke -self >/dev/null 2>&1 || true; unset BG BGT; exit "$rc"; }
trap cleanup EXIT
trap 'rc=$?; printf "ABORT: rc=%s at line %s\n" "$rc" "$LINENO" >&2; exit "$rc"' ERR

MGMT_KUBECONFIG=~/.kube/ok-mgmt.yaml; SHARED_KUBECONFIG=~/.kube/ok-shared.yaml
COMP=vaultconfig.platform.openkubes.ai
T1_FILE=~/temp/kubernauts/ok/openkubes/platform/secrets/vault/crossplane/vaultconfig-composition.T1.yaml
GATE=/tmp/phase3-T1-gate.json
OLD_POLICY=ok-robotics-sa-obs; NEW_POLICY=okvc-ok-robotics-sa-obs
POLICY_RES=policies.vault.vault.upbound.io;              POLICY_MR=ok-robotics-ee43e699198c
ROLE_RES=authbackendroles.kubernetes.vault.upbound.io;   ROLE_MR=ok-robotics-6cae6fef03f6
CONF_RES=authbackendconfigs.kubernetes.vault.upbound.io; CONF_MR=ok-robotics-1cf8d3106f89
BACK_RES=backends.auth.vault.upbound.io;                 BACK_MR=ok-robotics-05b190692d43
export KUBECONFIG="$MGMT_KUBECONFIG"
vault_exec(){ local t="$1"; shift; printf '%s\n' "$t" | kubectl --kubeconfig "$SHARED_KUBECONFIG" -n vault exec -i vault-0 -- sh -c 'IFS= read -r VAULT_TOKEN; export VAULT_TOKEN; exec "$@"' sh "$@"; }
paused_confirmed(){ kubectl get "$@" -o json | jq -e '.metadata.annotations["crossplane.io/paused"]=="true" and any(.status.conditions[]?; .type=="Synced" and .status=="False" and .reason=="ReconcilePaused")' >/dev/null; }

rm -f "$GATE"

# ── Manual XR + no Automatic XR on this Composition ──
[[ "$(kubectl get vaultconfig ok-robotics -o jsonpath='{.spec.compositionUpdatePolicy}')" == "Manual" ]] || { echo "ABORT: target XR is not explicitly Manual" >&2; exit 1; }
kubectl get vaultconfig -A -o json | jq -e --arg comp "$COMP" '[.items[]|select((.spec.compositionRef.name // "")==$comp and (.spec.compositionUpdatePolicy // "Automatic")!="Manual")]|length==0' >/dev/null || { echo "ABORT: an Automatic XR uses this Composition" >&2; exit 1; }

# ── break-glass + frozen precondition ──
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

paused_confirmed vaultconfig ok-robotics || { echo "ABORT: XR not ReconcilePaused" >&2; exit 1; }
for pair in "$POLICY_RES $POLICY_MR" "$ROLE_RES $ROLE_MR" "$CONF_RES $CONF_MR" "$BACK_RES $BACK_MR"; do set -- $pair
  paused_confirmed "$1" "$2" || { echo "ABORT: $2 not ReconcilePaused" >&2; exit 1; }; done
# legacy Policy MR is in the known safe ForceNew-failure state
kubectl get "$POLICY_RES" "$POLICY_MR" -o json | jq -e --arg old "$OLD_POLICY" --arg new "$NEW_POLICY" \
  '.metadata.annotations["crossplane.io/external-name"]==$old and .spec.forProvider.name==$new and any(.status.conditions[]?; .type=="LastAsyncOperation" and .reason=="AsyncUpdateFailure")' >/dev/null \
  || { echo "ABORT: legacy Policy MR not in expected ForceNew-failure state" >&2; exit 1; }
# XR references exactly the 4 known MRs, no second Policy yet
REFS="$(kubectl get vaultconfig ok-robotics -o json | jq -r '.spec.resourceRefs[]|"\(.kind)/\(.name)"' | sort | tr '\n' ',')"
EXP="$(printf '%s\n' "Backend/$BACK_MR" "AuthBackendConfig/$CONF_MR" "AuthBackendRole/$ROLE_MR" "Policy/$POLICY_MR" | sort | tr '\n' ',')"
[[ "$REFS" == "$EXP" ]] || { echo "ABORT: unexpected resourceRefs pre-T1: $REFS" >&2; exit 1; }
echo "PRECONDITION OK (frozen; legacy MR stuck as expected; 4 refs)"

# ── APPLY T1 + exactly one new revision ──
COMP_UID="$(kubectl get composition "$COMP" -o jsonpath='{.metadata.uid}')"
OLDREV="$(kubectl get vaultconfig ok-robotics -o jsonpath='{.spec.compositionRevisionRef.name}')"
OLD_MAX="$(kubectl get compositionrevision -l "crossplane.io/composition-name=$COMP" -o json | jq --arg u "$COMP_UID" '[.items[]|select(any(.metadata.ownerReferences[]?;.uid==$u))|.spec.revision]|max // 0')"
kubectl apply -f "$T1_FILE"
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
kubectl get composition "$COMP" -o json | jq -S '.spec' > /tmp/t1-composition-spec.json
kubectl get compositionrevision "$NEWREV" -o json | jq -S '.spec|del(.revision)' > /tmp/t1-revision-spec.json
if ! diff -u /tmp/t1-composition-spec.json /tmp/t1-revision-spec.json; then echo "ABORT: revision snapshot differs from Composition" >&2; exit 1; fi
echo "(a) SNAPSHOT == COMPOSITION"

# ── (b) semantic OLD->NEW diff (HUMAN GATE) ──
echo "── (b) OLD -> NEW revision diff (HUMAN GATE) ──"
kubectl get compositionrevision "$OLDREV" -o json | jq -S '.spec|del(.revision)' > /tmp/t1-old-revision.json
kubectl get compositionrevision "$NEWREV" -o json | jq -S '.spec|del(.revision)' > /tmp/t1-new-revision.json
diff -u /tmp/t1-old-revision.json /tmp/t1-new-revision.json || true
echo

# ── atomic gate file ──
NEWREV_HASH="$(kubectl get compositionrevision "$NEWREV" -o json | jq -S '.spec|del(.revision)' | shasum -a256 | awk '{print $1}')"
GATE_TMP="$(mktemp /tmp/phase3-T1-gate.XXXXXX)"
jq -n --arg comp "$COMP" --arg compUID "$COMP_UID" --arg oldrev "$OLDREV" --arg newrev "$NEWREV" --arg hash "$NEWREV_HASH" \
  '{composition:$comp,compositionUID:$compUID,oldRevision:$oldrev,newRevision:$newrev,normalizedSpecSHA256:$hash}' > "$GATE_TMP"
mv "$GATE_TMP" "$GATE"
cat "$GATE"; echo
cat <<'GATE'
===================================================================
HUMAN GATE — the (b) diff must show ONLY these changes:

  old Policy MR (policy-<role>):
    name reverted to legacy  <cluster>-<role>
    managementPolicies ["*"]
    paused: "true" added

  new okvc Policy MR (policy-okvc-<role>):
    added; external-name okvc-<cluster>-<role>
    forProvider.name okvc-<cluster>-<role>
    managementPolicies ["Observe"]
    paused: "true"

  Backend, AuthBackendConfig, AuthBackendRole:
    paused: "true" added

  Role tokenPolicies: remains okvc- only
  No other functional change (SA bindings / TTL / ProviderConfig / mount)

Nothing promoted or unpaused. If the diff matches -> run phase3-T1-import.
===================================================================
GATE
