#!/usr/bin/env bash
#
# OK-167 — cluster context guard.
#
# Runs as the first dependency of every Makefile target that reads or changes a
# cluster. Use those targets: Make exports the isolated KUBECONFIG to both the
# guard and its commands. Running `make guard` does not export it to the caller.
#
# It refuses to let anything in this spike talk to a cluster other than the
# local kind cluster. It never contacts a cluster itself: every check reads the
# kubeconfig file only, so the guard also works before the cluster exists and
# can be tested against synthetic kubeconfigs.
#
# Exit codes
#   0  all checks passed
#   10 KUBECONFIG is unset or empty
#   11 KUBECONFIG is not an absolute path
#   12 KUBECONFIG points outside <spike>/.local/
#   13 KUBECONFIG names a file that does not exist
#   14 the kubeconfig holds more or fewer than exactly one context
#   15 the current context is not the expected kind context
#   16 the API server is not on https://127.0.0.1:
#   17 kubectl's minor version is more than one away from the cluster's
#   18 the file is not a parseable kubeconfig
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

# Pins live in versions.env only (BRIEF B8).
if [ -f "$SPIKE_ROOT/versions.env" ]; then
  # shellcheck disable=SC1091
  . "$SPIKE_ROOT/versions.env"
fi

EXPECTED_CONTEXT="${CLUSTER_CONTEXT:-kind-ok167}"
EXPECTED_K8S_VERSION="${KUBERNETES_VERSION:-v1.36.4}"

# kubectl is resolved through a variable so the binary can be swapped. An
# explicit KUBECTL always wins. Otherwise the candidates are tried in order and
# the first one within one minor version of the cluster is chosen: on this host
# the binary first on PATH is Docker Desktop's and lags the pinned node image by
# two minors (evidence/00-preflight.md, finding F2), while Homebrew's is current.
# Picking by version rather than by hard-coded path keeps this working on a host
# where the two are installed the other way round.
if [ -z "${KUBECTL:-}" ]; then
  _want_minor="$(printf '%s' "$EXPECTED_K8S_VERSION" | sed -E 's/^v[0-9]+\.([0-9]+).*/\1/')"
  for _cand in kubectl /opt/homebrew/bin/kubectl /usr/local/bin/kubectl; do
    command -v "$_cand" >/dev/null 2>&1 || continue
    _got_minor="$("$_cand" version --client=true -o json 2>/dev/null \
      | jq -r '.clientVersion.gitVersion // empty' | sed -E 's/^v[0-9]+\.([0-9]+).*/\1/')"
    printf '%s' "$_got_minor" | grep -qE '^[0-9]+$' || continue
    _skew=$(( _got_minor - _want_minor )); [ "$_skew" -lt 0 ] && _skew=$(( -_skew ))
    if [ "$_skew" -le 1 ]; then KUBECTL="$_cand"; break; fi
    # Remember the first usable one so the skew check below can report it.
    [ -z "${KUBECTL:-}" ] && KUBECTL="$_cand"
  done
  KUBECTL="${KUBECTL:-kubectl}"
  unset _want_minor _cand _got_minor _skew
fi

# The canonical kubeconfig for this spike. Anything under .local/ is accepted so
# the guard can be exercised against synthetic kubeconfigs in Phase 1; the
# directory is the security boundary, the file name is only convention. A
# synthetic file that names a real cluster still fails checks 15/16 below.
CANONICAL_KUBECONFIG="$SPIKE_ROOT/.local/kubeconfig"

ok167::require_tool "$KUBECTL" "needed to parse the kubeconfig"
ok167::require_tool jq "needed to parse kubectl's JSON output"

# ---------------------------------------------------------------------------
# 1. KUBECONFIG must be set
# ---------------------------------------------------------------------------
if [ -z "${KUBECONFIG:-}" ]; then
  ok167::error "KUBECONFIG is unset or empty."
  ok167::error "Expected: $CANONICAL_KUBECONFIG"
  exit 10
fi

