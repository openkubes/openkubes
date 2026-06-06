#!/usr/bin/env bash
set -euo pipefail

log() {
  echo "[deploy-full] $*"
}

fail() {
  echo "[deploy-full] ERROR: $*" >&2
  exit 1
}

require_env() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    fail "missing required environment variable: ${name}"
  fi
}

require_file_with_objects() {
  local file="$1"
  [[ -f "${file}" ]] || fail "manifest file not found: ${file}"
  if ! grep -Eq '^[[:space:]]*apiVersion:' "${file}"; then
    fail "manifest file appears empty or contains no Kubernetes objects: ${file}"
  fi
}

wait_for_workload_kubeconfig() {
  local retries="${1:-90}"
  local sleep_seconds="${2:-10}"
  local i

  rm -f "${WORKLOAD_KUBECONFIG}"

  for ((i=1; i<=retries; i++)); do
    if KUBECONFIG="${MGMT_KUBECONFIG}" clusterctl get kubeconfig "${CLUSTER_NAME}" -n "${NAMESPACE}" > "${WORKLOAD_KUBECONFIG}" 2>/dev/null; then
      if [[ -s "${WORKLOAD_KUBECONFIG}" ]]; then
        log "wrote workload kubeconfig: ${WORKLOAD_KUBECONFIG}"
        return 0
      fi
    fi
    log "workload kubeconfig not ready yet (${i}/${retries}), retrying in ${sleep_seconds}s"
    sleep "${sleep_seconds}"
  done

  fail "unable to obtain workload kubeconfig for cluster ${CLUSTER_NAME} from management cluster"
}

wait_for_workload_apiserver() {
  local retries="${1:-60}"
  local sleep_seconds="${2:-10}"
  local i

  log "waiting for workload API server to become reachable"

  for ((i=1; i<=retries; i++)); do
    if KUBECONFIG="${WORKLOAD_KUBECONFIG}" kubectl get --raw=/readyz >/dev/null 2>&1; then
      log "workload API server is reachable"
      return 0
    fi
    log "workload API server not reachable yet (${i}/${retries}), retrying in ${sleep_seconds}s"
    sleep "${sleep_seconds}"
  done

  fail "workload API server did not become reachable in time"
}

install_cni() {
  case "${CNI_PLUGIN}" in
    calico)
      require_file_with_objects "addons/calico/calico.yaml"
      log "installing Calico into workload cluster ${CLUSTER_NAME}"
      KUBECONFIG="${WORKLOAD_KUBECONFIG}" kubectl apply --validate=false -f addons/calico/calico.yaml
      ;;
    cilium)
      require_file_with_objects "addons/cilium/cilium.yaml"
      log "installing Cilium into workload cluster ${CLUSTER_NAME}"
      KUBECONFIG="${WORKLOAD_KUBECONFIG}" kubectl apply --validate=false -f addons/cilium/cilium.yaml
      ;;
    none|"")
      log "skipping CNI installation because CNI_PLUGIN=${CNI_PLUGIN:-<empty>}"
      ;;
    *)
      fail "unsupported CNI_PLUGIN=${CNI_PLUGIN}"
      ;;
  esac
}

install_multus_if_enabled() {
  if [[ "${MULTUS_ENABLED}" == "true" ]]; then
    require_file_with_objects "addons/multus/multus.yaml"
    log "installing Multus into workload cluster ${CLUSTER_NAME}"
    KUBECONFIG="${WORKLOAD_KUBECONFIG}" kubectl apply --validate=false -f addons/multus/multus.yaml
  else
    log "MULTUS_ENABLED=${MULTUS_ENABLED}, skipping Multus"
  fi
}

