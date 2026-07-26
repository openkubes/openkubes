#!/usr/bin/env bash
# Phase 3 / 3D-3a (hardened) — deliberately delete the now-ORPHANED legacy Vault policy
# ok-robotics-sa-obs. Vault-only; no Crossplane change.
# Flow: PRECHECK -> GLOBAL NO-REFERENCE PROOF -> DELETE -> POST-DELETE PROOF -> JSON HANDOFF.
# The delete is authorised ONLY by the no-reference proof; it is NEVER auto-reverted. A three-
# state recovery model (NOT_STARTED / ATTEMPTED / CONFIRMED) governs the abort path so the
# script never blindly re-deletes, never reconstructs the deleted policy, and never claims
# success when Vault is unreachable.
set -Eeuo pipefail
SUCCESS=0; DELETE_STATE="NOT_STARTED"; LEGACY_ARCHIVE=""
MGMT_KUBECONFIG=~/.kube/ok-mgmt.yaml; SHARED_KUBECONFIG=~/.kube/ok-shared.yaml

# ── consumer VSO Secret coordinates on ok-robotics ──
ROBOTICS_KUBECONFIG=~/.kube/ok-robotics.yaml
VSO_SECRET_NS=ok-observability
VSO_SECRET_NAME=ok-observability-credentials

OLD_POLICY=ok-robotics-sa-obs; NEW_POLICY=okvc-ok-robotics-sa-obs
POLICY_RES=policies.vault.vault.upbound.io;              POLICY_MR=ok-robotics-ee43e699198c
ROLE_RES=authbackendroles.kubernetes.vault.upbound.io;   ROLE_MR=ok-robotics-6cae6fef03f6
CONF_RES=authbackendconfigs.kubernetes.vault.upbound.io; CONF_MR=ok-robotics-1cf8d3106f89
BACK_RES=backends.auth.vault.upbound.io;                 BACK_MR=ok-robotics-05b190692d43
NEW_MR=ok-robotics-f3f5cd82a670
T5_GATE=/tmp/phase3-T5-gate.json
T5_DONE_FILE=/tmp/phase3-T5-done
DONE_FILE=/tmp/phase3-T6-done
export KUBECONFIG="$MGMT_KUBECONFIG"

vault_exec(){ local t="$1"; shift; printf '%s\n' "$t" | kubectl --kubeconfig "$SHARED_KUBECONFIG" -n vault exec -i vault-0 -- sh -c 'IFS= read -r VAULT_TOKEN; export VAULT_TOKEN; exec "$@"' sh "$@"; }
old_policy_hash(){ vault_exec "$BGT" vault policy read "$OLD_POLICY" | shasum -a256 | awk '{print $1}'; }
new_policy_hash(){ vault_exec "$BGT" vault policy read "$NEW_POLICY" | shasum -a256 | awk '{print $1}'; }
mr_active_ok(){ kubectl get "$1" "$2" -o json | jq -e '(.metadata.annotations["crossplane.io/paused"]//"")!="true" and any(.status.conditions[]?; .type=="Synced" and .status=="True" and .reason=="ReconcileSuccess") and any(.status.conditions[]?; .type=="Ready" and .status=="True")' >/dev/null; }
xr_active_ok(){ kubectl get vaultconfig ok-robotics -o json | jq -e '(.metadata.annotations["crossplane.io/paused"]//"")!="true" and any(.status.conditions[]?; .type=="Synced" and .status=="True" and .reason=="ReconcileSuccess")' >/dev/null; }
old_mr_gone(){ local out; if ! out="$(kubectl get "$POLICY_RES" "$POLICY_MR" --ignore-not-found -o name 2>/dev/null)"; then echo "ERROR: could not determine whether OLD MR exists" >&2; return 2; fi; [[ -z "$out" ]]; }
uid_of(){ kubectl get "$1" "$2" -o jsonpath='{.metadata.uid}'; }
en_of(){ kubectl get "$1" "$2" -o jsonpath='{.metadata.annotations.crossplane\.io/external-name}'; }
vso_hash(){ kubectl --kubeconfig "$ROBOTICS_KUBECONFIG" -n "$VSO_SECRET_NS" get secret "$VSO_SECRET_NAME" -o json | jq -S -c '.data' | shasum -a256 | awk '{print $1}'; }
vso_health_gate(){
  kubectl --kubeconfig "$ROBOTICS_KUBECONFIG" -n "$VSO_SECRET_NS" get vaultauth ok-robotics -o json | jq -e '
    .status.valid==true and (([.status.conditions[]?|select(.status=="True")|.type]) as $ok | (["Healthy","Ready"]-$ok)==[])' >/dev/null || return 1
  kubectl --kubeconfig "$ROBOTICS_KUBECONFIG" -n "$VSO_SECRET_NS" get vaultstaticsecret "$VSO_SECRET_NAME" -o json | jq -e '
    ([.status.conditions[]?|select(.status=="True")|.type]) as $ok | (["SecretSynced","Healthy","Ready"]-$ok)==[]' >/dev/null || return 1
}
four_keep_refs(){ local got exp
  got="$(kubectl get vaultconfig ok-robotics -o json | jq -r '.spec.resourceRefs[]|[.apiVersion,.kind,.name]|@tsv' | sort)"
  exp="$(printf '%s\n' \
    "auth.vault.upbound.io/v1alpha1"$'\t'"Backend"$'\t'"$BACK_MR" \
    "kubernetes.vault.upbound.io/v1alpha1"$'\t'"AuthBackendConfig"$'\t'"$CONF_MR" \
    "kubernetes.vault.upbound.io/v1alpha1"$'\t'"AuthBackendRole"$'\t'"$ROLE_MR" \
    "vault.vault.upbound.io/v1alpha1"$'\t'"Policy"$'\t'"$NEW_MR" | sort)"
  [[ "$got" == "$exp" ]]; }
