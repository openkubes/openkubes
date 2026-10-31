#!/usr/bin/env bash
#
# OK-211 — install K3s in ok-knative-local with the ok-local flags (B9 Phase 2).
#
# Deviation from ok-local (README "Deviations from ok-local"): the install
# script is fetched from the versioned tag, its SHA-256 is checked against
# versions.env, and it is copied into the VM instead of being piped from
# get.k3s.io. The script itself then downloads the k3s binary for the pinned
# version and verifies it against the release's sha256sum file.
#
# Idempotent: if K3s already runs the pinned version, nothing is installed.
#
# Exit codes: 0 ok, 1 checksum mismatch (STOP-4), 3 download, 34 timeout, 30-33 lib.sh.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPIKE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=./lib.sh
. "$SCRIPT_DIR/lib.sh"
ok211::load_versions
ok211::vm_guard || exit $?

ip="$(ok211::vm_ip)"
installed="$(ok211::vm_ssh 'k3s --version 2>/dev/null | head -1' || true)"
if printf '%s' "$installed" | grep -qF "k3s version $K3S_VERSION "; then
  ok211::ok "K3s $K3S_VERSION already installed ($installed)"
else
  dir="$SPIKE_ROOT/.local/k3s"; mkdir -p "$dir"
  script="$dir/install-$K3S_VERSION.sh"
  # '+' must be percent-encoded in the tag path.
  url="https://raw.githubusercontent.com/k3s-io/k3s/${K3S_VERSION/+/%2B}/install.sh"
  curl -fsSL --proto '=https' --tlsv1.2 --retry 3 --max-time 120 "$url" -o "$script.part" \
    || ok211::die "download failed: $url" 3
  got="$(shasum -a 256 "$script.part" | awk '{print $1}')"
  [ "$got" = "$K3S_INSTALL_SHA256" ] \
    || ok211::die "install.sh checksum $got != pin $K3S_INSTALL_SHA256 (STOP-4)" 1
  mv "$script.part" "$script"
  ok211::info "install.sh $K3S_VERSION verified (sha256 $got); copying into the VM"
  ok211::vm_scp "$script" /tmp/k3s-install.sh
  ok211::info "running K3s install: --disable=traefik --tls-san=$ip"
  ok211::vm_ssh "sudo env INSTALL_K3S_VERSION='$K3S_VERSION' sh /tmp/k3s-install.sh --disable=traefik --tls-san='$ip' && rm -f /tmp/k3s-install.sh" 2>&1 \
    | tee "$SPIKE_ROOT/.local/k3s/install-$(ok211::stamp).log" | sed 's/^/  k3s-install: /' >&2
fi

ok211::info "waiting for node $VM_NAME to become Ready"
for _ in $(seq 1 60); do
  if ok211::vm_ssh "sudo k3s kubectl get node '$VM_NAME' -o jsonpath='{.status.conditions[?(@.type==\"Ready\")].status}'" 2>/dev/null | grep -qx True; then
    ok211::ok "node $VM_NAME Ready ($(ok211::vm_ssh 'k3s --version | head -1'))"
    exit 0
  fi
  sleep 5
done
ok211::die "node $VM_NAME not Ready within 300 s" 34
