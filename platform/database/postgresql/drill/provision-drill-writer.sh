#!/usr/bin/env bash
set -Eeuo pipefail

readonly EXPECTED_CLUSTER=ok-robotics
readonly MINIO_NAMESPACE=minio
readonly DATABASE_NAMESPACE=database-ok-robotics
readonly OWNER_LABEL='platform.openkubes.ai/managed-by=ok-145-minio-provisioner'
readonly ENDPOINT='https://minio.minio.svc:9000'
readonly MC_IMAGE='quay.io/minio/mc:RELEASE.2025-08-13T08-35-41Z@sha256:eb4ea9884b77704230e2423e9004d2fa738dc272876b9cc41a297d29443b8780'
readonly GO_IMAGE='golang@sha256:b6ed3fd0452c0e9bcdef5597f29cc1418f61672e9d3a2f55bf02e7222c014abd'
readonly ROOT_SECRET=minio-root-credentials
readonly SOURCE_READER_SECRET=ok-db-backups-ok-robotics-reader
readonly SOURCE_READER_POLICY=ok-db-backups-reader
readonly DRILL_POLICY=ok-db-drill-writer

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly SOURCE_READER_POLICY_FILE="$SCRIPT_DIR/minio-policy-backups-readonly.json"
readonly DRILL_POLICY_FILE="$SCRIPT_DIR/minio-policy-drill-write.json"
KUBECONFIG_PATH=
RUN_ID=
ACTION=
WORK_DIR=
TEMP_POD=

usage() {
  echo 'Usage: provision-drill-writer.sh --kubeconfig PATH --run-id DNS_LABEL (--ensure|--delete)' >&2
}

while (($#)); do
  case "$1" in
    --kubeconfig) KUBECONFIG_PATH="${2:?missing value}"; shift 2 ;;
    --run-id) RUN_ID="${2:?missing value}"; shift 2 ;;
    --ensure) ACTION=ensure; shift ;;
    --delete) ACTION=delete; shift ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'ERROR: unknown argument %q\n' "$1" >&2; usage; exit 2 ;;
  esac
done

