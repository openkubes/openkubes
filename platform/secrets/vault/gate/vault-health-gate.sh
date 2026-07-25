#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Vault health gate — datacenter secret backend (ADR-Platform-025, OK-110)
#
# Deterministic, re-runnable RUNTIME gate against a LIVE Vault. This is the
# "readiness ≠ installed" gate from ADR-025: provider-helm's Release=deployed
# only proves INSTALLED; operational readiness is asserted here and supplies
# acceptance evidence (mirrors the observability contract-test-gate discipline).
#
# States asserted:
#   Initialized  Unsealed  RaftHealthy  TLSReady  AuditEnabled  Configured
#
# Read-only. Unauthenticated checks use sys/health + sys/seal-status + the TLS
# handshake. Authenticated checks (RaftHealthy autopilot, AuditEnabled,
# Configured) need a token (VAULT_TOKEN); without one they are reported SKIP
# unless --require-auth is set (then they FAIL).
#
# Exit code: 0 only if every REQUIRED check PASSed. Any FAIL → exit 1.
# SKIP does not fail the gate unless --require-auth promotes it to a FAIL.
#
# Dependencies: bash, curl, jq, openssl.
#
# Usage:
#   VAULT_ADDR=https://vault.ok-shared.internal:443 \
#   VAULT_CACERT=./ok-shared-ca.crt \
#   VAULT_SNI=vault.ok-shared.internal \
#   VAULT_EXPECT_REPLICAS=3 \
#   VAULT_TOKEN=s.xxxx \
#   VAULT_EXPECT_AUTH_MOUNTS=ok-robotics \
#   VAULT_RESOLVE_IP=192.168.100.x \   # optional: pin SNI host to an IP (ingress)
#   ./vault-health-gate.sh [--require-auth] [--json]
# ─────────────────────────────────────────────────────────────────────────────
set -u -o pipefail

VAULT_ADDR="${VAULT_ADDR:-https://vault.ok-shared.internal:443}"
VAULT_CACERT="${VAULT_CACERT:-}"
VAULT_SNI="${VAULT_SNI:-vault.ok-shared.internal}"
VAULT_EXPECT_REPLICAS="${VAULT_EXPECT_REPLICAS:-3}"
VAULT_TOKEN="${VAULT_TOKEN:-}"
VAULT_EXPECT_AUTH_MOUNTS="${VAULT_EXPECT_AUTH_MOUNTS:-}"   # comma-sep cluster ids

REQUIRE_AUTH=0
JSON_OUT=0
for arg in "$@"; do
  case "$arg" in
    --require-auth) REQUIRE_AUTH=1 ;;
    --json)         JSON_OUT=1 ;;
    *) echo "unknown arg: $arg" >&2; exit 2 ;;
  esac
done

for bin in curl jq openssl; do
  command -v "$bin" >/dev/null 2>&1 || { echo "ERROR: '$bin' is required" >&2; exit 2; }
done

# host:port for openssl (strip scheme)
HOSTPORT="${VAULT_ADDR#*://}"
HOST="${HOSTPORT%%:*}"
PORT="${HOSTPORT##*:}"; [ "$PORT" = "$HOST" ] && PORT=443

CURL=(curl -sS --max-time 10)
[ -n "$VAULT_CACERT" ] && CURL+=(--cacert "$VAULT_CACERT")
# Optional SNI pinning: present VAULT_SNI while connecting to an explicit IP.
# Portable (no getent). Only needed when the SNI host does not resolve to the
# target — e.g. hitting the ingress MetalLB IP directly. For a port-forward,
# leave VAULT_RESOLVE_IP unset and curl uses VAULT_ADDR's host directly.
if [ -n "${VAULT_RESOLVE_IP:-}" ] && [ -n "$VAULT_SNI" ]; then
  CURL+=(--resolve "${VAULT_SNI}:${PORT}:${VAULT_RESOLVE_IP}")
fi

declare -a RESULTS   # "STATE|VERDICT|detail"
FAILED=0

record() { RESULTS+=("$1|$2|$3"); [ "$2" = "FAIL" ] && FAILED=1; }

