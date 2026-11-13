#!/usr/bin/env bash
#
# OK-211 — fetch the K3s kubeconfig into .local/kubeconfig (B8 `kubeconfig`).
#
# /etc/rancher/k3s/k3s.yaml is redirected straight into a mode-600 file under
# .local/ and never printed (B4 rule 6). Cluster, user and context are renamed
# to ok211 and the server is set to the tunnel endpoint https://127.0.0.1:6450.
# K3s's API certificate includes 127.0.0.1, so TLS verification stays on.
#
# Exit codes: 0 ok, 2 prerequisite, 38 unexpected kubeconfig shape, 30-33 lib.sh.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPIKE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=./lib.sh
. "$SCRIPT_DIR/lib.sh"
ok211::load_versions
ok211::vm_guard || exit $?
ok211::require_tool yq

umask 077
dst="$SPIKE_ROOT/.local/kubeconfig"
tmp="$SPIKE_ROOT/.local/kubeconfig.new"
ok211::touch_private "$tmp"
ok211::vm_ssh 'sudo cat /etc/rancher/k3s/k3s.yaml' > "$tmp"

# The shape K3s writes: one cluster, one user, one context, all named "default".
shape="$(yq -N '[(.clusters|length), (.users|length), (.contexts|length)] | join(",")' "$tmp")"
[ "$shape" = "1,1,1" ] || { rm -f "$tmp"; ok211::die "unexpected kubeconfig shape (clusters,users,contexts) = $shape" 38; }

CTX="$CLUSTER_CONTEXT" SRV="$API_SERVER" yq -i '
  .clusters[0].name = strenv(CTX) |
  .clusters[0].cluster.server = strenv(SRV) |
  .users[0].name = strenv(CTX) |
  .contexts[0].name = strenv(CTX) |
  .contexts[0].context.cluster = strenv(CTX) |
  .contexts[0].context.user = strenv(CTX) |
  .["current-context"] = strenv(CTX)
' "$tmp"
chmod 600 "$tmp"
mv "$tmp" "$dst"
ok211::assert_private "$dst"
ok211::ok "kubeconfig written to .local/kubeconfig (context $CLUSTER_CONTEXT, server $API_SERVER, mode 600)"
