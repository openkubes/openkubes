#!/usr/bin/env bash
# crossplane-upgrade.sh
# Called by the Crossplane upgrade Job.
# Uses clusterctl upgrade apply for reliable CAPI upgrades.
set -euo pipefail

SA_DIR="/var/run/secrets/kubernetes.io/serviceaccount"
KUBECONFIG_FILE="/tmp/in-cluster.kubeconfig"

log()  { echo "[upgrade] $*"; }
fail() { echo "[upgrade] ERROR: $*" >&2; exit 1; }

# Build in-cluster kubeconfig
kubectl config set-cluster in-cluster \
  --server="https://kubernetes.default.svc" \
  --certificate-authority="${SA_DIR}/ca.crt" \
  --kubeconfig="${KUBECONFIG_FILE}"
kubectl config set-credentials in-cluster-sa \
  --token="$(cat ${SA_DIR}/token)" \
  --kubeconfig="${KUBECONFIG_FILE}"
kubectl config set-context in-cluster \
  --cluster=in-cluster --user=in-cluster-sa \
  --kubeconfig="${KUBECONFIG_FILE}"
kubectl config use-context in-cluster \
  --kubeconfig="${KUBECONFIG_FILE}"

export KUBECONFIG="${KUBECONFIG_FILE}"
export MGMT_KUBECONFIG="${KUBECONFIG_FILE}"

NAMESPACE="${CLUSTER_NAME}"
TARGET_VERSION="${TARGET_KUBERNETES_VERSION}"
TARGET_IMAGE="quay.io/capk/ubuntu-2404-container-disk:${TARGET_VERSION}"

log "starting upgrade of cluster '${CLUSTER_NAME}' to ${TARGET_VERSION}"

# ---------------------------------------------------------------
# Step 1: Check if target VM image exists on quay.io/capk
# ---------------------------------------------------------------
log "checking if VM image ${TARGET_IMAGE} exists..."

AVAILABLE=$(curl -s \
  "https://quay.io/api/v1/repository/capk/ubuntu-2404-container-disk/tag/?limit=50" \
  2>/dev/null | jq -r '.tags[]?.name' 2>/dev/null || echo "")

if [ -n "${AVAILABLE}" ]; then
  log "available VM images:"
  echo "${AVAILABLE}" | while read -r v; do
    log "  quay.io/capk/ubuntu-2404-container-disk:${v}"
  done
  if ! echo "${AVAILABLE}" | grep -qx "${TARGET_VERSION}"; then
    fail "VM image for ${TARGET_VERSION} not found on quay.io/capk!
Available versions: $(echo "${AVAILABLE}" | tr '\n' ' ')
Only upgrade to available versions, e.g. v1.33.5 → v1.34.1"
  fi
  log "VM image ${TARGET_IMAGE} is available ✅"
else
  log "WARNING: could not check quay.io, proceeding anyway..."
fi

# ---------------------------------------------------------------
# Step 2: Verify cluster exists and is Provisioned
# ---------------------------------------------------------------
log "verifying cluster status..."
PHASE=$(kubectl get cluster "${CLUSTER_NAME}" -n "${NAMESPACE}" \
  -o jsonpath='{.status.phase}' 2>/dev/null || true)

[ -z "${PHASE}" ] && \
  fail "cluster '${CLUSTER_NAME}' not found in namespace '${NAMESPACE}'"
[ "${PHASE}" != "Provisioned" ] && \
  fail "cluster is in phase '${PHASE}', expected 'Provisioned'"

CURRENT_VERSION=$(kubectl get kubeadmcontrolplane \
  "${CLUSTER_NAME}-control-plane" -n "${NAMESPACE}" \
  -o jsonpath='{.spec.version}' 2>/dev/null || echo "unknown")

log "cluster is Provisioned ✅"
log "current version: ${CURRENT_VERSION}"
log "target version:  ${TARGET_VERSION}"

if [ "${CURRENT_VERSION}" = "${TARGET_VERSION}" ]; then
  log "cluster is already on ${TARGET_VERSION}, nothing to do ✅"
  exit 0
fi

# ---------------------------------------------------------------
# Step 3: Create new MachineTemplates with target VM image
# ---------------------------------------------------------------
CP_TEMPLATE_NEW="${CLUSTER_NAME}-control-plane-${TARGET_VERSION//./}"
MD_TEMPLATE_NEW="${CLUSTER_NAME}-md-0-${TARGET_VERSION//./}"

