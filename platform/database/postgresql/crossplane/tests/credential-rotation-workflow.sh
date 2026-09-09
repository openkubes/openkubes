#!/usr/bin/env bash
# Approval-gated double-buffer credential lifecycle for one Database.
# Secrets are passed through stdin or SecretKeyRefs; never argv, logs, or temp files.
set -Eeuo pipefail
umask 077

MGMT_KUBECONFIG=${MGMT_KUBECONFIG:?set MGMT_KUBECONFIG}
WORKLOAD_KUBECONFIG=${WORKLOAD_KUBECONFIG:?set WORKLOAD_KUBECONFIG}
XR_NAME=${XR_NAME:?set XR_NAME to the cluster-scoped Database name}
BASE_SECRET=${BASE_SECRET:?set BASE_SECRET to the management source Secret base name}
WORKLOAD_NAMESPACE=${WORKLOAD_NAMESPACE:?set WORKLOAD_NAMESPACE}
CNPG_CLUSTER=${CNPG_CLUSTER:?set CNPG_CLUSTER}
SOURCE_NAMESPACE=${SOURCE_NAMESPACE:-crossplane-system}
APPROVE_MGMT=${APPROVE_MGMT:-no}
PSQL_IMAGE=${PSQL_IMAGE:-}
APPROVE_CREDENTIAL_ROTATION=${APPROVE_CREDENTIAL_ROTATION:-no}
# The provider-readback heartbeat is a 300s quantum; allow the 900s freshness bound
# so finalization cannot time out just before the refreshed Cluster status is observed.
TIMEOUT=${TIMEOUT:-900}
POLL=${POLL:-5}

mgmt() { kubectl --kubeconfig "$MGMT_KUBECONFIG" "$@"; }
work() { kubectl --kubeconfig "$WORKLOAD_KUBECONFIG" "$@"; }
die() { echo "ERROR: $*" >&2; exit 2; }
need_approval() {
  [[ "$APPROVE_MGMT" == yes ]] || die "APPROVE_MGMT=yes is required"
  [[ "$APPROVE_CREDENTIAL_ROTATION" == yes ]] || die "APPROVE_CREDENTIAL_ROTATION=yes is required"
  echo "APPROVED: $1" >&2
}

keys_are_exact() {
  local kube=$1 ns=$2 name=$3
  kubectl --kubeconfig "$kube" -n "$ns" get secret "$name" -o json |
    python3 -c 'import json,sys; d=json.load(sys.stdin); print(" ".join(sorted((d.get("data") or {}).keys())))' |
    grep -Fxq 'password username'
}
username_is() { local kube=$1 ns=$2 name=$3 expected=$4; kubectl --kubeconfig "$kube" -n "$ns" get secret "$name" -o jsonpath='{.data.username}' | base64 -d | grep -Fxq "$expected"; }
secret_rv() { mgmt -n "$SOURCE_NAMESPACE" get secret "$1" -o jsonpath='{.metadata.resourceVersion}'; }
remote_rv() { work -n "$WORKLOAD_NAMESPACE" get secret "$1" -o jsonpath='{.metadata.resourceVersion}'; }
# Silver's Composition hashes the observed base64 Secret data string, not decoded password bytes.
password_digest() { work -n "$WORKLOAD_NAMESPACE" get secret "$1" -o jsonpath='{.data.password}' | sha256sum | awk '{print $1}'; }
role_rv() {
  work -n "$WORKLOAD_NAMESPACE" get cluster.postgresql.cnpg.io "$CNPG_CLUSTER" -o json |
    python3 -c 'import json,sys; d=json.load(sys.stdin); role=sys.argv[1]; print(d.get("status",{}).get("managedRolesStatus",{}).get("passwordStatus",{}).get(role,{}).get("resourceVersion", ""))' "$1"
}
role_reconciled() {
  work -n "$WORKLOAD_NAMESPACE" get cluster.postgresql.cnpg.io "$CNPG_CLUSTER" -o json |
    python3 -c 'import json,sys; d=json.load(sys.stdin); role=sys.argv[1]; print("yes" if role in d.get("status",{}).get("managedRolesStatus",{}).get("byStatus",{}).get("reconciled",[]) else "no")' "$1"
}
annotation() {
  mgmt get database "$XR_NAME" -o json |
    python3 -c 'import json,sys; print(json.load(sys.stdin).get("metadata",{}).get("annotations",{}).get(sys.argv[1], ""))' "$1"
}
active_slot() { annotation platform.openkubes.ai/active-credential-slot | { read -r x || true; echo "${x:-a}"; }; }