freeze_keep_set(){
  kubectl annotate vaultconfig ok-robotics crossplane.io/paused=true --overwrite >/dev/null 2>&1 || true
  for ref in "$BACK_RES $BACK_MR" "$CONF_RES $CONF_MR" "$ROLE_RES $ROLE_MR" "$POLICY_RES $NEW_MR"; do set -- $ref
    kubectl annotate "$1" "$2" crossplane.io/paused=true --overwrite >/dev/null 2>&1 || true; done
}
# After a TYPED dispatch, a listing is benign ONLY as a genuine EMPTY list. In this Vault (via
# kubectl exec) an empty `vault list -format=json` yields stdout `{}` + exit 2 (kubectl adds a
# "command terminated with exit code 2" line). Require exit==2, strip the known wrapper/blank
# lines, then accept ONLY an empty JSON object `{}` or a literal "No value found" line. Any other
# residual output (e.g. "permission denied") is a real error -> not benign -> caller aborts.
# PROBE FINDING (2026-07-26): in this Vault (via kubectl exec) an EMPTY `vault list -format=json`
# and a NON-EXISTENT path produce an IDENTICAL signature: rc=2, stdout `{}`, stderr
# "command terminated with exit code 2". Output alone therefore cannot tell "empty" from "wrong
# path". So the empty signature is accepted ONLY for a pre-validated, named endpoint class (the
# dispatch already proved the mount type / the path is a fixed built-in). Exact string compares
# (not jq) avoid the jq-on-empty-input fail-open.
known_empty_list(){ local kind="$1" stdout="$2" stderr="$3" status="$4"
  [[ "$status" == "2" ]] || return 1
  case "$kind" in
    token-roles|identity-entity-ids|identity-group-ids|userpass-users|kubernetes-roles) ;;
    *) return 1 ;;
  esac
  [[ "$stdout" == "{}" ]] || return 1
  [[ "$stderr" == "command terminated with exit code 2" ]]; }
# Three-state policy read reported as DATA on stdout (PRESENT|ABSENT|UNKNOWN), never as a shell
# return code — so the caller's case is always reached under set -Eeuo pipefail (a `return 1/2`
# from a function while `-e` is active would otherwise fire the ERR trap first).
# NOTE: adjust the NotFound pattern to the installed Vault version if needed.
legacy_policy_read_state(){ local out
  if out="$(vault_exec "$BGT" vault policy read "$OLD_POLICY" 2>&1)"; then printf '%s\n' PRESENT; return 0; fi
  if grep -qiE 'no policy named|policy .* not found|policy .* does not exist' <<<"$out"; then printf '%s\n' ABSENT; return 0; fi
  printf 'ERROR: policy-read failed without a confirmed NotFound: %s\n' "$out" >&2; printf '%s\n' UNKNOWN; return 0; }
