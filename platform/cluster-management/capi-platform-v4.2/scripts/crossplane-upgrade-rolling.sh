#!/usr/bin/env bash
# crossplane-upgrade.sh
# Called either:
#   a) by the Crossplane upgrade Job (KubeVirtClusterUpgradeClaim) — uses TARGET_KUBERNETES_VERSION
#   b) by crossplane-deploy.sh when version drift is detected      — uses KUBERNETES_VERSION
#
# Upgrade mechanism:
#   1. Creates new KubevirtMachineTemplates with the target VM image
#      (checkStrategy: none — avoids SSH bootstrap check issues)
#   2. Patches KubeadmControlPlane → CAPI rolls CP nodes one by one
#   3. Cleans up CP ghost nodes
#   4. Ensures bootstrap tokens exist in workload cluster before worker rollout
#      (fixes race condition where KCP controller drops connection during upgrade)
#   5. Patches MachineDeployment → CAPI rolls worker nodes
#   6. Waits for worker Machines directly (not updatedReplicas which can be empty)
#   7. Cleans up worker ghost nodes
set -euo pipefail

SA_DIR="/var/run/secrets/kubernetes.io/serviceaccount"
KUBECONFIG_FILE="/tmp/in-cluster.kubeconfig"

log()  { echo "[upgrade] $*"; }
fail() { echo "[upgrade] ERROR: $*" >&2; exit 1; }

# ── Normalise: accept TARGET_KUBERNETES_VERSION or KUBERNETES_VERSION ──────────
TARGET_KUBERNETES_VERSION="${TARGET_KUBERNETES_VERSION:-${KUBERNETES_VERSION:-}}"
[ -n "${TARGET_KUBERNETES_VERSION}" ] || \
  fail "no target version set — set TARGET_KUBERNETES_VERSION or KUBERNETES_VERSION"

# ── Build in-cluster kubeconfig ────────────────────────────────────────────────
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
CP_TEMPLATE_NEW="${CLUSTER_NAME}-control-plane-${TARGET_VERSION//./}"
MD_TEMPLATE_NEW="${CLUSTER_NAME}-md-0-${TARGET_VERSION//./}"
WORKLOAD_KUBECONFIG="/tmp/workload-${CLUSTER_NAME}.kubeconfig"

log "starting upgrade of cluster '${CLUSTER_NAME}' to ${TARGET_VERSION}"

# ── Helper: get workload kubeconfig ───────────────────────────────────────────
get_workload_kubeconfig() {
  if clusterctl get kubeconfig "${CLUSTER_NAME}" \
    -n "${NAMESPACE}" > "${WORKLOAD_KUBECONFIG}" 2>/dev/null; then
    return 0
  fi
  return 1
}

# ── Helper: cleanup ghost nodes in workload cluster ────────────────────────────
cleanup_ghost_nodes() {
  log "cleaning up ghost nodes in workload cluster..."
  if get_workload_kubeconfig; then
    # Ghost nodes are:
    # 1. unschedulable (SchedulingDisabled) — being drained by CAPI
    # 2. Ready=False — node lost connection
    # Note: do NOT filter by version here — valid nodes may temporarily
    # report old version while kubelet restarts after upgrade.
    GHOST_NODES=$(KUBECONFIG="${WORKLOAD_KUBECONFIG}" kubectl get nodes \
      -o json 2>/dev/null | \
      jq -r '.items[] | select(
        (.spec.unschedulable == true) or
        (.status.conditions[] | select(.type=="Ready") | .status == "False")
      ) | .metadata.name' 2>/dev/null || echo "")

    if [ -n "${GHOST_NODES}" ]; then
      for NODE in ${GHOST_NODES}; do
        log "deleting ghost node: ${NODE}"
        KUBECONFIG="${WORKLOAD_KUBECONFIG}" kubectl delete node "${NODE}" \
          --ignore-not-found || true
      done
      log "ghost nodes cleaned up ✅"
    else
      log "no ghost nodes found ✅"
    fi
  else
    log "WARNING: could not retrieve workload kubeconfig for ghost node cleanup"
  fi
}