consumer_sweep() {
  local hits
  hits=$(KUBECONFIG="$WORKLOAD_KUBECONFIG" python3 - "$BASE_SECRET" <<'PY'
import json, os, subprocess, sys
base=sys.argv[1]; hits=[]
kinds=("pods","deployments","statefulsets","daemonsets","jobs","cronjobs","replicasets")
def get(kind):
    raw=subprocess.run(["kubectl","get",kind,"-A","-o","json"],check=True,capture_output=True,text=True).stdout
    return json.loads(raw).get("items",[])
def inspect(item, podspec):
    meta=item.get("metadata",{}); n=f'{meta.get("namespace","")}/{meta.get("name","")}'
    cs=podspec.get("containers",[])+podspec.get("initContainers",[])
    for c in cs:
        for e in c.get("env",[]):
            if e.get("valueFrom",{}).get("secretKeyRef",{}).get("name")==base: hits.append(n+" secretRef")
            if e.get("name") in {"PGUSER","POSTGRES_USER","DB_USER"} and e.get("value")=="app": hits.append(n+" base-owner env")
        for e in c.get("envFrom",[]):
            if e.get("secretRef",{}).get("name")==base: hits.append(n+" envFrom")
    for v in podspec.get("volumes",[]):
        if v.get("secret",{}).get("secretName")==base: hits.append(n+" volume")
for item in get("pods"):
    inspect(item,item.get("spec",{}))
for kind in kinds[1:]:
    for item in get(kind):
        spec=item.get("spec",{}); template=spec.get("template",{})
        if kind == "cronjobs": template=spec.get("jobTemplate",{}).get("spec",{}).get("template",{})
        inspect(item,template.get("spec",{}))
print("\n".join(sorted(set(hits))))
PY
)
  [[ -z "$hits" ]] || die "consumer sweep found base-owner use:\n$hits"
  local primary
  primary=$(work -n "$WORKLOAD_NAMESPACE" get pods -l "cnpg.io/cluster=$CNPG_CLUSTER,cnpg.io/instanceRole=primary" -o jsonpath='{.items[0].metadata.name}')
  [[ -n "$primary" ]] || die "no CNPG primary for consumer sweep"
  local db_hits
  db_hits=$(work -n "$WORKLOAD_NAMESPACE" exec "$primary" -c postgres -- psql -U postgres -d postgres -X -Atqc "select usename from pg_stat_activity where usename = 'app';" 2>/dev/null || true)
  [[ -z "$db_hits" ]] || die "live base-owner sessions found: $db_hits"
}

preflight() {
  local a="${BASE_SECRET}-a" b="${BASE_SECRET}-b" slot role rv
  for s in "$a" "$b"; do
    mgmt -n "$SOURCE_NAMESPACE" get secret "$s" >/dev/null || die "missing management source Secret $SOURCE_NAMESPACE/$s"
    keys_are_exact "$MGMT_KUBECONFIG" "$SOURCE_NAMESPACE" "$s" || die "$s must contain exactly username/password keys"
    username_is "$MGMT_KUBECONFIG" "$SOURCE_NAMESPACE" "$s" "app_${s##*-}" || die "$s username is not app_${s##*-}"
    work -n "$WORKLOAD_NAMESPACE" get secret "$s" >/dev/null || die "missing workload mirror $WORKLOAD_NAMESPACE/$s"
    keys_are_exact "$WORKLOAD_KUBECONFIG" "$WORKLOAD_NAMESPACE" "$s" || die "remote $s must contain exactly username/password keys"
    username_is "$WORKLOAD_KUBECONFIG" "$WORKLOAD_NAMESPACE" "$s" "app_${s##*-}" || die "remote $s username is not app_${s##*-}"
  done
  for slot in a b; do
    role="app_${slot}"; rv=$(remote_rv "${BASE_SECRET}-${slot}")
    [[ "$(role_reconciled "$role")" == yes ]] || die "$role is not CNPG-reconciled"
    [[ "$rv" == "$(role_rv "$role")" ]] || die "$role applied RV does not match remote Secret RV"
  done
  consumer_sweep
  echo "PASS: both credential slots are present, applied, and no base-owner consumer was found"
}

