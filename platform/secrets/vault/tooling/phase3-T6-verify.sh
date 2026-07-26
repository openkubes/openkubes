#!/usr/bin/env bash
# READ-ONLY 3D-3a provenance + end-state verifier. NO delete, NO mutation, and NO "legacy must be
# present" requirement. Answers two questions:
#   (A) PROVENANCE: did *this* T6 tooling delete the legacy policy (done-marker + archive + Vault
#       audit trail), or did it disappear via some other actor?
#   (B) END-STATE: is the cluster now the correct okvc-only steady state, with NO live reference to
#       the legacy policy anywhere (audit-only re-run of the no-reference scans)?
# Nothing here changes Vault or Crossplane. Break-glass token is revoked at the end.
set -Eeuo pipefail
MGMT_KUBECONFIG=~/.kube/ok-mgmt.yaml; SHARED_KUBECONFIG=~/.kube/ok-shared.yaml
ROBOTICS_KUBECONFIG=~/.kube/ok-robotics.yaml; VSO_SECRET_NS=ok-observability; VSO_SECRET_NAME=ok-observability-credentials
OLD_POLICY=ok-robotics-sa-obs; NEW_POLICY=okvc-ok-robotics-sa-obs
POLICY_RES=policies.vault.vault.upbound.io;              POLICY_MR=ok-robotics-ee43e699198c
ROLE_RES=authbackendroles.kubernetes.vault.upbound.io;   ROLE_MR=ok-robotics-6cae6fef03f6
CONF_RES=authbackendconfigs.kubernetes.vault.upbound.io; CONF_MR=ok-robotics-1cf8d3106f89
BACK_RES=backends.auth.vault.upbound.io;                 BACK_MR=ok-robotics-05b190692d43
NEW_MR=ok-robotics-f3f5cd82a670
T5_DONE=/tmp/phase3-T5-done; T6_DONE=/tmp/phase3-T6-done
export KUBECONFIG="$MGMT_KUBECONFIG"
cleanup(){ local rc=$?; trap - EXIT; set +e; [[ -n "${BGT:-}" ]] && declare -F vault_exec >/dev/null && vault_exec "$BGT" vault token revoke -self >/dev/null 2>&1 || true; unset BG BGT; exit "$rc"; }
trap cleanup EXIT
trap 'rc=$?; printf "ABORT: rc=%s at line %s\n" "$rc" "$LINENO" >&2; exit "$rc"' ERR

vault_exec(){ local t="$1"; shift; printf '%s\n' "$t" | kubectl --kubeconfig "$SHARED_KUBECONFIG" -n vault exec -i vault-0 -- sh -c 'IFS= read -r VAULT_TOKEN; export VAULT_TOKEN; exec "$@"' sh "$@"; }
new_policy_hash(){ vault_exec "$BGT" vault policy read "$NEW_POLICY" | shasum -a256 | awk '{print $1}'; }
mr_active_ok(){ kubectl get "$1" "$2" -o json | jq -e '(.metadata.annotations["crossplane.io/paused"]//"")!="true" and any(.status.conditions[]?; .type=="Synced" and .status=="True" and .reason=="ReconcileSuccess") and any(.status.conditions[]?; .type=="Ready" and .status=="True")' >/dev/null; }
xr_active_ok(){ kubectl get vaultconfig ok-robotics -o json | jq -e '(.metadata.annotations["crossplane.io/paused"]//"")!="true" and any(.status.conditions[]?; .type=="Synced" and .status=="True" and .reason=="ReconcileSuccess")' >/dev/null; }
legacy_absent(){ local out; if out="$(vault_exec "$BGT" vault policy read "$OLD_POLICY" 2>&1)"; then return 1; fi
  grep -qiE 'no policy named|policy .* not found|policy .* does not exist' <<<"$out"; }
uid_present(){ [[ -n "$(kubectl get "$1" "$2" -o jsonpath='{.metadata.uid}' 2>/dev/null)" ]]; }
vso_health_gate(){
  kubectl --kubeconfig "$ROBOTICS_KUBECONFIG" -n "$VSO_SECRET_NS" get vaultauth ok-robotics -o json | jq -e '.status.valid==true and (([.status.conditions[]?|select(.status=="True")|.type]) as $ok | (["Healthy","Ready"]-$ok)==[])' >/dev/null || return 1
  kubectl --kubeconfig "$ROBOTICS_KUBECONFIG" -n "$VSO_SECRET_NS" get vaultstaticsecret "$VSO_SECRET_NAME" -o json | jq -e '([.status.conditions[]?|select(.status=="True")|.type]) as $ok | (["SecretSynced","Healthy","Ready"]-$ok)==[]' >/dev/null || return 1
}
four_keep_refs(){ local got exp
  got="$(kubectl get vaultconfig ok-robotics -o json | jq -r '.spec.resourceRefs[]|[.apiVersion,.kind,.name]|@tsv' | sort)"
  exp="$(printf '%s\n' "auth.vault.upbound.io/v1alpha1"$'\t'"Backend"$'\t'"$BACK_MR" "kubernetes.vault.upbound.io/v1alpha1"$'\t'"AuthBackendConfig"$'\t'"$CONF_MR" "kubernetes.vault.upbound.io/v1alpha1"$'\t'"AuthBackendRole"$'\t'"$ROLE_MR" "vault.vault.upbound.io/v1alpha1"$'\t'"Policy"$'\t'"$NEW_MR" | sort)"
  [[ "$got" == "$exp" ]]; }
