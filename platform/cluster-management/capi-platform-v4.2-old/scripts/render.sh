#!/usr/bin/env bash
set -euo pipefail

output_file="${1:?output file required}"

required_vars=(
  CLUSTER_NAME
  NAMESPACE
  KUBERNETES_VERSION
  CONTROL_PLANE_REPLICAS
  WORKER_REPLICAS
  POD_CIDR
  SERVICE_CIDR
  DNS_DOMAIN_SUFFIX
  INFRA_CLUSTER_SECRET_NAME
  INFRA_CLUSTER_SECRET_NAMESPACE
  CONTROL_PLANE_SERVICE_TYPE
  CONTROL_PLANE_ENDPOINT_IP
  CONTROL_PLANE_ENDPOINT_PORT
  KUBEVIRT_VM_NAMESPACE
  VM_IMAGE_URL
  CONTROL_PLANE_CPU_CORES
  CONTROL_PLANE_MEMORY
  WORKER_CPU_CORES
  WORKER_MEMORY
)

for v in "${required_vars[@]}"; do
  if [[ -z "${!v:-}" ]]; then
    echo "ERROR: required variable is empty or unset: ${v}"
    exit 1
  fi
done

tmp_file="$(mktemp)"

cat \
  templates/namespace.yaml.tpl \
  templates/cluster.yaml.tpl \
  templates/kubevirt-cluster.yaml.tpl \
  templates/kubevirt-control-plane-template.yaml.tpl \
  templates/kcp.yaml.tpl \
  templates/kubevirt-md.yaml.tpl \
  > "${tmp_file}"

envsubst < "${tmp_file}" > "${output_file}"

rm -f "${tmp_file}"
echo "Rendered manifest written to ${output_file}"
