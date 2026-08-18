#!/usr/bin/env bash
# Render or execute an isolated CNPG recovery drill. Credential values are
# never accepted: the caller pre-provisions two distinct Secrets in NAMESPACE.
set -Eeuo pipefail

# Wait until a pod reaches a TERMINAL phase, then return 0 only for Succeeded.
# `kubectl wait --for=jsonpath=...=Succeeded` cannot be satisfied by a Failed pod, so it burns the
# whole timeout and headlines "timed out waiting for the condition" — burying the pod's own error,
# which is the thing you actually needed. Five drill runs were lost to that.
wait_pod_terminal() {
  local pod="$1" timeout="${2:-180}" i phase
  for ((i=0; i<timeout; i+=3)); do
    phase="$(kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$NAMESPACE" get pod "$pod" \
      -o jsonpath='{.status.phase}' 2>/dev/null || true)"
    case "$phase" in
      Succeeded) return 0 ;;
      Failed) printf 'pod %s FAILED (phase=%s); its output follows:\n' "$pod" "$phase" >&2; return 1 ;;
    esac
    sleep 3
  done
  printf 'pod %s did not reach a terminal phase within %ss (last phase=%s)\n' "$pod" "$timeout" "${phase:-unknown}" >&2
  return 1
}

usage() {
  cat <<'EOF'
Usage:
  run-restore-drill.sh --source-cluster DNS_LABEL --run-id DNS_LABEL \
    --namespace DNS_LABEL --minio-endpoint URL --minio-ca-secret DNS_LABEL \
    --source-credentials-secret DNS_LABEL --drill-credentials-secret DNS_LABEL \
    --backup-id BARMAN_BACKUP_ID \
    --database-api-version GROUP/VERSION --database-kind KIND \
    --database-name NAME --database-uid UID \
    --postgres-image IMAGE@sha256:DIGEST --storage-class NAME \
    [--storage-size 10Gi] [--kubeconfig PATH] [--timeout 20m] \
    [--render-only | --execute --approve-isolated-restore] [--retain]

The recovery cluster name is always recovery-RUN_ID. The source folder name,
bootstrap source, external-cluster name, and plugin serverName are always
derived from the one --source-cluster value. Secret values are neither accepted
nor rendered. Execution requires an existing namespace and two distinct,
pre-provisioned credential Secrets in that namespace.
EOF
}

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
TEMPLATE="${SCRIPT_DIR}/recovery-cluster.template.yaml"
EXPECTED_TARGET_CLUSTER=ok-robotics
EXPECTED_SOURCE_CLUSTER=ok-robotics
EXPECTED_NAMESPACE=database-ok-robotics
EXPECTED_MINIO_ENDPOINT=https://minio.minio.svc:9000
EXPECTED_MINIO_CA_SECRET=minio-backup-store-ca
SOURCE_CLUSTER=
RUN_ID=
NAMESPACE=
MINIO_ENDPOINT=
MINIO_CA_SECRET=
SOURCE_CREDENTIALS_SECRET=
DRILL_CREDENTIALS_SECRET=
BACKUP_ID=
DATABASE_API_VERSION=
DATABASE_KIND=
DATABASE_NAME=
DATABASE_UID=
POSTGRES_IMAGE=
STORAGE_CLASS=
STORAGE_SIZE=10Gi
KUBECONFIG_PATH=
TIMEOUT=20m
MODE=render
APPROVED=false
RETAIN=false
CREATED=false
SUCCEEDED=false
WRITER_PROVISIONED=false
WORK_DIR=
RENDERED=
PROBE_POD=
CHECK_STREAM=

while (($#)); do
  case "$1" in
    --source-cluster) SOURCE_CLUSTER="${2:?missing value}"; shift 2 ;;
    --run-id) RUN_ID="${2:?missing value}"; shift 2 ;;
    --namespace) NAMESPACE="${2:?missing value}"; shift 2 ;;
    --minio-endpoint) MINIO_ENDPOINT="${2:?missing value}"; shift 2 ;;
    --minio-ca-secret) MINIO_CA_SECRET="${2:?missing value}"; shift 2 ;;
    --source-credentials-secret) SOURCE_CREDENTIALS_SECRET="${2:?missing value}"; shift 2 ;;
    --drill-credentials-secret) DRILL_CREDENTIALS_SECRET="${2:?missing value}"; shift 2 ;;
    --backup-id) BACKUP_ID="${2:?missing value}"; shift 2 ;;
    --database-api-version) DATABASE_API_VERSION="${2:?missing value}"; shift 2 ;;
    --database-kind) DATABASE_KIND="${2:?missing value}"; shift 2 ;;
    --database-name) DATABASE_NAME="${2:?missing value}"; shift 2 ;;
    --database-uid) DATABASE_UID="${2:?missing value}"; shift 2 ;;
    --postgres-image) POSTGRES_IMAGE="${2:?missing value}"; shift 2 ;;
    --storage-class) STORAGE_CLASS="${2:?missing value}"; shift 2 ;;
    --storage-size) STORAGE_SIZE="${2:?missing value}"; shift 2 ;;
    --kubeconfig) KUBECONFIG_PATH="${2:?missing value}"; shift 2 ;;
    --timeout) TIMEOUT="${2:?missing value}"; shift 2 ;;
    --render-only) MODE=render; shift ;;
    --execute) MODE=execute; shift ;;
    --approve-isolated-restore) APPROVED=true; shift ;;
    --retain) RETAIN=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'ERROR: unknown argument %q\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
done

for required in SOURCE_CLUSTER RUN_ID NAMESPACE MINIO_ENDPOINT MINIO_CA_SECRET SOURCE_CREDENTIALS_SECRET DRILL_CREDENTIALS_SECRET BACKUP_ID DATABASE_API_VERSION DATABASE_KIND DATABASE_NAME DATABASE_UID POSTGRES_IMAGE STORAGE_CLASS; do
  [[ -n "${!required}" ]] || { printf 'ERROR: %s is required\n' "$required" >&2; exit 2; }