vault_api() { # $1 = path ; uses token if set
  local path="$1"; shift || true
  if [ -n "$VAULT_TOKEN" ]; then
    "${CURL[@]}" -H "X-Vault-Token: ${VAULT_TOKEN}" "${VAULT_ADDR}${path}" "$@"
  else
    "${CURL[@]}" "${VAULT_ADDR}${path}" "$@"
  fi
}

# ── TLSReady ─────────────────────────────────────────────────────────────────
# Handshake must succeed against the pinned CA, the presented cert must carry the
# expected SNI in its SANs, and plain-HTTP to the API must NOT work (tls off).
check_tls() {
  local sans
  sans="$(echo | openssl s_client -connect "${HOST}:${PORT}" -servername "${VAULT_SNI}" \
          ${VAULT_CACERT:+-CAfile "$VAULT_CACERT"} 2>/dev/null \
          | openssl x509 -noout -ext subjectAltName 2>/dev/null)"
  if [ -z "$sans" ]; then
    record TLSReady FAIL "TLS handshake/cert read failed against ${HOST}:${PORT} (CA=${VAULT_CACERT:-none})"
    return
  fi
  if ! echo "$sans" | grep -q "DNS:${VAULT_SNI}"; then
    record TLSReady FAIL "server cert SAN does not include DNS:${VAULT_SNI} — got: $(echo "$sans" | tr -d '\n')"
    return
  fi
  # verify chain against the pinned CA explicitly
  if [ -n "$VAULT_CACERT" ]; then
    if ! echo | openssl s_client -connect "${HOST}:${PORT}" -servername "${VAULT_SNI}" \
          -CAfile "$VAULT_CACERT" -verify_return_error >/dev/null 2>&1; then
      record TLSReady FAIL "cert does not verify against pinned CA ${VAULT_CACERT}"
      return
    fi
  fi
  record TLSReady PASS "TLS ok, SAN includes ${VAULT_SNI}$([ -n "$VAULT_CACERT" ] && echo ', chain verified')"
}

# ── Initialized + Unsealed ───────────────────────────────────────────────────
check_seal() {
  local js init sealed t n
  js="$(vault_api /v1/sys/seal-status)" || { record Initialized FAIL "sys/seal-status unreachable"; record Unsealed FAIL "sys/seal-status unreachable"; return; }
  init="$(echo "$js" | jq -r '.initialized // empty')"
  sealed="$(echo "$js" | jq -r '.sealed // empty')"
  t="$(echo "$js" | jq -r '.t // empty')"; n="$(echo "$js" | jq -r '.n // empty')"
  if [ "$init" = "true" ]; then record Initialized PASS "initialized";
  elif [ "$init" = "false" ]; then record Initialized FAIL "NOT initialized (run bootstrap ceremony)";
  else record Initialized FAIL "could not read .initialized: $js"; fi
  if [ "$sealed" = "false" ]; then record Unsealed PASS "unsealed (threshold ${t}/${n})";
  elif [ "$sealed" = "true" ]; then record Unsealed FAIL "SEALED (unseal threshold ${t}/${n} not met)";
  else record Unsealed FAIL "could not read .sealed: $js"; fi
}

# ── RaftHealthy (authenticated: autopilot state) ─────────────────────────────
check_raft() {
  if [ -z "$VAULT_TOKEN" ]; then
    [ "$REQUIRE_AUTH" = 1 ] && record RaftHealthy FAIL "no VAULT_TOKEN (--require-auth)" \
                            || record RaftHealthy SKIP "no VAULT_TOKEN — authenticated check skipped"
    return
  fi
  local js healthy voters leader
  js="$(vault_api /v1/sys/storage/raft/autopilot/state)" || { record RaftHealthy FAIL "autopilot state unreachable"; return; }
  healthy="$(echo "$js" | jq -r '.data.healthy // empty')"
  leader="$(echo "$js" | jq -r '.data.leader // empty')"
  voters="$(echo "$js" | jq -r '[.data.servers[]? | select(.status=="voter")] | length')"
  if [ "$healthy" = "true" ] && [ -n "$leader" ] && [ "$voters" = "$VAULT_EXPECT_REPLICAS" ]; then
    record RaftHealthy PASS "healthy, leader=${leader}, voters=${voters}/${VAULT_EXPECT_REPLICAS}"
  else
    record RaftHealthy FAIL "healthy=${healthy} leader=${leader:-none} voters=${voters}/${VAULT_EXPECT_REPLICAS}"
  fi
}