# Capture a command's stdout, stderr, and exit status SEPARATELY, WITHOUT tripping the ERR trap on
# an expected non-zero (the command runs as an `if` condition; `set +e` alone does not suppress the
# ERR trap for a failing command-substitution assignment). Splitting the streams lets callers reject
# a successful list that unexpectedly wrote to stderr, and lets known_empty_list see the real stderr.
capture_status_split(){ local __cs_out="$1" __cs_err="$2" __cs_rc="$3" __cs_of __cs_ef __cs_status; shift 3
  __cs_of="$(mktemp /tmp/t6-stdout.XXXXXX)"; __cs_ef="$(mktemp /tmp/t6-stderr.XXXXXX)"
  if "$@" >"$__cs_of" 2>"$__cs_ef"; then __cs_status=0; else __cs_status=$?; fi
  printf -v "$__cs_out" '%s' "$(cat "$__cs_of")"; printf -v "$__cs_err" '%s' "$(cat "$__cs_ef")"; printf -v "$__cs_rc" '%s' "$__cs_status"
  rm -f "$__cs_of" "$__cs_ef"; }

cleanup(){ local rc=$?; trap - EXIT; set +e
  if ((SUCCESS==0)); then
    case "$DELETE_STATE" in
      NOT_STARTED) echo "RECOVERY: DELETE_NOT_STARTED — nothing was changed." >&2 ;;
      ATTEMPTED)   echo "RECOVERY: DELETE_ATTEMPTED — outcome uncertain. NOT retrying delete, NOT claiming success." >&2
                   if lst="$(vault_exec "$BGT" vault policy list 2>/dev/null)"; then
                     if grep -Fxq "$OLD_POLICY" <<<"$lst"; then echo "RECOVERY: legacy policy STILL present (delete did not take). Inspect before retry." >&2
                     else echo "RECOVERY: legacy policy ABSENT (delete appears to have completed). Inspect before any action." >&2; fi
                   else echo "RECOVERY: Vault unreachable — cannot determine legacy policy state. Inspect manually before any retry." >&2; fi ;;
      CONFIRMED)   echo "RECOVERY: DELETE_CONFIRMED — legacy deleted as intended; a later check failed. Freezing keep-set; legacy policy is NOT reconstructed." >&2
                   freeze_keep_set ;;
    esac
    [[ -n "${LEGACY_ARCHIVE:-}" ]] && echo "RECOVERY: legacy HCL archived at $LEGACY_ARCHIVE (for MANUAL inspection only; never auto-restored)." >&2
  fi
  [[ -n "${BGT:-}" ]] && vault_exec "$BGT" vault token revoke -self >/dev/null 2>&1 || true
  # legacy HCL archive is kept in all cases as manual-recovery evidence (never auto-restored)
  unset BG BGT; exit "$rc"; }
trap cleanup EXIT
trap 'rc=$?; printf "ABORT: rc=%s at line %s\n" "$rc" "$LINENO" >&2; exit "$rc"' ERR

# ── chain-of-custody: 3D-2 handoff (JSON) ──
test -s "$T5_GATE" || { echo "ABORT: T5 gate file missing" >&2; exit 1; }
test -s "$T5_DONE_FILE" || { echo "ABORT: successful 3D-2 handoff missing" >&2; exit 1; }
jq -e '.oldPolicyPreserved==true' "$T5_DONE_FILE" >/dev/null || { echo "ABORT: 3D-2 handoff does not attest oldPolicyPreserved" >&2; exit 1; }
[[ "$(jq -er '.remainingMR' "$T5_DONE_FILE")" == "$NEW_MR" ]] || { echo "ABORT: 3D-2 handoff remainingMR != NEW_MR" >&2; exit 1; }
[[ "$(jq -er '.removedMR' "$T5_DONE_FILE")" == "$POLICY_MR" ]] || { echo "ABORT: 3D-2 handoff removedMR != legacy MR" >&2; exit 1; }
OLD_HASH_EXPECTED="$(jq -er '.oldPolicySHA256' "$T5_DONE_FILE")"
NEW_HASH_EXPECTED="$(jq -er '.newPolicySHA256' "$T5_DONE_FILE")"
[[ -n "$OLD_HASH_EXPECTED" && -n "$NEW_HASH_EXPECTED" ]] || { echo "ABORT: 3D-2 handoff missing policy hashes" >&2; exit 1; }
T5REV="$(jq -er '.newRevision' "$T5_GATE")"
T5_COMP="$(jq -er '.composition' "$T5_GATE")"
T5_COMP_UID="$(jq -er '.compositionUID' "$T5_GATE")"
T5_REV_HASH="$(jq -er '.normalizedSpecSHA256' "$T5_GATE")"
[[ "$(kubectl get vaultconfig ok-robotics -o jsonpath='{.spec.compositionUpdatePolicy}')" == "Manual" ]] || { echo "ABORT: XR not Manual" >&2; exit 1; }
[[ "$(kubectl get composition "$T5_COMP" -o jsonpath='{.metadata.uid}')" == "$T5_COMP_UID" ]] || { echo "ABORT: Composition identity changed since T5" >&2; exit 1; }
[[ "$(kubectl get compositionrevision "$T5REV" -o json | jq -S '.spec|del(.revision)' | shasum -a256 | awk '{print $1}')" == "$T5_REV_HASH" ]] || { echo "ABORT: proven T5 revision content changed" >&2; exit 1; }