done
DNS_LABEL_RE='^[a-z0-9]([-a-z0-9]*[a-z0-9])?$'
[[ "$DATABASE_API_VERSION" =~ ^[a-z0-9.-]+/[a-z0-9]+$ ]] \
  || { echo 'ERROR: --database-api-version must be a Kubernetes group/version' >&2; exit 2; }
[[ "$DATABASE_KIND" =~ ^[A-Z][A-Za-z0-9]*$ ]] \
  || { echo 'ERROR: --database-kind must be a Kubernetes kind' >&2; exit 2; }
[[ "$DATABASE_NAME" =~ $DNS_LABEL_RE && ${#DATABASE_NAME} -le 63 ]] \
  || { echo 'ERROR: --database-name must be a DNS label' >&2; exit 2; }
[[ "$DATABASE_UID" =~ ^[A-Za-z0-9][-A-Za-z0-9.]*$ ]] \
  || { echo 'ERROR: --database-uid is malformed' >&2; exit 2; }
[[ "$BACKUP_ID" =~ ^[0-9]{8}T[0-9]{6}$ ]] \
  || { echo 'ERROR: --backup-id must be a Barman backup ID (YYYYMMDDTHHMMSS)' >&2; exit 2; }
for field in SOURCE_CLUSTER RUN_ID NAMESPACE MINIO_CA_SECRET SOURCE_CREDENTIALS_SECRET DRILL_CREDENTIALS_SECRET; do
  value="${!field}"
  [[ ${#value} -le 63 && "$value" =~ $DNS_LABEL_RE ]] \
    || { printf 'ERROR: %s must be a DNS label of at most 63 characters\n' "$field" >&2; exit 2; }
done
RECOVERY_CLUSTER="recovery-${RUN_ID}"
[[ ${#RECOVERY_CLUSTER} -le 63 ]] || { echo 'ERROR: recovery-RUN_ID exceeds 63 characters' >&2; exit 2; }
[[ "$SOURCE_CREDENTIALS_SECRET" != "$DRILL_CREDENTIALS_SECRET" ]] \
  || { echo 'ERROR: source and drill credential Secrets must be distinct' >&2; exit 2; }
[[ "$SOURCE_CLUSTER" == "$EXPECTED_SOURCE_CLUSTER" ]] \
  || { echo "ERROR: this OK-145 drill is authorized only for source cluster $EXPECTED_SOURCE_CLUSTER" >&2; exit 2; }
[[ "$NAMESPACE" == "$EXPECTED_NAMESPACE" ]] \
  || { echo "ERROR: this OK-145 drill is authorized only for namespace $EXPECTED_NAMESPACE" >&2; exit 2; }
# https only, and deliberately not "https preferred": the drill authenticates to the
# backup source with a credential whose whole purpose is custody of backups, and the
# isolation argument in ADR-Platform-032 §11.3 assumes that credential is not observable
# in transit. A plaintext endpoint is refused rather than warned about.
[[ "$MINIO_ENDPOINT" =~ ^https://[^[:space:]]+$ ]] \
  || { echo 'ERROR: --minio-endpoint must be an https URL without whitespace (plaintext is refused)' >&2; exit 2; }
[[ "$MINIO_ENDPOINT" == "$EXPECTED_MINIO_ENDPOINT" ]] \
  || { echo "ERROR: this OK-145 drill is authorized only for the in-cluster MinIO endpoint" >&2; exit 2; }
[[ "$MINIO_CA_SECRET" == "$EXPECTED_MINIO_CA_SECRET" ]] \
  || { echo "ERROR: this OK-145 drill is authorized only for CA Secret $EXPECTED_MINIO_CA_SECRET" >&2; exit 2; }
[[ "$SOURCE_CREDENTIALS_SECRET" == "ok-db-backups-${EXPECTED_SOURCE_CLUSTER}-reader" ]] \
  || { echo 'ERROR: source credential Secret is outside the reviewed drill tuple' >&2; exit 2; }
[[ "$DRILL_CREDENTIALS_SECRET" == "ok-db-drill-${RUN_ID}-writer" ]] \
  || { echo 'ERROR: drill credential Secret is outside the reviewed run tuple' >&2; exit 2; }
[[ "$MINIO_ENDPOINT" =~ ^https://[A-Za-z0-9._:-]+(/[A-Za-z0-9._~!\$\&\(\)\*\+\,\;\=\:\@%/-]*)?$ ]] \
  || { echo 'ERROR: --minio-endpoint contains unsupported URL characters' >&2; exit 2; }
[[ "$POSTGRES_IMAGE" =~ ^[-A-Za-z0-9._/:]+@sha256:[0-9a-f]{64}$ ]] \
  || { echo 'ERROR: --postgres-image must be pinned by sha256 digest' >&2; exit 2; }
[[ "$STORAGE_CLASS" =~ ^[a-z0-9]([-a-z0-9.]*[a-z0-9])?$ && ${#STORAGE_CLASS} -le 253 ]] \
  || { echo 'ERROR: --storage-class must be a DNS subdomain' >&2; exit 2; }
[[ "$STORAGE_SIZE" =~ ^[1-9][0-9]*(Ei|Pi|Ti|Gi|Mi|Ki)$ ]] \
  || { echo 'ERROR: --storage-size must be a positive binary Kubernetes quantity' >&2; exit 2; }
[[ "$TIMEOUT" =~ ^[1-9][0-9]*[smh]$ ]] \
  || { echo 'ERROR: --timeout must be a positive integer followed by s, m, or h' >&2; exit 2; }
[[ -r "$TEMPLATE" ]] || { echo 'ERROR: recovery template is unreadable' >&2; exit 1; }
command -v envsubst >/dev/null || { echo "ERROR: required command 'envsubst' not found" >&2; exit 1; }

cleanup() {
  local rc=$?
  trap - EXIT ERR
  set +e
  if [[ -n "$PROBE_POD" && -n "$KUBECONFIG_PATH" ]]; then
    kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$NAMESPACE" delete pod "$PROBE_POD" \
      --ignore-not-found=true --wait=true >/dev/null
    PROBE_POD=
  fi
  if [[ "$CREATED" == true && ( "$RETAIN" != true || "$SUCCEEDED" != true ) ]]; then
    kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$NAMESPACE" delete -f "$RENDERED" \
      --ignore-not-found=false --wait=true >/dev/null
    cleanup_rc=$?
    if ((cleanup_rc != 0 && rc == 0)); then rc=$cleanup_rc; fi
    kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$NAMESPACE" delete pvc \
      -l "cnpg.io/cluster=${RECOVERY_CLUSTER}" --wait=true >/dev/null
    pvc_rc=$?
    if ((pvc_rc != 0 && rc == 0)); then rc=$pvc_rc; fi
    CREATED=false
  fi
  if [[ "$WRITER_PROVISIONED" == true && ( "$RETAIN" != true || "$SUCCEEDED" != true ) ]]; then
    cleanup_drill_prefix
    prefix_rc=$?
    if ((prefix_rc != 0 && rc == 0)); then rc=$prefix_rc; fi
    bash "$SCRIPT_DIR/provision-drill-writer.sh" --kubeconfig "$KUBECONFIG_PATH" --run-id "$RUN_ID" --delete
    writer_rc=$?
    if ((writer_rc != 0 && rc == 0)); then rc=$writer_rc; fi
  fi
  [[ -n "$WORK_DIR" && -d "$WORK_DIR" ]] && rm -rf -- "$WORK_DIR"
  exit "$rc"
}
trap cleanup EXIT
trap 'rc=$?; printf "ABORT: rc=%s at line %s\n" "$rc" "$LINENO" >&2; exit "$rc"' ERR

WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/ok-db-restore-drill.XXXXXX")"
[[ -d "$WORK_DIR" ]] || { echo 'ERROR: mktemp did not create a work directory' >&2; exit 1; }
RENDERED="${WORK_DIR}/recovery-cluster.yaml"
[[ ! -e "$RENDERED" ]] || { echo 'ERROR: refusing to overwrite rendered manifest' >&2; exit 1; }
export SOURCE_CLUSTER RUN_ID NAMESPACE MINIO_ENDPOINT MINIO_CA_SECRET SOURCE_CREDENTIALS_SECRET BACKUP_ID
export DRILL_CREDENTIALS_SECRET POSTGRES_IMAGE STORAGE_CLASS STORAGE_SIZE RECOVERY_CLUSTER
envsubst '${SOURCE_CLUSTER} ${RUN_ID} ${NAMESPACE} ${MINIO_ENDPOINT} ${MINIO_CA_SECRET} ${SOURCE_CREDENTIALS_SECRET} ${DRILL_CREDENTIALS_SECRET} ${BACKUP_ID} ${POSTGRES_IMAGE} ${STORAGE_CLASS} ${STORAGE_SIZE} ${RECOVERY_CLUSTER}' \
  <"$TEMPLATE" >"$RENDERED"
if grep -q '\${[A-Z_][A-Z_]*}' "$RENDERED"; then
  echo 'ERROR: rendered manifest contains unresolved placeholders' >&2
  exit 1
fi

if [[ "$MODE" == render ]]; then
  cat "$RENDERED"
  exit 0
fi
[[ "$APPROVED" == true ]] \
  || { echo 'ERROR: execution requires --approve-isolated-restore' >&2; exit 2; }
[[ -n "$KUBECONFIG_PATH" && -r "$KUBECONFIG_PATH" ]] \
  || { echo 'ERROR: execution requires a readable --kubeconfig' >&2; exit 2; }
for command in kubectl grep python3 sha256sum date sed seq awk wc; do
  command -v "$command" >/dev/null || { printf "ERROR: required command '%s' not found\n" "$command" >&2; exit 1; }
done

CHECK_STREAM="$WORK_DIR/checks.jsonl"
[[ ! -e "$CHECK_STREAM" ]] || { echo 'ERROR: refusing to overwrite JSONL check stream' >&2; exit 1; }
: >"$CHECK_STREAM"

append_observation() {
  python3 "$SCRIPT_DIR/append-observation.py" --stream "$CHECK_STREAM" "$@"
}

PROFILE_CHECK_COUNT="$(awk '/^-- check: [a-z0-9-]+[[:space:]]*$/ { count++ } END { print count + 0 }' "$SCRIPT_DIR/check-profile.sql")"
[[ "$PROFILE_CHECK_COUNT" =~ ^[1-9][0-9]*$ ]] \
  || { echo 'ERROR: check profile declares no checks' >&2; exit 1; }
CHECK_PROFILE_DIGEST="sha256:$(sha256sum "$SCRIPT_DIR/check-profile.sql" | awk '{print $1}')"
append_observation --event profile \
  --observed digest "$CHECK_PROFILE_DIGEST" --observed-int expectedChecks "$PROFILE_CHECK_COUNT"
append_observation --event database \
  --observed apiVersion "$DATABASE_API_VERSION" --observed kind "$DATABASE_KIND" \
  --observed name "$DATABASE_NAME" --observed uid "$DATABASE_UID"

cleanup_drill_prefix() {
  local cleanup_pod="ok-145-drill-prefix-cleanup-${RUN_ID}"
  local existing_cleanup
  existing_cleanup="$(kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$NAMESPACE" get pod "$cleanup_pod" --ignore-not-found -o name)"
  [[ -z "$existing_cleanup" ]] \
    || { printf 'ERROR: cleanup pod %s already exists; refusing to claim it\n' "$cleanup_pod" >&2; return 1; }
  PROBE_POD="$cleanup_pod"
  kubectl --kubeconfig "$KUBECONFIG_PATH" apply -f - >/dev/null <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: $cleanup_pod
  namespace: $NAMESPACE
  labels: {platform.openkubes.ai/database-drill-run: $RUN_ID}
spec:
  restartPolicy: Never
  automountServiceAccountToken: false
  securityContext: {seccompProfile: {type: RuntimeDefault}}
  containers:
  - name: cleanup
    image: quay.io/minio/mc:RELEASE.2025-08-13T08-35-41Z@sha256:eb4ea9884b77704230e2423e9004d2fa738dc272876b9cc41a297d29443b8780
    securityContext:
      allowPrivilegeEscalation: false
      capabilities: {drop: [ALL]}
      runAsNonRoot: true
      runAsUser: 1000
      runAsGroup: 1000
    command: [sh, -c]
    args:
    - |
      set -eu
      export SSL_CERT_FILE=/ca/ca.crt MC_CONFIG_DIR=/tmp/mc
      export MC_HOST_drill="https://\${ACCESS_KEY_ID}:\${ACCESS_SECRET_KEY}@minio.minio.svc:9000"
      mc rm --recursive --force "drill/ok-db-drill/$RUN_ID" >/dev/null
      echo 'PASS: isolated drill prefix removed'
    envFrom: [{secretRef: {name: $DRILL_CREDENTIALS_SECRET}}]
    volumeMounts: [{name: ca, mountPath: /ca, readOnly: true}]
  volumes:
  - name: ca
    secret: {secretName: $MINIO_CA_SECRET, items: [{key: ca.crt, path: ca.crt}]}
EOF
  if ! wait_pod_terminal "$cleanup_pod" 120; then
    kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$NAMESPACE" logs "$cleanup_pod" >&2 || true
    return 1
  fi
  kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$NAMESPACE" logs "$cleanup_pod"
  kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$NAMESPACE" delete pod "$cleanup_pod" --wait=true >/dev/null
  PROBE_POD=
}

CURRENT_CONTEXT="$(kubectl --kubeconfig "$KUBECONFIG_PATH" config current-context)"
CURRENT_CLUSTER="$(kubectl --kubeconfig "$KUBECONFIG_PATH" config view --minify -o jsonpath='{.clusters[0].name}')"
[[ "$CURRENT_CONTEXT" == "$EXPECTED_TARGET_CLUSTER" || "$CURRENT_CLUSTER" == "$EXPECTED_TARGET_CLUSTER" ]] \
  || { printf "ERROR: kubeconfig identifies context '%s' / cluster '%s', not %s\n" "$CURRENT_CONTEXT" "$CURRENT_CLUSTER" "$EXPECTED_TARGET_CLUSTER" >&2; exit 2; }
kubectl --kubeconfig "$KUBECONFIG_PATH" get namespace "$NAMESPACE" >/dev/null
kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$NAMESPACE" get secret "$SOURCE_CREDENTIALS_SECRET" >/dev/null
for target in \
  "objectstore.barmancloud.cnpg.io/${RECOVERY_CLUSTER}-source" \
  "objectstore.barmancloud.cnpg.io/${RECOVERY_CLUSTER}-destination" \
  "cluster.postgresql.cnpg.io/${RECOVERY_CLUSTER}"; do
  if ! existing="$(kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$NAMESPACE" get "$target" --ignore-not-found -o name)"; then
    printf "ERROR: could not prove temporary target '%s' is absent\n" "$target" >&2
    exit 1
  fi
  if [[ -n "$existing" ]]; then
    printf "ERROR: temporary target '%s' already exists; refusing to clobber it\n" "$target" >&2
    exit 1
  fi
done
if [[ -n "$(kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$NAMESPACE" get pvc -l "cnpg.io/cluster=${RECOVERY_CLUSTER}" -o name)" ]]; then
  echo 'ERROR: recovery PVC already exists; refusing to clobber it' >&2
  exit 1
fi

# Capture the provisioner's own verdict rather than restating it: the effective-policy result
# recorded in the artifact must be the output of the check that ran, not a sentence written here.
PROVISION_STDOUT="$WORK_DIR/provision.stdout"
PROVISION_STDERR="$WORK_DIR/provision.stderr"
if ! bash "$SCRIPT_DIR/provision-drill-writer.sh" --kubeconfig "$KUBECONFIG_PATH" --run-id "$RUN_ID" --ensure \
    >"$PROVISION_STDOUT" 2>"$PROVISION_STDERR"; then
  cat "$PROVISION_STDOUT"
  cat "$PROVISION_STDERR" >&2
  exit 1
fi
cat "$PROVISION_STDOUT"
if [[ -s "$PROVISION_STDERR" ]]; then
  cat "$PROVISION_STDERR" >&2
fi
WRITER_PROVISIONED=true
python3 - "$PROVISION_STDOUT" "$CHECK_STREAM" <<'PY'
import json
import sys
from pathlib import Path

events = []
for raw in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        continue
    if isinstance(value, dict) and value.get("event") == "effective-policy":
        events.append(value)
if len(events) != 1:
    raise ValueError(f"expected one structured effective-policy observation, found {len(events)}")
with Path(sys.argv[2]).open("a", encoding="utf-8") as stream:
    stream.write(json.dumps(events[0], separators=(",", ":"), sort_keys=True) + "\n")
PY
kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$NAMESPACE" get secret "$DRILL_CREDENTIALS_SECRET" >/dev/null

BACKUP_ROWS="$(kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$NAMESPACE" get backups.postgresql.cnpg.io \
  -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.metadata.uid}{"\t"}{.status.phase}{"\t"}{.status.backupId}{"\t"}{.status.stoppedAt}{"\n"}{end}')"
BACKUP_MATCH="$(printf '%s\n' "$BACKUP_ROWS" | awk -F '\t' -v id="$BACKUP_ID" '
  $4 == id { count++; row = $0 }
  END { if (count != 1) exit 1; print row }
')" || { echo 'ERROR: requested backup ID did not resolve to exactly one Backup object' >&2; exit 1; }
IFS=$'\t' read -r BACKUP_NAME BACKUP_UID BACKUP_PHASE RESOLVED_BACKUP_ID BACKUP_STOPPED <<<"$BACKUP_MATCH"
SOURCE_CLUSTER_UID="$(kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$NAMESPACE" get cluster "$SOURCE_CLUSTER" -o jsonpath='{.metadata.uid}')"
SOURCE_SYSTEM_ID="$(kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$NAMESPACE" get cluster "$SOURCE_CLUSTER" -o jsonpath='{.status.systemID}')"
PLUGIN_IDENTITY="$(kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$NAMESPACE" get cluster "$SOURCE_CLUSTER" \
  -o jsonpath='{range .spec.plugins[?(@.isWALArchiver==true)]}{.name}{"\n"}{end}' | awk 'NF {count++; value=$0} END {if (count != 1) exit 1; print value}')" \
  || { echo 'ERROR: source cluster does not resolve exactly one WAL-archiver plugin' >&2; exit 1; }
SOURCE_OBJECT_STORE="$(kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$NAMESPACE" get cluster "$SOURCE_CLUSTER" \
  -o jsonpath='{range .spec.plugins[?(@.isWALArchiver==true)]}{.parameters.barmanObjectName}{"\n"}{end}')"
SOURCE_SERVER_NAME="$(kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$NAMESPACE" get cluster "$SOURCE_CLUSTER" \
  -o jsonpath='{range .spec.plugins[?(@.isWALArchiver==true)]}{.parameters.serverName}{"\n"}{end}')"
[[ -n "$SOURCE_OBJECT_STORE" && -n "$SOURCE_SERVER_NAME" ]] \
  || { echo 'ERROR: source ObjectStore/serverName could not be resolved' >&2; exit 1; }
[[ "$SOURCE_SERVER_NAME" == "$SOURCE_CLUSTER" ]] \
  || { echo 'ERROR: resolved source serverName differs from the single-input recovery identity' >&2; exit 1; }
RESOLVED_ENDPOINT="$(kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$NAMESPACE" get objectstore "$SOURCE_OBJECT_STORE" -o jsonpath='{.spec.configuration.endpointURL}')"
RESOLVED_DESTINATION="$(kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$NAMESPACE" get objectstore "$SOURCE_OBJECT_STORE" -o jsonpath='{.spec.configuration.destinationPath}')"
[[ "$RESOLVED_ENDPOINT" == "$MINIO_ENDPOINT" ]] \
  || { echo 'ERROR: requested endpoint differs from the resolved source endpoint' >&2; exit 1; }
[[ "$RESOLVED_DESTINATION" =~ ^s3://([^/]+)(/(.*))?$ ]] \
  || { echo 'ERROR: resolved ObjectStore destinationPath is not canonical s3://bucket[/prefix]' >&2; exit 1; }
RESOLVED_BUCKET="${BASH_REMATCH[1]}"
RESOLVED_BASE_PREFIX="${BASH_REMATCH[3]:-}"
RESOLVED_BASE_PREFIX="${RESOLVED_BASE_PREFIX%/}"
if [[ -n "$RESOLVED_BASE_PREFIX" ]]; then
  RESOLVED_PATH_PREFIX="${RESOLVED_BASE_PREFIX}/${SOURCE_SERVER_NAME}/"
else
  RESOLVED_PATH_PREFIX="${SOURCE_SERVER_NAME}/"
fi
CANONICAL_SERVER_DIRECTORY="s3://${RESOLVED_BUCKET}/${RESOLVED_PATH_PREFIX}"
WAL_STATUS="$(kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$NAMESPACE" get cluster "$SOURCE_CLUSTER" -o jsonpath='{range .status.conditions[?(@.type=="ContinuousArchiving")]}{.status}{end}')"
LAST_SUCCESSFUL="$(kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$NAMESPACE" get objectstore "$SOURCE_OBJECT_STORE" -o "jsonpath={.status.serverRecoveryWindow.${SOURCE_SERVER_NAME}.lastSuccessfulBackupTime}")"
FIRST_RECOVERABLE="$(kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$NAMESPACE" get objectstore "$SOURCE_OBJECT_STORE" -o "jsonpath={.status.serverRecoveryWindow.${SOURCE_SERVER_NAME}.firstRecoverabilityPoint}")"
LAST_FAILED="$(kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$NAMESPACE" get objectstore "$SOURCE_OBJECT_STORE" -o "jsonpath={.status.serverRecoveryWindow.${SOURCE_SERVER_NAME}.lastFailedBackupTime}")"
[[ "$BACKUP_PHASE" == completed && "$RESOLVED_BACKUP_ID" == "$BACKUP_ID" ]] \
  || { echo 'ERROR: selected Backup is not the requested completed backup' >&2; exit 1; }
[[ -n "$BACKUP_UID" && -n "$SOURCE_CLUSTER_UID" && -n "$SOURCE_SYSTEM_ID" ]] \
  || { echo 'ERROR: source identity metadata is incomplete' >&2; exit 1; }
AVAILABILITY_VERDICT="$(python3 - "$FIRST_RECOVERABLE" "$BACKUP_STOPPED" "$LAST_SUCCESSFUL" "$LAST_FAILED" <<'PY'
import sys
from datetime import datetime

def instant(value: str, label: str) -> datetime:
    if not value:
        raise ValueError(f"{label} is missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{label} is not RFC3339: {value!r}") from error
    if parsed.tzinfo is None:
        raise ValueError(f"{label} has no timezone")
    return parsed

first = instant(sys.argv[1], "firstRecoverabilityPoint")
stopped = instant(sys.argv[2], "Backup.stoppedAt")
last = instant(sys.argv[3], "lastSuccessfulBackupTime")
failed = instant(sys.argv[4], "lastFailedBackupTime") if sys.argv[4] else None
if first > last:
    raise ValueError("ObjectStore recovery window is incoherent (first > last)")
if failed is not None and failed == last:
    raise ValueError("ObjectStore success/failure timestamps are ambiguous")
if failed is not None and failed > last:
    raise ValueError("ObjectStore reports a failure newer than its last success")
if first > stopped:
    raise ValueError("selected backup is outside the retained recovery window (BackupUnavailable)")
if stopped > last:
    raise ValueError("ObjectStore observation has not caught up to the selected backup")
print("BackupWindowContainsExecution")
PY
)" || { echo 'ERROR: selected backup availability is not positively established' >&2; exit 1; }
if [[ "$WAL_STATUS" == False ]]; then
  echo 'ERROR: ContinuousArchiving=False is counter-proof (ContinuousArchivingFailed)' >&2
  exit 1
elif [[ "$WAL_STATUS" == True ]]; then
  PROTECTION_REASON="$(python3 - "$SCRIPT_DIR/../crossplane/composition.yaml" <<'PY'
import pathlib
import re
import sys

source = pathlib.Path(sys.argv[1]).read_text()
matches = re.findall(r'\{\{- \$protectionValidReason := "([A-Za-z0-9]+)" \}\}', source)
if len(matches) != 1:
    raise SystemExit("Composition must declare exactly one $protectionValidReason constant")
print(matches[0])
PY
)"
  PROTECTION_STATE=Valid
else
  PROTECTION_REASON=WALArchivingUnproven
  PROTECTION_STATE=Unknown
fi
printf 'ProtectionReady=%s reason=%s selectedBackupAvailability=Valid/%s lastSuccessfulBackupTime=%s firstRecoverabilityPoint=%s wal=%s\n' \
  "$PROTECTION_STATE" "$PROTECTION_REASON" "$AVAILABILITY_VERDICT" "$LAST_SUCCESSFUL" "$FIRST_RECOVERABLE" "${WAL_STATUS:-missing}"

DEPLOYMENT_ROWS="$(kubectl --kubeconfig "$KUBECONFIG_PATH" -n cnpg-system get deployments.apps \
  -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.metadata.labels.app\.kubernetes\.io/version}{"\t"}{.spec.template.spec.containers[0].image}{"\n"}{end}')"

# Version comes from the image reference that actually runs. The app.kubernetes.io/version
# label is optional metadata — absent on ok-robotics after its 2026-08-18 rebuild — so it is
# a cross-check, not the source. If both are present and disagree, the version is ambiguous
# and the run must stop rather than record a guess into evidence.
discover_version() {
  printf '%s\n' "$DEPLOYMENT_ROWS" | awk -F '\t' -v want="$1" '
    $1 != want { next }
    {
      count++
      label = $2
      image = $3
      tag = ""
      # strip any @sha256:... digest, then take the text after the final ":"
      sub(/@.*$/, "", image)
      if (match(image, /:[^:\/]+$/)) tag = substr(image, RSTART + 1)
      sub(/^v/, "", tag)
      sub(/^v/, "", label)
      if (tag == "") next
      if (label != "" && label != tag) next
      value = tag
      found++
    }
    END { if (count != 1 || found != 1) exit 1; print value }'
}
CNPG_VERSION="$(discover_version cnpg-controller-manager)" \
  || { echo 'ERROR: CNPG version could not be discovered from its Deployment image (missing tag, or label disagrees)' >&2; exit 1; }
PLUGIN_VERSION="$(discover_version barman-cloud)" \
  || { echo 'ERROR: backup plugin version could not be discovered from its Deployment image (missing tag, or label disagrees)' >&2; exit 1; }
VERIFIER_VERSION="sha256:$(
  sha256sum "$SCRIPT_DIR/run-restore-drill.sh" "$SCRIPT_DIR/write-restore-evidence.py" | awk '{print $1}' | sha256sum | awk '{print $1}'
)"
append_observation --event backup \
  --observed backupId "$RESOLVED_BACKUP_ID" --observed apiVersion postgresql.cnpg.io/v1 \
  --observed kind Backup --observed namespace "$NAMESPACE" --observed name "$BACKUP_NAME" \
  --observed uid "$BACKUP_UID" --observed stoppedAt "$BACKUP_STOPPED"
append_observation --event source \
  --observed systemIdentifier "$SOURCE_SYSTEM_ID" --observed clusterApiVersion postgresql.cnpg.io/v1 \
  --observed clusterKind Cluster --observed clusterNamespace "$NAMESPACE" \
  --observed clusterName "$SOURCE_CLUSTER" --observed clusterUid "$SOURCE_CLUSTER_UID" \
  --observed endpoint "$RESOLVED_ENDPOINT" --observed bucket "$RESOLVED_BUCKET" \
  --observed pathPrefix "$RESOLVED_PATH_PREFIX" --observed serverName "$SOURCE_SERVER_NAME" \
  --observed canonicalServerDirectory "$CANONICAL_SERVER_DIRECTORY"
append_observation --event runtime \
  --observed verifierVersion "$VERIFIER_VERSION" --observed cnpgVersion "$CNPG_VERSION" \
  --observed pluginIdentity "$PLUGIN_IDENTITY" --observed pluginVersion "$PLUGIN_VERSION"

STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
START_EPOCH="$(date -u +%s)"
MANIFEST_DIGEST="$(sha256sum "$RENDERED" | awk '{print $1}')"
CREATED=true
kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$NAMESPACE" apply -f "$RENDERED"
PROMOTION_LOG="$WORK_DIR/promotion.log"
PROMOTION_LOG_CAPTURED=false
for _ in $(seq 1 600); do
  while IFS= read -r recovery_pod; do
    [[ "$recovery_pod" == *-full-recovery-* ]] || continue
    recovery_phase="$(kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$NAMESPACE" get pod "$recovery_pod" -o jsonpath='{.status.phase}')"
    if [[ "$recovery_phase" == Succeeded ]]; then
      kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$NAMESPACE" logs "$recovery_pod" -c full-recovery >"$PROMOTION_LOG"
      PROMOTION_LOG_CAPTURED=true
      break 2
    fi
  done < <(kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$NAMESPACE" get pods \
    -l "cnpg.io/cluster=${RECOVERY_CLUSTER}" -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}')
  sleep 1
done
[[ "$PROMOTION_LOG_CAPTURED" == true ]] || { echo 'ERROR: no successful full-recovery pod log was captured' >&2; exit 1; }
kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$NAMESPACE" wait \
  --for=condition=Ready "cluster.postgresql.cnpg.io/${RECOVERY_CLUSTER}" --timeout="$TIMEOUT"
PRIMARY_POD="$(kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$NAMESPACE" get pod \
  -l "cnpg.io/cluster=${RECOVERY_CLUSTER},role=primary" -o jsonpath='{.items[0].metadata.name}')"
[[ -n "$PRIMARY_POD" ]] || { echo 'ERROR: ready cluster has no primary pod' >&2; exit 1; }
WORKLOAD_SERVICE_ACCOUNT="$(kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$NAMESPACE" get pod "$PRIMARY_POD" -o jsonpath='{.spec.serviceAccountName}')"
[[ -n "$WORKLOAD_SERVICE_ACCOUNT" ]] || { echo 'ERROR: recovery workload has no ServiceAccount' >&2; exit 1; }

