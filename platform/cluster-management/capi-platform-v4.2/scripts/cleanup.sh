#!/usr/bin/env bash
set -euo pipefail

log() {
  echo "[cleanup] $*"
}

fail() {
  echo "[cleanup] ERROR: $*" >&2
  exit 1
}

require_env() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    fail "missing required environment variable: ${name}"
  fi
}

delete_if_exists() {
  local kind="$1"
  local name="$2"
  local namespace="$3"

  if KUBECONFIG="${MGMT_KUBECONFIG}" kubectl -n "${namespace}" get "${kind}" "${name}" >/dev/null 2>&1; then
    log "deleting ${kind}/${name} in namespace ${namespace}"
    KUBECONFIG="${MGMT_KUBECONFIG}" kubectl -n "${namespace}" delete "${kind}" "${name}" --ignore-not-found
  else
    log "${kind}/${name} not found in namespace ${namespace}, skipping"
  fi
}

wait_cluster_deleted() {
  local retries="${1:-90}"
  local sleep_seconds="${2:-10}"
  local i

  for ((i=1; i<=retries; i++)); do
    if ! KUBECONFIG="${MGMT_KUBECONFIG}" kubectl -n "${NAMESPACE}" get cluster "${CLUSTER_NAME}" >/dev/null 2>&1; then
      log "cluster/${CLUSTER_NAME} is gone"
      return 0
    fi
    log "cluster/${CLUSTER_NAME} still exists (${i}/${retries}), retrying in ${sleep_seconds}s"
    sleep "${sleep_seconds}"
  done

  fail "cluster/${CLUSTER_NAME} still exists after waiting"
}

delete_infra_namespace() {
  local base_secret="${INFRA_CLUSTER_SECRET_BASE_NAME:-external-infra-kubeconfig}"
  local base_ns="${INFRA_CLUSTER_SECRET_BASE_NAMESPACE:-capk-system}"

  log "deleting namespace ${NAMESPACE} from infra cluster"

  if ! KUBECONFIG="${MGMT_KUBECONFIG}" kubectl get secret "${base_secret}" \
    -n "${base_ns}" >/dev/null 2>&1; then
    log "WARNING: base infra secret ${base_secret} not found in ${base_ns}, skipping infra namespace cleanup"
    return 0
  fi

  local tmp_infra_kc
  tmp_infra_kc="$(mktemp /tmp/infra-kubeconfig-XXXXXX.yaml)"

  KUBECONFIG="${MGMT_KUBECONFIG}" kubectl get secret "${base_secret}" \
    -n "${base_ns}" \
    -o jsonpath='{.data.kubeconfig}' | base64 -d > "${tmp_infra_kc}"

  if [ ! -s "${tmp_infra_kc}" ]; then
    log "WARNING: infra kubeconfig is empty, skipping infra namespace cleanup"
    rm -f "${tmp_infra_kc}"
    return 0
  fi

  if KUBECONFIG="${tmp_infra_kc}" kubectl get namespace "${NAMESPACE}" >/dev/null 2>&1; then
    KUBECONFIG="${tmp_infra_kc}" kubectl delete namespace "${NAMESPACE}" --ignore-not-found
    log "infra namespace ${NAMESPACE} deleted"
  else
    log "infra namespace ${NAMESPACE} not found on infra cluster, skipping"
  fi

  rm -f "${tmp_infra_kc}"
}

