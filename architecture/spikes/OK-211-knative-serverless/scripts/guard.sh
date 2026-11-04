#!/usr/bin/env bash
#
# OK-211 — cluster context guard (adapted from OK-167 scripts/guard.sh).
#
# Runs as the first dependency of every Makefile target that reads or changes
# the cluster. Make exports the isolated KUBECONFIG to the guard and to the
# commands that follow it.
#
# It refuses to let anything in this spike talk to a cluster other than the
# K3s cluster in the VM ok-knative-local, reached through the SSH tunnel on
# https://127.0.0.1:6450. Checks 1-5 read the kubeconfig file only, so they
# also work before the cluster exists and can be tested against synthetic
# kubeconfigs. Check 6 (`--node`) asks the API server and is used from
# Phase 2 on.
#
# Usage: scripts/guard.sh [--node]
#
# Exit codes
#   0  all checks passed
#   10 KUBECONFIG is unset or empty
#   11 KUBECONFIG is not a single absolute path
#   12 KUBECONFIG points outside <spike>/.local/ (also through a symlink)
#   13 KUBECONFIG names a file that does not exist
#   14 the kubeconfig holds more or fewer than exactly one context
#   15 the current context is not ok211
#   16 the API server is not exactly https://127.0.0.1:6450, or the kubeconfig
#      uses proxies, plugins, external credential files or skips TLS checks
#   17 kubectl's minor version differs from the cluster's
#   18 the file is not a readable, parseable kubeconfig
#   19 the kubectl in use is not <spike>/.local/bin/kubectl
#   20 (--node) the cluster does not consist of exactly the node ok-knative-local
#   2  a prerequisite of the guard itself is missing
#
# On a path outside .local/ the guard prints the offending path but never the
# file's contents: a kubeconfig for a real cluster is exactly the thing that
# must not end up in the session output.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPIKE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# shellcheck source=./lib.sh
. "$SCRIPT_DIR/lib.sh"
ok211::load_versions

CHECK_NODE=0
case "${1:-}" in
  --node) CHECK_NODE=1 ;;
  '') : ;;
  *) ok211::die "usage: $0 [--node]" 2 ;;
esac

EXPECTED_CONTEXT="$CLUSTER_CONTEXT"
EXPECTED_SERVER="$API_SERVER"
EXPECTED_K8S_VERSION="$KUBERNETES_VERSION"
EXPECTED_NODE="$VM_NAME"
CANONICAL_KUBECONFIG="$SPIKE_ROOT/.local/kubeconfig"
CANONICAL_KUBECTL="$SPIKE_ROOT/.local/bin/kubectl"

ok211::require_tool jq "needed to parse kubectl's JSON output"