PROMOTION_TARGET="$(python3 "$SCRIPT_DIR/extract-promotion-target.py" "$PROMOTION_LOG")"
REACHED_TIMELINE="${PROMOTION_TARGET%%|*}"
REACHED_LSN="${PROMOTION_TARGET#*|}"
printf 'PROMOTION reachedTimeline=%s reachedLSN=%s source=postgres-promotion-log\n' "$REACHED_TIMELINE" "$REACHED_LSN"

PSQL_STDOUT="$WORK_DIR/psql.stdout"
PSQL_STDERR="$WORK_DIR/psql.stderr"
set +e
kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$NAMESPACE" exec -i "$PRIMARY_POD" -c postgres \
  -- psql -XAtq -U postgres -d app -v ON_ERROR_STOP=1 <"$SCRIPT_DIR/check-profile.sql" \
  >"$PSQL_STDOUT" 2>"$PSQL_STDERR"
PSQL_RC=$?
set -e
PSQL_RECORDS="$(awk 'NF {count++} END {print count + 0}' "$PSQL_STDOUT")"
PSQL_STDERR_BYTES="$(wc -c <"$PSQL_STDERR" | awk '{print $1}')"
if ((PSQL_RC == 0)); then PSQL_RESULT=PASS; else PSQL_RESULT=FAIL; fi
append_observation --event psql --observed result "$PSQL_RESULT" \
  --observed-int exitCode "$PSQL_RC" --observed-int jsonRecords "$PSQL_RECORDS" \
  --observed-int stderrBytes "$PSQL_STDERR_BYTES"