wait_role_present() {
  local role=$1 deadline=$((SECONDS+TIMEOUT)) rv
  while (( SECONDS < deadline )); do
    rv=$(remote_rv "${BASE_SECRET}-${role#app_}" 2>/dev/null || true)
    if [[ -n "$rv" && "$(role_reconciled "$role" 2>/dev/null || true)" == yes && "$(role_rv "$role" 2>/dev/null || true)" == "$rv" ]]; then printf '%s' "$rv"; return 0; fi
    sleep "$POLL"
  done
  die "timeout waiting for initial mirror and CNPG role $role"
}

wait_overlap_status() {
  local active=$1 id=$2 deadline=$((SECONDS+TIMEOUT))
  while (( SECONDS < deadline )); do
    if [[ "$(mgmt get database "$XR_NAME" -o jsonpath='{.metadata.annotations.platform\.openkubes\.ai/credential-rotation-id}' 2>/dev/null || true)" == "$id" && "$(mgmt get database "$XR_NAME" -o jsonpath='{.status.credentials.activeRole}' 2>/dev/null || true)" == "app_${active}" && "$(mgmt get database "$XR_NAME" -o jsonpath='{.status.credentials.applied}' 2>/dev/null || true)" == true && "$(mgmt get database "$XR_NAME" -o jsonpath='{.status.credentials.reason}' 2>/dev/null || true)" == CredentialOverlapActive && "$(mgmt get database "$XR_NAME" -o jsonpath='{.status.credentials.previousCredentialAccepted}' 2>/dev/null || true)" == true && "$(mgmt get database "$XR_NAME" -o jsonpath='{.status.credentials.previousCredentialRevoked}' 2>/dev/null || true)" != true ]]; then return 0; fi
    sleep "$POLL"
  done
  die "timeout waiting for matching rotationId, CredentialOverlapActive, and previousCredentialAccepted"
}

wait_finalized_status() {
  local id=$1 deadline=$((SECONDS+TIMEOUT))
  while (( SECONDS < deadline )); do
    if [[ "$(mgmt get database "$XR_NAME" -o jsonpath='{.metadata.annotations.platform\.openkubes\.ai/credential-rotation-id}' 2>/dev/null || true)" == "$id" && "$(mgmt get database "$XR_NAME" -o jsonpath='{.status.credentials.applied}' 2>/dev/null || true)" == true && "$(mgmt get database "$XR_NAME" -o jsonpath='{.status.credentials.previousCredentialRevoked}' 2>/dev/null || true)" == true && "$(mgmt get database "$XR_NAME" -o jsonpath='{.status.credentials.previousCredentialAccepted}' 2>/dev/null || true)" == false && "$(mgmt get database "$XR_NAME" -o jsonpath='{.status.credentials.reason}' 2>/dev/null || true)" == CredentialRotationFinalized ]]; then return 0; fi
    sleep "$POLL"
  done
  die "timeout waiting for credential fields to report CredentialRotationFinalized"
}

wait_role() {
  local role=$1 old_remote_rv=$2 deadline=$((SECONDS+TIMEOUT)) new_remote_rv
  while (( SECONDS < deadline )); do
    new_remote_rv=$(remote_rv "${BASE_SECRET}-${role#app_}" 2>/dev/null || true)
    if [[ -n "$new_remote_rv" && "$new_remote_rv" != "$old_remote_rv" && "$(role_reconciled "$role" 2>/dev/null || true)" == yes && "$(role_rv "$role" 2>/dev/null || true)" == "$new_remote_rv" ]]; then
      printf '%s' "$new_remote_rv"; return 0
    fi
    sleep "$POLL"
  done
  die "timeout waiting for remote Secret RV change and CNPG role $role"
}

rotate_source() {
  local name=$1 slot=${1##*-}
  [[ "$slot" == a || "$slot" == b ]] || die "source Secret must end in -a or -b"
  # Password bytes flow from openssl through stdin to kubectl. They never enter argv or a file.
  openssl rand -base64 48 | tr -d '\n' | mgmt -n "$SOURCE_NAMESPACE" create secret generic "$name" \
    --type=kubernetes.io/basic-auth --from-literal="username=app_${slot}" --from-file=password=/dev/stdin \
    --dry-run=client -o yaml | mgmt apply -f - >/dev/null
}

patch_rotation() {
  local slot=$1 previous_rv=$2 previous_digest=$3 id=$4 now=$5
  mgmt patch database "$XR_NAME" --type=merge -p "$(python3 - "$slot" "$previous_rv" "$previous_digest" "$id" "$now" <<'PY'
import json,sys
slot,rv,previous_digest,rid,now=sys.argv[1:]
print(json.dumps({"metadata":{"annotations":{
 "platform.openkubes.ai/active-credential-slot":slot,
 "platform.openkubes.ai/credential-rotation-id":rid,
 "platform.openkubes.ai/credential-rotated-at":now,
 "platform.openkubes.ai/previous-credential-resource-version":rv,
 "platform.openkubes.ai/previous-credential-digest":previous_digest}}}))
PY
)" >/dev/null
}

