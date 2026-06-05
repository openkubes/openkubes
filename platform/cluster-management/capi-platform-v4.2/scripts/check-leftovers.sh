#!/usr/bin/env bash
set -euo pipefail

NS="${1:-capi-workload}"
CLUSTER="${2:-ok1}"

echo "=== Live resources in ${NS} matching ${CLUSTER} ==="
kubectl -n "${NS}" get   cluster,kubeadmcontrolplane.controlplane.cluster.x-k8s.io,machinedeployment.cluster.x-k8s.io,machineset.cluster.x-k8s.io,machine.cluster.x-k8s.io,kubevirtcluster.infrastructure.cluster.x-k8s.io,kubevirtmachine.infrastructure.cluster.x-k8s.io,kubevirtmachinetemplate.infrastructure.cluster.x-k8s.io,kubeadmconfigtemplate.bootstrap.cluster.x-k8s.io   --ignore-not-found 2>/dev/null | grep -E "${CLUSTER}|NAME" || true

echo
echo "=== Remaining finalizers in ${NS} ==="
for r in   cluster.cluster.x-k8s.io   kubeadmcontrolplane.controlplane.cluster.x-k8s.io   machinedeployment.cluster.x-k8s.io   machineset.cluster.x-k8s.io   machine.cluster.x-k8s.io   kubevirtcluster.infrastructure.cluster.x-k8s.io   kubevirtmachine.infrastructure.cluster.x-k8s.io
do
  kubectl -n "${NS}" get "${r}" -o json --ignore-not-found 2>/dev/null | jq -r --arg C "${CLUSTER}" '
    .items[]? |
    select(.metadata.name | test($C)) |
    select((.metadata.finalizers // []) | length > 0) |
    [.kind, .metadata.name, ((.metadata.finalizers // []) | join(","))] |
    @tsv'
done

echo
echo "=== Recent events in ${NS} matching ${CLUSTER} ==="
kubectl -n "${NS}" get events --sort-by=.lastTimestamp 2>/dev/null | grep -E "${CLUSTER}|LAST SEEN|TYPE" || true
