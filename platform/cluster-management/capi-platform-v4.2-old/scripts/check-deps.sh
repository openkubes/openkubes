#!/usr/bin/env bash
set -euo pipefail

deps=(kubectl clusterctl envsubst jq)
for dep in "${deps[@]}"; do
  if ! command -v "${dep}" >/dev/null 2>&1; then
    echo "ERROR: required dependency not found: ${dep}"
    exit 1
  fi
done

MGMT_CFG="${MGMT_KUBECONFIG:-${KUBECONFIG:-}}"
if [[ -z "${MGMT_CFG}" ]]; then
  echo "ERROR: neither MGMT_KUBECONFIG nor KUBECONFIG is set"
  exit 1
fi

required_crds=(
  "clusters.cluster.x-k8s.io"
  "machinedeployments.cluster.x-k8s.io"
  "kubeadmconfigtemplates.bootstrap.cluster.x-k8s.io"
  "kubeadmcontrolplanes.controlplane.cluster.x-k8s.io"
  "kubevirtclusters.infrastructure.cluster.x-k8s.io"
  "kubevirtmachinetemplates.infrastructure.cluster.x-k8s.io"
)

for crd in "${required_crds[@]}"; do
  if ! KUBECONFIG="${MGMT_CFG}" kubectl get crd "${crd}" >/dev/null 2>&1; then
    echo "ERROR: required CRD missing on management cluster: ${crd}"
    echo "ERROR: MGMT_KUBECONFIG points to: ${MGMT_CFG}"
    exit 1
  fi
done

kv_cluster_kind="$(KUBECONFIG="${MGMT_CFG}" kubectl get crd kubevirtclusters.infrastructure.cluster.x-k8s.io -o jsonpath='{.spec.names.kind}')"
kv_machine_tmpl_kind="$(KUBECONFIG="${MGMT_CFG}" kubectl get crd kubevirtmachinetemplates.infrastructure.cluster.x-k8s.io -o jsonpath='{.spec.names.kind}')"

if [[ "${kv_cluster_kind}" != "KubevirtCluster" ]]; then
  echo "WARNING: expected installed KubeVirt cluster kind to be KubevirtCluster, got: ${kv_cluster_kind}"
fi

if [[ "${kv_machine_tmpl_kind}" != "KubevirtMachineTemplate" ]]; then
  echo "WARNING: expected installed KubeVirt machine template kind to be KubevirtMachineTemplate, got: ${kv_machine_tmpl_kind}"
fi

ctx="$(KUBECONFIG="${MGMT_CFG}" kubectl config current-context 2>/dev/null || true)"
echo "All dependencies found."
echo "Management context: ${ctx}"
echo "KubeVirt kinds: ${kv_cluster_kind}, ${kv_machine_tmpl_kind}"
