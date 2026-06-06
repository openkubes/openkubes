#!/usr/bin/env bash
# crossplane-cleanup.sh
# Called by the Crossplane cleanup Job.
# All parameters come from environment variables (ConfigMap).
set -euo pipefail

SA_DIR="/var/run/secrets/kubernetes.io/serviceaccount"
KUBECONFIG_FILE="/tmp/in-cluster.kubeconfig"

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

make cleanup-local \
  country="${COUNTRY}" \
  provider="${PROVIDER}" \
  cluster-name="${CLUSTER_NAME}"