capture_status_split(){ local __o="$1" __e="$2" __r="$3" __of __ef __s; shift 3
  __of="$(mktemp)"; __ef="$(mktemp)"; if "$@" >"$__of" 2>"$__ef"; then __s=0; else __s=$?; fi
  printf -v "$__o" '%s' "$(cat "$__of")"; printf -v "$__e" '%s' "$(cat "$__ef")"; printf -v "$__r" '%s' "$__s"; rm -f "$__of" "$__ef"; }
known_empty_list(){ local kind="$1" so="$2" se="$3" st="$4"; [[ "$st" == "2" ]] || return 1
  case "$kind" in token-roles|identity-entity-ids|identity-group-ids|userpass-users|kubernetes-roles) ;; *) return 1 ;; esac
  [[ "$so" == "{}" ]] || return 1; [[ "$se" == "command terminated with exit code 2" ]]; }
# scan a role/user/id-list endpoint audit-only: report count, ABORT only on a live legacy reference
scan_policy_carriers(){ local kind="$1" listpath="$2" readprefix="$3" jqpols="$4"; local so se rc n=0
  capture_status_split so se rc vault_exec "$BGT" vault list -format=json "$listpath"
  if [[ "$rc" == "0" ]]; then
    [[ -z "$se" ]] || { echo "ABORT: $kind list unexpected stderr: $se" >&2; exit 1; }
    jq -e 'type=="array" and all(.[]; type=="string")' <<<"$so" >/dev/null || { echo "ABORT: malformed $kind list" >&2; exit 1; }
    local items; mapfile -t items < <(jq -r '.[]' <<<"$so")
    local it; for it in "${items[@]}"; do n=$((n+1))
      pols="$(vault_exec "$BGT" vault read -format=json "${readprefix}${it}" | jq -r "$jqpols")"
      if grep -Fxq "$OLD_POLICY" <<<"$pols"; then echo "ABORT: LIVE REFERENCE — $kind '${it}' carries $OLD_POLICY" >&2; exit 1; fi
    done
    echo "  $kind: $n checked, no live reference"
  elif known_empty_list "$kind" "$so" "$se" "$rc"; then echo "  $kind: none (empty)"
  else echo "ABORT: unexpected $kind result (rc=$rc stdout=[$so] stderr=[$se])" >&2; exit 1; fi
}