# A list of files (a:b:c) is rejected outright: a single path is the only shape
# whose target can be reasoned about.
case "$KUBECONFIG" in
  *:*)
    ok167::error "KUBECONFIG holds multiple paths; exactly one is required."
    exit 11
    ;;
esac

# ---------------------------------------------------------------------------
# 2. KUBECONFIG must be absolute and inside <spike>/.local/
# ---------------------------------------------------------------------------
case "$KUBECONFIG" in
  /*) : ;;
  *)
    ok167::error "KUBECONFIG must be an absolute path, got: $KUBECONFIG"
    ok167::error "Expected: $CANONICAL_KUBECONFIG"
    exit 11
    ;;
esac

# Resolve `..`, symlinked parent directories AND a symlinked final component
# before comparing. Two escapes are possible and both are closed here:
#   <spike>/.local/../../../.kube/config   — traversal through the parent
#   <spike>/.local/link -> ~/.kube/config  — a symlink sitting inside .local/
# macOS has no `readlink -f`, so the final component is followed by hand.
resolve_path() {
  local target="$1"
  local dir base depth=0

  while [ -L "$target" ] && [ "$depth" -lt 32 ]; do
    local link
    link="$(readlink "$target")"
    case "$link" in
      /*) target="$link" ;;
      *)  target="$(dirname "$target")/$link" ;;
    esac
    depth=$(( depth + 1 ))
  done
  if [ "$depth" -ge 32 ]; then
    ok167::error "KUBECONFIG resolves through too many symlinks: $1"
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
    ok167::error "KUBECONFIG points outside the spike's .local/ directory."
    ok167::error "  given:    $KUBECONFIG"
    ok167::error "  resolved: $RESOLVED_KUBECONFIG"
    ok167::error "  allowed:  ${RESOLVED_ALLOWED_PREFIX}*"
    ok167::error "This spike must never touch a real cluster's kubeconfig."
    exit 12
    ;;
esac

# ---------------------------------------------------------------------------
# 3. The file must exist
# ---------------------------------------------------------------------------
if [ ! -f "$KUBECONFIG" ]; then
  ok167::error "KUBECONFIG names a file that does not exist: $KUBECONFIG"
  ok167::error "Run 'make up' first; kind writes the kubeconfig there."
  exit 13
fi

# ---------------------------------------------------------------------------
# 3b. The file must be a parseable kubeconfig
# ---------------------------------------------------------------------------
# Without this, a file that is not a kubeconfig at all (a symlink to /etc/hosts,
# a truncated write) makes kubectl fail inside a pipeline and `set -o pipefail`
# turns it into a bare exit 1 with no explanation. A guard that fails
# incomprehensibly gets disabled, so it fails clearly instead.
if ! KUBECONFIG_JSON="$("$KUBECTL" config view -o json 2>&1)"; then
  ok167::error "KUBECONFIG is not a parseable kubeconfig: $KUBECONFIG"
  # Parser diagnostics can include malformed credential fields; do not echo them.
  exit 18
fi
if ! printf '%s' "$KUBECONFIG_JSON" | jq -e . >/dev/null 2>&1; then
  ok167::error "kubectl returned output that is not JSON for: $KUBECONFIG"
  exit 18
fi

# ---------------------------------------------------------------------------
# 4. Exactly one context
# ---------------------------------------------------------------------------
# A second context is a second way to reach a second cluster. Even if it is not
# current, a stray --context or a `use-context` would reach it.
CONTEXT_COUNT="$(printf '%s' "$KUBECONFIG_JSON" | jq '[.contexts // [] | .[]] | length')"
if [ "$CONTEXT_COUNT" != "1" ]; then
  ok167::error "Expected exactly one context in the kubeconfig, found: $CONTEXT_COUNT"
  if [ "$CONTEXT_COUNT" != "0" ]; then
    ok167::error "Context names: $(printf '%s' "$KUBECONFIG_JSON" | jq -r '[.contexts[].name] | join(", ")')"
  fi
  exit 14
fi

# ---------------------------------------------------------------------------
# 5. The current context must be the expected kind context
# ---------------------------------------------------------------------------
CURRENT_CONTEXT="$("$KUBECTL" config current-context 2>/dev/null || true)"
if [ "$CURRENT_CONTEXT" != "$EXPECTED_CONTEXT" ]; then
  ok167::error "Current context is '${CURRENT_CONTEXT:-<none>}', expected '$EXPECTED_CONTEXT'."
  exit 15
fi

# ---------------------------------------------------------------------------
# 6. The API server must be local
# ---------------------------------------------------------------------------
# kind publishes its API server on 127.0.0.1 with a random high port. Anything
# else means the context points somewhere this spike must not reach.
CLUSTER_NAME_FOR_CONTEXT="$(printf '%s' "$KUBECONFIG_JSON" \
  | jq -r --arg ctx "$CURRENT_CONTEXT" '.contexts[] | select(.name == $ctx) | .context.cluster')"
SERVER_URL="$(printf '%s' "$KUBECONFIG_JSON" \
  | jq -r --arg c "$CLUSTER_NAME_FOR_CONTEXT" '.clusters[] | select(.name == $c) | .cluster.server')"

# Match the complete authority. A prefix check accepts userinfo such as
# https://127.0.0.1:443@remote.example:6443, whose actual host is remote.example.
if [[ ! "$SERVER_URL" =~ ^https://127[.]0[.]0[.]1:([0-9]{1,5})$ ]]; then
  ok167::die "API server must be exactly https://127.0.0.1:<port>, without userinfo, path or query" 16
fi
PORT=$(( 10#${BASH_REMATCH[1]} ))
[ "$PORT" -ge 1 ] && [ "$PORT" -le 65535 ] \
  || ok167::die "API server port is outside 1..65535" 16

# kind embeds its CA and client keys. File references, credential plugins and
# proxies are unnecessary here and could escape the spike's access boundary.
# config view does not execute plugins or flatten referenced credential files.
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
  ok167::die "kubeconfig must contain one local cluster/user, embedded credentials, verified TLS and no proxy/plugin" 16
fi

# ---------------------------------------------------------------------------
# 7. kubectl version skew
# ---------------------------------------------------------------------------
# B6 requires kubectl within one minor version of the cluster. The binary first
# on PATH is Docker Desktop's and is two minors behind the pinned node image, so
# this is checked rather than assumed.
CLIENT_MINOR="$("$KUBECTL" version --client=true -o json 2>/dev/null \
  | jq -r '.clientVersion.gitVersion' | sed -E 's/^v[0-9]+\.([0-9]+).*/\1/')"