# ── Helper: ensure bootstrap tokens exist in workload cluster ─────────────────
# Root cause: KCP controller can drop its connection to the workload cluster
# during upgrade, causing bootstrap tokens to never be created there.
# kubeadm join then fails with "token not found".
# Fix: read tokens from KubeadmConfig objects and create them manually.
ensure_bootstrap_tokens() {
  log "ensuring bootstrap tokens exist in workload cluster..."

  if ! get_workload_kubeconfig; then
    log "WARNING: could not retrieve workload kubeconfig, skipping token check"
    return 0
  fi

  # Find all KubeadmConfig objects for this cluster's worker machines
  CONFIGS=$(kubectl get kubeadmconfig -n "${NAMESPACE}" \
    -o json 2>/dev/null | \
    jq -r '.items[] | select(.spec.joinConfiguration != null) | .metadata.name' \
    2>/dev/null || echo "")

  if [ -z "${CONFIGS}" ]; then
    log "no KubeadmConfig objects found, skipping token check"
    return 0
  fi

  for CONFIG in ${CONFIGS}; do
    TOKEN=$(kubectl get kubeadmconfig "${CONFIG}" -n "${NAMESPACE}" \
      -o jsonpath='{.spec.joinConfiguration.discovery.bootstrapToken.token}' \
      2>/dev/null || echo "")

    [ -z "${TOKEN}" ] && continue

    TOKEN_ID=$(echo "${TOKEN}" | cut -d. -f1)
    TOKEN_SECRET=$(echo "${TOKEN}" | cut -d. -f2)

    # Check if token already exists in workload cluster
    if KUBECONFIG="${WORKLOAD_KUBECONFIG}" kubectl get secret \
      "bootstrap-token-${TOKEN_ID}" -n kube-system >/dev/null 2>&1; then
      log "bootstrap token ${TOKEN_ID} already exists ✅"
      continue
    fi

    log "creating missing bootstrap token ${TOKEN_ID} for ${CONFIG}..."
    KUBECONFIG="${WORKLOAD_KUBECONFIG}" kubectl create secret generic \
      "bootstrap-token-${TOKEN_ID}" \
      -n kube-system \
      --type bootstrap.kubernetes.io/token \
      --from-literal=token-id="${TOKEN_ID}" \
      --from-literal=token-secret="${TOKEN_SECRET}" \
      --from-literal=usage-bootstrap-authentication=true \
      --from-literal=usage-bootstrap-signing=true \
      --from-literal=auth-extra-groups=system:bootstrappers:kubeadm:default-node-token \
      2>/dev/null || log "WARNING: could not create token ${TOKEN_ID}"

    log "bootstrap token ${TOKEN_ID} created ✅"
  done
}

# ── Step 1: Check if target VM image exists on quay.io/capk ───────────────────
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

# ── Step 2: Verify cluster exists and is Provisioned ──────────────────────────
log "verifying cluster status..."
PHASE=$(kubectl get cluster "${CLUSTER_NAME}" -n "${NAMESPACE}" \
  -o jsonpath='{.status.phase}' 2>/dev/null || true)

[ -z "${PHASE}" ] && \
  fail "cluster '${CLUSTER_NAME}' not found in namespace '${NAMESPACE}'"
[ "${PHASE}" != "Provisioned" ] && \
  fail "cluster is in phase '${PHASE}', expected 'Provisioned'"

CURRENT_CP_VERSION=$(kubectl get kubeadmcontrolplane \
  "${CLUSTER_NAME}-control-plane" -n "${NAMESPACE}" \
  -o jsonpath='{.spec.version}' 2>/dev/null || echo "unknown")

CURRENT_MD_VERSION=$(kubectl get machinedeployment \
  "${CLUSTER_NAME}-md-0" -n "${NAMESPACE}" \
  -o jsonpath='{.spec.template.spec.version}' 2>/dev/null || echo "unknown")

log "cluster is Provisioned ✅"
log "current control plane version: ${CURRENT_CP_VERSION}"
log "current worker version:        ${CURRENT_MD_VERSION}"
log "target version:                ${TARGET_VERSION}"

if [ "${CURRENT_CP_VERSION}" = "${TARGET_VERSION}" ] && \
   [ "${CURRENT_MD_VERSION}" = "${TARGET_VERSION}" ]; then
  log "control plane and workers are already on ${TARGET_VERSION}, nothing to do ✅"
  exit 0
fi

# ── Step 3: Create new KubevirtMachineTemplates with target VM image ───────────
# Note: checkStrategy=none avoids SSH bootstrap check which fails without SSH key
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
    .spec.template.spec.virtualMachineBootstrapCheck.checkStrategy = "none" |
    (.spec.template.spec.virtualMachineTemplate.spec.template.spec.volumes[]
      | select(.containerDisk != null)
      | .containerDisk.image) = $image
    ' | kubectl apply -f -

  log "template ${NEW_TEMPLATE} created ✅"
