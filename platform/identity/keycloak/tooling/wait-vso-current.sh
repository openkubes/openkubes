#!/usr/bin/env bash
# kubectl wait cannot compare status.lastGeneration with metadata.generation.
# Watch each VSS and accept only SecretSynced=True for the generation being observed.
set -Eeuo pipefail

: "${KUBECTL:?KUBECTL is required}"
: "${TIMEOUT:?TIMEOUT is required}"
: "${KUBECONFIG:?KUBECONFIG is required}"
: "${NAMESPACE:?NAMESPACE is required}"
: "${WAIT_TIMEOUT:?WAIT_TIMEOUT is required}"

(( $# > 0 )) || { echo "ERROR: at least one VaultStaticSecret name is required" >&2; exit 2; }

for name in "$@"; do
  echo "Waiting for VaultStaticSecret $NAMESPACE/$name: SecretSynced=True at current generation"
  set +o pipefail
  "$TIMEOUT" "$WAIT_TIMEOUT" "$KUBECTL" --kubeconfig "$KUBECONFIG" get vaultstaticsecret "$name" \
    -n "$NAMESPACE" --watch -o \
    'jsonpath={.metadata.generation}{" "}{.status.lastGeneration}{" "}{.status.conditions[?(@.type=="SecretSynced")].status}{"\n"}' |
    awk '$1 == $2 && $3 == "True" { found=1; exit 0 } END { if (!found) exit 1 }'
  statuses=("${PIPESTATUS[@]}")
  set -o pipefail
  if (( statuses[1] != 0 )); then
    echo "ERROR: VaultStaticSecret $NAMESPACE/$name did not become current and SecretSynced=True within $WAIT_TIMEOUT" >&2
    exit 1
  fi
done
