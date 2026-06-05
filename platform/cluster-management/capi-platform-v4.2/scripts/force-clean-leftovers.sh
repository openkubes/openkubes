#!/usr/bin/env bash
set -euo pipefail

NS="${1:-capi-workload}"
CLUSTER="${2:-ok1}"

echo "Best-effort finalizer cleanup for ${CLUSTER} in ${NS}"

for r in   machine.cluster.x-k8s.io   machineset.cluster.x-k8s.io   machinedeployment.cluster.x-k8s.io   kubeadmcontrolplane.controlplane.cluster.x-k8s.io   kubevirtmachine.infrastructure.cluster.x-k8s.io   kubevirtcluster.infrastructure.cluster.x-k8s.io   cluster.cluster.x-k8s.io
do
  kubectl -n "${NS}" get "${r}" -o json --ignore-not-found 2>/dev/null | jq -r --arg C "${CLUSTER}" '
    .items[]? | select(.metadata.name | test($C)) | .kind + " " + .metadata.name' | while read -r kind name; do
      [ -n "${kind:-}" ] || continue
      echo "Patching finalizers on ${kind}/${name}"
      kubectl -n "${NS}" patch "$(echo "$kind" | tr '[:upper:]' '[:lower:]')" "${name}" --type merge -p '{"metadata":{"finalizers":[]}}' || true
  done
done

echo "Deleting leftovers"
kubectl -n "${NS}" delete cluster "${CLUSTER}" --ignore-not-found || true
kubectl -n "${NS}" delete kubeadmcontrolplane "${CLUSTER}-control-plane" --ignore-not-found || true
kubectl -n "${NS}" delete machinedeployment "${CLUSTER}-md-0" --ignore-not-found || true
kubectl -n "${NS}" delete kubevirtcluster "${CLUSTER}" --ignore-not-found || true
kubectl -n "${NS}" delete kubevirtmachinetemplate "${CLUSTER}-control-plane" --ignore-not-found || true
kubectl -n "${NS}" delete kubevirtmachinetemplate "${CLUSTER}-md-0" --ignore-not-found || true
kubectl -n "${NS}" delete kubeadmconfigtemplate "${CLUSTER}-md-0" --ignore-not-found || true