[[ -n "$KUBECONFIG_PATH" && -r "$KUBECONFIG_PATH" ]] || { echo 'ERROR: readable --kubeconfig is required' >&2; exit 2; }
[[ -n "$RUN_ID" && "$RUN_ID" =~ ^[a-z0-9]([-a-z0-9]*[a-z0-9])?$ && ${#RUN_ID} -le 32 ]] \
  || { echo 'ERROR: --run-id must be a DNS label of at most 32 characters' >&2; exit 2; }
[[ "$ACTION" == ensure || "$ACTION" == delete ]] || { echo 'ERROR: select exactly one of --ensure or --delete' >&2; exit 2; }
for command in kubectl docker openssl; do
  command -v "$command" >/dev/null || { printf "ERROR: required command '%s' not found\n" "$command" >&2; exit 1; }
done

cleanup() {
  local rc=$?
  trap - EXIT ERR
  set +e
  if [[ -n "$TEMP_POD" ]]; then
    kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$MINIO_NAMESPACE" delete pod "$TEMP_POD" \
      --ignore-not-found=true --wait=true >/dev/null
  fi
  [[ -n "$WORK_DIR" && -d "$WORK_DIR" ]] && rm -rf -- "$WORK_DIR"
  exit "$rc"
}
trap cleanup EXIT
trap 'rc=$?; printf "ABORT: rc=%s at line %s\n" "$rc" "$LINENO" >&2; exit "$rc"' ERR

context="$(kubectl --kubeconfig "$KUBECONFIG_PATH" config current-context)"
cluster="$(kubectl --kubeconfig "$KUBECONFIG_PATH" config view --minify -o jsonpath='{.clusters[0].name}')"
[[ "$context" == "$EXPECTED_CLUSTER" || "$cluster" == "$EXPECTED_CLUSTER" ]] \
  || { echo 'ERROR: kubeconfig does not identify ok-robotics' >&2; exit 2; }

readonly WRITER_SECRET="ok-db-drill-${RUN_ID}-writer"
for namespace in "$MINIO_NAMESPACE" "$DATABASE_NAMESPACE"; do
  kubectl --kubeconfig "$KUBECONFIG_PATH" get namespace "$namespace" >/dev/null
done
for required in "$ROOT_SECRET" "$SOURCE_READER_SECRET"; do
  kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$MINIO_NAMESPACE" get secret "$required" >/dev/null
done

if [[ "$ACTION" == ensure ]]; then
  for namespace in "$MINIO_NAMESPACE" "$DATABASE_NAMESPACE"; do
    existing="$(kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$namespace" get secret "$WRITER_SECRET" --ignore-not-found -o name)"
    if [[ -n "$existing" ]]; then
      owner="$(kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$namespace" get secret "$WRITER_SECRET" -o jsonpath='{.metadata.labels.platform\.openkubes\.ai/managed-by}')"
      [[ "$owner" == ok-145-minio-provisioner ]] || { echo 'ERROR: writer Secret exists without OK-145 ownership' >&2; exit 1; }
    fi
  done
  if ! kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$MINIO_NAMESPACE" get secret "$WRITER_SECRET" >/dev/null 2>&1; then
    access_secret="$(openssl rand -hex 32)"
    printf 'ACCESS_KEY_ID=%s\nACCESS_SECRET_KEY=%s\n' "$RUN_ID" "$access_secret" \
      | kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$MINIO_NAMESPACE" create secret generic "$WRITER_SECRET" --from-env-file=/dev/stdin >/dev/null
    kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$MINIO_NAMESPACE" label secret "$WRITER_SECRET" "$OWNER_LABEL" >/dev/null
    unset access_secret
  fi
  kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$MINIO_NAMESPACE" get secret "$WRITER_SECRET" \
    -o go-template='ACCESS_KEY_ID={{index .data "ACCESS_KEY_ID" | base64decode}}{{"\n"}}ACCESS_SECRET_KEY={{index .data "ACCESS_SECRET_KEY" | base64decode}}{{"\n"}}' \
    | kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$DATABASE_NAMESPACE" create secret generic "$WRITER_SECRET" \
        --from-env-file=/dev/stdin --dry-run=client -o yaml \
    | kubectl --kubeconfig "$KUBECONFIG_PATH" apply -f - >/dev/null
  kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$DATABASE_NAMESPACE" label secret "$WRITER_SECRET" "$OWNER_LABEL" --overwrite >/dev/null
else
  for namespace in "$MINIO_NAMESPACE" "$DATABASE_NAMESPACE"; do
    owner="$(kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$namespace" get secret "$WRITER_SECRET" -o jsonpath='{.metadata.labels.platform\.openkubes\.ai/managed-by}')"
    [[ "$owner" == ok-145-minio-provisioner ]] || { echo 'ERROR: refusing to delete a writer Secret without OK-145 ownership' >&2; exit 1; }
  done
fi

WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/ok-145-drill-writer.XXXXXX")"
HELPER="$WORK_DIR/minio-admin-helper"
GO_CACHE_ROOT="${TMPDIR:-/tmp}/openkubes-ok145-go-cache"
mkdir -p "$GO_CACHE_ROOT/build" "$GO_CACHE_ROOT/mod"
docker run --rm --user "$(id -u):$(id -g)" -e CGO_ENABLED=0 -e GOCACHE=/cache/build -e GOMODCACHE=/cache/mod \
  -v "$GO_CACHE_ROOT:/cache" \
  -v "$SCRIPT_DIR/minio-admin-helper:/src:ro" -v "$WORK_DIR:/out" -w /src "$GO_IMAGE" \
  go build -trimpath -ldflags=-buildid= -o /out/minio-admin-helper .

