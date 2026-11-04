#!/usr/bin/env bash
#
# OK-211 — render a manifest template: replace __NAME__ with the value of NAME
# from versions.env (pins are maintained there only, B6) and print the result.
#
# Usage: scripts/render.sh <file>...
# Fails (exit 1) if a placeholder has no value or one is left unreplaced, so a
# missing pin can never become an empty image reference.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./lib.sh
. "$SCRIPT_DIR/lib.sh"
ok211::load_versions

[ "$#" -gt 0 ] || ok211::die "usage: $0 <file>..." 2
for f in "$@"; do
  content="$(cat "$f")"
  while IFS= read -r name; do
    value="${!name:-}"
    [ -n "$value" ] || ok211::die "$f: no value for placeholder __${name}__ in versions.env" 1
    content="${content//__${name}__/$value}"
  done < <(grep -oE '__[A-Z0-9_]+__' "$f" | sort -u | sed 's/^__//; s/__$//')
  if printf '%s' "$content" | grep -qE '__[A-Z0-9_]+__'; then
    ok211::die "$f: unreplaced placeholder left" 1
  fi
  printf '%s\n---\n' "$content"
done
