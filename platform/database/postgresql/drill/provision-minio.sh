#!/usr/bin/env bash
set -Eeuo pipefail

readonly EXPECTED_CLUSTER=ok-robotics
readonly NAMESPACE=minio
readonly DATABASE_NAMESPACE=database-ok-robotics
readonly OWNER_LABEL='platform.openkubes.ai/managed-by=ok-145-minio-provisioner'
readonly ENDPOINT='https://minio.minio.svc:9000'
readonly MC_IMAGE='quay.io/minio/mc:RELEASE.2025-08-13T08-35-41Z@sha256:eb4ea9884b77704230e2423e9004d2fa738dc272876b9cc41a297d29443b8780'
readonly GO_IMAGE='golang@sha256:b6ed3fd0452c0e9bcdef5597f29cc1418f61672e9d3a2f55bf02e7222c014abd'
readonly ROOT_SECRET=minio-root-credentials
readonly READER_SECRET=ok-db-backups-ok-robotics-reader
readonly PRODUCER_SECRET=ok-db-backups-ok-robotics-writer
readonly READER_POLICY=ok-db-backups-reader
readonly DRILL_POLICY=ok-db-drill-writer
readonly PRODUCER_POLICY=ok-db-backups-ok-robotics-writer

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
KUBECONFIG_PATH=
EXECUTE=false
WORK_DIR=
TEMP_POD=

usage() {
  cat <<'EOF'
Usage: provision-minio.sh --kubeconfig PATH --execute

Provisions the fixed OK-145 MinIO backup store on ok-robotics. Credential
values are generated or read by Kubernetes Secret refs and travel only via
environment variables or stdin.
EOF
}

while (($#)); do
  case "$1" in
    --kubeconfig) KUBECONFIG_PATH="${2:?missing value}"; shift 2 ;;
    --execute) EXECUTE=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'ERROR: unknown argument %q\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ "$EXECUTE" == true ]] || { echo 'ERROR: execution requires --execute' >&2; exit 2; }
[[ -n "$KUBECONFIG_PATH" && -r "$KUBECONFIG_PATH" ]] \
  || { echo 'ERROR: --kubeconfig must name a readable file' >&2; exit 2; }
for command in kubectl docker openssl; do
  command -v "$command" >/dev/null || { printf "ERROR: required command '%s' not found\n" "$command" >&2; exit 1; }
done

cleanup() {
  local rc=$?
  trap - EXIT ERR
  set +e
  if [[ -n "$TEMP_POD" ]]; then
    kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$NAMESPACE" delete pod "$TEMP_POD" \
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
  || { printf "ERROR: kubeconfig identifies context '%s' / cluster '%s', not %s\n" "$context" "$cluster" "$EXPECTED_CLUSTER" >&2; exit 2; }
kubectl --kubeconfig "$KUBECONFIG_PATH" get crd certificates.cert-manager.io issuers.cert-manager.io >/dev/null

assert_owned_or_absent() {
  local kind="$1" name="$2" namespace_args=()
  [[ "$3" == cluster ]] || namespace_args=(-n "$3")
  local found label
  found="$(kubectl --kubeconfig "$KUBECONFIG_PATH" "${namespace_args[@]}" get "$kind" "$name" --ignore-not-found -o name)"
  [[ -n "$found" ]] || return 0
  label="$(kubectl --kubeconfig "$KUBECONFIG_PATH" "${namespace_args[@]}" get "$kind" "$name" -o jsonpath='{.metadata.labels.platform\.openkubes\.ai/managed-by}')"
  [[ "$label" == ok-145-minio-provisioner ]] \
    || { printf "ERROR: existing %s/%s is not owned by this provisioner\n" "$kind" "$name" >&2; exit 1; }
}

assert_owned_or_absent namespace "$NAMESPACE" cluster
assert_owned_or_absent namespace "$DATABASE_NAMESPACE" cluster
for target in issuer/minio-bootstrap-selfsigned certificate/minio-backup-store-ca issuer/minio-backup-store-ca certificate/minio-server service/minio persistentvolumeclaim/minio-data deployment/minio; do
  assert_owned_or_absent "${target%/*}" "${target#*/}" "$NAMESPACE"
done
for secret in "$ROOT_SECRET" "$READER_SECRET" "$PRODUCER_SECRET"; do
  assert_owned_or_absent secret "$secret" "$NAMESPACE"
done
for secret in "$READER_SECRET" "$PRODUCER_SECRET" minio-backup-store-ca; do
  assert_owned_or_absent secret "$secret" "$DATABASE_NAMESPACE"
done

if ! kubectl --kubeconfig "$KUBECONFIG_PATH" get namespace "$NAMESPACE" >/dev/null 2>&1; then
  kubectl --kubeconfig "$KUBECONFIG_PATH" create namespace "$NAMESPACE" >/dev/null
  kubectl --kubeconfig "$KUBECONFIG_PATH" label namespace "$NAMESPACE" "$OWNER_LABEL" >/dev/null
fi
if ! kubectl --kubeconfig "$KUBECONFIG_PATH" get namespace "$DATABASE_NAMESPACE" >/dev/null 2>&1; then
  kubectl --kubeconfig "$KUBECONFIG_PATH" create namespace "$DATABASE_NAMESPACE" >/dev/null
  kubectl --kubeconfig "$KUBECONFIG_PATH" label namespace "$DATABASE_NAMESPACE" "$OWNER_LABEL" >/dev/null
fi

create_secret_if_absent() {
  local name="$1" access_key="$2" access_secret
  if kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$NAMESPACE" get secret "$name" >/dev/null 2>&1; then
    return 0
  fi
  access_secret="$(openssl rand -hex 32)"
  printf 'ACCESS_KEY_ID=%s\nACCESS_SECRET_KEY=%s\n' "$access_key" "$access_secret" \
    | kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$NAMESPACE" create secret generic "$name" \
        --from-env-file=/dev/stdin >/dev/null
  kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$NAMESPACE" label secret "$name" "$OWNER_LABEL" >/dev/null
  unset access_secret
}

if ! kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$NAMESPACE" get secret "$ROOT_SECRET" >/dev/null 2>&1; then
  root_user="$(openssl rand -hex 16)"
  root_password="$(openssl rand -hex 32)"
  printf 'MINIO_ROOT_USER=%s\nMINIO_ROOT_PASSWORD=%s\n' "$root_user" "$root_password" \
    | kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$NAMESPACE" create secret generic "$ROOT_SECRET" \
        --from-env-file=/dev/stdin >/dev/null
  kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$NAMESPACE" label secret "$ROOT_SECRET" "$OWNER_LABEL" >/dev/null
  unset root_user root_password
fi
create_secret_if_absent "$READER_SECRET" "$EXPECTED_CLUSTER"
create_secret_if_absent "$PRODUCER_SECRET" "${EXPECTED_CLUSTER}-producer"

kubectl --kubeconfig "$KUBECONFIG_PATH" apply -f "$SCRIPT_DIR/minio.yaml" >/dev/null
kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$NAMESPACE" wait certificate/minio-backup-store-ca certificate/minio-server \
  --for=condition=Ready --timeout=180s >/dev/null
kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$NAMESPACE" rollout status deployment/minio --timeout=180s >/dev/null
ca_key="$(kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$NAMESPACE" get secret minio-backup-store-ca -o jsonpath='{.data.ca\.crt}')"
[[ -n "$ca_key" ]] || { echo 'ERROR: minio-backup-store-ca lacks required ca.crt' >&2; exit 1; }
unset ca_key

