#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# VaultInstance singleton conformance — ADR-Platform-025 criterion 14, OK-110.
#
# Deterministic, re-runnable, READ-ONLY check that the singleton invariant is
# actually ENFORCED (not merely documented) on the target cluster (ok-mgmt):
#
#   1. the ValidatingAdmissionPolicy is installed and fail-closed (Fail);
#   2. its Binding is installed with validationActions: [Deny];
#   3. the live VaultInstance population is <= 1, and the one that exists (if
#      any) is named `ok-shared-vault`.
#
# It does NOT prove that a second CREATE is rejected — that is the companion
# negative test (singleton-negative-test.sh), which exercises the policy.
#
# Read-only: only `kubectl get`. Exit 0 iff every REQUIRED check PASSed; any
# FAIL → exit 1. Dependencies: kubectl, jq.
#
# Usage:
#   KUBECONFIG=~/.kube/ok-mgmt.yaml ./singleton-conformance.sh [--context CTX]
# ─────────────────────────────────────────────────────────────────────────────
set -u -o pipefail

POLICY="vaultinstance-singleton.platform.openkubes.ai"
XR_RESOURCE="vaultinstances.platform.openkubes.ai"
ALLOWED_NAME="ok-shared-vault"

CTX_ARGS=()
for arg in "$@"; do
  case "$arg" in
    --context) shift; CTX_ARGS=(--context "${1:-}") ;;
    --context=*) CTX_ARGS=(--context "${arg#*=}") ;;
    "") ;;
    *) ;;
  esac
done

for bin in kubectl jq; do
  command -v "$bin" >/dev/null 2>&1 || { echo "ERROR: '$bin' is required" >&2; exit 2; }
done

KUBECTL=(kubectl "${CTX_ARGS[@]}")

FAILS=0
pass() { printf '  PASS  %s\n' "$1"; }
fail() { printf '  FAIL  %s\n' "$1"; FAILS=$((FAILS + 1)); }
warn() { printf '  WARN  %s\n' "$1"; }

echo "VaultInstance singleton conformance (ADR-025 crit. 14)"
echo "-------------------------------------------------------"

# 1. ValidatingAdmissionPolicy present + fail-closed.
if pol_json="$("${KUBECTL[@]}" get validatingadmissionpolicy "$POLICY" -o json 2>/dev/null)"; then
  fp="$(jq -r '.spec.failurePolicy // "Fail"' <<<"$pol_json")"
  if [ "$fp" = "Fail" ]; then
    pass "ValidatingAdmissionPolicy '$POLICY' present and fail-closed (failurePolicy: Fail)"
  else
    fail "ValidatingAdmissionPolicy '$POLICY' is failurePolicy: $fp (expected Fail — fail-closed)"
  fi
  if jq -e '[.spec.validations[].expression] | any(test("ok-shared-vault"))' <<<"$pol_json" >/dev/null; then
    pass "policy pins the singleton name in a validation expression"
  else
    fail "policy has no validation pinning the name '$ALLOWED_NAME'"
  fi
else
  fail "ValidatingAdmissionPolicy '$POLICY' is NOT installed — singleton not enforced"
fi

# 2. Binding present with Deny action, referencing the policy.
if bnd_json="$("${KUBECTL[@]}" get validatingadmissionpolicybinding "$POLICY" -o json 2>/dev/null)"; then
  ref="$(jq -r '.spec.policyName // ""' <<<"$bnd_json")"
  if [ "$ref" = "$POLICY" ]; then
    pass "Binding references policy '$POLICY'"
  else
    fail "Binding policyName is '$ref' (expected '$POLICY')"
  fi
  if jq -e '.spec.validationActions | index("Deny")' <<<"$bnd_json" >/dev/null; then
    pass "Binding enforces validationActions: [Deny]"
  else
    fail "Binding does not Deny (validationActions missing 'Deny') — policy is audit-only"
  fi
else
  fail "ValidatingAdmissionPolicyBinding '$POLICY' is NOT installed — policy inert"
fi

# 3. Live VaultInstance population.
if ! names="$("${KUBECTL[@]}" get "$XR_RESOURCE" -o jsonpath='{.items[*].metadata.name}' 2>/dev/null)"; then
  warn "cannot list $XR_RESOURCE (CRD/XRD not installed yet?) — population check skipped"
else
  # shellcheck disable=SC2206
  arr=($names)
  count=${#arr[@]}
  if [ "$count" -le 1 ]; then
    pass "VaultInstance population = $count (<= 1, singleton bound holds)"
  else
    fail "VaultInstance population = $count (> 1) — singleton VIOLATED: ${arr[*]}"
  fi
  if [ "$count" -eq 1 ] && [ "${arr[0]}" != "$ALLOWED_NAME" ]; then
    fail "the single VaultInstance is '${arr[0]}' (expected '$ALLOWED_NAME')"
  elif [ "$count" -eq 0 ]; then
    warn "no VaultInstance exists yet — enforcement is in place, singleton not yet created"
  fi
fi

echo "-------------------------------------------------------"
if [ "$FAILS" -eq 0 ]; then
  echo "RESULT: PASS — singleton invariant is enforced (crit. 14)"
  exit 0
fi
echo "RESULT: FAIL — $FAILS check(s) failed"
exit 1