main() {
  log "starting"

  require_env CLUSTER_NAME
  require_env NAMESPACE

  export MGMT_KUBECONFIG="${MGMT_KUBECONFIG:-${KUBECONFIG:-}}"
  export WORKLOAD_KUBECONFIG="${WORKLOAD_KUBECONFIG:-rendered/${CLUSTER_NAME}.kubeconfig}"
  export CLEAN_RENDERED="${CLEAN_RENDERED:-true}"
  export INFRA_CLUSTER_SECRET_BASE_NAME="${INFRA_CLUSTER_SECRET_BASE_NAME:-external-infra-kubeconfig}"
  export INFRA_CLUSTER_SECRET_NAME="${INFRA_CLUSTER_SECRET_BASE_NAME}-${CLUSTER_NAME}"

  [[ -n "${MGMT_KUBECONFIG}" ]] || fail "MGMT_KUBECONFIG is empty and KUBECONFIG is not set"

  if [[ -x "./scripts/check-deps.sh" ]]; then
    ./scripts/check-deps.sh
  fi

  log "CLUSTER_NAME=${CLUSTER_NAME}"
  log "NAMESPACE=${NAMESPACE}"
  log "MGMT_KUBECONFIG=${MGMT_KUBECONFIG}"
  log "WORKLOAD_KUBECONFIG=${WORKLOAD_KUBECONFIG}"
  log "CLEAN_RENDERED=${CLEAN_RENDERED}"
  log "INFRA_CLUSTER_SECRET_NAME=${INFRA_CLUSTER_SECRET_NAME}"

  log "management cluster objects before cleanup"
  KUBECONFIG="${MGMT_KUBECONFIG}" kubectl -n "${NAMESPACE}" get cluster || true
  KUBECONFIG="${MGMT_KUBECONFIG}" kubectl -n "${NAMESPACE}" get kubeadmcontrolplane || true
  KUBECONFIG="${MGMT_KUBECONFIG}" kubectl -n "${NAMESPACE}" get machinedeployment || true
  KUBECONFIG="${MGMT_KUBECONFIG}" kubectl -n "${NAMESPACE}" get kubevirtcluster || true
  KUBECONFIG="${MGMT_KUBECONFIG}" kubectl -n "${NAMESPACE}" get kubevirtmachinetemplate || true
  KUBECONFIG="${MGMT_KUBECONFIG}" kubectl -n "${NAMESPACE}" get kubeadmconfigtemplate || true

  if command -v make >/dev/null 2>&1 && grep -q "^delete-cluster:" Makefile 2>/dev/null; then
    log "using make delete-cluster"
    KUBECONFIG="${MGMT_KUBECONFIG}" make delete-cluster country="${COUNTRY:-de}" provider="${PROVIDER:-kubevirt}" cluster-name="${CLUSTER_NAME}" || true
  else
    log "falling back to direct kubectl deletion"
    delete_if_exists cluster "${CLUSTER_NAME}" "${NAMESPACE}"
  fi

  log "waiting for cluster deletion"
  wait_cluster_deleted 90 10

  log "best-effort cleanup of remaining related objects"
  delete_if_exists kubeadmcontrolplane "${CLUSTER_NAME}-control-plane" "${NAMESPACE}"
  delete_if_exists machinedeployment "${CLUSTER_NAME}-md-0" "${NAMESPACE}"
  delete_if_exists kubevirtcluster "${CLUSTER_NAME}" "${NAMESPACE}"
  delete_if_exists kubevirtmachinetemplate "${CLUSTER_NAME}-control-plane" "${NAMESPACE}"
  delete_if_exists kubevirtmachinetemplate "${CLUSTER_NAME}-md-0" "${NAMESPACE}"
  delete_if_exists kubeadmconfigtemplate "${CLUSTER_NAME}-md-0" "${NAMESPACE}"

  log "deleting per-cluster infra secret ${INFRA_CLUSTER_SECRET_NAME} from namespace ${NAMESPACE}"
  delete_if_exists secret "${INFRA_CLUSTER_SECRET_NAME}" "${NAMESPACE}"

  log "deleting namespace ${NAMESPACE} from management cluster"
  if KUBECONFIG="${MGMT_KUBECONFIG}" kubectl get namespace "${NAMESPACE}" >/dev/null 2>&1; then
    KUBECONFIG="${MGMT_KUBECONFIG}" kubectl delete namespace "${NAMESPACE}" --ignore-not-found
    log "namespace ${NAMESPACE} deleted"
  else
    log "namespace ${NAMESPACE} not found, skipping"
  fi

  delete_infra_namespace

  if [[ "${CLEAN_RENDERED}" == "true" ]]; then
    log "removing rendered artifacts"
    rm -f "rendered/${CLUSTER_NAME}.yaml" || true
    rm -f "${WORKLOAD_KUBECONFIG}" || true
  else
    log "keeping rendered artifacts"
  fi

  log "done"
}

main "$@"
