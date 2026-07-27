#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Vault outage evidence snapshot — ADR-Platform-025 crit. 8 / ADR-018.
#
# READ-ONLY. Captures, at a labeled test phase, the consumer-side invariants that
# must hold across a Vault outage (see runbooks/vault-outage-recovery.md):
#
#   - consumer Secret present? + a sha256 of its (base64) contents so you can
#     prove "unchanged during outage" WITHOUT ever printing secret values;
#   - VaultStaticSecret sync condition;
#   - target workload readiness;
#   - Vault pod count + seal state (best-effort).
#
# The one hard invariant: the consumer Secret must be PRESENT at every phase.
# The script EXITS 1 if the Secret is absent (unless --allow-absent), so a broken
# soft-dependency is caught automatically.
#
# Config via env:
#   CONSUMER_CONTEXT (kube context for the consumer, e.g. ok-robotics)
#   CONSUMER_NS      (default: ok-observability)
#   SECRET_NAME      (default: ok-observability-credentials)
#   VSS_NAME         (VaultStaticSecret name; default: $SECRET_NAME)
#   WORKLOADS        (space-separated kind/name, e.g. "statefulset/opensearch-cluster-master deployment/grafana")
#   VAULT_CONTEXT    (kube context for Vault, e.g. ok-shared)
#   VAULT_NS         (default: vault)
#
# Usage:
#   ./outage-evidence.sh --phase baseline [--out crit8-evidence.log] [--allow-absent]
#
# Dependencies: kubectl, jq, sha256sum (or shasum).
# ─────────────────────────────────────────────────────────────────────────────
set -u -o pipefail

CONSUMER_NS="${CONSUMER_NS:-ok-observability}"
SECRET_NAME="${SECRET_NAME:-ok-observability-credentials}"
VSS_NAME="${VSS_NAME:-$SECRET_NAME}"
WORKLOADS="${WORKLOADS:-}"
VAULT_NS="${VAULT_NS:-vault}"

PHASE=""
OUT=""
ALLOW_ABSENT=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --phase) shift; PHASE="${1:-}" ;;
    --phase=*) PHASE="${1#*=}" ;;
    --out) shift; OUT="${1:-}" ;;
    --out=*) OUT="${1#*=}" ;;
    --allow-absent) ALLOW_ABSENT=1 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
  shift
done
[ -n "$PHASE" ] || { echo "ERROR: --phase <name> is required" >&2; exit 2; }

for bin in kubectl jq; do
  command -v "$bin" >/dev/null 2>&1 || { echo "ERROR: '$bin' is required" >&2; exit 2; }
done
sha() { if command -v sha256sum >/dev/null 2>&1; then sha256sum | cut -d' ' -f1; else shasum -a 256 | cut -d' ' -f1; fi; }

CC=(kubectl); [ -n "${CONSUMER_CONTEXT:-}" ] && CC=(kubectl --context "$CONSUMER_CONTEXT")
VC=(kubectl); [ -n "${VAULT_CONTEXT:-}" ] && VC=(kubectl --context "$VAULT_CONTEXT")

ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "════════════════════════════════════════════════════════════════"
echo "PHASE: $PHASE    ($ts)"
echo "────────────────────────────────────────────────────────────────"

# 1. Consumer Secret presence + content hash (no plaintext).
secret_present="no"; secret_hash="-"; secret_rv="-"
if sjson="$("${CC[@]}" -n "$CONSUMER_NS" get secret "$SECRET_NAME" -o json 2>/dev/null)"; then
  secret_present="yes"
  secret_rv="$(jq -r '.metadata.resourceVersion' <<<"$sjson")"
  secret_hash="$(jq -S -c '.data // {}' <<<"$sjson" | sha)"
  nkeys="$(jq -r '(.data // {}) | length' <<<"$sjson")"
  echo "Secret $CONSUMER_NS/$SECRET_NAME: PRESENT  keys=$nkeys  rv=$secret_rv"
  echo "  content-sha256: $secret_hash   (compare across phases; changes only on deliberate rotation)"
else
  echo "Secret $CONSUMER_NS/$SECRET_NAME: ABSENT  <<< INVARIANT BROKEN"
fi

# 2. VaultStaticSecret sync condition (best-effort; VSO condition schema varies).
if vjson="$("${CC[@]}" -n "$CONSUMER_NS" get vaultstaticsecret "$VSS_NAME" -o json 2>/dev/null)"; then
  echo "VaultStaticSecret $VSS_NAME conditions:"
  jq -r '(.status.conditions // []) | if length==0 then "  (no conditions reported)" else .[] | "  - \(.type)=\(.status) reason=\(.reason // "-") msg=\(.message // "-")" end' <<<"$vjson"
else
  echo "VaultStaticSecret $VSS_NAME: not found / CRD absent (SKIP)"
fi

# 3. Target workload readiness.
if [ -n "$WORKLOADS" ]; then
  echo "Workloads:"
  for w in $WORKLOADS; do
    if wj="$("${CC[@]}" -n "$CONSUMER_NS" get "$w" -o json 2>/dev/null)"; then
      ready="$(jq -r '.status.readyReplicas // 0' <<<"$wj")"
      want="$(jq -r '.status.replicas // .spec.replicas // 0' <<<"$wj")"
      echo "  - $w: Ready $ready/$want"
    else
      echo "  - $w: not found (SKIP)"
    fi
  done
fi

# 4. Vault side (best-effort).
vpods="$("${VC[@]}" -n "$VAULT_NS" get pods -l app.kubernetes.io/name=vault --no-headers 2>/dev/null | wc -l | tr -d ' ')"
sealed="unknown"
if [ "${vpods:-0}" -gt 0 ]; then
  sealed="$("${VC[@]}" -n "$VAULT_NS" exec vault-0 -- vault status -format=json 2>/dev/null | jq -r '.sealed' 2>/dev/null || echo unknown)"
fi
echo "Vault ($VAULT_NS): pods=$vpods  sealed=$sealed"

# Append a compact TSV row for the evidence log.
if [ -n "$OUT" ]; then
  printf '%s\t%s\tsecret=%s\thash=%s\trv=%s\tvault_pods=%s\tsealed=%s\n' \
    "$ts" "$PHASE" "$secret_present" "$secret_hash" "$secret_rv" "${vpods:-0}" "$sealed" >>"$OUT"
  echo "(appended to $OUT)"
fi

echo "════════════════════════════════════════════════════════════════"
if [ "$secret_present" != "yes" ] && [ "$ALLOW_ABSENT" -ne 1 ]; then
  echo "RESULT: FAIL — consumer Secret absent at phase '$PHASE' (soft-dependency invariant broken)"
  exit 1
fi
echo "RESULT: captured (phase '$PHASE')"
exit 0