# ---------------------------------------------------------------------------
# 0. kubectl must be the pinned binary in .local/bin/ (B4 rule 3, B8 check 5)
# ---------------------------------------------------------------------------
# A kubectl from PATH is two minors away on this host (OK-167 F2) and could
# carry a different plugin or credential setup. The comparison uses physical
# paths so a symlink in .local/bin/ pointing elsewhere is also refused.
KUBECTL="${KUBECTL:-$CANONICAL_KUBECTL}"
physical() {
  local p="$1" d
  d="$(dirname "$p")"
  [ -d "$d" ] || { printf '%s\n' "$p"; return; }
  while [ -L "$p" ]; do
    local l; l="$(readlink "$p")"
    case "$l" in /*) p="$l" ;; *) p="$(dirname "$p")/$l" ;; esac
  done
  printf '%s/%s\n' "$(cd "$(dirname "$p")" && pwd -P)" "$(basename "$p")"
}
case "$KUBECTL" in
  /*) : ;;
  *) KUBECTL="$(command -v "$KUBECTL" 2>/dev/null || printf '%s' "$KUBECTL")" ;;
esac
if [ "$(physical "$KUBECTL")" != "$(physical "$CANONICAL_KUBECTL")" ]; then
  ok211::error "kubectl in use is '$KUBECTL', expected ${CANONICAL_KUBECTL#"$SPIKE_ROOT/"}."
  ok211::error "Never use a kubectl from PATH; run 'make kubectl-pin'."
  exit 19
fi
[ -x "$CANONICAL_KUBECTL" ] || ok211::die "pinned kubectl missing: run 'make kubectl-pin'" 2

# ---------------------------------------------------------------------------
# 1. KUBECONFIG must be set, single, absolute
# ---------------------------------------------------------------------------
if [ -z "${KUBECONFIG:-}" ]; then
  ok211::error "KUBECONFIG is unset or empty."
  ok211::error "Expected: $CANONICAL_KUBECONFIG"
  exit 10
fi
case "$KUBECONFIG" in
  *:*)
    ok211::error "KUBECONFIG holds multiple paths; exactly one is required."
    exit 11
    ;;
esac
case "$KUBECONFIG" in
  /*) : ;;
  *)
    ok211::error "KUBECONFIG must be an absolute path, got: $KUBECONFIG"
    exit 11
    ;;
esac

# ---------------------------------------------------------------------------
# 2. KUBECONFIG must resolve to a path inside <spike>/.local/
# ---------------------------------------------------------------------------
# Two escapes are closed here (OK-167 hurdle C5):
#   <spike>/.local/../../../.kube/config   — traversal through the parent
#   <spike>/.local/link -> ~/.kube/config  — a symlink sitting inside .local/
# macOS has no `readlink -f`, so the final component is followed by hand.
resolve_path() {
  local target="$1" dir base depth=0 link
  while [ -L "$target" ] && [ "$depth" -lt 32 ]; do
    link="$(readlink "$target")"
    case "$link" in
      /*) target="$link" ;;
      *)  target="$(dirname "$target")/$link" ;;
    esac
    depth=$(( depth + 1 ))
  done
  if [ "$depth" -ge 32 ]; then
    ok211::error "KUBECONFIG resolves through too many symlinks: $1"
    exit 12
  fi
  dir="$(dirname "$target")"
  base="$(basename "$target")"
  if [ -d "$dir" ]; then
    printf '%s/%s\n' "$(cd "$dir" && pwd -P)" "$base"
  else
    printf '%s\n' "$target"
  fi
}

RESOLVED_KUBECONFIG="$(resolve_path "$KUBECONFIG")"
RESOLVED_ALLOWED_PREFIX="$(cd "$SPIKE_ROOT" && pwd -P)/.local/"
case "$RESOLVED_KUBECONFIG" in
  "$RESOLVED_ALLOWED_PREFIX"*) : ;;
  *)
    ok211::error "KUBECONFIG points outside the spike's .local/ directory."
    ok211::error "  given:    $(printf '%s' "$KUBECONFIG" | ok211::tilde)"
    ok211::error "  resolved: $(printf '%s' "$RESOLVED_KUBECONFIG" | ok211::tilde)"
    ok211::error "This spike must never touch a real cluster's kubeconfig."
    exit 12
    ;;
esac

# ---------------------------------------------------------------------------
# 3. The file must exist and be a readable, parseable kubeconfig
# ---------------------------------------------------------------------------
if [ ! -f "$KUBECONFIG" ]; then
  ok211::error "KUBECONFIG names a file that does not exist: ${KUBECONFIG#"$SPIKE_ROOT/"}"
  ok211::error "Run 'make kubeconfig' (Phase 2) first."
  exit 13
fi
if [ ! -r "$KUBECONFIG" ]; then
  ok211::error "KUBECONFIG is not readable: ${KUBECONFIG#"$SPIKE_ROOT/"}"
  exit 18
fi
# Without this, a file that is not a kubeconfig at all makes kubectl fail
# inside a pipeline and `pipefail` turns it into a bare exit 1. A guard that
# fails incomprehensibly gets disabled, so it fails clearly instead.
if ! KUBECONFIG_JSON="$("$KUBECTL" config view -o json 2>/dev/null)"; then
  ok211::error "KUBECONFIG is not a parseable kubeconfig: ${KUBECONFIG#"$SPIKE_ROOT/"}"
  # Parser diagnostics can include malformed credential fields; do not echo them.
  exit 18
fi
if ! printf '%s' "$KUBECONFIG_JSON" | jq -e 'type == "object"' >/dev/null 2>&1; then
  ok211::error "kubectl returned output that is not a JSON object for: ${KUBECONFIG#"$SPIKE_ROOT/"}"
  exit 18
fi

# ---------------------------------------------------------------------------
# 4. Exactly one context
# ---------------------------------------------------------------------------
# A second context is a second way to reach a second cluster. Even if it is not
# current, a stray --context or a `use-context` would reach it.
CONTEXT_COUNT="$(printf '%s' "$KUBECONFIG_JSON" | jq '[.contexts // [] | .[]] | length')"
if [ "$CONTEXT_COUNT" != "1" ]; then
  ok211::error "Expected exactly one context in the kubeconfig, found: $CONTEXT_COUNT"
  if [ "$CONTEXT_COUNT" != "0" ]; then
    ok211::error "Context names: $(printf '%s' "$KUBECONFIG_JSON" | jq -r '[.contexts[].name] | join(", ")')"
  fi
  exit 14
fi

# ---------------------------------------------------------------------------
# 5. The current context must be ok211
# ---------------------------------------------------------------------------
CURRENT_CONTEXT="$(printf '%s' "$KUBECONFIG_JSON" | jq -r '.["current-context"] // ""')"
if [ "$CURRENT_CONTEXT" != "$EXPECTED_CONTEXT" ]; then
  ok211::error "Current context is '${CURRENT_CONTEXT:-<none>}', expected '$EXPECTED_CONTEXT'."
  exit 15
fi

# ---------------------------------------------------------------------------
# 6. The API server must be exactly the tunnel endpoint
# ---------------------------------------------------------------------------
# An exact string match. A prefix check would accept userinfo such as
# https://127.0.0.1:6450@remote.example:6443, and any other loopback port may
# be an ok-local tunnel (6443, 6444).
CLUSTER_NAME_FOR_CONTEXT="$(printf '%s' "$KUBECONFIG_JSON" \
  | jq -r --arg ctx "$CURRENT_CONTEXT" '.contexts[] | select(.name == $ctx) | .context.cluster')"
SERVER_URL="$(printf '%s' "$KUBECONFIG_JSON" \
  | jq -r --arg c "$CLUSTER_NAME_FOR_CONTEXT" '[.clusters[]? | select(.name == $c) | .cluster.server][0] // ""')"
if [ "$SERVER_URL" != "$EXPECTED_SERVER" ]; then
  ok211::error "API server is '${SERVER_URL:-<none>}', expected exactly '$EXPECTED_SERVER'."
  exit 16
fi

# K3s embeds its CA and client keys. File references, credential plugins,
# proxies and skipped TLS verification are unnecessary here and could escape
# the spike's access boundary (B4 rule 9).
# shellcheck disable=SC2016  # jq variables are literal
if ! printf '%s' "$KUBECONFIG_JSON" | jq -e --arg cluster "$CLUSTER_NAME_FOR_CONTEXT" '
  (.clusters | length) == 1 and
  (.users | length) == 1 and
  (.clusters[0].name == $cluster) and
  (.contexts[0].context.user == .users[0].name) and
  (.clusters[0].cluster | (.["insecure-skip-tls-verify"] // false) == false and
    (.["proxy-url"] // "") == "" and
    (.["certificate-authority"] // "") == "" and
    (.["tls-server-name"] // "") == "") and
  (.users[0].user | has("exec") or has("auth-provider") or
    has("client-certificate") or has("client-key") or has("tokenFile") | not)
' >/dev/null; then
  ok211::error "kubeconfig must hold one cluster and one user with embedded credentials, verified TLS and no proxy or plugin."
  exit 16
fi

# ---------------------------------------------------------------------------
# 7. kubectl minor version must equal the cluster's
# ---------------------------------------------------------------------------
CLIENT_MINOR="$("$KUBECTL" version --client=true -o json 2>/dev/null \
  | jq -r '.clientVersion.gitVersion // ""' | sed -E 's/^v[0-9]+\.([0-9]+).*/\1/')"
CLUSTER_MINOR="$(printf '%s' "$EXPECTED_K8S_VERSION" | sed -E 's/^v[0-9]+\.([0-9]+).*/\1/')"
if ! printf '%s' "$CLIENT_MINOR" | grep -qE '^[0-9]+$' \
  || ! printf '%s' "$CLUSTER_MINOR" | grep -qE '^[0-9]+$'; then
  ok211::die "Could not determine kubectl/cluster minor versions; refusing to skip the skew check" 17
fi
if [ "$CLIENT_MINOR" != "$CLUSTER_MINOR" ]; then
  ok211::error "kubectl minor v1.$CLIENT_MINOR differs from cluster v1.$CLUSTER_MINOR."
  exit 17
fi

# ---------------------------------------------------------------------------
# 8. (--node) The cluster is exactly the single node ok-knative-local
# ---------------------------------------------------------------------------
# Only now, with every static check passed, is the API server contacted.
if [ "$CHECK_NODE" = "1" ]; then
  if ! NODES_JSON="$("$KUBECTL" get nodes -o json --request-timeout=10s 2>/dev/null)"; then
    ok211::error "could not list nodes through $EXPECTED_SERVER (tunnel down? 'make tunnel-status')"
    exit 20
  fi
  NODE_NAMES="$(printf '%s' "$NODES_JSON" | jq -r '[.items[].metadata.name] | join(",")')"
  if [ "$NODE_NAMES" != "$EXPECTED_NODE" ]; then
    ok211::error "cluster nodes are '${NODE_NAMES:-<none>}', expected exactly '$EXPECTED_NODE'."
    exit 20
  fi
  SERVER_MINOR="$("$KUBECTL" version -o json --request-timeout=10s 2>/dev/null \
    | jq -r '.serverVersion.minor // ""' | tr -dc '0-9')"
  if [ "$SERVER_MINOR" != "$CLUSTER_MINOR" ]; then
    ok211::error "server minor '${SERVER_MINOR:-?}' differs from the pinned v1.$CLUSTER_MINOR."
    exit 17
  fi
fi

# ---------------------------------------------------------------------------
# Passed
# ---------------------------------------------------------------------------
if [ "${OK211_GUARD_QUIET:-0}" != "1" ]; then
  extra=""; [ "$CHECK_NODE" = "1" ] && extra=" node=$EXPECTED_NODE"
  ok211::ok "guard: context=$CURRENT_CONTEXT server=$SERVER_URL kubectl=v1.$CLIENT_MINOR$extra"
fi