# ── break-glass ──
read -rsp 'Vault break-glass password: ' BG; printf '\n'
BGT="$(printf '%s' "$BG" | jq -Rs '{password: .}' | kubectl --kubeconfig "$SHARED_KUBECONFIG" -n vault exec -i vault-0 -- sh -c '
  set -eu; umask 077; p="$(mktemp)"; trap "rm -f \"$p\"" EXIT; cat >"$p"; vault write -format=json auth/userpass/login/breakglass - <"$p"' | jq -er '.auth.client_token')"
unset BG; test -n "$BGT"
vault_exec "$BGT" vault token lookup >/dev/null || { echo "ABORT: break-glass lookup failed" >&2; exit 1; }
echo "BREAK-GLASS TOKEN OK"

# ── PRECHECK: post-3D-2 steady state ──
[[ "$(kubectl get vaultconfig ok-robotics -o jsonpath='{.spec.compositionRevisionRef.name}')" == "$T5REV" ]] || { echo "ABORT: XR not on T5 revision" >&2; exit 1; }
xr_active_ok || { echo "ABORT: XR not active/ReconcileSuccess" >&2; exit 1; }
old_mr_gone || { echo "ABORT: legacy Policy MR object still present / unreadable (3D-2 not complete)" >&2; exit 1; }
four_keep_refs || { echo "ABORT: resourceRefs not exactly the 4 keep MRs" >&2; exit 1; }
for pair in "$BACK_RES $BACK_MR" "$CONF_RES $CONF_MR" "$ROLE_RES $ROLE_MR" "$POLICY_RES $NEW_MR"; do set -- $pair
  mr_active_ok "$1" "$2" || { echo "ABORT: keep-set MR not active: $2" >&2; exit 1; }; done
[[ "$(en_of "$POLICY_RES" "$NEW_MR")" == "$NEW_POLICY" ]] || { echo "ABORT: okvc- MR external-name != okvc-" >&2; exit 1; }
kubectl get "$POLICY_RES" "$NEW_MR" -o json | jq -e '.spec.managementPolicies==["*"]' >/dev/null || { echo "ABORT: okvc- MR not full-management" >&2; exit 1; }
B_UID="$(uid_of "$BACK_RES" "$BACK_MR")"; C_UID="$(uid_of "$CONF_RES" "$CONF_MR")"; R_UID="$(uid_of "$ROLE_RES" "$ROLE_MR")"; N_UID="$(uid_of "$POLICY_RES" "$NEW_MR")"
for u in "$B_UID" "$C_UID" "$R_UID" "$N_UID"; do [[ -n "$u" ]] || { echo "ABORT: missing keep-set UID" >&2; exit 1; }; done
vault_exec "$BGT" vault read -format=json auth/kubernetes/ok-robotics/role/sa-obs | jq -e '.data.token_policies==["okvc-ok-robotics-sa-obs"]' >/dev/null || { echo "ABORT: role not okvc-only" >&2; exit 1; }
POL="$(vault_exec "$BGT" vault policy list)"
grep -Fxq "$OLD_POLICY" <<<"$POL" || { echo "ABORT: legacy policy already absent (nothing to do / unexpected)" >&2; exit 1; }
grep -Fxq "$NEW_POLICY" <<<"$POL" || { echo "ABORT: okvc policy missing" >&2; exit 1; }
[[ "$(old_policy_hash)" == "$OLD_HASH_EXPECTED" ]] || { echo "ABORT: legacy policy content differs from 3D-2 baseline" >&2; exit 1; }
[[ "$(new_policy_hash)" == "$NEW_HASH_EXPECTED" ]] || { echo "ABORT: okvc- policy content differs from 3D-2 baseline" >&2; exit 1; }
vso_health_gate || { echo "ABORT: VSO not healthy before 3D-3a" >&2; exit 1; }
VSO_BEFORE="$(vso_hash)"
echo "PRECHECK OK (XR active on T5; old MR gone; 4 refs; keep-set active; both policies == 3D-2 baseline; VSO healthy)"

# ── GLOBAL NO-REFERENCE PROOF (fail-closed, with evidence) ──
echo "── NO-REFERENCE PROOF ──"
# (1) Crossplane: scan ALL Policy MRs
kubectl get "$POLICY_RES" -o json | jq -e --arg old "$OLD_POLICY" \
  '[.items[]|select(.metadata.annotations["crossplane.io/external-name"]==$old or .spec.forProvider.name==$old)]|length==0' >/dev/null \
  || { echo "ABORT: a Crossplane Policy MR still references $OLD_POLICY" >&2; exit 1; }
