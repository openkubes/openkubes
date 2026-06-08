#!/usr/bin/env bash
# crossplane-upgrade.sh
# MVP upgrade path for OpenKubes/CAPK.
#
# CAPK v0.11.x rolling upgrades can hang with "Waiting for a node with matching
# ProviderID to exist". For the MVP we therefore use a deterministic
# replace-upgrade: cleanly delete the workload cluster and recreate it with the
# same name, endpoint settings and target Kubernetes version.
#
# The old experimental rolling implementation is kept as
# crossplane-upgrade-rolling.sh and can be enabled explicitly with:
#   UPGRADE_STRATEGY=RollingUpdate OPENKUBES_ENABLE_EXPERIMENTAL_ROLLING=true
set -euo pipefail

SA_DIR="/var/run/secrets/kubernetes.io/serviceaccount"
KUBECONFIG_FILE="/tmp/in-cluster.kubeconfig"
WORKLOAD_KUBECONFIG="/tmp/workload-${CLUSTER_NAME:-cluster}.kubeconfig"
OPENKUBES_SYSTEM_NAMESPACE="${OPENKUBES_SYSTEM_NAMESPACE:-openkubes-system}"

log()  { echo "[upgrade-mvp] $*"; }
fail() { echo "[upgrade-mvp] ERROR: $*" >&2; exit 1; }

json_get() {
  local json_file="$1"
  local filter="$2"
  local fallback="${3:-}"
  jq -r "${filter} // \"${fallback}\"" "${json_file}" 2>/dev/null || echo "${fallback}"
}

require() {
  local name="$1"
  [ -n "${!name:-}" ] || fail "missing required value: ${name}"
}

build_incluster_kubeconfig() {
  kubectl config set-cluster in-cluster \
    --server="https://kubernetes.default.svc" \
    --certificate-authority="${SA_DIR}/ca.crt" \
    --kubeconfig="${KUBECONFIG_FILE}" >/dev/null
  kubectl config set-credentials in-cluster-sa \
    --token="$(cat "${SA_DIR}/token")" \
    --kubeconfig="${KUBECONFIG_FILE}" >/dev/null
  kubectl config set-context in-cluster \
    --cluster=in-cluster --user=in-cluster-sa \
    --kubeconfig="${KUBECONFIG_FILE}" >/dev/null
  kubectl config use-context in-cluster \
    --kubeconfig="${KUBECONFIG_FILE}" >/dev/null

  export KUBECONFIG="${KUBECONFIG_FILE}"
  export MGMT_KUBECONFIG="${KUBECONFIG_FILE}"
  export RUNNER_MODE=true
}

get_workload_kubeconfig() {
  clusterctl get kubeconfig "${CLUSTER_NAME}" -n "${CLUSTER_NAME}" \
    > "${WORKLOAD_KUBECONFIG}" 2>/dev/null
}