if ((PSQL_RC != 0)); then
  cat "$PSQL_STDERR" >&2
  echo 'ERROR: psql check profile execution failed; no artifact will be written' >&2
  exit 1
fi
[[ "$PSQL_RECORDS" == "$PROFILE_CHECK_COUNT" ]] \
  || { printf 'ERROR: psql emitted %s JSONL records; profile declares %s\n' "$PSQL_RECORDS" "$PROFILE_CHECK_COUNT" >&2; exit 1; }
python3 - "$PSQL_STDOUT" "$CHECK_STREAM" <<'PY'
import json
import sys
from pathlib import Path

records = []
for number, raw in enumerate(Path(sys.argv[1]).read_text(encoding="utf-8").splitlines(), 1):
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError(f"psql line {number} is not JSON: {error}") from error
    if not isinstance(value, dict) or value.get("event") != "check":
        raise ValueError(f"psql line {number} is not a check event")
    if value.get("result") != "PASS":
        raise ValueError(f"psql check {value.get('name')!r} did not pass")
    records.append(value)
with Path(sys.argv[2]).open("a", encoding="utf-8") as stream:
    for value in records:
        stream.write(json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n")
PY
printf 'CHECK_PROFILE records=%s digest=%s:\n' "$PSQL_RECORDS" "$CHECK_PROFILE_DIGEST"
cat "$PSQL_STDOUT"

KNOWN_OBJECT="${RESOLVED_PATH_PREFIX}base/${BACKUP_ID}/backup.info"
# The denial probe is a sibling directly under the canonical server directory.
# It never risks depositing a stray object inside a real base-backup directory.
DENIAL_OBJECT="${RESOLVED_PATH_PREFIX}ok145-write-denial-${RUN_ID}"
probe_pod_name="ok-145-recovery-policy-probe-${RUN_ID}"
existing_probe="$(kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$NAMESPACE" get pod "$probe_pod_name" --ignore-not-found -o name)"
[[ -z "$existing_probe" ]] \
  || { printf 'ERROR: policy probe pod %s already exists; refusing to claim it\n' "$probe_pod_name" >&2; exit 1; }