echo "  [1] Crossplane: no Policy MR references $OLD_POLICY"
# (2) per-mount, dispatched by auth TYPE. ONLY the reviewed types (token/userpass/kubernetes)
#     are accepted; any other enabled type fails closed until a reviewed scanner exists.
AUTH_JSON="$(vault_exec "$BGT" vault auth list -format=json)"
jq -e 'type=="object" and all(to_entries[]; (.key|type)=="string" and (.value|type)=="object" and (.value.type|type)=="string")' <<<"$AUTH_JSON" >/dev/null \
  || { echo "ABORT: malformed vault auth list JSON" >&2; exit 1; }
mapfile -t AUTH_MOUNTS < <(jq -r 'keys[]' <<<"$AUTH_JSON")
for m in "${AUTH_MOUNTS[@]}"; do
  type="$(jq -r --arg m "$m" '.[$m].type' <<<"$AUTH_JSON")"
  case "$type" in
    token)
      echo "  [2] mount ${m} (token): handled by token-role + accessor scans (steps 3/5)" ;;
    userpass)
      capture_status_split out err lrc vault_exec "$BGT" vault list -format=json "auth/${m}users"
      if [[ "$lrc" == "0" ]]; then
        [[ -z "$err" ]] || { echo "ABORT: userpass users listing returned unexpected stderr for ${m}: ${err}" >&2; exit 1; }
        jq -e 'type=="array" and all(.[]; type=="string")' <<<"$out" >/dev/null || { echo "ABORT: malformed user list for mount ${m}" >&2; exit 1; }
        mapfile -t USERS < <(jq -r '.[]' <<<"$out")
        for user in "${USERS[@]}"; do
          pols="$(vault_exec "$BGT" vault read -format=json "auth/${m}users/${user}" | jq -r '(.data.token_policies//[])[],(.data.policies//[])[]')"
          if grep -Fxq "$OLD_POLICY" <<<"$pols"; then echo "ABORT: userpass user ${m}users/${user} references $OLD_POLICY" >&2; exit 1; fi
        done
        echo "  [2] mount ${m} (userpass): ${#USERS[@]} user(s) checked, clean"
      elif known_empty_list userpass-users "$out" "$err" "$lrc"; then echo "  [2] mount ${m} (userpass): none (empty)"
      else echo "ABORT: unexpected userpass users result for ${m} (rc=${lrc} stdout=[${out}] stderr=[${err}])" >&2; exit 1; fi ;;
    kubernetes)
      capture_status_split out err lrc vault_exec "$BGT" vault list -format=json "auth/${m}role"
      if [[ "$lrc" == "0" ]]; then
        [[ -z "$err" ]] || { echo "ABORT: kubernetes roles listing returned unexpected stderr for ${m}: ${err}" >&2; exit 1; }
        jq -e 'type=="array" and all(.[]; type=="string")' <<<"$out" >/dev/null || { echo "ABORT: malformed role list for mount ${m}" >&2; exit 1; }
        mapfile -t ROLES < <(jq -r '.[]' <<<"$out")
        for r in "${ROLES[@]}"; do
          pols="$(vault_exec "$BGT" vault read -format=json "auth/${m}role/${r}" | jq -r '(.data.token_policies//[])[],(.data.policies//[])[]')"
          if grep -Fxq "$OLD_POLICY" <<<"$pols"; then echo "ABORT: auth role ${m}role/${r} references $OLD_POLICY" >&2; exit 1; fi
        done
        echo "  [2] mount ${m} (kubernetes): ${#ROLES[@]} role(s) checked, clean"
      elif known_empty_list kubernetes-roles "$out" "$err" "$lrc"; then echo "  [2] mount ${m} (kubernetes): none (empty)"
      else echo "ABORT: unexpected kubernetes roles result for ${m} (rc=${lrc} stdout=[${out}] stderr=[${err}])" >&2; exit 1; fi ;;
    *)
      echo "ABORT: enabled auth type '${type}' at '${m}' has no reviewed policy scanner (fail-closed)" >&2; exit 1 ;;
  esac
