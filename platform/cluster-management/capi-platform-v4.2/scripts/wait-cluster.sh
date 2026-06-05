#!/usr/bin/env bash
set -euo pipefail

cluster_name="${1:?cluster name required}"
namespace="${2:-default}"

echo "Waiting for Cluster/${cluster_name} infrastructure to become ready..."
kubectl wait --namespace "${namespace}" \
  --for=condition=InfrastructureReady \
  "cluster/${cluster_name}" \
  --timeout=30m

echo "Waiting for Cluster/${cluster_name} control plane to become ready..."
kubectl wait --namespace "${namespace}" \
  --for=condition=ControlPlaneReady \
  "cluster/${cluster_name}" \
  --timeout=30m

echo "Cluster ${cluster_name} reports infrastructure and control plane ready."
echo
echo "Machines:"
kubectl get machines -n "${namespace}" -l "cluster.x-k8s.io/cluster-name=${cluster_name}" -o wide || true
echo
echo "KubeadmControlPlane:"
kubectl get kubeadmcontrolplane -n "${namespace}" || true