workload_is_on_target() {
  get_workload_kubeconfig || return 1

  local cp_ready workers_ready old_nodes desired
  desired="${WORKER_REPLICAS:-1}"

  cp_ready=$(KUBECONFIG="${WORKLOAD_KUBECONFIG}" kubectl get nodes -o json 2>/dev/null | \
    jq -r --arg v "${TARGET_VERSION}" \
    '[.items[]
      | select((.metadata.labels["node-role.kubernetes.io/control-plane"] // "") != "")
      | select(.status.nodeInfo.kubeletVersion == $v)
      | select(.status.conditions[] | select(.type=="Ready" and .status=="True"))
    ] | length' 2>/dev/null || echo 0)

  workers_ready=$(KUBECONFIG="${WORKLOAD_KUBECONFIG}" kubectl get nodes -o json 2>/dev/null | \
    jq -r --arg v "${TARGET_VERSION}" \
    '[.items[]
      | select((.metadata.labels["node-role.kubernetes.io/control-plane"] // "") == "")
      | select(.status.nodeInfo.kubeletVersion == $v)
      | select(.status.conditions[] | select(.type=="Ready" and .status=="True"))
    ] | length' 2>/dev/null || echo 0)

  old_nodes=$(KUBECONFIG="${WORKLOAD_KUBECONFIG}" kubectl get nodes -o json 2>/dev/null | \
    jq -r --arg v "${TARGET_VERSION}" \
    '[.items[] | select(.status.nodeInfo.kubeletVersion != $v)] | length' 2>/dev/null || echo 99)

  log "target verification: control-plane-ready=${cp_ready}, workers-ready=${workers_ready}/${desired}, old-nodes=${old_nodes}"
  [ "${cp_ready}" -ge 1 ] && [ "${workers_ready}" = "${desired}" ] && [ "${old_nodes}" = "0" ]
}

wait_for_target_nodes() {
  log "verifying recreated workload cluster nodes are Ready on ${TARGET_VERSION}"
  for i in $(seq 1 120); do
    if workload_is_on_target; then
      log "all workload nodes are Ready on ${TARGET_VERSION} ✅"
      return 0
    fi
    log "waiting for workload nodes on ${TARGET_VERSION} (${i}/120)"
    sleep 10
  done

  log "final management status:"
  kubectl -n "${CLUSTER_NAME}" get cluster,kubeadmcontrolplane,machinedeployment,machines || true
  if [ -f "${WORKLOAD_KUBECONFIG}" ]; then
    log "final workload nodes:"
    KUBECONFIG="${WORKLOAD_KUBECONFIG}" kubectl get nodes -o wide || true
  fi
  fail "recreated cluster did not become fully Ready on ${TARGET_VERSION}"
}

load_live_claim_values() {
  local claim_file="/tmp/openkubes-claim-${CLUSTER_NAME}.json"

  if kubectl get kubevirtclusterclaim "${CLUSTER_NAME}" \
    -n "${OPENKUBES_SYSTEM_NAMESPACE}" -o json > "${claim_file}" 2>/dev/null; then
    log "loaded live KubeVirtClusterClaim ${OPENKUBES_SYSTEM_NAMESPACE}/${CLUSTER_NAME}"
  else
    log "WARNING: live KubeVirtClusterClaim not found; using environment/default values"
    echo '{}' > "${claim_file}"
  fi

  COUNTRY="${COUNTRY:-$(json_get "${claim_file}" '.spec.country' 'de')}"
  PROVIDER="${PROVIDER:-$(json_get "${claim_file}" '.spec.provider' 'kubevirt')}"
  CNI_PLUGIN="${CNI_PLUGIN:-$(json_get "${claim_file}" '.spec.cni' 'calico')}"
  MULTUS_ENABLED="${MULTUS_ENABLED:-$(json_get "${claim_file}" '.spec.multus' 'false')}"
  CONTROL_PLANE_ENDPOINT_IP="${CONTROL_PLANE_ENDPOINT_IP:-$(json_get "${claim_file}" '.spec.endpointIP' '')}"
  CONTROL_PLANE_REPLICAS="${CONTROL_PLANE_REPLICAS:-$(json_get "${claim_file}" '.spec.controlPlane.replicas' '1')}"
  WORKER_REPLICAS="${WORKER_REPLICAS:-$(json_get "${claim_file}" '.spec.workers.replicas' '1')}"
  RUNNER_IMAGE="${RUNNER_IMAGE:-$(json_get "${claim_file}" '.spec.runnerImage' 'kubernautslabs/capi-platform-runner:v4.2')}"

  require COUNTRY
  require PROVIDER
  require CNI_PLUGIN
  require MULTUS_ENABLED
  require CONTROL_PLANE_ENDPOINT_IP
  require CONTROL_PLANE_REPLICAS
  require WORKER_REPLICAS
}

patch_live_claim_to_target() {
  if kubectl get kubevirtclusterclaim "${CLUSTER_NAME}" -n "${OPENKUBES_SYSTEM_NAMESPACE}" >/dev/null 2>&1; then
    log "patching live KubeVirtClusterClaim to ${TARGET_VERSION}"
    kubectl patch kubevirtclusterclaim "${CLUSTER_NAME}" \
      -n "${OPENKUBES_SYSTEM_NAMESPACE}" \
      --type merge \
      -p "{\"spec\":{\"controlPlane\":{\"kubernetesVersion\":\"${TARGET_VERSION}\"}}}"
  else
    log "live KubeVirtClusterClaim does not exist; skipping claim patch"
  fi
}

resume_claim() {
  log "resuming Crossplane reconciliation on claim '${CLUSTER_NAME}' (trap)..."
  kubectl annotate kubevirtclusterclaim "${CLUSTER_NAME}" \
    -n "${OPENKUBES_SYSTEM_NAMESPACE}" \
    crossplane.io/paused- \
    2>/dev/null || true
}

run_recreate_upgrade() {
  log "using MVP replace-upgrade strategy"
  log "cluster=${CLUSTER_NAME} target=${TARGET_VERSION} endpoint=${CONTROL_PLANE_ENDPOINT_IP} cni=${CNI_PLUGIN} multus=${MULTUS_ENABLED} cp=${CONTROL_PLANE_REPLICAS} workers=${WORKER_REPLICAS}"

  if workload_is_on_target; then
    log "cluster is already fully on ${TARGET_VERSION}; nothing to do ✅"
    exit 0
  fi

  patch_live_claim_to_target

  # ── Pause Crossplane reconciliation to prevent it from interfering ────────────
  # While we delete and recreate the CAPI cluster, Crossplane must not try to
  # reconcile the claim in parallel — it would fight us by re-creating resources.
  # trap resume_claim EXIT ensures the claim is always unpaused, even on failure.
  log "pausing Crossplane reconciliation on claim '${CLUSTER_NAME}'..."
  trap resume_claim EXIT
  kubectl annotate kubevirtclusterclaim "${CLUSTER_NAME}" \
    -n "${OPENKUBES_SYSTEM_NAMESPACE}" \
    crossplane.io/paused=true \
    --overwrite 2>/dev/null || true

  log "deleting current workload cluster resources"
  make cleanup-local \
    country="${COUNTRY}" \
    provider="${PROVIDER}" \
    cluster-name="${CLUSTER_NAME}" \
    namespace="${CLUSTER_NAME}" \
    outdir="rendered"

  log "recreating workload cluster on ${TARGET_VERSION}"
  VM_IMAGE_URL_OVERRIDE="quay.io/capk/ubuntu-2404-container-disk:${TARGET_VERSION}" \
  make deploy-full-local \
    country="${COUNTRY}" \
    provider="${PROVIDER}" \
    cluster-name="${CLUSTER_NAME}" \
    namespace="${CLUSTER_NAME}" \
    kubernetes-version="${TARGET_VERSION}" \
    control-plane-replicas="${CONTROL_PLANE_REPLICAS}" \
    worker-replicas="${WORKER_REPLICAS}" \
    cni="${CNI_PLUGIN}" \
    multus="${MULTUS_ENABLED}" \
    endpoint-ip="${CONTROL_PLANE_ENDPOINT_IP}" \
    outdir="rendered"

  wait_for_target_nodes

  # resume_claim() is called automatically via trap EXIT

  log "cluster '${CLUSTER_NAME}' successfully replace-upgraded to ${TARGET_VERSION} 🎉"
}

main() {
  require CLUSTER_NAME
  TARGET_VERSION="${TARGET_KUBERNETES_VERSION:-${KUBERNETES_VERSION:-}}"
  [ -n "${TARGET_VERSION}" ] || fail "no target version set; set TARGET_KUBERNETES_VERSION or KUBERNETES_VERSION"
  UPGRADE_STRATEGY="${UPGRADE_STRATEGY:-Recreate}"

  build_incluster_kubeconfig
  load_live_claim_values

  if [ "${UPGRADE_STRATEGY}" = "RollingUpdate" ] && [ "${OPENKUBES_ENABLE_EXPERIMENTAL_ROLLING:-false}" = "true" ]; then
    log "using experimental CAPK rolling upgrade path"
    export TARGET_KUBERNETES_VERSION="${TARGET_VERSION}"
    exec /bin/bash /workspace/scripts/crossplane-upgrade-rolling.sh
  fi

  run_recreate_upgrade
}

main "$@"