done
# (3) token roles
capture_status_split out err lrc vault_exec "$BGT" vault list -format=json auth/token/roles
if [[ "$lrc" == "0" ]]; then
  [[ -z "$err" ]] || { echo "ABORT: token-role listing returned unexpected stderr: ${err}" >&2; exit 1; }
  jq -e 'type=="array" and all(.[]; type=="string")' <<<"$out" >/dev/null || { echo "ABORT: malformed token-role list" >&2; exit 1; }
  mapfile -t TROLES < <(jq -r '.[]' <<<"$out")
  for tr in "${TROLES[@]}"; do
    role_json="$(vault_exec "$BGT" vault read -format=json "auth/token/roles/${tr}")"
    jq -e 'type=="object" and (.data|type=="object") and ((.data.allowed_policies//[])|type=="array") and ((.data.allowed_policies_glob//[])|type=="array")' <<<"$role_json" >/dev/null \
      || { echo "ABORT: malformed token-role response for ${tr}" >&2; exit 1; }
    jq -e --arg old "$OLD_POLICY" '(.data.allowed_policies//[])|index($old)==null' <<<"$role_json" >/dev/null \
      || { echo "ABORT: token role ${tr} explicitly allows $OLD_POLICY" >&2; exit 1; }
    # do NOT re-implement Vault's glob matching; if any glob is configured, stop for manual review
    GLOB_COUNT="$(jq -er '(.data.allowed_policies_glob//[])|length' <<<"$role_json")"
    ((GLOB_COUNT==0)) || { echo "ABORT: token role ${tr} has allowed_policies_glob (${GLOB_COUNT}); manual matching review required" >&2; exit 1; }
  done
  echo "  [3] token roles: ${#TROLES[@]} checked (literal allow-list + no globs), clean"
elif known_empty_list token-roles "$out" "$err" "$lrc"; then echo "  [3] token roles: none (empty)"
else echo "ABORT: unexpected token-role result (rc=${lrc} stdout=[${out}] stderr=[${err}])" >&2; exit 1; fi
# (4) identity entities + groups
for kind in entity group; do
  capture_status_split out err lrc vault_exec "$BGT" vault list -format=json "identity/${kind}/id"
  if [[ "$lrc" == "0" ]]; then
    [[ -z "$err" ]] || { echo "ABORT: identity ${kind} listing returned unexpected stderr: ${err}" >&2; exit 1; }
    jq -e 'type=="array" and all(.[]; type=="string")' <<<"$out" >/dev/null || { echo "ABORT: malformed identity ${kind} list" >&2; exit 1; }
    mapfile -t IDS < <(jq -r '.[]' <<<"$out")
    for id in "${IDS[@]}"; do
      pols="$(vault_exec "$BGT" vault read -format=json "identity/${kind}/id/${id}" | jq -r '(.data.policies//[])[]')"
      if grep -Fxq "$OLD_POLICY" <<<"$pols"; then echo "ABORT: identity ${kind} ${id} references $OLD_POLICY" >&2; exit 1; fi
    done
    echo "  [4] identity ${kind}: ${#IDS[@]} checked, clean"
  elif known_empty_list "identity-${kind}-ids" "$out" "$err" "$lrc"; then echo "  [4] identity ${kind}: none (empty)"
  else echo "ABORT: unexpected identity ${kind} result (rc=${lrc} stdout=[${out}] stderr=[${err}])" >&2; exit 1; fi
done
# (5a) prove the target role issues PERSISTED service tokens, so the accessor enumeration is
#      COMPLETE (batch tokens are not persisted and cannot be listed via accessors).
ROLE_JSON="$(vault_exec "$BGT" vault read -format=json auth/kubernetes/ok-robotics/role/sa-obs)"
TOKEN_TYPE="$(jq -er '.data.token_type // "default"' <<<"$ROLE_JSON")"
case "$TOKEN_TYPE" in
  service|default-service) echo "  [5a] target role token_type=${TOKEN_TYPE} -> persisted service tokens" ;;
  default)
    # role uses the mount default -> read the mount token_type STRICTLY from the already-validated
    # AUTH_JSON. No fallback; the four valid mount values are service|default-service|batch|default-batch.
    MOUNT_TT="$(jq -er '.["kubernetes/ok-robotics/"].config.token_type | select(type=="string" and length>0)' <<<"$AUTH_JSON")" \
      || { echo "ABORT: cannot determine Kubernetes auth mount token_type" >&2; exit 1; }
    case "$MOUNT_TT" in
      service|default-service) echo "  [5a] role token_type=default; mount token_type=${MOUNT_TT} -> persisted service tokens" ;;
      batch|default-batch) echo "ABORT: mount token_type=${MOUNT_TT}; active batch tokens cannot be enumerated" >&2; exit 1 ;;
      *) echo "ABORT: unsupported mount token_type '${MOUNT_TT}'" >&2; exit 1 ;;
    esac ;;
  *) echo "ABORT: role token_type '${TOKEN_TYPE}' may issue batch tokens; accessor scan cannot prove absence" >&2; exit 1 ;;