PROBE_POD="$probe_pod_name"
kubectl --kubeconfig "$KUBECONFIG_PATH" apply -f - >/dev/null <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: $PROBE_POD
  namespace: $NAMESPACE
  labels: {platform.openkubes.ai/database-drill-run: $RUN_ID}
spec:
  serviceAccountName: $WORKLOAD_SERVICE_ACCOUNT
  restartPolicy: Never
  automountServiceAccountToken: false
  securityContext: {seccompProfile: {type: RuntimeDefault}}
  containers:
  - name: probe
    image: quay.io/minio/mc:RELEASE.2025-08-13T08-35-41Z@sha256:eb4ea9884b77704230e2423e9004d2fa738dc272876b9cc41a297d29443b8780
    securityContext:
      allowPrivilegeEscalation: false
      capabilities: {drop: [ALL]}
      runAsNonRoot: true
      runAsUser: 1000
      runAsGroup: 1000
    command: [sh, -c]
    args:
    - |
      set -eu
      export SSL_CERT_FILE=/ca/ca.crt MC_CONFIG_DIR=/tmp/mc
      export MC_HOST_source="https://\${ACCESS_KEY_ID}:\${ACCESS_SECRET_KEY}@minio.minio.svc:9000"
      mc stat "source/$RESOLVED_BUCKET/$KNOWN_OBJECT" >/dev/null
      digest_line="\$(mc cat "source/$RESOLVED_BUCKET/$KNOWN_OBJECT" | sha256sum)"
      digest="\${digest_line%% *}"
      set +e
      denial="\$(printf 'ok-145 authenticated denial probe\n' | mc --json pipe "source/$RESOLVED_BUCKET/$DENIAL_OBJECT" 2>&1)"
      denial_rc=\$?
      set -e
      test "\$denial_rc" -ne 0
      # Order matters: exclude inconclusive causes FIRST. Checking the denial wording before
      # the transport/credential cases would report a TLS or DNS failure as "wrong denial code",
      # i.e. fail for the wrong reason and send the next reader down the wrong path.
      case "\$denial" in
        *NoSuchBucket*|*x509*|*certificate*|*TLS*|*credential*|*lookup*|*dial*|*"connection refused"*)
          printf 'ERROR: denial was inconclusive, not a permission denial: %s\n' "\$denial" >&2
          exit 1
          ;;
      esac
      # Match the CLIENT'S denial rendering, not a wire code it does not surface. Measured:
      # mc renders a 403 as "Insufficient permissions to access this path" and never prints
      # "AccessDenied" (plain or --json). boto3/aws-cli DO surface the code, so both forms are
      # accepted and the raw text is recorded for the reviewer either way.
      case "\$denial" in
        *AccessDenied*|*"Insufficient permissions"*|*"Access Denied"*) ;;
        *) printf 'ERROR: write failed without an authenticated permission denial: %s\n' "\$denial" >&2; exit 1;;
      esac
      # Did-not-land check: the refused object must not exist. stat MUST fail.
      set +e
      landed="\$(mc stat "source/$RESOLVED_BUCKET/$DENIAL_OBJECT" 2>&1)"
      landed_rc=\$?
      set -e
      if [ "\$landed_rc" -eq 0 ]; then
        printf 'ERROR: refused write actually landed: %s\n' "\$landed" >&2
        exit 1
      fi
      echo "KNOWN_OBJECT_SHA256=\$digest"
      printf 'WRITE_DENIAL_RAW=%s\n' "\$denial"
      echo 'WRITE_DENIAL=authenticated permission denial, object absent'
    envFrom: [{secretRef: {name: $SOURCE_CREDENTIALS_SECRET}}]
    volumeMounts: [{name: ca, mountPath: /ca, readOnly: true}]
  volumes:
  - name: ca
    secret: {secretName: $MINIO_CA_SECRET, items: [{key: ca.crt, path: ca.crt}]}