# Creates a per-cluster infra secret with namespace=KUBEVIRT_VM_NAMESPACE.
# CAPK uses the "namespace" key in the secret to determine where to create
# the LoadBalancer service on the infra cluster. Without this, all clusters
# share capi-workload and their LB services collide.
prepare_infra_secret() {
  local base_secret="${INFRA_CLUSTER_SECRET_BASE_NAME}"
  local base_ns="${INFRA_CLUSTER_SECRET_BASE_NAMESPACE:-capk-system}"
  local cluster_secret="${INFRA_CLUSTER_SECRET_NAME}"   # = base_secret-<clustername>
  local mgmt_ns="${NAMESPACE}"
  local infra_ns="${KUBEVIRT_VM_NAMESPACE}"
  local tmp_kubeconfig

  tmp_kubeconfig="$(mktemp /tmp/infra-kubeconfig-XXXXXX.yaml)"
  trap 'rm -f "${tmp_kubeconfig:-}"' RETURN

  # --- 1. verify base secret exists ---
  if ! KUBECONFIG="${MGMT_KUBECONFIG}" kubectl get secret "${base_secret}" -n "${base_ns}" >/dev/null 2>&1; then
    fail "base infra secret ${base_secret} not found in namespace ${base_ns}"
  fi

  # --- 2. extract infra kubeconfig and create namespace on infra cluster ---
  log "extracting infra cluster kubeconfig from secret ${base_secret} in ${base_ns}"
  KUBECONFIG="${MGMT_KUBECONFIG}" kubectl get secret "${base_secret}" \
    -n "${base_ns}" \
    -o jsonpath='{.data.kubeconfig}' \
    | base64 -d > "${tmp_kubeconfig}"

  if [[ ! -s "${tmp_kubeconfig}" ]]; then
    fail "infra kubeconfig extracted from secret is empty"
  fi

  log "ensuring namespace ${infra_ns} exists on infra cluster"
  KUBECONFIG="${tmp_kubeconfig}" kubectl create namespace "${infra_ns}" \
    --dry-run=client -o yaml \
    | KUBECONFIG="${tmp_kubeconfig}" kubectl apply -f -

  # --- 3. create per-cluster secret with namespace=infra_ns on mgmt cluster ---
  log "creating per-cluster infra secret ${cluster_secret} in ${mgmt_ns} (infra namespace: ${infra_ns})"

  KUBECONFIG="${MGMT_KUBECONFIG}" kubectl get secret "${base_secret}" \
    -n "${base_ns}" -o json \
    | jq \
        --arg name   "${cluster_secret}" \
        --arg ns     "${mgmt_ns}" \
        --arg infrans "$(echo -n "${infra_ns}" | base64)" \
        'del(.metadata.resourceVersion, .metadata.uid, .metadata.creationTimestamp, .metadata.ownerReferences)
         | .metadata.name      = $name
         | .metadata.namespace = $ns
         | .data.namespace     = $infrans' \
    | KUBECONFIG="${MGMT_KUBECONFIG}" kubectl apply -f -

  log "per-cluster infra secret ${cluster_secret} is ready in namespace ${mgmt_ns}"
}

wait_for_nodes_ready() {
  log "waiting for workload cluster nodes to become Ready"
  KUBECONFIG="${WORKLOAD_KUBECONFIG}" kubectl wait --for=condition=Ready nodes --all --timeout=20m
}

show_debug_info() {
  log "management cluster view:"
  KUBECONFIG="${MGMT_KUBECONFIG}" kubectl -n "${NAMESPACE}" get cluster "${CLUSTER_NAME}" || true
  KUBECONFIG="${MGMT_KUBECONFIG}" kubectl -n "${NAMESPACE}" get kubeadmcontrolplane || true
  KUBECONFIG="${MGMT_KUBECONFIG}" kubectl -n "${NAMESPACE}" get machinedeployment || true

  log "workload cluster view:"
  KUBECONFIG="${WORKLOAD_KUBECONFIG}" kubectl get nodes -o wide || true
  KUBECONFIG="${WORKLOAD_KUBECONFIG}" kubectl get pods -A || true
}