run_admin_action() {
  local user_secret="$1" policy_name="$2" managed_action="$3" policy_file="$4" policy_subject="$5" emit="$6"
  local pod_name="ok-145-drill-identity-${RUN_ID}"
  [[ -z "$(kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$MINIO_NAMESPACE" get pod "$pod_name" --ignore-not-found -o name)" ]] \
    || { echo 'ERROR: temporary admin pod already exists' >&2; exit 1; }
  TEMP_POD="$pod_name"
  kubectl --kubeconfig "$KUBECONFIG_PATH" apply -f - >/dev/null <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: $TEMP_POD
  namespace: $MINIO_NAMESPACE
  labels: {platform.openkubes.ai/managed-by: ok-145-minio-provisioner}
spec:
  restartPolicy: Never
  automountServiceAccountToken: false
  securityContext: {seccompProfile: {type: RuntimeDefault}}
  containers:
  - name: admin
    image: $MC_IMAGE
    command: [sh, -c, 'sleep 600']
    securityContext:
      allowPrivilegeEscalation: false
      capabilities: {drop: [ALL]}
      runAsNonRoot: true
      runAsUser: 1000
      runAsGroup: 1000
    env:
    - {name: MINIO_ENDPOINT, value: $ENDPOINT}
    - name: MINIO_ROOT_USER
      valueFrom: {secretKeyRef: {name: $ROOT_SECRET, key: MINIO_ROOT_USER}}
    - name: MINIO_ROOT_PASSWORD
      valueFrom: {secretKeyRef: {name: $ROOT_SECRET, key: MINIO_ROOT_PASSWORD}}
    - name: MINIO_MANAGED_USER
      valueFrom: {secretKeyRef: {name: $user_secret, key: ACCESS_KEY_ID}}
    - name: MINIO_MANAGED_SECRET
      valueFrom: {secretKeyRef: {name: $user_secret, key: ACCESS_SECRET_KEY}}
    - {name: MINIO_POLICY_NAME, value: $policy_name}
    - {name: MINIO_MANAGED_ACTION, value: $managed_action}
    - {name: MINIO_POLICY_SUBJECT, value: $policy_subject}
    - {name: MINIO_CA_PATH, value: /ca/ca.crt}
    volumeMounts: [{name: ca, mountPath: /ca, readOnly: true}]
  volumes:
  - name: ca
    secret: {secretName: minio-backup-store-ca, items: [{key: ca.crt, path: ca.crt}]}
EOF
  kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$MINIO_NAMESPACE" wait pod/"$TEMP_POD" --for=condition=Ready --timeout=120s >/dev/null
  kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$MINIO_NAMESPACE" exec -i "$TEMP_POD" -- sh -c \
    'umask 077; cat > /tmp/minio-admin-helper; chmod 0700 /tmp/minio-admin-helper' <"$HELPER"
  if [[ "$emit" == true ]]; then
    kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$MINIO_NAMESPACE" exec -i "$TEMP_POD" -- /tmp/minio-admin-helper <"$policy_file"
  else
    kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$MINIO_NAMESPACE" exec -i "$TEMP_POD" -- /tmp/minio-admin-helper <"$policy_file" >/dev/null
  fi
  kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$MINIO_NAMESPACE" delete pod "$TEMP_POD" --wait=true >/dev/null
  TEMP_POD=
}

if [[ "$ACTION" == ensure ]]; then
  run_admin_action "$WRITER_SECRET" "$DRILL_POLICY" ensure "$DRILL_POLICY_FILE" drill-writer false
  run_admin_action "$SOURCE_READER_SECRET" "$SOURCE_READER_POLICY" verify "$SOURCE_READER_POLICY_FILE" source-reader true
  echo 'PASS: per-run writer reconciled and source reader effective policy verified'
else
  run_admin_action "$WRITER_SECRET" "$DRILL_POLICY" delete /dev/null drill-writer false
  kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$DATABASE_NAMESPACE" delete secret "$WRITER_SECRET" --wait=true >/dev/null
  kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$MINIO_NAMESPACE" delete secret "$WRITER_SECRET" --wait=true >/dev/null
  echo 'PASS: per-run writer identity and Secrets removed'
fi
