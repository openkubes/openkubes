#!/usr/bin/env bash
# Temporary guard for the initial MkDocs GitHub Pages cutover.
# The existing branch-published docs/ website must remain byte-for-byte
# recoverable before switching the publishing source to GitHub Actions.
set -euo pipefail
cd "$(dirname "$0")/../.."

BASELINE="c16fff88ddbf11f24e8e7a60e8f8dfec2527d9ee"
git cat-file -e "${BASELINE}^{commit}"
if ! git diff --quiet "$BASELINE" HEAD -- docs/; then
  echo "::error::Legacy docs/ differs from the pre-cutover backup ${BASELINE}."
  echo "::error::Do not proceed until a new rollback snapshot and procedure are approved."
  exit 1
fi
test "$(git show "${BASELINE}:docs/CNAME")" = "openkubes.org"
test "$(cat docs/CNAME)" = "openkubes.org"
test -f docs/index.html
echo "Pre-cutover rollback guard passed: docs/ equals saved baseline ${BASELINE}."