done

# ── Step 4: Patch KubeadmControlPlane → CAPI rolls CP nodes one by one ────────
log "patching KubeadmControlPlane to ${TARGET_VERSION} with template ${CP_TEMPLATE_NEW}..."

kubectl patch kubeadmcontrolplane "${CLUSTER_NAME}-control-plane" \
  -n "${NAMESPACE}" \
  --type merge \
  -p "{
    \"spec\": {
      \"version\": \"${TARGET_VERSION}\",
      \"machineTemplate\": {
        \"spec\": {
          \"infrastructureRef\": {
            \"name\": \"${CP_TEMPLATE_NEW}\"
          }
        }
      }
    }
  }"

log "KubeadmControlPlane patched ✅ — CAPI will now roll control plane nodes"

# ── Step 5: Wait for control plane upgrade ────────────────────────────────────
log "waiting for control plane upgrade (up to 15min)..."
kubectl wait kubeadmcontrolplane "${CLUSTER_NAME}-control-plane" \
  -n "${NAMESPACE}" \
  --for=condition=Available \
  --timeout=900s

log "control plane upgraded ✅"

# ── Step 6: Cleanup CP ghost nodes ────────────────────────────────────────────
cleanup_ghost_nodes

# ── Step 7: Ensure bootstrap tokens exist before worker rollout ───────────────
ensure_bootstrap_tokens

# ── Step 8: Patch MachineDeployment → CAPI rolls worker nodes ─────────────────
log "patching MachineDeployment to ${TARGET_VERSION} with template ${MD_TEMPLATE_NEW}..."

kubectl patch machinedeployment "${CLUSTER_NAME}-md-0" \
  -n "${NAMESPACE}" \
  --type merge \
  -p "{
    \"spec\": {
      \"template\": {
        \"metadata\": {
          \"annotations\": {
            \"openkubes.ai/upgrade-version\": \"${TARGET_VERSION}\",
            \"openkubes.ai/upgrade-timestamp\": \"$(date -u +%Y%m%d%H%M%S)\"
          }
        },
        \"spec\": {
          \"version\": \"${TARGET_VERSION}\",
          \"infrastructureRef\": {
            \"name\": \"${MD_TEMPLATE_NEW}\",
            \"apiGroup\": \"infrastructure.cluster.x-k8s.io\",
            \"kind\": \"KubevirtMachineTemplate\"
          }
        }
      }
    }
  }"

log "MachineDeployment patched ✅ — CAPI will now roll worker nodes"

# ── Step 9: Wait for worker Machines via CAPI status ─────────────────────────
# Note: .status.updatedReplicas on MachineDeployment can be empty even when
# rollout is complete — we check Machine objects directly instead.
# Note: CAPI Machine Running does NOT guarantee the real node has joined.
#       The real kubelet version check happens in Step 9b.
#       Auto-restart for stuck VMs is also in Step 9b.
log "waiting for worker Machines to be Running on ${TARGET_VERSION} (up to 20min)..."

DESIRED=$(kubectl get machinedeployment "${CLUSTER_NAME}-md-0" \
  -n "${NAMESPACE}" -o jsonpath='{.spec.replicas}' 2>/dev/null || echo "1")

# Track VMs we already restarted to avoid restart loops
RESTARTED_VMS=""

for i in $(seq 1 120); do
  RUNNING=$(kubectl get machines -n "${NAMESPACE}" \
    --selector="cluster.x-k8s.io/deployment-name=${CLUSTER_NAME}-md-0" \
    -o json 2>/dev/null | \
    jq -r --arg v "${TARGET_VERSION}" \
    '[.items[] | select(.status.phase=="Running" and .spec.version==$v)] | length' \
    2>/dev/null || echo "0")

  log "worker Machines Running on ${TARGET_VERSION}: ${RUNNING}/${DESIRED} (${i}/120)"

  if [ "${RUNNING}" = "${DESIRED}" ] && [ "${DESIRED}" != "0" ]; then
    log "all worker Machines upgraded ✅"
    break
  fi

  [ "${i}" = "120" ] && fail "worker upgrade timed out after 1200s"
  sleep 10
done

# ── Step 9b: Wait for workload worker nodes to report TARGET_VERSION ──────────
# This is the real check — CAPI Machine status alone is not sufficient.
# Auto-restart VMs if nodes don't appear after 5min (kubeadm join race condition).
log "waiting for workload worker nodes to report kubelet ${TARGET_VERSION}..."

