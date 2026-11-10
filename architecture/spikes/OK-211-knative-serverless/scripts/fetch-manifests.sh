#!/usr/bin/env bash
#
# OK-211 — download upstream release manifests and verify their SHA-256.
#
# Usage: scripts/fetch-manifests.sh <line>
#   <line>  1.23 | 1.24 | cert-manager
#
# Files land in <spike>/.local/manifests/<line>/ (BRIEF B4 rule 10). Nothing is
# ever applied from a URL; later targets apply only these local copies.
#
# Every file is checked against two sources:
#   1. the digest GitHub publishes for the release asset (API field `digest`),
#      fetched at download time — independent of anything in this repository;
#   2. the pin in versions.env (MANIFEST_SHA256_<LINE>_<ASSET>), once that file
#      exists (Phase 1). Before that, the pin check is reported as "no pin yet".
#
# A mismatch against either source is STOP-4: the script exits non-zero and
# deletes nothing, so the offending file can be inspected.
#
# Output: one line per asset on stdout, tab-separated:
#   <line> <repo> <tag> <asset> <sha256> <github-digest-check> <pin-check>
# and .local/manifests/<line>/SHA256SUMS in `shasum -a 256` format.
#
# Exit codes
#   0  all files downloaded and verified
#   1  a checksum mismatch (STOP-4)
#   2  usage error or missing prerequisite
#   3  download or API error
#
# Portability: bash 3.2 (macOS) — no associative arrays, no mapfile.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPIKE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

die() { printf 'FAIL %s\n' "$1" >&2; exit "${2:-1}"; }
info() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >&2; }

for t in curl jq shasum; do
  command -v "$t" >/dev/null 2>&1 || die "required tool not found: $t" 2
done

LINE="${1:-}"
[ -n "$LINE" ] || die "usage: $0 <1.23|1.24|cert-manager>" 2

if [ -f "$SPIKE_ROOT/versions.env" ]; then
  # shellcheck disable=SC1091
  . "$SPIKE_ROOT/versions.env"
fi

# Release tags per line. versions.env wins once it exists; the defaults here
# are the BRIEF B6 values and only bridge Phase 0, before versions.env exists.
case "$LINE" in
  1.23)
    SERVING_TAG="${SERVING_1_23:-knative-v1.23.0}"
    KOURIER_TAG="${KOURIER_1_23:-knative-v1.23.0}"
    EVENTING_TAG="${EVENTING_1_23:-knative-v1.23.1}"
    ;;
  1.24)
    SERVING_TAG="${SERVING_1_24:-knative-v1.24.0}"
    KOURIER_TAG="${KOURIER_1_24:-knative-v1.24.0}"
    EVENTING_TAG="${EVENTING_1_24:-knative-v1.24.0}"
    ;;
  cert-manager)
    CERT_MANAGER_TAG="${CERT_MANAGER_VERSION:-v1.21.3}"
    ;;
  *) die "unknown line '$LINE' (expected 1.23, 1.24 or cert-manager)" 2 ;;
esac

# The asset list: "<repo> <tag> <asset>" per line. serving-default-domain.yaml
# is deliberately absent: its job sets an sslip.io domain, this spike uses
# ok211.internal (BRIEF B6), and a file that is never downloaded cannot be
# applied by accident.
asset_list() {
  case "$LINE" in
    1.23|1.24)
      cat <<EOF
knative/serving $SERVING_TAG serving-crds.yaml
knative/serving $SERVING_TAG serving-core.yaml
knative/serving $SERVING_TAG serving-post-install-jobs.yaml
knative/serving $SERVING_TAG serving-storage-version-migration.yaml
knative-extensions/net-kourier $KOURIER_TAG kourier.yaml
knative/eventing $EVENTING_TAG eventing-crds.yaml
knative/eventing $EVENTING_TAG eventing-core.yaml
knative/eventing $EVENTING_TAG in-memory-channel.yaml
knative/eventing $EVENTING_TAG mt-channel-broker.yaml
knative/eventing $EVENTING_TAG eventing-post-install.yaml
knative/eventing $EVENTING_TAG event-display.yaml
EOF
      ;;
    cert-manager)
      printf 'cert-manager/cert-manager %s cert-manager.yaml\n' "$CERT_MANAGER_TAG"
      ;;
  esac
}

# versions.env key for a pin: MANIFEST_SHA256_1_24_SERVING_CORE and so on.
pin_key() {
  printf 'MANIFEST_SHA256_%s_%s' \
    "$(printf '%s' "$LINE" | tr 'a-z.-' 'A-Z__')" \
    "$(printf '%s' "${1%.yaml}" | tr 'a-z.-' 'A-Z__')"
}

umask 077
OUT_DIR="$SPIKE_ROOT/.local/manifests/$LINE"
API_DIR="$SPIKE_ROOT/.local/manifests/.api"
mkdir -p "$OUT_DIR" "$API_DIR"
SUMS="$OUT_DIR/SHA256SUMS"
: > "$SUMS.tmp"

CURL=(curl -fsSL --proto '=https' --tlsv1.2 --retry 3 --max-time 120)
mismatch=0

# Read the list from a here-string rather than a pipe so `mismatch` survives
# the loop (OK-167 hurdle C2).
while read -r repo tag asset; do
  [ -n "$repo" ] || continue

  api_json="$API_DIR/$(printf '%s_%s' "$repo" "$tag" | tr '/' '_').json"
  if [ ! -s "$api_json" ]; then
    "${CURL[@]}" -H 'Accept: application/vnd.github+json' \
      "https://api.github.com/repos/$repo/releases/tags/$tag" -o "$api_json" \
      || die "GitHub API request failed for $repo $tag" 3
  fi
  gh_digest="$(jq -r --arg n "$asset" '.assets[] | select(.name == $n) | .digest // empty' "$api_json")"
  [ -n "$gh_digest" ] || die "asset $asset not found in release $repo $tag" 3

  file="$OUT_DIR/$asset"
  info "fetch $repo $tag $asset"
  "${CURL[@]}" "https://github.com/$repo/releases/download/$tag/$asset" -o "$file.part" \
    || die "download failed: $repo $tag $asset" 3
  mv "$file.part" "$file"

  sha="$(shasum -a 256 "$file" | awk '{print $1}')"
  printf '%s  %s\n' "$sha" "$asset" >> "$SUMS.tmp"

  if [ "sha256:$sha" = "$gh_digest" ]; then gh_check="github-ok"
  else gh_check="GITHUB-MISMATCH($gh_digest)"; mismatch=1; fi

  key="$(pin_key "$asset")"
  pin="${!key:-}"
  if [ -z "$pin" ]; then pin_check="no-pin-yet"
  elif [ "$pin" = "$sha" ]; then pin_check="pin-ok"
  else pin_check="PIN-MISMATCH($key=$pin)"; mismatch=1; fi

  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$LINE" "$repo" "$tag" "$asset" "$sha" "$gh_check" "$pin_check"
done <<< "$(asset_list)"

mv "$SUMS.tmp" "$SUMS"

[ "$mismatch" -eq 0 ] || die "checksum mismatch for line $LINE — STOP-4, files kept for inspection in ${OUT_DIR#"$SPIKE_ROOT/"}" 1
info "line $LINE: all files verified, sums in ${SUMS#"$SPIKE_ROOT/"}"