main() {
  log "starting"

  require_env CLUSTER_NAME
  require_env NAMESPACE
  require_env KUBERNETES_VERSION
  require_env POD_CIDR
  require_env SERVICE_CIDR
  require_env DNS_DOMAIN_SUFFIX
  require_env INFRA_CLUSTER_SECRET_BASE_NAME
  require_env INFRA_CLUSTER_SECRET_NAME
  require_env INFRA_CLUSTER_SECRET_NAMESPACE
  require_env CONTROL_PLANE_SERVICE_TYPE
  require_env CONTROL_PLANE_ENDPOINT_IP
  require_env CONTROL_PLANE_ENDPOINT_PORT
  require_env KUBEVIRT_VM_NAMESPACE
  require_env VM_IMAGE_URL
  require_env CONTROL_PLANE_CPU_CORES
  require_env CONTROL_PLANE_MEMORY
  require_env WORKER_CPU_CORES
  require_env WORKER_MEMORY
  require_env CONTROL_PLANE_REPLICAS
  require_env WORKER_REPLICAS

  export CNI_PLUGIN="${CNI_PLUGIN:-calico}"
  export MULTUS_ENABLED="${MULTUS_ENABLED:-false}"

  export MGMT_KUBECONFIG="${MGMT_KUBECONFIG:-${KUBECONFIG:-}}"
  export WORKLOAD_KUBECONFIG="${WORKLOAD_KUBECONFIG:-rendered/${CLUSTER_NAME}.kubeconfig}"

  [[ -n "${MGMT_KUBECONFIG}" ]] || fail "MGMT_KUBECONFIG is empty and KUBECONFIG is not set"
  mkdir -p "$(dirname "${WORKLOAD_KUBECONFIG}")"

  if [[ -x "./scripts/validate-env.sh" ]]; then
    ./scripts/validate-env.sh
  fi

  if [[ -x "./scripts/check-deps.sh" ]]; then
    ./scripts/check-deps.sh
  fi

  log "CLUSTER_NAME=${CLUSTER_NAME}"
  log "NAMESPACE=${NAMESPACE}"
  log "KUBERNETES_VERSION=${KUBERNETES_VERSION}"
  log "CNI_PLUGIN=${CNI_PLUGIN}"
  log "MULTUS_ENABLED=${MULTUS_ENABLED}"
  log "MGMT_KUBECONFIG=${MGMT_KUBECONFIG}"
  log "WORKLOAD_KUBECONFIG=${WORKLOAD_KUBECONFIG}"
  log "INFRA_CLUSTER_SECRET_NAME=${INFRA_CLUSTER_SECRET_NAME}"
  log "KUBEVIRT_VM_NAMESPACE=${KUBEVIRT_VM_NAMESPACE}"

  log "ensuring namespace ${NAMESPACE} exists on management cluster"
  KUBECONFIG="${MGMT_KUBECONFIG}" kubectl create namespace "${NAMESPACE}" \
    --dry-run=client -o yaml \
    | KUBECONFIG="${MGMT_KUBECONFIG}" kubectl apply -f -

  # Creates infra namespace + per-cluster secret with correct namespace key
  prepare_infra_secret

  log "rendering cluster manifests"
  ./scripts/render.sh "rendered/${CLUSTER_NAME}.yaml"

  [[ -f "rendered/${CLUSTER_NAME}.yaml" ]] || fail "rendered manifest not found: rendered/${CLUSTER_NAME}.yaml"

  log "applying rendered cluster manifests to management cluster"
  KUBECONFIG="${MGMT_KUBECONFIG}" kubectl apply -f "rendered/${CLUSTER_NAME}.yaml"

  log "waiting until workload kubeconfig can be retrieved from management cluster"
  wait_for_workload_kubeconfig 90 10

  wait_for_workload_apiserver 60 10

  install_cni
  install_multus_if_enabled

  wait_for_nodes_ready

  log "final management cluster status"
  KUBECONFIG="${MGMT_KUBECONFIG}" kubectl -n "${NAMESPACE}" get cluster "${CLUSTER_NAME}" -o wide || true
  KUBECONFIG="${MGMT_KUBECONFIG}" kubectl -n "${NAMESPACE}" get kubeadmcontrolplane || true
  KUBECONFIG="${MGMT_KUBECONFIG}" kubectl -n "${NAMESPACE}" get machinedeployment || true

  show_debug_info

  log "done"
}

main "$@"
