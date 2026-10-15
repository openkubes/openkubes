#!/usr/bin/env bash
# OK-202: read-only Kubernetes preflight for OpenKubes Docs Agent.
# No kubectl apply/create/patch/delete, no secret reads, no credential dumps.
set -u

if ! command -v kubectl >/dev/null 2>&1; then
  echo "ERROR: kubectl not installed" >&2
  exit 1
fi

context="$(kubectl config current-context 2>/dev/null)" || {
  echo "ERROR: no active Kubernetes context" >&2
  exit 1
}
printf 'Active context: %s\n' "$context"
printf 'This script only reads API metadata and public resource names.\n\n'

check() {
  printf '\n=== %s ===\n' "$1"
  shift
  if ! "$@"; then
    printf 'WARNING: command failed or resource absent (see above).\n' >&2
  fi
}

check "kagent API resources" kubectl api-resources --api-group=kagent.dev
check "kagent CRDs (names only)" kubectl get crd agents.kagent.dev modelconfigs.kagent.dev remotemcpservers.kagent.dev -o custom-columns=NAME:.metadata.name,VERSION:.spec.versions[0].name
check "kagent namespaces" kubectl get namespaces -o custom-columns=NAME:.metadata.name
check "kagent pods (no logs/secrets)" kubectl get pods -n kagent -o wide
check "ModelConfigs (namespaces and names only)" kubectl get modelconfigs.kagent.dev -A -o custom-columns=NAMESPACE:.metadata.namespace,NAME:.metadata.name
check "RemoteMCPServers (namespaces and names only)" kubectl get remotemcpservers.kagent.dev -A -o custom-columns=NAMESPACE:.metadata.namespace,NAME:.metadata.name
check "kagent Agent tool schema" kubectl explain agent.spec.declarative.tools --api-version=kagent.dev/v1alpha2
check "kagent RemoteMCPServer schema" kubectl explain remotemcpserver.spec --api-version=kagent.dev/v1alpha2
check "Existing docs namespace (absence expected)" kubectl get namespace openkubes-assistant
check "Ollama service names (no credentials)" kubectl get services -A -o custom-columns=NAMESPACE:.metadata.namespace,NAME:.metadata.name,PORTS:.spec.ports[*].port --no-headers

printf '\nPreflight complete. No cluster resources were changed.\n'
printf 'Review context and output BEFORE attempting a deployment.\n'
