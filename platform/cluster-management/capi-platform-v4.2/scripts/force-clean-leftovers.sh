#!/usr/bin/env bash
set -euo pipefail

NS="${1:-capi-workload}"
CLUSTER="${2:-ok1}"
CROSSPLANE_NS="${3:-openkubes-system}"

echo "Best-effort finalizer cleanup for ${CLUSTER} in ${NS}"

# ---------------------------------------------------------------
# Step 1: CAPI Finalizer cleanup
# ---------------------------------------------------------------
# Ensure namespace exists for patching (may already be Terminating)
kubectl create ns "${NS}" 2>/dev/null || true

for r in \
  machine.cluster.x-k8s.io \
  machineset.cluster.x-k8s.io \
  machinedeployment.cluster.x-k8s.io \
  kubeadmcontrolplane.controlplane.cluster.x-k8s.io \
  kubevirtmachine.infrastructure.cluster.x-k8s.io \
  kubevirtcluster.infrastructure.cluster.x-k8s.io \
  cluster.cluster.x-k8s.io
do
  kubectl -n "${NS}" get "${r}" -o json --ignore-not-found 2>/dev/null | \
    jq -r --arg C "${CLUSTER}" '
      .items[]? | select(.metadata.name | test($C)) | .kind + " " + .metadata.name' | \
    while read -r kind name; do
      [ -n "${kind:-}" ] || continue
      echo "Patching finalizers on ${kind}/${name}"
      kubectl -n "${NS}" patch \
        "$(echo "$kind" | tr '[:upper:]' '[:lower:]')" "${name}" \
        --type merge -p '{"metadata":{"finalizers":[]}}' || true
    done
done

echo "Deleting CAPI leftovers"
kubectl -n "${NS}" delete cluster "${CLUSTER}" --ignore-not-found || true
kubectl -n "${NS}" delete kubeadmcontrolplane "${CLUSTER}-control-plane" --ignore-not-found || true
kubectl -n "${NS}" delete machinedeployment "${CLUSTER}-md-0" --ignore-not-found || true
kubectl -n "${NS}" delete kubevirtcluster "${CLUSTER}" --ignore-not-found || true
kubectl -n "${NS}" delete kubevirtmachinetemplate "${CLUSTER}-control-plane" --ignore-not-found || true
kubectl -n "${NS}" delete kubevirtmachinetemplate "${CLUSTER}-md-0" --ignore-not-found || true
kubectl -n "${NS}" delete kubeadmconfigtemplate "${CLUSTER}-md-0" --ignore-not-found || true

# ---------------------------------------------------------------
# Step 2: Delete namespace
# ---------------------------------------------------------------
echo "Deleting namespace ${NS}"
kubectl delete ns "${NS}" --ignore-not-found || true

# ---------------------------------------------------------------
# Step 3: Crossplane cleanup
# ---------------------------------------------------------------
echo "Cleaning up Crossplane state for claim '${CLUSTER}'"

# Delete the KubeVirtClusterClaim
kubectl delete kubevirtclusterclaim "${CLUSTER}" \
  -n "${CROSSPLANE_NS}" --ignore-not-found 2>/dev/null || true

# Find and remove finalizers from the XR (has hash suffix)
XR_NAME=$(kubectl get kubevirtcluster.platform.openkubes.ai \
  -l "crossplane.io/claim-name=${CLUSTER}" \
  -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)

if [ -n "${XR_NAME}" ]; then
  echo "Removing finalizers from XR ${XR_NAME}"
  kubectl patch kubevirtcluster.platform.openkubes.ai "${XR_NAME}" \
    --type=json -p='[{"op":"remove","path":"/metadata/finalizers"}]' \
    2>/dev/null || true
fi

# Delete all composed Objects for this XR
if [ -n "${XR_NAME}" ]; then
  echo "Deleting composed Objects for XR ${XR_NAME}"
  kubectl delete objects.kubernetes.crossplane.io \
    -l "crossplane.io/composite=${XR_NAME}" \
    2>/dev/null || true
fi

echo "Force cleanup for ${CLUSTER} complete"
