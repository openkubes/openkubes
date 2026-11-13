#!/usr/bin/env bash
#
# OK-211 — place the pinned kubectl in .local/bin/ (BRIEF B6, B8 `kubectl-pin`).
#
# Downloads kubectl $KUBECTL_VERSION for this host from dl.k8s.io and checks it
# against two sources: the pin in versions.env and the official .sha256 file
# next to the binary. Idempotent: an existing binary with the pinned checksum
# is kept.
#
# Exit codes: 0 ok, 1 checksum mismatch (STOP-4), 2 prerequisite/platform, 3 download.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPIKE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=./lib.sh
. "$SCRIPT_DIR/lib.sh"
ok211::load_versions
ok211::require_tool curl
ok211::require_tool shasum

os="$(uname -s)"; arch="$(uname -m)"
[ "$os" = "Darwin" ] && [ "$arch" = "arm64" ] \
  || ok211::die "only darwin/arm64 is pinned (KUBECTL_SHA256_DARWIN_ARM64); host is $os/$arch" 2
pin="$KUBECTL_SHA256_DARWIN_ARM64"

bin_dir="$SPIKE_ROOT/.local/bin"
target="$bin_dir/kubectl"
mkdir -p "$bin_dir"

if [ -f "$target" ] && [ "$(shasum -a 256 "$target" | awk '{print $1}')" = "$pin" ]; then
  ok211::ok "kubectl $KUBECTL_VERSION already pinned (sha256 $pin)"
  exit 0
fi

url="https://dl.k8s.io/release/$KUBECTL_VERSION/bin/darwin/arm64/kubectl"
CURL=(curl -fsSL --proto '=https' --tlsv1.2)
official="$("${CURL[@]}" --retry 3 --max-time 60 "$url.sha256")" || ok211::die "download failed: $url.sha256" 3
# dl.k8s.io can be slow from this network (≈ 150 KB/s observed on 2026-10-30).
# Each attempt resumes the partial file (-C -) instead of starting over; the
# checksum below decides whether the result is usable, not curl's exit code.
ok211::info "download $url (resumable)"
done_ok=0
for attempt in 1 2 3 4 5 6; do
  if "${CURL[@]}" -C - --max-time 900 --speed-limit 1024 --speed-time 60 "$url" -o "$target.part"; then
    done_ok=1; break
  fi
  ok211::warn "attempt $attempt interrupted at $(wc -c < "$target.part" | tr -d ' ') bytes; resuming"
done
[ "$done_ok" = "1" ] || ok211::die "download failed after 6 attempts: $url" 3
got="$(shasum -a 256 "$target.part" | awk '{print $1}')"

if [ "$got" != "$pin" ] || [ "$got" != "$official" ]; then
  ok211::error "checksum mismatch for kubectl $KUBECTL_VERSION (STOP-4)"
  ok211::error "  downloaded: $got"
  ok211::error "  pin:        $pin"
  ok211::error "  official:   $official"
  ok211::die "kept for inspection: ${target#"$SPIKE_ROOT/"}.part" 1
fi
chmod 755 "$target.part"
mv "$target.part" "$target"
ok211::ok "kubectl $("$target" version --client=true -o json | jq -r .clientVersion.gitVersion) pinned (sha256 $got = pin = official)"
