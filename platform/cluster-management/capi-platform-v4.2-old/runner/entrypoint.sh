#!/usr/bin/env bash
set -euo pipefail

echo "[runner] capi-platform-v4.2 separate addons"
echo "[runner] kubectl:    $(kubectl version --client=true --output=yaml 2>/dev/null | awk '/gitVersion:/ {print $2; exit}')"
echo "[runner] clusterctl: $(clusterctl version 2>/dev/null | head -n1 || true)"
echo "[runner] helm:       $(helm version --short 2>/dev/null || true)"
echo "[runner] kustomize:  $(kustomize version 2>/dev/null || true)"
echo "[runner] yq:         $(yq --version 2>/dev/null || true)"

if [[ -n "${KUBECONFIG:-}" ]]; then
  echo "[runner] KUBECONFIG=${KUBECONFIG}"
fi
if [[ -n "${MGMT_KUBECONFIG:-}" ]]; then
  echo "[runner] MGMT_KUBECONFIG=${MGMT_KUBECONFIG}"
fi
if [[ -n "${WORKLOAD_KUBECONFIG:-}" ]]; then
  echo "[runner] WORKLOAD_KUBECONFIG=${WORKLOAD_KUBECONFIG}"
fi

exec "$@"