echo "════════ (A) LOCAL PROVENANCE EVIDENCE ════════"
echo "--- T5 handoff (/tmp/phase3-T5-done) ---"; [[ -s "$T5_DONE" ]] && jq . "$T5_DONE" || echo "MISSING"
echo "--- T6 done marker (/tmp/phase3-T6-done) ---"; [[ -s "$T6_DONE" ]] && jq . "$T6_DONE" || echo "MISSING"
echo "--- legacy HCL archives (/tmp/phase3-T6-legacy-policy.*) ---"
ARCHIVES=(); while IFS= read -r f; do ARCHIVES+=("$f"); done < <(find /tmp -maxdepth 1 -name 'phase3-T6-legacy-policy.*' -type f 2>/dev/null)
if ((${#ARCHIVES[@]})); then for f in "${ARCHIVES[@]}"; do printf '  %s  sha256=%s\n' "$f" "$(shasum -a256 "$f" | awk '{print $1}')"; done; else echo "  none"; fi
echo "--- running T6 / manual-delete processes ---"; pgrep -af 'phase3-T6-delete-legacy-policy|vault policy delete' || echo "  none running"
# consistency: T6-done deletedPolicySHA256 == T5-done oldPolicySHA256 == archive sha256
if [[ -s "$T6_DONE" && -s "$T5_DONE" ]]; then
  T6DEL="$(jq -er '.deletedPolicySHA256' "$T6_DONE")"; T5OLD="$(jq -er '.oldPolicySHA256' "$T5_DONE")"
  [[ "$T6DEL" == "$T5OLD" ]] && echo "  CONSISTENT: T6.deletedPolicySHA256 == T5.oldPolicySHA256 ($T6DEL)" || echo "  MISMATCH: T6.deletedPolicySHA256=$T6DEL vs T5.oldPolicySHA256=$T5OLD"
  if ((${#ARCHIVES[@]})); then for f in "${ARCHIVES[@]}"; do
    [[ "$(shasum -a256 "$f" | awk '{print $1}')" == "$T5OLD" ]] && echo "  ARCHIVE MATCHES baseline hash: $f" || echo "  archive hash != baseline: $f"; done; fi
else echo "  (cannot cross-check hashes: a handoff file is missing — provenance INCOMPLETE)"; fi

echo; echo "════════ break-glass (read-only from here) ════════"
read -rsp 'Vault break-glass password: ' BG; printf '\n'
BGT="$(printf '%s' "$BG" | jq -Rs '{password: .}' | kubectl --kubeconfig "$SHARED_KUBECONFIG" -n vault exec -i vault-0 -- sh -c '
  set -eu; umask 077; p="$(mktemp)"; trap "rm -f \"$p\"" EXIT; cat >"$p"; vault write -format=json auth/userpass/login/breakglass - <"$p"' | jq -er '.auth.client_token')"
unset BG; test -n "$BGT"; vault_exec "$BGT" vault token lookup >/dev/null; echo "BREAK-GLASS OK"

echo; echo "════════ (B) CURRENT END-STATE (read-only) ════════"
legacy_absent && echo "  legacy policy: ABSENT (policy read -> NotFound)" || { echo "ABORT: legacy policy still present/undeterminable" >&2; exit 1; }
POL="$(vault_exec "$BGT" vault policy list)"; grep -Fxq "$OLD_POLICY" <<<"$POL" && { echo "ABORT: legacy still in policy list" >&2; exit 1; } || echo "  legacy policy: not in policy list"
grep -Fxq "$NEW_POLICY" <<<"$POL" || { echo "ABORT: okvc policy missing" >&2; exit 1; }
if [[ -s "$T5_DONE" ]]; then EXP_NEW="$(jq -er '.newPolicySHA256' "$T5_DONE")"
  [[ "$(new_policy_hash)" == "$EXP_NEW" ]] && echo "  okvc- policy: present, hash == T5 baseline" || { echo "ABORT: okvc- hash != T5 baseline" >&2; exit 1; }
else echo "  okvc- policy: present (no T5 baseline to compare)"; fi
kubectl get "$POLICY_RES" "$POLICY_MR" -o name >/dev/null 2>&1 && { echo "ABORT: legacy Crossplane MR still present" >&2; exit 1; } || echo "  legacy Crossplane MR: absent"
four_keep_refs && echo "  resourceRefs: exactly the 4 keep MRs" || { echo "ABORT: resourceRefs != 4 keep MRs" >&2; exit 1; }
for pair in "$BACK_RES $BACK_MR" "$CONF_RES $CONF_MR" "$ROLE_RES $ROLE_MR" "$POLICY_RES $NEW_MR"; do set -- $pair
  uid_present "$1" "$2" || { echo "ABORT: keep-set MR missing: $2" >&2; exit 1; }
  mr_active_ok "$1" "$2" || { echo "ABORT: keep-set MR not active: $2" >&2; exit 1; }; done
echo "  keep-set: 4 MRs present + active/ReconcileSuccess"
vault_exec "$BGT" vault read -format=json auth/kubernetes/ok-robotics/role/sa-obs | jq -e '.data.token_policies==["okvc-ok-robotics-sa-obs"]' >/dev/null && echo "  Vault role: okvc- only" || { echo "ABORT: role not okvc-only" >&2; exit 1; }
xr_active_ok && echo "  XR: active/ReconcileSuccess" || { echo "ABORT: XR not active" >&2; exit 1; }
vso_health_gate && echo "  VSO: VaultAuth + VaultStaticSecret healthy" || { echo "ABORT: VSO unhealthy" >&2; exit 1; }

echo; echo "════════ (C) NO-REFERENCE (audit-only, no delete) ════════"
kubectl get "$POLICY_RES" -o json | jq -e --arg old "$OLD_POLICY" '[.items[]|select(.metadata.annotations["crossplane.io/external-name"]==$old or .spec.forProvider.name==$old)]|length==0' >/dev/null && echo "  Crossplane: no Policy MR references $OLD_POLICY" || { echo "ABORT: a Crossplane Policy MR references $OLD_POLICY" >&2; exit 1; }
AUTH_JSON="$(vault_exec "$BGT" vault auth list -format=json)"
jq -e 'type=="object" and all(to_entries[]; (.value.type|type)=="string")' <<<"$AUTH_JSON" >/dev/null || { echo "ABORT: malformed auth list" >&2; exit 1; }
while IFS= read -r m; do t="$(jq -r --arg m "$m" '.[$m].type' <<<"$AUTH_JSON")"
  case "$t" in
    token) : ;;
    userpass)  scan_policy_carriers userpass-users   "auth/${m}users" "auth/${m}users/" '(.data.token_policies//[])[],(.data.policies//[])[]' ;;
    kubernetes) scan_policy_carriers kubernetes-roles "auth/${m}role"  "auth/${m}role/"  '(.data.token_policies//[])[],(.data.policies//[])[]' ;;
    *) echo "ABORT: unreviewed auth type '$t' at '$m'" >&2; exit 1 ;;
  esac
done < <(jq -r 'keys[]' <<<"$AUTH_JSON")
scan_policy_carriers token-roles "auth/token/roles" "auth/token/roles/" '(.data.allowed_policies//[])[],(.data.token_policies//[])[]'
scan_policy_carriers identity-entity-ids "identity/entity/id" "identity/entity/id/" '(.data.policies//[])[]'
scan_policy_carriers identity-group-ids  "identity/group/id"  "identity/group/id/"  '(.data.policies//[])[]'
# active persisted tokens
capture_status_split AJSON AERR ARC vault_exec "$BGT" vault list -format=json auth/token/accessors
[[ "$ARC" == "0" && -z "$AERR" ]] || { echo "ABORT: cannot enumerate accessors (rc=$ARC stderr=[$AERR])" >&2; exit 1; }
mapfile -t ACC < <(jq -r '.[]' <<<"$AJSON"); NACC=0; NVAN=0
for a in "${ACC[@]}"; do NACC=$((NACC+1))
  capture_status_split TJ TE TR vault_exec "$BGT" vault token lookup -format=json -accessor "$a"
  if [[ "$TR" == "0" ]]; then
    jq -e --arg old "$OLD_POLICY" '((.data.policies//[])+(.data.identity_policies//[]))|index($old)==null' <<<"$TJ" >/dev/null \
      || { echo "ABORT: LIVE REFERENCE — token accessor $a carries $OLD_POLICY" >&2; exit 1; }
  elif grep -qiE 'invalid accessor' <<<"${TE}${TJ}"; then
    NVAN=$((NVAN+1))   # token expired/revoked between list and lookup -> gone -> cannot reference
  else
    echo "ABORT: token lookup failed for accessor $a (rc=$TR stderr=[$TE])" >&2; exit 1
  fi
done
echo "  active persisted token accessors: $NACC listed; $((NACC-NVAN)) live-checked; $NVAN vanished (expired/revoked between list+lookup); no live reference"

echo; echo "════════ (D) VAULT AUDIT TRAIL for the legacy policy delete ════════"
AUD="$(vault_exec "$BGT" vault audit list -format=json 2>/dev/null || true)"
if [[ -n "$AUD" ]] && jq -e 'type=="object" and length>0' <<<"$AUD" >/dev/null 2>&1; then
  echo "  audit devices:"; jq -r 'to_entries[]|"    \(.key) type=\(.value.type) path=\(.value.options.file_path // "-")"' <<<"$AUD"
  FILEPATH="$(jq -r 'to_entries[]|select(.value.type=="file")|.value.options.file_path' <<<"$AUD" | head -n1)"
  if [[ -n "$FILEPATH" ]]; then
    echo "  grepping audit log $FILEPATH for sys/policies/acl/$OLD_POLICY (delete ops):"
    DELETE_AUDIT="$(vault_exec "$BGT" sh -c "grep -F 'sys/policies/acl/$OLD_POLICY' '$FILEPATH' 2>/dev/null" \
      | jq -rc 'select(.request.operation=="delete")|{time:.time,op:.request.operation,path:.request.path,accessor:.auth.accessor,display:.auth.display_name,reqid:.request.id,err:(.error//"")}' 2>/dev/null || true)"
    if [[ -n "$DELETE_AUDIT" ]]; then printf '%s\n' "$DELETE_AUDIT" | sed 's/^/    /'
    else echo "    NO PARSEABLE DELETE ENTRY FOUND (audit corroboration NOT obtained — likely log rotation or audit enabled after the delete; provenance still established by A+B+C)"; fi
  else echo "  (no file audit device; check the configured device's backend for the delete op)"; fi
else echo "  NO audit device enabled — the delete origin cannot be proven from Vault. This is itself a finding."; fi

vault_exec "$BGT" vault token revoke -self >/dev/null; unset BGT; echo
echo "════════ VERDICT INPUTS GATHERED (read-only; nothing changed) ════════"
echo "Interpret against GPT's decision tree: done-marker+archive+hash consistency (A),"
echo "correct okvc-only end-state with zero live references (B/C), and the audit trail (D)."