esac
# (5b) enumerate active (persisted) token accessors and check each token's policies.
# STRICT: the current break-glass token is itself an active persisted token, so this list MUST be
# non-empty and enumerable with rc=0 and clean stderr; an rc-2 "{}" empty signature is NOT accepted.
capture_status_split accessor_json accessor_err arc vault_exec "$BGT" vault list -format=json auth/token/accessors
[[ "$arc" == "0" ]] || { echo "ABORT: cannot enumerate active token accessors (rc=${arc} stdout=[${accessor_json}] stderr=[${accessor_err}])" >&2; exit 1; }
[[ -z "$accessor_err" ]] || { echo "ABORT: accessor listing returned unexpected stderr: ${accessor_err}" >&2; exit 1; }
jq -e 'type=="array" and all(.[]; type=="string")' <<<"$accessor_json" >/dev/null || { echo "ABORT: malformed token-accessor list" >&2; exit 1; }
mapfile -t ACCESSORS < <(jq -r '.[]' <<<"$accessor_json")
ACCESSORS_CHECKED=0; ACCESSORS_VANISHED=0
for accessor in "${ACCESSORS[@]}"; do
  # a short-lived token can expire/revoke between list and lookup ("invalid accessor"); a vanished
  # token cannot carry the policy -> skip it. Any other lookup error is a real failure -> abort.
  capture_status_split token_json token_err token_rc vault_exec "$BGT" vault token lookup -format=json -accessor "$accessor"
  if [[ "$token_rc" == "0" ]]; then
    ACCESSORS_CHECKED=$((ACCESSORS_CHECKED+1))
    jq -e --arg old "$OLD_POLICY" '((.data.policies//[])+(.data.identity_policies//[]))|index($old)==null' <<<"$token_json" >/dev/null \
      || { echo "ABORT: active token accessor ${accessor} still carries $OLD_POLICY" >&2; exit 1; }
  elif grep -qiE 'invalid accessor' <<<"${token_err}${token_json}"; then
    ACCESSORS_VANISHED=$((ACCESSORS_VANISHED+1))
  else
    echo "ABORT: token lookup failed for accessor ${accessor} (rc=${token_rc} stderr=[${token_err}])" >&2; exit 1
  fi
done
echo "  [5b] active persisted token accessors: ${#ACCESSORS[@]} listed; ${ACCESSORS_CHECKED} live-checked; ${ACCESSORS_VANISHED} vanished; no live reference"
echo "NO-REFERENCE PROOF OK ($OLD_POLICY unreferenced by any Crossplane MR / auth role / userpass user / token role / identity entity+group / active persisted token; target role issues only persisted service tokens)"

# ── archive legacy HCL (evidence only; never auto-restored) ──
LEGACY_ARCHIVE="$(mktemp /tmp/phase3-T6-legacy-policy.XXXXXX)"
( umask 077; vault_exec "$BGT" vault policy read "$OLD_POLICY" > "$LEGACY_ARCHIVE" )
test -s "$LEGACY_ARCHIVE" || { echo "ABORT: could not archive legacy policy HCL" >&2; exit 1; }
DELETED_SHA="$(shasum -a256 "$LEGACY_ARCHIVE" | awk '{print $1}')"
[[ "$DELETED_SHA" == "$OLD_HASH_EXPECTED" ]] || { echo "ABORT: archived legacy HCL hash != baseline" >&2; exit 1; }

# ── immediate pre-delete re-check ──
POLp="$(vault_exec "$BGT" vault policy list)"
grep -Fxq "$OLD_POLICY" <<<"$POLp" || { echo "ABORT: legacy policy vanished just before delete" >&2; exit 1; }
[[ "$(old_policy_hash)" == "$OLD_HASH_EXPECTED" ]] || { echo "ABORT: legacy hash changed just before delete" >&2; exit 1; }
[[ "$(new_policy_hash)" == "$NEW_HASH_EXPECTED" ]] || { echo "ABORT: okvc- hash changed just before delete" >&2; exit 1; }