CLUSTER_MINOR="$(printf '%s' "$EXPECTED_K8S_VERSION" | sed -E 's/^v[0-9]+\.([0-9]+).*/\1/')"

if ! printf '%s' "$CLIENT_MINOR" | grep -qE '^[0-9]+$' \
  || ! printf '%s' "$CLUSTER_MINOR" | grep -qE '^[0-9]+$'; then
  ok167::die "Could not determine kubectl/cluster minor versions; refusing to skip the skew check" 17
else
  SKEW=$(( CLIENT_MINOR - CLUSTER_MINOR ))
  [ "$SKEW" -lt 0 ] && SKEW=$(( -SKEW ))
  if [ "$SKEW" -gt 1 ]; then
    ok167::error "kubectl minor v1.$CLIENT_MINOR is $SKEW minors from cluster v1.$CLUSTER_MINOR (max 1)."
    ok167::error "kubectl in use: $(command -v "$KUBECTL")"
    ok167::error "Set KUBECTL to a closer binary, e.g. KUBECTL=/opt/homebrew/bin/kubectl."
    exit 17
  fi
fi

# ---------------------------------------------------------------------------
# Passed
# ---------------------------------------------------------------------------
if [ "${OK167_GUARD_QUIET:-0}" != "1" ]; then
  ok167::ok "guard: context=$CURRENT_CONTEXT server=$SERVER_URL kubeconfig=${KUBECONFIG#"$SPIKE_ROOT/"}"
fi