# ── AuditEnabled (authenticated) ─────────────────────────────────────────────
check_audit() {
  if [ -z "$VAULT_TOKEN" ]; then
    [ "$REQUIRE_AUTH" = 1 ] && record AuditEnabled FAIL "no VAULT_TOKEN (--require-auth)" \
                            || record AuditEnabled SKIP "no VAULT_TOKEN — authenticated check skipped"
    return
  fi
  local js count
  js="$(vault_api /v1/sys/audit)" || { record AuditEnabled FAIL "sys/audit unreachable"; return; }
  count="$(echo "$js" | jq -r '[.data // . | to_entries[] | select(.key|endswith("/"))] | length')"
  if [ "${count:-0}" -ge 1 ]; then record AuditEnabled PASS "${count} audit device(s) enabled";
  else record AuditEnabled FAIL "no audit device enabled (bootstrap must enable one before revoking root)"; fi
}

# ── Configured (authenticated; reconciler-dependent — ADR-025 item 13 open) ──
# Minimal, well-defined slice: each expected cluster has its dedicated k8s auth
# mount auth/kubernetes/<cluster> (ADR-025 trust model). Policies/roles depend on
# the still-open Day-1/2 config reconciler decision and are intentionally NOT
# asserted here beyond mount presence.
check_configured() {
  if [ -z "$VAULT_EXPECT_AUTH_MOUNTS" ]; then
    record Configured SKIP "VAULT_EXPECT_AUTH_MOUNTS unset — nothing to assert (config reconciler TBD, ADR-025 item 13)"
    return
  fi
  if [ -z "$VAULT_TOKEN" ]; then
    [ "$REQUIRE_AUTH" = 1 ] && record Configured FAIL "no VAULT_TOKEN (--require-auth)" \
                            || record Configured SKIP "no VAULT_TOKEN — authenticated check skipped"
    return
  fi
  local js missing=""
  js="$(vault_api /v1/sys/auth)" || { record Configured FAIL "sys/auth unreachable"; return; }
  IFS=',' read -ra mounts <<< "$VAULT_EXPECT_AUTH_MOUNTS"
  for m in "${mounts[@]}"; do
    m="$(echo "$m" | xargs)"; [ -z "$m" ] && continue
    echo "$js" | jq -e --arg p "kubernetes/${m}/" '(.data // .) | has($p)' >/dev/null 2>&1 \
      || missing+=" auth/kubernetes/${m}"
  done
  if [ -z "$missing" ]; then record Configured PASS "dedicated k8s auth mount(s) present: ${VAULT_EXPECT_AUTH_MOUNTS}";
  else record Configured FAIL "missing dedicated auth mount(s):${missing}"; fi
}

check_tls
check_seal
check_raft
check_audit
check_configured

# ── Report ───────────────────────────────────────────────────────────────────
if [ "$JSON_OUT" = 1 ]; then
  printf '{"addr":"%s","expect_replicas":%s,"checks":[' "$VAULT_ADDR" "$VAULT_EXPECT_REPLICAS"
  for i in "${!RESULTS[@]}"; do
    IFS='|' read -r s v d <<< "${RESULTS[$i]}"
    printf '%s{"state":"%s","verdict":"%s","detail":"%s"}' "$([ "$i" -gt 0 ] && echo ,)" "$s" "$v" "${d//\"/\'}"
  done
  printf '],"gate":"%s"}\n' "$([ "$FAILED" = 0 ] && echo PASS || echo FAIL)"
else
  echo "Vault health gate — ${VAULT_ADDR} (expect ${VAULT_EXPECT_REPLICAS} voters)"
  echo "──────────────────────────────────────────────────────────────"
  for r in "${RESULTS[@]}"; do
    IFS='|' read -r s v d <<< "$r"
    printf '  %-13s %-4s  %s\n' "$s" "$v" "$d"
  done
  echo "──────────────────────────────────────────────────────────────"
  echo "  GATE: $([ "$FAILED" = 0 ] && echo 'PASS ✅' || echo 'FAIL ❌')"
fi

exit "$FAILED"