log "creating new KubevirtMachineTemplates with image ${TARGET_IMAGE}..."

for SUFFIX in "control-plane" "md-0"; do
  OLD_TEMPLATE="${CLUSTER_NAME}-${SUFFIX}"
  NEW_TEMPLATE="${CLUSTER_NAME}-${SUFFIX}-${TARGET_VERSION//./}"

  if kubectl get kubevirtmachinetemplate "${NEW_TEMPLATE}" \
    -n "${NAMESPACE}" >/dev/null 2>&1; then
    log "template ${NEW_TEMPLATE} already exists, skipping"
    continue
  fi

  kubectl get kubevirtmachinetemplate "${OLD_TEMPLATE}" \
    -n "${NAMESPACE}" -o json | \
    jq --arg name "${NEW_TEMPLATE}" \
       --arg image "${TARGET_IMAGE}" \
    '
    .metadata.name = $name |
    del(.metadata.resourceVersion) |
    del(.metadata.uid) |
    del(.metadata.creationTimestamp) |
    del(.metadata.annotations["kubectl.kubernetes.io/last-applied-configuration"]) |
    (.spec.template.spec.virtualMachineTemplate.spec.template.spec.volumes[]
      | select(.containerDisk != null)
      | .containerDisk.image) = $image
    ' | kubectl apply -f -

  log "template ${NEW_TEMPLATE} created ✅"
done

# ---------------------------------------------------------------
# Step 4: Use clusterctl upgrade apply
# ---------------------------------------------------------------
log "running clusterctl upgrade apply..."

clusterctl upgrade apply \
  --kubeconfig "${KUBECONFIG_FILE}" \
  --namespace "${NAMESPACE}" \
  --control-plane "${NAMESPACE}/${CLUSTER_NAME}-control-plane:${TARGET_VERSION}" \
  --worker "${NAMESPACE}/${CLUSTER_NAME}-md-0:${TARGET_VERSION}" \
  -v 5 || true

log "clusterctl upgrade apply completed"

# ---------------------------------------------------------------
# Step 5: Wait for control plane upgrade
# ---------------------------------------------------------------
log "waiting for control plane upgrade (up to 15min)..."
kubectl wait kubeadmcontrolplane "${CLUSTER_NAME}-control-plane" \
  -n "${NAMESPACE}" \
  --for=condition=Available \
  --timeout=900s

log "control plane upgraded ✅"

# ---------------------------------------------------------------
# Step 6: Wait for worker rollout
# ---------------------------------------------------------------
log "waiting for worker rollout (up to 15min)..."
for i in $(seq 1 90); do
  DESIRED=$(kubectl get machinedeployment "${CLUSTER_NAME}-md-0" \
    -n "${NAMESPACE}" -o jsonpath='{.spec.replicas}' 2>/dev/null || echo "0")
  READY=$(kubectl get machinedeployment "${CLUSTER_NAME}-md-0" \
    -n "${NAMESPACE}" -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
  UPDATED=$(kubectl get machinedeployment "${CLUSTER_NAME}-md-0" \
    -n "${NAMESPACE}" -o jsonpath='{.status.updatedReplicas}' 2>/dev/null || echo "0")

  log "workers: desired=${DESIRED} ready=${READY} updated=${UPDATED} (${i}/90)"

  if [ "${READY}" = "${DESIRED}" ] && \
     [ "${UPDATED}" = "${DESIRED}" ] && \
     [ "${DESIRED}" != "0" ]; then
    log "all workers upgraded ✅"
    break
  fi
  [ "${i}" = "90" ] && fail "worker upgrade timed out after 900s"
  sleep 10
done

# ---------------------------------------------------------------
# Step 7: Final status
# ---------------------------------------------------------------
log "final cluster status:"
kubectl get cluster "${CLUSTER_NAME}" -n "${NAMESPACE}"
kubectl get machines -n "${NAMESPACE}"

log ""
log "cluster '${CLUSTER_NAME}' successfully upgraded to ${TARGET_VERSION} 🎉"
log ""
log "Don't forget to update kubevirt.env and ok1.yaml:"
log "  VM_IMAGE_URL=${TARGET_IMAGE}"
log "  kubernetesVersion: ${TARGET_VERSION}"
