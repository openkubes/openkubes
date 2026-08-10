#!/usr/bin/env bash
# Resolve how clients reach the registry, without committing this estate's addresses.
#
# ok-shared runs no MetalLB of its own, and its node network is not reachable from an operator
# workstation, so clients go through the ingress VIP that lives on the infrastructure cluster.
# DNS for the .internal zone is not wired yet (OK-57), which is the only reason an address is
# needed at all: once that name resolves, step 2 below answers and everything else is dead code.
#
# The address is therefore discovered, not hardcoded. It is a property of a particular
# installation, and this repository holds contracts and profiles rather than one estate's
# topology. Sourced, never executed.

: "${REGISTRY_HOST:=registry.ok-shared.internal}"
: "${REGISTRY_CLUSTER:=ok-shared}"

# Where the ingress VIP is published, by convention rather than by literal: the infrastructure
# cluster exposes a LoadBalancer Service named after the workload cluster it fronts.
: "${REGISTRY_LB_SERVICE:=${REGISTRY_CLUSTER}-ingress}"
: "${REGISTRY_LB_NAMESPACE:=${REGISTRY_CLUSTER}}"
: "${REGISTRY_LB_KUBECONFIG:=}"

registry_lb_discover() {
  local address=''

  # 1. An explicit value always wins, for an operator on a different network path.
  if [ -n "${REGISTRY_LB:-}" ]; then
    printf '%s' "$REGISTRY_LB"
    return 0
  fi

  # 2. Real DNS, once OK-57 lands. Preferred, and makes the rest of this obsolete.
  address="$(getent hosts "$REGISTRY_HOST" 2>/dev/null | awk 'NR==1{print $1}')"
  if [ -n "$address" ]; then
    printf '%s' "$address"
    return 0
  fi

  # 3. Ask the infrastructure cluster where it publishes this cluster's ingress.
  if [ -n "$REGISTRY_LB_KUBECONFIG" ] && [ -r "$REGISTRY_LB_KUBECONFIG" ]; then
    address="$(kubectl --kubeconfig "$REGISTRY_LB_KUBECONFIG" \
      -n "$REGISTRY_LB_NAMESPACE" get service "$REGISTRY_LB_SERVICE" \
      -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null)"
    if [ -n "$address" ]; then
      printf '%s' "$address"
      return 0
    fi
  fi

  return 1
}

if [ -z "${REGISTRY_LB:-}" ]; then
  REGISTRY_LB="$(registry_lb_discover)" || {
    echo "ERROR: cannot determine how to reach ${REGISTRY_HOST}." >&2
    echo "       Tried: \$REGISTRY_LB, DNS for ${REGISTRY_HOST}, and the LoadBalancer address of" >&2
    echo "       Service ${REGISTRY_LB_NAMESPACE}/${REGISTRY_LB_SERVICE} on the infrastructure cluster." >&2
    echo "       Set REGISTRY_LB=<ingress address>, or REGISTRY_LB_KUBECONFIG=<infra kubeconfig>." >&2
    return 1 2>/dev/null || exit 1
  }
fi
export REGISTRY_HOST REGISTRY_LB