provision() {
  need_approval "Provision double-buffer source Secrets for Database $XR_NAME?"
  local created_slots=""
  provision_cleanup() { for slot in $created_slots; do mgmt -n "$SOURCE_NAMESPACE" delete secret "${BASE_SECRET}-${slot}" --ignore-not-found >/dev/null 2>&1 || true; done; }
  trap provision_cleanup ERR
  for slot in a b; do
    name="${BASE_SECRET}-${slot}"
    if mgmt -n "$SOURCE_NAMESPACE" get secret "$name" >/dev/null 2>&1; then
      die "$SOURCE_NAMESPACE/$name already exists; provision refuses overwrite (use start/finalize rotation)"
    fi
  done
  for slot in a b; do
    name="${BASE_SECRET}-${slot}"
    openssl rand -base64 48 | tr -d '\n' | mgmt -n "$SOURCE_NAMESPACE" create secret generic "$name" \
      --type=kubernetes.io/basic-auth --from-literal="username=app_${slot}" --from-file=password=/dev/stdin \
      --dry-run=client -o yaml | mgmt apply -f - >/dev/null
    created_slots="$created_slots $slot"
  done
  id=$(python3 -c 'import uuid; print(uuid.uuid4())')
  mgmt patch database "$XR_NAME" --type=merge -p "$(python3 - "$id" <<'PY'
import json,sys
print(json.dumps({"metadata":{"annotations":{"platform.openkubes.ai/credential-bootstrap-id":sys.argv[1]}}}))
PY
)" >/dev/null
  for slot in a b; do wait_role_present "app_${slot}" >/dev/null; done
  trap - ERR
  echo "PASS: double-buffer source Secrets provisioned and both CNPG roles applied"
}

start() {
  need_approval "Start credential rotation for Database $XR_NAME?"
  [[ "$PSQL_IMAGE" == *@sha256:* ]] || die "PSQL_IMAGE must include a sha256 digest"
  preflight
  local active inactive previous_rv previous_digest old_inactive_rv id now new_remote_rv
  active=$(active_slot); [[ "$active" == a || "$active" == b ]] || die "invalid active slot $active"
  inactive=$([[ "$active" == a ]] && echo b || echo a)
  previous_rv=$(remote_rv "${BASE_SECRET}-${active}")
  previous_digest=$(password_digest "${BASE_SECRET}-${active}")
  [[ "$previous_digest" =~ ^[a-f0-9]{64}$ ]] || die "could not fingerprint previous workload password"
  old_inactive_rv=$(remote_rv "${BASE_SECRET}-${inactive}")
  id=$(python3 -c 'import uuid; print(uuid.uuid4())')
  now=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  rotate_source "${BASE_SECRET}-${inactive}"
  new_remote_rv=$(wait_role "app_${inactive}" "$old_inactive_rv")
  patch_rotation "$inactive" "$previous_rv" "$previous_digest" "$id" "$now"
  wait_overlap_status "$inactive" "$id"
  suffix=$(printf '%s' "$id" | tr -cd 'a-f0-9' | cut -c1-12)
  trap cleanup EXIT
  proof_pod="${BASE_SECRET}-rotation-active-${suffix}"
  run_auth_pod "$proof_pod" "${BASE_SECRET}-${inactive}" "app_${inactive}"
  work -n "$WORKLOAD_NAMESPACE" delete pod "$proof_pod" --ignore-not-found >/dev/null
  proof_pod="${BASE_SECRET}-rotation-previous-${suffix}"
  run_auth_pod "$proof_pod" "${BASE_SECRET}-${active}" "app_${active}"
  echo "PASS: rotation $id staged and applied; both active and previous credentials authenticate"
}

