#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# VaultInstance singleton NEGATIVE TEST — ADR-Platform-025 criterion 14, OK-110.
#
# Proves the guard actually ENFORCES: a SECOND VaultInstance is rejected by the
# admission policy. Non-mutating — uses `kubectl apply --dry-run=server`, which
# runs the full admission chain (including the ValidatingAdmissionPolicy) but
# PERSISTS NOTHING.
#
#   NEGATIVE (must be denied): create a decoy VaultInstance with a different
#     name -> expect the API server to reject it with the singleton policy
#     message ("criterion 14" / "singleton").
#   POSITIVE control (must NOT be denied by this policy): the allowed name
#     `ok-shared-vault` passes admission (dry-run OK, or an AlreadyExists error
#     if the singleton already exists — both mean the policy did not block it).
#
# Exit 0 iff the negative case is denied by our policy AND the positive control
# is not blocked by our policy. Dependencies: kubectl.
#
# Usage:
#   KUBECONFIG=~/.kube/ok-mgmt.yaml ./singleton-negative-test.sh [--context CTX]
# ─────────────────────────────────────────────────────────────────────────────
set -u -o pipefail

ALLOWED_NAME="ok-shared-vault"
DECOY_NAME="ok-shared-vault-neg-test"
XR_RESOURCE="vaultinstances.platform.openkubes.ai"
POLICY_SIG='criterion 14|singleton|vaultinstance-singleton'

CTX_ARGS=()
while [ "$#" -gt 0 ]; do
  case "$1" in
    --context) shift; CTX_ARGS=(--context "${1:-}") ;;
    --context=*) CTX_ARGS=(--context "${1#*=}") ;;
    *) ;;
  esac
  shift
done

command -v kubectl >/dev/null 2>&1 || { echo "ERROR: 'kubectl' is required" >&2; exit 2; }
KUBECTL=(kubectl "${CTX_ARGS[@]}")

# Preflight: the VaultInstance CRD/XRD must be present, else the test is moot.
if ! "${KUBECTL[@]}" get crd "$XR_RESOURCE" >/dev/null 2>&1; then
  echo "FAIL: CRD '$XR_RESOURCE' not found — apply the XRD before testing enforcement." >&2
  exit 1
fi

vaultinstance_manifest() {
  cat <<YAML
apiVersion: platform.openkubes.ai/v1alpha1
kind: VaultInstance
metadata:
  name: $1
spec:
  clusterRef: ok-shared
  replicas: 3
  dataStorageClass: local-path
YAML
}

echo "VaultInstance singleton negative test (ADR-025 crit. 14)"
echo "--------------------------------------------------------"

# ── NEGATIVE: a second VaultInstance must be denied by the policy ─────────────
neg_out="$(vaultinstance_manifest "$DECOY_NAME" | "${KUBECTL[@]}" apply --dry-run=server -f - 2>&1)"
neg_rc=$?
if [ "$neg_rc" -eq 0 ]; then
  echo "  FAIL  decoy '$DECOY_NAME' was ADMITTED (dry-run) — singleton NOT enforced."
  echo "        output: $neg_out"
  NEG_OK=0
elif grep -qiE "$POLICY_SIG" <<<"$neg_out"; then
  echo "  PASS  decoy '$DECOY_NAME' denied by the singleton policy."
  echo "        server: $(grep -iE "$POLICY_SIG" <<<"$neg_out" | head -1 | sed 's/^[[:space:]]*//')"
  NEG_OK=1
else
  echo "  FAIL  decoy '$DECOY_NAME' was rejected, but NOT by the singleton policy:"
  echo "        $neg_out"
  NEG_OK=0
fi

# ── POSITIVE control: the allowed name must not be blocked by THIS policy ─────
pos_out="$(vaultinstance_manifest "$ALLOWED_NAME" | "${KUBECTL[@]}" apply --dry-run=server -f - 2>&1)"
pos_rc=$?
if [ "$pos_rc" -eq 0 ]; then
  echo "  PASS  allowed name '$ALLOWED_NAME' passes admission (dry-run OK)."
  POS_OK=1
elif grep -qiE "$POLICY_SIG" <<<"$pos_out"; then
  echo "  FAIL  singleton policy wrongly blocks the allowed name '$ALLOWED_NAME':"
  echo "        $pos_out"
  POS_OK=0
elif grep -qiE "already exists|AlreadyExists" <<<"$pos_out"; then
  echo "  PASS  '$ALLOWED_NAME' not blocked by the policy (already exists — admission passed)."
  POS_OK=1
else
  echo "  WARN  '$ALLOWED_NAME' dry-run failed for an unrelated reason (not the singleton policy):"
  echo "        $pos_out"
  POS_OK=1
fi

echo "--------------------------------------------------------"
if [ "${NEG_OK:-0}" -eq 1 ] && [ "${POS_OK:-0}" -eq 1 ]; then
  echo "RESULT: PASS — a second VaultInstance is rejected; the singleton holds (crit. 14)"
  exit 0
fi
echo "RESULT: FAIL — singleton enforcement not proven"
exit 1