EOF
if ! wait_pod_terminal "$PROBE_POD" 180; then
  kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$NAMESPACE" logs "$PROBE_POD" >&2 || true
  exit 1
fi
PROBE_OUTPUT="$(kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$NAMESPACE" logs "$PROBE_POD")"
printf 'ISOLATION_PROBE serviceAccount=%s object=%s\n%s\n' "$WORKLOAD_SERVICE_ACCOUNT" "$KNOWN_OBJECT" "$PROBE_OUTPUT"
KNOWN_OBJECT_SHA256="$(printf '%s\n' "$PROBE_OUTPUT" | sed -n 's/^KNOWN_OBJECT_SHA256=//p')"
WRITE_DENIAL_RAW="$(printf '%s\n' "$PROBE_OUTPUT" | sed -n 's/^WRITE_DENIAL_RAW=//p')"
[[ -n "$WRITE_DENIAL_RAW" ]] || { echo 'ERROR: probe recorded no raw denial response' >&2; exit 1; }
printf '%s\n' "$PROBE_OUTPUT" | grep -q '^WRITE_DENIAL=authenticated permission denial, object absent$' \
  || { echo 'ERROR: probe did not confirm an authenticated denial with the object absent' >&2; exit 1; }
[[ "$KNOWN_OBJECT_SHA256" =~ ^[0-9a-f]{64}$ ]] || { echo 'ERROR: readable object digest missing' >&2; exit 1; }
kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$NAMESPACE" delete pod "$PROBE_POD" --wait=true >/dev/null
PROBE_POD=

