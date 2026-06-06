#!/usr/bin/env bash
# crossplane-upgrade.sh
# Called by the Crossplane upgrade Job.
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
STRATEGY="${UPGRADE_STRATEGY:-RollingUpdate}"

log "starting upgrade of cluster '${CLUSTER_NAME}' to ${TARGET_VERSION}"

# ---------------------------------------------------------------
# Step 1: Check if target VM image exists on quay.io/capk
# ---------------------------------------------------------------
TARGET_IMAGE="quay.io/capk/ubuntu-2404-container-disk:${TARGET_VERSION}"
log "checking if VM image ${TARGET_IMAGE} exists..."

AVAILABLE=$(curl -s \
  "https://quay.io/api/v1/repository/capk/ubuntu-2404-container-disk/tag/?limit=50" \
  2>/dev/null | \
  python3 -c "
import sys, json
d = json.load(sys.stdin)
for t in d.get('tags', []):
    print(t['name'])
" 2>/dev/null || echo "")

if [ -n "${AVAILABLE}" ]; then
  log "available VM images:"
  echo "${AVAILABLE}" | while read v; do log "  quay.io/capk/ubuntu-2404-container-disk:${v}"; done

  if ! echo "${AVAILABLE}" | grep -qx "${TARGET_VERSION}"; then
    fail "VM image for ${TARGET_VERSION} not found on quay.io/capk!
Available versions: $(echo ${AVAILABLE} | tr '\n' ' ')
Note: only upgrade to available versions, e.g. v1.33.5 → v1.34.1"
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

[ -z "${PHASE}" ] && fail "cluster '${CLUSTER_NAME}' not found in namespace '${NAMESPACE}'"
[ "${PHASE}" != "Provisioned" ] && \
  fail "cluster is in phase '${PHASE}', expected 'Provisioned'"
log "cluster is Provisioned ✅"

# Get current version
CURRENT_VERSION=$(kubectl get kubeadmcontrolplane \
  "${CLUSTER_NAME}-control-plane" -n "${NAMESPACE}" \
  -o jsonpath='{.spec.version}' 2>/dev/null || echo "unknown")
log "current version: ${CURRENT_VERSION}"
log "target version:  ${TARGET_VERSION}"

# ---------------------------------------------------------------
# Step 3: Update KubevirtMachineTemplates with new VM image
# ---------------------------------------------------------------
log "updating VM image in KubevirtMachineTemplates to ${TARGET_IMAGE}..."

# Create new MachineTemplates (CAPI requires new templates for upgrades)
for TEMPLATE in "${CLUSTER_NAME}-control-plane" "${CLUSTER_NAME}-md-0"; do
  NEW_TEMPLATE="${TEMPLATE}-${TARGET_VERSION//./}"

  # Get existing template and update image
  kubectl get kubevirtmachinetemplate "${TEMPLATE}" \
    -n "${NAMESPACE}" -o json | \
    python3 -c "
import sys, json
d = json.load(sys.stdin)
d['metadata']['name'] = '${NEW_TEMPLATE}'
# Remove resource version and uid for creation
d['metadata'].pop('resourceVersion', None)
d['metadata'].pop('uid', None)
d['metadata'].pop('creationTimestamp', None)
# Update image
vols = d['spec']['template']['spec']['virtualMachineTemplate']['spec']['template']['spec']['volumes']
for v in vols:
    if 'containerDisk' in v:
        v['containerDisk']['image'] = '${TARGET_IMAGE}'
print(json.dumps(d))
" | kubectl apply -f - || log "WARNING: could not create template ${NEW_TEMPLATE}"
done

log "VM image templates updated ✅"

# ---------------------------------------------------------------
# Step 4: Upgrade Control Plane
# ---------------------------------------------------------------
log "upgrading KubeadmControlPlane to ${TARGET_VERSION}..."

kubectl patch kubeadmcontrolplane "${CLUSTER_NAME}-control-plane" \
  -n "${NAMESPACE}" --type=merge \
  -p "{
    \"spec\": {
      \"version\": \"${TARGET_VERSION}\",
      \"machineTemplate\": {
        \"infrastructureRef\": {
          \"name\": \"${CLUSTER_NAME}-control-plane-${TARGET_VERSION//./}\"
        }
      }
    }
  }"

log "waiting for control plane upgrade (up to 10min)..."
kubectl wait kubeadmcontrolplane "${CLUSTER_NAME}-control-plane" \
  -n "${NAMESPACE}" \
  --for=condition=Available \
  --timeout=600s

log "control plane upgraded to ${TARGET_VERSION} ✅"

# ---------------------------------------------------------------
# Step 5: Upgrade Workers
# ---------------------------------------------------------------
log "upgrading MachineDeployment workers to ${TARGET_VERSION}..."

kubectl patch machinedeployment "${CLUSTER_NAME}-md-0" \
  -n "${NAMESPACE}" --type=merge \
  -p "{
    \"spec\": {
      \"template\": {
        \"spec\": {
          \"version\": \"${TARGET_VERSION}\",
          \"infrastructureRef\": {
            \"name\": \"${CLUSTER_NAME}-md-0-${TARGET_VERSION//./}\"
          }
        }
      }
    }
  }"

log "waiting for worker rollout (up to 10min)..."
for i in $(seq 1 60); do
  DESIRED=$(kubectl get machinedeployment "${CLUSTER_NAME}-md-0" \
    -n "${NAMESPACE}" -o jsonpath='{.spec.replicas}' 2>/dev/null || echo "0")
  READY=$(kubectl get machinedeployment "${CLUSTER_NAME}-md-0" \
    -n "${NAMESPACE}" -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
  UPDATED=$(kubectl get machinedeployment "${CLUSTER_NAME}-md-0" \
    -n "${NAMESPACE}" -o jsonpath='{.status.updatedReplicas}' 2>/dev/null || echo "0")

  log "workers: desired=${DESIRED} ready=${READY} updated=${UPDATED} (${i}/60)"

  if [ "${READY}" = "${DESIRED}" ] && [ "${UPDATED}" = "${DESIRED}" ] && \
     [ "${DESIRED}" != "0" ]; then
    log "all workers upgraded ✅"
    break
  fi
  [ "${i}" = "60" ] && fail "worker upgrade timed out"
  sleep 10
done

# ---------------------------------------------------------------
# Step 6: Final status
# ---------------------------------------------------------------
log "final cluster status:"
kubectl get cluster "${CLUSTER_NAME}" -n "${NAMESPACE}"
kubectl get machines -n "${NAMESPACE}"

log "cluster '${CLUSTER_NAME}' successfully upgraded to ${TARGET_VERSION} 🎉"
log ""
log "Update kubevirt.env:"
log "  VM_IMAGE_URL=${TARGET_IMAGE}"
