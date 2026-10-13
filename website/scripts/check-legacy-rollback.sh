#!/usr/bin/env bash
# Verify that the original GitHub Pages website remains recoverable.
# Intentional, reviewed changes to docs/ must not be rejected here.
set -euo pipefail
cd "$(dirname "$0")/../.."

BASELINE="c16fff88ddbf11f24e8e7a60e8f8dfec2527d9ee"

# Require the pinned pre-cutover snapshot in this repository's history.
git cat-file -e "${BASELINE}^{commit}"
git merge-base --is-ancestor "$BASELINE" HEAD || {
  echo "::error::Legacy rollback baseline is not an ancestor of the release commit."
  exit 1
}

# Ensure the snapshot contains a usable legacy homepage and DNS configuration.
git cat-file -e "${BASELINE}:docs/index.html"
git cat-file -e "${BASELINE}:docs/CNAME"
test "$(git show "${BASELINE}:docs/CNAME")" = "openkubes.org"

# Verify we can actually extract the pinned legacy site from Git.
rollback_dir="$(mktemp -d)"
trap 'rm -rf "$rollback_dir"' EXIT
git archive "$BASELINE" docs/ | tar -x -C "$rollback_dir"
test -s "$rollback_dir/docs/index.html"
test "$(cat "$rollback_dir/docs/CNAME")" = "openkubes.org"

# Safeguard the current release's domain, independently of rollback contents.
test "$(cat docs/CNAME)" = "openkubes.org"
test -s docs/index.html

echo "Legacy rollback snapshot is recoverable from ${BASELINE}; reviewed docs/ changes are permitted."