append_observation --event check --value name selected-backup-object-readable --value result PASS \
  --observed object "$KNOWN_OBJECT" --observed sha256 "sha256:$KNOWN_OBJECT_SHA256"
append_observation --event isolation --value result PASS \
  --observed writeDenialRawResponse "$WRITE_DENIAL_RAW" --observed writeDenialObject "$DENIAL_OBJECT" \
  --observed-bool writeDenialObjectAbsent true

COMPLETED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
COMPLETED_EPOCH="$(date -u +%s)"
DURATION_SECONDS=$((COMPLETED_EPOCH - START_EPOCH))
EVIDENCE_RELATIVE="platform/database/postgresql/drill/evidence/restoreverified-${RUN_ID}.yaml"
EVIDENCE_PATH="${SCRIPT_DIR}/evidence/restoreverified-${RUN_ID}.yaml"
append_observation --event recovery \
  --observed requestedTarget "backupID=${BACKUP_ID}" --observed reachedTimeline "$REACHED_TIMELINE" \
  --observed reachedLsn "$REACHED_LSN" --observed startedAt "$STARTED_AT" \
  --observed completedAt "$COMPLETED_AT" --observed-int durationSeconds "$DURATION_SECONDS" \
  --observed manifestDigest "sha256:$MANIFEST_DIGEST"
append_observation --event run --observed runId "$RUN_ID" --observed evidenceRef "$EVIDENCE_RELATIVE"
python3 "$SCRIPT_DIR/write-restore-evidence.py" \
  --output "$EVIDENCE_PATH" --stream "$CHECK_STREAM" \
  --check-profile "$SCRIPT_DIR/check-profile.sql" --evidence-ref "$EVIDENCE_RELATIVE"
python3 "$SCRIPT_DIR/tests/restore-evidence-check.py" "$EVIDENCE_PATH"
SUCCEEDED=true
printf 'RESULT: PASS recovery=%s source=ok-db-backups/%s backupId=%s destination=ok-db-drill/%s evidence=%s\n' \
  "$RECOVERY_CLUSTER" "$SOURCE_CLUSTER" "$BACKUP_ID" "$RUN_ID" "$EVIDENCE_RELATIVE"
if [[ "$RETAIN" == true ]]; then
  printf 'RETAINED: resources with run label %s in namespace %s\n' "$RUN_ID" "$NAMESPACE"
fi
