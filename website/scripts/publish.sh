#!/usr/bin/env bash
# OK-196: GitHub-only, build-first website release.
# Uses reviewed remote main and GitHub Actions; never changes local tracked files.
set -euo pipefail
cd "$(dirname "$0")/../.."

fail() { echo "ERROR: $*" >&2; exit 1; }
require() { command -v "$1" >/dev/null 2>&1 || fail "Missing required command: $1"; }
for cmd in git gh; do require "$cmd"; done

repo="openkubes/openkubes"
preview_workflow="ok196-mkdocs-preview.yml"
release_workflow="ok196-pages-release.yml"

fetch_refs() { git fetch origin main; }
main_sha() { git rev-parse refs/remotes/origin/main; }
verify_remote_revision() {
  local expected="$1"
  fetch_refs
  test "$(main_sha)" = "$expected" ||
    fail "main advanced during validation; restart and review the new commit."
}

# Dispatch exactly one GitHub Actions run, identify by SHA and start time, and watch it.
dispatch_and_watch() {
  local target="$1" workflow="$2" mode="$3" started run_id attempt job
  started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  if test "$mode" = preview; then
    gh workflow run "$workflow" --repo "$repo" --ref main
    job=preview
  elif test "$mode" = dry-run; then
    gh workflow run "$workflow" --repo "$repo" --ref main \
      -f dry_run=true -f expected_sha="$target"
    job=build
  else
    gh workflow run "$workflow" --repo "$repo" --ref main \
      -f dry_run=false -f expected_sha="$target" \
      -f release_confirmation=PUBLISH_OPENKUBES_ORG
    job=publish
  fi
  run_id=""
  for attempt in $(seq 1 30); do
    run_id="$(gh run list --repo "$repo" --workflow "$workflow" \
      --event workflow_dispatch --json databaseId,headSha,createdAt --limit 30 \
      --jq "[.[] | select(.headSha == \"$target\" and .createdAt >= \"$started\")] | sort_by(.createdAt) | reverse | .[0].databaseId // empty")"
    test -n "$run_id" && break
    sleep 2
  done
  test -n "$run_id" || fail "Cannot identify workflow run. Inspect GitHub Actions."
  echo "Watching https://github.com/$repo/actions/runs/$run_id"
  gh run watch "$run_id" --repo "$repo" --exit-status
  test "$(gh run view "$run_id" --repo "$repo" --json conclusion --jq .conclusion)" = success ||
    fail "Workflow did not succeed."
  test "$(gh run view "$run_id" --repo "$repo" --json jobs \
    --jq "[.jobs[] | select(.name == \"$job\" and .conclusion == \"success\")] | length")" = 1 ||
    fail "Expected '$job' job did not succeed."
  echo "Validated commit: $target"
  echo "Build artifacts: https://github.com/$repo/actions/runs/$run_id"
}

preview() {
  local target="$1"
  verify_remote_revision "$target"
  dispatch_and_watch "$target" "$preview_workflow" preview
  verify_remote_revision "$target"
  echo "GitHub Actions preview build succeeded; download the generated HTML from the workflow artifact."
  echo "No public preview site or Cloudflare deployment is used."
}

publish() {
  local target="$1" enabled confirmation
  preview "$target"
  dispatch_and_watch "$target" "$release_workflow" dry-run
  verify_remote_revision "$target"
  echo "Ready to publish reviewed main commit $target to https://openkubes.org/"
  printf 'Type OK to continue: '
  IFS= read -r confirmation </dev/tty || fail "Interactive confirmation required."
  test "$confirmation" = OK || fail "Publication cancelled."
  verify_remote_revision "$target"
  enabled="$(gh variable get OK196_PAGES_RELEASE_ENABLED --repo "$repo" 2>/dev/null || true)"
  test "$enabled" = false ||
    fail "Repository release switch must be false before starting (got '$enabled')."
  (
    trap 'gh variable set OK196_PAGES_RELEASE_ENABLED --repo "$repo" --body false || echo "WARNING: Reset the release variable manually!" >&2' EXIT
    gh variable set OK196_PAGES_RELEASE_ENABLED --repo "$repo" --body true
    dispatch_and_watch "$target" "$release_workflow" production
  )
  echo "Production workflow completed. Verify https://openkubes.org/"
}

case "${1:-}" in
  preview)
    fetch_refs
    preview "$(main_sha)"
    ;;
  release|publish)
    fetch_refs
    publish "$(main_sha)"
    ;;
  status)
    fetch_refs
    printf 'Remote main: %s\n' "$(main_sha)"
    echo "GitHub Actions preview runs:"
    gh run list --repo "$repo" --workflow "$preview_workflow" --limit 5
    echo "GitHub Pages release runs:"
    gh run list --repo "$repo" --workflow "$release_workflow" --limit 5
    ;;
  *)
    echo "Usage: $0 preview|release|publish|status" >&2
    exit 2
    ;;
esac
