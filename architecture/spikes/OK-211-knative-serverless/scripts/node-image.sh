#!/usr/bin/env bash
#
# OK-211 — list or remove a container image on the node (S4, BRIEF B9 Phase 5).
#
# Usage: scripts/node-image.sh list [<pattern>]
#        scripts/node-image.sh rmi <image digest sha256:… or image reference>
#
# Runs `sudo k3s crictl` in ok-knative-local through ok211::vm_ssh. rmi refuses
# when a pod in any namespace still uses the image (B9 S4), and afterwards
# checks that `crictl images --digests` no longer lists it.
# Exit codes: 0 ok, 1 still in use or still listed, 2 usage, 30-33 from lib.sh.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPIKE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=./lib.sh
. "$SCRIPT_DIR/lib.sh"
ok211::load_versions
ok211::vm_guard || exit $?
K="${KUBECTL:-$SPIKE_ROOT/.local/bin/kubectl}"

op="${1:-}"; ref="${2:-}"
case "$op" in
  list)
    ok211::vm_ssh "sudo k3s crictl images --digests" | { if [ -n "$ref" ]; then grep -E "IMAGE|$ref" || true; else cat; fi; }
    ;;
  rmi)
    [ -n "$ref" ] || ok211::die "usage: $0 rmi <digest|reference>" 2
    digest="${ref##*@}"
    case "$digest" in sha256:[0-9a-f]*) : ;; *) ok211::die "rmi needs a digest (sha256:…) or a reference with @sha256:…, got '$ref'" 2 ;; esac
    users="$("$K" get pods -A -o json | jq -r --arg d "$digest" '.items[] | select(any(.status.containerStatuses[]?, .status.initContainerStatuses[]?; (.imageID // "") | endswith($d))) | "\(.metadata.namespace)/\(.metadata.name)"')"
    [ -z "$users" ] || ok211::die "image $digest is still used by: $(echo "$users" | tr '\n' ' ')" 1
    # crictl rmi accepts the image ID; find the ID(s) whose repo digest matches.
    ids="$(ok211::vm_ssh "sudo k3s crictl images --digests -o json" | jq -r --arg d "$digest" '.images[] | select(any(.repoDigests[]?; endswith($d))) | .id')"
    if [ -z "$ids" ]; then
      ok211::info "image $digest not present on the node"
    else
      for id in $ids; do ok211::vm_ssh "sudo k3s crictl rmi $id" >/dev/null; done
    fi
    if ok211::vm_ssh "sudo k3s crictl images --digests -o json" | jq -e --arg d "$digest" 'any(.images[]; any(.repoDigests[]?; endswith($d)))' >/dev/null; then
      ok211::die "image $digest is still listed after rmi" 1
    fi
    ok211::ok "image $digest removed from the node (crictl images --digests no longer lists it)"
    ;;
  *) ok211::die "usage: $0 list [pattern] | rmi <digest>" 2 ;;
esac