mirror_credentials_secret() {
  local name="$1"
  kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$NAMESPACE" get secret "$name" \
    -o go-template='ACCESS_KEY_ID={{index .data "ACCESS_KEY_ID" | base64decode}}{{"\n"}}ACCESS_SECRET_KEY={{index .data "ACCESS_SECRET_KEY" | base64decode}}{{"\n"}}' \
    | kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$DATABASE_NAMESPACE" create secret generic "$name" \
        --from-env-file=/dev/stdin --dry-run=client -o yaml \
    | kubectl --kubeconfig "$KUBECONFIG_PATH" apply -f - >/dev/null
  kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$DATABASE_NAMESPACE" label secret "$name" "$OWNER_LABEL" --overwrite >/dev/null
}
mirror_credentials_secret "$READER_SECRET"
mirror_credentials_secret "$PRODUCER_SECRET"
kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$NAMESPACE" get secret minio-backup-store-ca \
  -o go-template='{{index .data "ca.crt" | base64decode}}' \
  | kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$DATABASE_NAMESPACE" create secret generic minio-backup-store-ca \
      --from-file=ca.crt=/dev/stdin --dry-run=client -o yaml \
  | kubectl --kubeconfig "$KUBECONFIG_PATH" apply -f - >/dev/null
kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$DATABASE_NAMESPACE" label secret minio-backup-store-ca "$OWNER_LABEL" --overwrite >/dev/null

WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/ok-145-minio.XXXXXX")"
[[ -d "$WORK_DIR" ]] || { echo 'ERROR: failed to create work directory' >&2; exit 1; }
HELPER="$WORK_DIR/minio-admin-helper"
[[ ! -e "$HELPER" ]] || { echo 'ERROR: refusing to overwrite helper path' >&2; exit 1; }
GO_CACHE_ROOT="${TMPDIR:-/tmp}/openkubes-ok145-go-cache"
mkdir -p "$GO_CACHE_ROOT/build" "$GO_CACHE_ROOT/mod"
docker run --rm --user "$(id -u):$(id -g)" -e CGO_ENABLED=0 -e GOCACHE=/cache/build -e GOMODCACHE=/cache/mod \
  -v "$GO_CACHE_ROOT:/cache" \
  -v "$SCRIPT_DIR/minio-admin-helper:/src:ro" -v "$WORK_DIR:/out" -w /src "$GO_IMAGE" \
  go build -trimpath -ldflags=-buildid= -o /out/minio-admin-helper .