proof_secret=""
proof_pod=""
prove_overlap() {
  need_approval "Prove active and previous credentials for the current overlap on Database $XR_NAME?"
  [[ "$PSQL_IMAGE" == *@sha256:* ]] || die "PSQL_IMAGE must include a sha256 digest"
  local rid active_role previous_role active previous suffix
  rid=$(annotation platform.openkubes.ai/credential-rotation-id)
  active_role=$(mgmt get database "$XR_NAME" -o jsonpath='{.status.credentials.activeRole}')
  previous_role=$(mgmt get database "$XR_NAME" -o jsonpath='{.status.credentials.previousRole}')
  [[ -n "$rid" && "$active_role" =~ ^app_[ab]$ && "$previous_role" =~ ^app_[ab]$ && "$active_role" != "$previous_role" ]] || die "status lacks distinct activeRole/previousRole and rotationId"
  [[ "$(mgmt get database "$XR_NAME" -o jsonpath='{.status.credentials.reason}')" == CredentialOverlapActive ]] || die "credential status is not CredentialOverlapActive"
  [[ "$(mgmt get database "$XR_NAME" -o jsonpath='{.status.credentials.previousCredentialAccepted}')" == true ]] || die "previous credential is not reported accepted"
  active=${active_role#app_}; previous=${previous_role#app_}
  suffix=$(printf '%s' "$rid" | tr -cd 'a-f0-9' | cut -c1-12)
  trap cleanup EXIT
  proof_pod="${BASE_SECRET}-rotation-active-${suffix}"
  run_auth_pod "$proof_pod" "${BASE_SECRET}-${active}" "$active_role"
  work -n "$WORKLOAD_NAMESPACE" delete pod "$proof_pod" --ignore-not-found >/dev/null
  proof_pod="${BASE_SECRET}-rotation-previous-${suffix}"
  run_auth_pod "$proof_pod" "${BASE_SECRET}-${previous}" "$previous_role"
  echo "PASS: rotation $rid overlap proofs succeeded for $active_role and $previous_role"
}
cleanup() {
  [[ -n "$proof_pod" ]] && work -n "$WORKLOAD_NAMESPACE" delete pod "$proof_pod" --ignore-not-found >/dev/null 2>&1 || true
  [[ -n "$proof_secret" ]] && work -n "$WORKLOAD_NAMESPACE" delete secret "$proof_secret" --ignore-not-found >/dev/null 2>&1 || true
}
run_auth_pod() {
  local name=$1 secret=$2 expected=$3 mode=${4:-success}; local yaml phase logs deadline
  yaml=$(cat <<YAML
apiVersion: v1
kind: Pod
metadata:
  name: $name
  namespace: $WORKLOAD_NAMESPACE
spec:
  restartPolicy: Never
  securityContext:
    runAsNonRoot: true
    seccompProfile: {type: RuntimeDefault}
  containers:
  - name: psql
    image: $PSQL_IMAGE
    env:
    - name: PGHOST
      value: ${CNPG_CLUSTER}-rw
    - name: PGDATABASE
      value: app
    - name: PGUSER
      valueFrom: {secretKeyRef: {name: $secret, key: username}}
    - name: PGPASSWORD
      valueFrom: {secretKeyRef: {name: $secret, key: password}}
    securityContext:
      runAsNonRoot: true
      allowPrivilegeEscalation: false
      readOnlyRootFilesystem: true
      capabilities: {drop: [ALL]}
    command: [sh, -ec]
    args: ["test \"\$(psql -X -Atqc \"select current_user || E'|' || pg_has_role(current_user, 'app', 'member')\")\" = \"$expected|true\""]
    volumeMounts:
    - {name: tmp, mountPath: /tmp}
  volumes:
  - {name: tmp, emptyDir: {}}
YAML
)
  printf '%s\n' "$yaml" | work apply -f - >/dev/null
  deadline=$((SECONDS+TIMEOUT))
  while (( SECONDS < deadline )); do
    phase=$(work -n "$WORKLOAD_NAMESPACE" get pod "$name" -o jsonpath='{.status.phase}' 2>/dev/null || true)
    [[ "$phase" == Succeeded || "$phase" == Failed ]] && break
    sleep "$POLL"
  done
  [[ "$phase" == Succeeded || "$phase" == Failed ]] || die "timeout waiting for proof pod $name to reach a terminal phase"
  logs=$(work -n "$WORKLOAD_NAMESPACE" logs "pod/$name" 2>&1 || true)
  if [[ "$mode" == success ]]; then
    [[ "$phase" == Succeeded ]] || die "active credential authentication proof failed"
  else
    [[ "$phase" == Failed ]] || die "old credential proof unexpectedly succeeded"
    printf '%s' "$logs" | grep -Eiq 'password authentication failed|authentication failed' || die "old credential proof failed inconclusively (not an authentication rejection)"
    return 1
  fi
}

finalize() {
  need_approval "Finalize credential rotation for Database $XR_NAME?"
  preflight
  local active previous rid rotated policy expiry now previous_name active_name expected
  active=$(active_slot); previous=$([[ "$active" == a ]] && echo b || echo a)
  rid=$(annotation platform.openkubes.ai/credential-rotation-id); rotated=$(annotation platform.openkubes.ai/credential-rotated-at)
  previous_digest=$(annotation platform.openkubes.ai/previous-credential-digest)
  [[ -n "$rid" && -n "$rotated" && "$previous_digest" =~ ^[a-f0-9]{64}$ ]] || die "rotation annotations lack previous credential digest"
  [[ "$PSQL_IMAGE" == *@sha256:* ]] || die "PSQL_IMAGE must include a sha256 digest"
  policy=$(mgmt get database "$XR_NAME" -o jsonpath='{.spec.protection.policyRef}')
  expiry=$(python3 - "$rotated" "$policy" <<'PY'
from datetime import datetime,timedelta,timezone
import sys
x=datetime.fromisoformat(sys.argv[1].replace('Z','+00:00')); print((x+timedelta(hours=1 if sys.argv[2]=='production' else 24)).timestamp())
PY
)
  now=$(date +%s); (( $(printf '%.0f' "$expiry") <= now )) || die "refusing finalization before previousValidUntil"
  [[ "$(mgmt get database "$XR_NAME" -o jsonpath='{.status.credentials.previousCredentialAccepted}')" == true ]] || die "previous credential is not reported accepted; refusing finalization"
  previous_name="${BASE_SECRET}-${previous}"; active_name="${BASE_SECRET}-${active}"
  suffix=$(printf '%s' "$rid" | tr -cd 'a-f0-9' | cut -c1-12)
  proof_secret="${BASE_SECRET}-rotation-proof-${suffix}"
  trap cleanup EXIT
  work -n "$WORKLOAD_NAMESPACE" get secret "$previous_name" -o jsonpath='{.data.password}' | base64 -d | \
    work -n "$WORKLOAD_NAMESPACE" create secret generic "$proof_secret" --from-literal=username="app_${previous}" --from-file=password=/dev/stdin --dry-run=client -o yaml | work apply -f - >/dev/null
  old_previous_rv=$(remote_rv "$previous_name")
  rotate_source "$previous_name"
  mgmt patch database "$XR_NAME" --type=merge -p "$(python3 - "$rid" <<'PY'
import json,sys
print(json.dumps({"metadata":{"annotations":{"platform.openkubes.ai/credential-finalization-id":sys.argv[1]}}}))
PY
)" >/dev/null
  new_previous_rv=$(wait_role "app_${previous}" "$old_previous_rv")
  current_previous_digest=$(password_digest "$previous_name")
  [[ "$current_previous_digest" =~ ^[a-f0-9]{64}$ && "$current_previous_digest" != "$previous_digest" ]] || die "previous password digest did not change; refusing revocation proof"
  proof_pod="${BASE_SECRET}-rotation-active-${suffix}"
  run_auth_pod "$proof_pod" "$active_name" "app_${active}"
  work -n "$WORKLOAD_NAMESPACE" delete pod "$proof_pod" --ignore-not-found >/dev/null
  proof_pod="${BASE_SECRET}-rotation-old-${suffix}"
  if run_auth_pod "$proof_pod" "$proof_secret" "app_${previous}" reject; then die "old credential still authenticates"; fi
  wait_finalized_status "$rid"
  service_ready=$(mgmt get database "$XR_NAME" -o jsonpath='{.status.serviceReady}' 2>/dev/null || true)
  echo "PASS: rotation $rid finalized; active credential succeeds, old credential is rejected; serviceReady=$service_ready (credential finalization does not roll back on unrelated evidence failure)"
}

case "${1:-}" in
  preflight) preflight ;;
  provision) provision ;;
  start) start ;;
  finalize) finalize ;;
  prove-overlap) prove_overlap ;;
  *) echo "usage: $0 {preflight|provision|start|prove-overlap|finalize}" >&2; exit 2 ;;
esac