# ── DELIBERATE DELETE (authorised only by the no-reference proof; never auto-reverted) ──
DELETE_STATE="ATTEMPTED"
vault_exec "$BGT" vault policy delete "$OLD_POLICY" >/dev/null
# (a) absent from policy list — a failed list aborts (set -e) while state stays ATTEMPTED
POL2="$(vault_exec "$BGT" vault policy list)"
if grep -Fxq "$OLD_POLICY" <<<"$POL2"; then echo "ABORT: legacy policy still present in policy list after delete" >&2; exit 1; fi
# (b) definitive NotFound via three-state read reported as data; only ABSENT authorises CONFIRMED
policy_state="$(legacy_policy_read_state)"
case "$policy_state" in
  ABSENT)  DELETE_STATE="CONFIRMED" ;;
  PRESENT) echo "ABORT: legacy policy still readable after delete" >&2; exit 1 ;;
  UNKNOWN) echo "ABORT: unable to confirm legacy policy deletion (state stays ATTEMPTED)" >&2; exit 1 ;;
  *)       echo "ABORT: invalid policy-read state: ${policy_state}" >&2; exit 1 ;;
esac
echo "LEGACY POLICY DELETED + CONFIRMED ($OLD_POLICY now NotFound)"

# ── POST-DELETE PROOF ──
grep -Fxq "$NEW_POLICY" <<<"$POL2" || { echo "ABORT: okvc policy missing after delete" >&2; exit 1; }
[[ "$(new_policy_hash)" == "$NEW_HASH_EXPECTED" ]] || { echo "ABORT: okvc- policy content changed across delete" >&2; exit 1; }
kubectl get "$POLICY_RES" -o json | jq -e --arg old "$OLD_POLICY" '[.items[]|select(.metadata.annotations["crossplane.io/external-name"]==$old or .spec.forProvider.name==$old)]|length==0' >/dev/null || { echo "ABORT: a Crossplane Policy MR references the (now deleted) legacy policy" >&2; exit 1; }
vault_exec "$BGT" vault read -format=json auth/kubernetes/ok-robotics/role/sa-obs | jq -e '.data.token_policies==["okvc-ok-robotics-sa-obs"]' >/dev/null || { echo "ABORT: role drifted off okvc- after delete" >&2; exit 1; }
four_keep_refs || { echo "ABORT: resourceRefs changed after delete" >&2; exit 1; }
[[ "$(uid_of "$BACK_RES" "$BACK_MR")" == "$B_UID" && "$(uid_of "$CONF_RES" "$CONF_MR")" == "$C_UID" && "$(uid_of "$ROLE_RES" "$ROLE_MR")" == "$R_UID" && "$(uid_of "$POLICY_RES" "$NEW_MR")" == "$N_UID" ]] || { echo "ABORT: a keep-set MR identity changed across delete" >&2; exit 1; }
for pair in "$BACK_RES $BACK_MR" "$CONF_RES $CONF_MR" "$ROLE_RES $ROLE_MR" "$POLICY_RES $NEW_MR"; do set -- $pair
  mr_active_ok "$1" "$2" || { echo "ABORT: keep-set MR not active after delete: $2" >&2; exit 1; }; done
xr_active_ok || { echo "ABORT: XR not active/ReconcileSuccess after delete" >&2; exit 1; }
vso_health_gate || { echo "ABORT: VSO unhealthy after delete" >&2; exit 1; }
[[ "$(vso_hash)" == "$VSO_BEFORE" ]] || { echo "ABORT: consumer Secret changed across delete" >&2; exit 1; }
echo "POST-DELETE PROOF OK (legacy NotFound; okvc- hash-equal; role okvc-; 4 refs; 4 UIDs stable; XR+keep-set active; VSO intact)"

vault_exec "$BGT" vault token revoke -self >/dev/null; unset BGT; echo "BREAK-GLASS TOKEN REVOKED"
NEW_HASH_FINAL="$NEW_HASH_EXPECTED"
DONE_TMP="$(mktemp /tmp/phase3-T6-done.XXXXXX)"
jq -n --arg deletedPolicy "$OLD_POLICY" --arg deletedPolicySHA256 "$DELETED_SHA" --arg remainingPolicy "$NEW_POLICY" --arg remainingPolicySHA256 "$NEW_HASH_FINAL" --argjson accessorsChecked "$ACCESSORS_CHECKED" \
  '{deletedPolicy:$deletedPolicy,deletedPolicySHA256:$deletedPolicySHA256,remainingPolicy:$remainingPolicy,remainingPolicySHA256:$remainingPolicySHA256,noReferencesProven:true,crossplaneMRAbsent:true,activeTokenAccessorsChecked:$accessorsChecked}' > "$DONE_TMP"
mv "$DONE_TMP" "$DONE_FILE"
SUCCESS=1
echo "PHASE 3 3D-3a DONE (legacy Vault policy deleted after global no-reference proof; okvc- steady state intact). Ready for 3D-3b (final steady-state composition + commit). Legacy HCL archive: $LEGACY_ARCHIVE"