create_admin_pod() {
  local name="$1" user_secret="${2:-}" policy_name="${3:-}" policy_subject="${4:-bootstrap}"
  existing="$(kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$NAMESPACE" get pod "$name" --ignore-not-found -o name)"
  [[ -z "$existing" ]] || { printf "ERROR: temporary pod %s already exists\n" "$name" >&2; exit 1; }
  TEMP_POD="$name"
  if [[ -n "$user_secret" ]]; then
    managed_env="
        - name: MINIO_MANAGED_USER
          valueFrom: {secretKeyRef: {name: $user_secret, key: ACCESS_KEY_ID}}
        - name: MINIO_MANAGED_SECRET
          valueFrom: {secretKeyRef: {name: $user_secret, key: ACCESS_SECRET_KEY}}
        - name: MINIO_POLICY_NAME
          value: $policy_name
        - name: MINIO_POLICY_SUBJECT
          value: $policy_subject"
  else
    managed_env=''
  fi
  kubectl --kubeconfig "$KUBECONFIG_PATH" apply -f - >/dev/null <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: $name
  namespace: $NAMESPACE
  labels:
    platform.openkubes.ai/managed-by: ok-145-minio-provisioner
spec:
  restartPolicy: Never
  automountServiceAccountToken: false
  securityContext:
    seccompProfile:
      type: RuntimeDefault
  containers:
    - name: admin
      image: $MC_IMAGE
      command: [sh, -c, 'sleep 600']
      securityContext:
        allowPrivilegeEscalation: false
        capabilities:
          drop: [ALL]
        runAsNonRoot: true
        runAsUser: 1000
        runAsGroup: 1000
      env:
        - name: MINIO_ENDPOINT
          value: $ENDPOINT
        - name: MINIO_ROOT_USER
          valueFrom: {secretKeyRef: {name: $ROOT_SECRET, key: MINIO_ROOT_USER}}
        - name: MINIO_ROOT_PASSWORD
          valueFrom: {secretKeyRef: {name: $ROOT_SECRET, key: MINIO_ROOT_PASSWORD}}
        - name: MINIO_CA_PATH
          value: /var/run/minio-ca/ca.crt
        - name: MC_CONFIG_DIR
          value: /tmp/mc-config$managed_env
      volumeMounts:
        - name: ca
          mountPath: /var/run/minio-ca
          readOnly: true
  volumes:
    - name: ca
      secret:
        secretName: minio-backup-store-ca
        items: [{key: ca.crt, path: ca.crt}]
EOF
  kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$NAMESPACE" wait pod/"$name" --for=condition=Ready --timeout=120s >/dev/null
}

create_admin_pod ok-145-minio-policy-admin
kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$NAMESPACE" exec "$TEMP_POD" -- sh -c \
  'export SSL_CERT_FILE="$MINIO_CA_PATH" MC_HOST_ok145="https://${MINIO_ROOT_USER}:${MINIO_ROOT_PASSWORD}@minio.minio.svc:9000"; mc mb --ignore-existing ok145/ok-db-backups ok145/ok-db-drill'
for policy_spec in \
  "$READER_POLICY:$SCRIPT_DIR/minio-policy-backups-readonly.json" \
  "$DRILL_POLICY:$SCRIPT_DIR/minio-policy-drill-write.json" \
  "$PRODUCER_POLICY:$SCRIPT_DIR/minio-policy-backups-ok-robotics-writer.json"; do
  policy_name="${policy_spec%%:*}"
  policy_file="${policy_spec#*:}"
  kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$NAMESPACE" exec -i "$TEMP_POD" -- sh -c \
    "export SSL_CERT_FILE=\"\$MINIO_CA_PATH\" MC_HOST_ok145=\"https://\${MINIO_ROOT_USER}:\${MINIO_ROOT_PASSWORD}@minio.minio.svc:9000\"; mc admin policy create ok145 '$policy_name' /dev/stdin" \
    <"$policy_file"
done
kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$NAMESPACE" delete pod "$TEMP_POD" --wait=true >/dev/null
TEMP_POD=

for user_spec in \
  "$READER_SECRET:$READER_POLICY:$SCRIPT_DIR/minio-policy-backups-readonly.json:source-reader" \
  "$PRODUCER_SECRET:$PRODUCER_POLICY:$SCRIPT_DIR/minio-policy-backups-ok-robotics-writer.json:source-writer"; do
  IFS=: read -r user_secret policy_name policy_file policy_subject <<<"$user_spec"
  create_admin_pod "ok-145-${user_secret}-admin" "$user_secret" "$policy_name" "$policy_subject"
  kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$NAMESPACE" exec -i "$TEMP_POD" -- sh -c \
    'umask 077; test ! -e /tmp/minio-admin-helper; cat > /tmp/minio-admin-helper; chmod 0700 /tmp/minio-admin-helper' <"$HELPER"
  kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$NAMESPACE" exec -i "$TEMP_POD" -- /tmp/minio-admin-helper <"$policy_file"
  kubectl --kubeconfig "$KUBECONFIG_PATH" -n "$NAMESPACE" delete pod "$TEMP_POD" --wait=true >/dev/null
  TEMP_POD=
done

printf 'PASS: TLS MinIO, buckets, policies, reader Secret, and producer Secret reconciled on %s\n' "$EXPECTED_CLUSTER"