# Load infra kubeconfig for VM restarts
kubectl get secret "external-infra-kubeconfig-${CLUSTER_NAME}" \
  -n "${NAMESPACE}" -o jsonpath='{.data.kubeconfig}' | \
  base64 -d > /tmp/infra-upgrade.kubeconfig 2>/dev/null || true

RESTARTED_VMS=""

if get_workload_kubeconfig; then
  for i in $(seq 1 90); do
    READY_NEW=$(KUBECONFIG="${WORKLOAD_KUBECONFIG}" kubectl get nodes -o json 2>/dev/null | \
      jq -r --arg v "${TARGET_VERSION}" \
      '[.items[]
        | select((.metadata.labels["node-role.kubernetes.io/control-plane"] // "") == "")
        | select(.status.nodeInfo.kubeletVersion == $v)
        | select(.status.conditions[] | select(.type=="Ready" and .status=="True"))
      ] | length' 2>/dev/null || echo "0")

    OLD_WORKERS=$(KUBECONFIG="${WORKLOAD_KUBECONFIG}" kubectl get nodes -o json 2>/dev/null | \
      jq -r --arg v "${TARGET_VERSION}" \
      '[.items[]
        | select((.metadata.labels["node-role.kubernetes.io/control-plane"] // "") == "")
        | select(.status.nodeInfo.kubeletVersion != $v)
      ] | length' 2>/dev/null || echo "99")

    log "workload worker nodes Ready on ${TARGET_VERSION}: ${READY_NEW}/${DESIRED}, old workers still present: ${OLD_WORKERS} (${i}/90)"

    if [ "${READY_NEW}" = "${DESIRED}" ] && [ "${OLD_WORKERS}" = "0" ]; then
      log "workload worker nodes upgraded ✅"
      break
    fi

    # Auto-restart VMs stuck after 5min (30 iterations × 10s)
    if [ "${i}" -ge 30 ] && [ -f "/tmp/infra-upgrade.kubeconfig" ]; then
      STUCK_MACHINES=$(kubectl get machines -n "${NAMESPACE}" \
        --selector="cluster.x-k8s.io/deployment-name=${CLUSTER_NAME}-md-0" \
        -o json 2>/dev/null | \
        jq -r --arg v "${TARGET_VERSION}" \
        '.items[] | select(.spec.version==$v and .status.phase=="Running") | .metadata.name' \
        2>/dev/null || echo "")

      for MACHINE in ${STUCK_MACHINES}; do
        if echo "${RESTARTED_VMS}" | grep -q "${MACHINE}"; then
          continue
        fi
        log "worker ${MACHINE} not yet in workload cluster after 5min — restarting VM..."
        kubectl patch virtualmachine "${MACHINE}" -n "${NAMESPACE}" \
          --kubeconfig /tmp/infra-upgrade.kubeconfig \
          --type merge -p '{"spec":{"runStrategy":"Halted"}}' 2>/dev/null || true
        sleep 5
        kubectl patch virtualmachine "${MACHINE}" -n "${NAMESPACE}" \
          --kubeconfig /tmp/infra-upgrade.kubeconfig \
          --type merge -p '{"spec":{"runStrategy":"Always"}}' 2>/dev/null || true
        RESTARTED_VMS="${RESTARTED_VMS} ${MACHINE}"
        log "VM ${MACHINE} restarted ✅"
      done
    fi

    [ "${i}" = "90" ] && fail "worker nodes did not reach kubelet ${TARGET_VERSION} after 900s — upgrade incomplete!"
    sleep 10
  done
else
  fail "could not retrieve workload kubeconfig — cannot verify worker node versions"
fi

# ── Step 10: Cleanup worker ghost nodes ───────────────────────────────────────
cleanup_ghost_nodes

# ── Step 11: Final status ──────────────────────────────────────────────────────
log "final cluster status:"
kubectl get cluster "${CLUSTER_NAME}" -n "${NAMESPACE}"
kubectl get machines -n "${NAMESPACE}"

if [ -f "${WORKLOAD_KUBECONFIG}" ]; then
  log "workload cluster nodes:"
  KUBECONFIG="${WORKLOAD_KUBECONFIG}" kubectl get nodes -o wide || true
fi

log ""
log "cluster '${CLUSTER_NAME}' successfully upgraded to ${TARGET_VERSION} 🎉"
