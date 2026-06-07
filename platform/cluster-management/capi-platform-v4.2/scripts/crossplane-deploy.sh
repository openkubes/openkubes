#!/usr/bin/env bash
# crossplane-deploy.sh
# Called by the Crossplane deploy Job.
# All parameters come from environment variables (ConfigMap).
# If the cluster already exists and the version differs → delegates to crossplane-upgrade.sh.
set -euo pipefail

SA_DIR="/var/run/secrets/kubernetes.io/serviceaccount"
KUBECONFIG_FILE="/tmp/in-cluster.kubeconfig"

log()  { echo "[deploy] $*"; }
fail() { echo "[deploy] ERROR: $*" >&2; exit 1; }

# ── Build in-cluster kubeconfig ────────────────────────────────────────────────
kubectl config set-cluster in-cluster \
  --server="https://kubernetes.default.svc" \
  --certificate-authority="${SA_DIR}/ca.crt" \
  --kubeconfig="${KUBECONFIG_FILE}"

kubectl config set-credentials in-cluster-sa \
  --token="$(cat ${SA_DIR}/token)" \
  --kubeconfig="${KUBECONFIG_FILE}"

kubectl config set-context in-cluster \
  --cluster=in-cluster \
  --user=in-cluster-sa \
  --kubeconfig="${KUBECONFIG_FILE}"

kubectl config use-context in-cluster \
  --kubeconfig="${KUBECONFIG_FILE}"

export KUBECONFIG="${KUBECONFIG_FILE}"
export MGMT_KUBECONFIG="${KUBECONFIG_FILE}"
export RUNNER_MODE=true

# ── Check: does the cluster already exist and is Provisioned? ──────────────────
PHASE=$(kubectl get cluster "${CLUSTER_NAME}" -n "${CLUSTER_NAME}" \
  -o jsonpath='{.status.phase}' 2>/dev/null || echo "")

if [ "${PHASE}" = "Provisioned" ]; then
  CURRENT_VERSION=$(kubectl get kubeadmcontrolplane \
    "${CLUSTER_NAME}-control-plane" -n "${CLUSTER_NAME}" \
    -o jsonpath='{.spec.version}' 2>/dev/null || echo "")

  if [ "${CURRENT_VERSION}" = "${KUBERNETES_VERSION}" ]; then
    log "cluster '${CLUSTER_NAME}' already exists and is on ${KUBERNETES_VERSION} — nothing to do ✅"
    exit 0
  fi

  log "cluster '${CLUSTER_NAME}' is Provisioned on ${CURRENT_VERSION}, target is ${KUBERNETES_VERSION}"
  log "delegating to crossplane-upgrade.sh..."

  # crossplane-upgrade.sh uses TARGET_KUBERNETES_VERSION
  export TARGET_KUBERNETES_VERSION="${KUBERNETES_VERSION}"
  exec /bin/bash /workspace/scripts/crossplane-upgrade.sh
fi

# ── Normal deploy path ─────────────────────────────────────────────────────────
log "cluster '${CLUSTER_NAME}' does not exist yet (phase='${PHASE}') — deploying..."

make deploy-full-local \
  country="${COUNTRY}" \
  provider="${PROVIDER}" \
  cluster-name="${CLUSTER_NAME}" \
  cni="${CNI_PLUGIN}" \
  multus="${MULTUS_ENABLED}" \
  endpoint-ip="${CONTROL_PLANE_ENDPOINT_IP}" \
  kubernetes-version="${KUBERNETES_VERSION}" \
  control-plane-replicas="${CONTROL_PLANE_REPLICAS}" \
  worker-replicas="${WORKER_REPLICAS}"
