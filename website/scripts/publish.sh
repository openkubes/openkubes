#!/usr/bin/env bash
# OK-196: preview-first, single-command website release.
# Work exclusively with remote reviewed commits; never mutate contributors' local files.
set -euo pipefail
cd "$(dirname "$0")/../.."

fail() { echo "ERROR: $*" >&2; exit 1; }
require() { command -v "$1" >/dev/null 2>&1 || fail "Missing required command: $1"; }
for cmd in git gh curl; do require "$cmd"; done

repo="openkubes/openkubes"
preview_url="https://preview.openkubes.org/.well-known/ok196-preview-main-sha.txt"
workflow="ok196-pages-release.yml"

fetch_refs() { git fetch origin main website-preview; }
main_sha() { git rev-parse refs/remotes/origin/main; }
check_preview() {
  local wanted="$1" got attempt
  echo "Waiting for Cloudflare preview to serve main commit $wanted ..."
  for attempt in $(seq 1 40); do
    got="$(curl --fail --silent --show-error --location --max-time 15 -H 'Cache-Control: no-cache' "${preview_url}?check=${wanted}-${attempt}" 2>/dev/null || true)"
    if test "$got" = "$wanted"; then
      echo "Preview verified: $preview_url"
      return 0
    fi
    sleep 15
  done
  fail "Cloudflare preview did not serve the expected main commit."
}
verify_remote_revision() {
  local expected="$1"
  fetch_refs
  test "$(main_sha)" = "$expected" || fail "main advanced during release; restart and review the new commit."
}
preview() {
  local target="$1" worktree
  worktree="$(mktemp -d)"
  # A subshell owns the temporary worktree and cleans it on every exit path.
  (
    cleanup() {
      git worktree remove --force "$worktree" >/dev/null 2>&1 || true
      rmdir "$worktree" 2>/dev/null || true
    }
    trap cleanup EXIT
    git worktree add --detach "$worktree" refs/remotes/origin/website-preview
    git -C "$worktree" merge --no-edit "$target"
    printf '%s\n' "$target" > "$worktree/website/preview-main-sha.txt"
    git -C "$worktree" add website/preview-main-sha.txt
    if ! git -C "$worktree" diff --cached --quiet; then
      git -C "$worktree" commit -m "chore(website): record previewed main revision"
    fi
    git -C "$worktree" push origin HEAD:refs/heads/website-preview
  )
  check_preview "$target"
  echo "Preview is live: https://preview.openkubes.org/"
}
verify_preview_ancestry() {
  local target="$1"
  git merge-base --is-ancestor "$target" refs/remotes/origin/website-preview ||
    fail "Preview branch does not contain reviewed main commit."
  check_preview "$target"
}
# Watch only the run dispatched by this process; never select unrelated runs.
dispatch_and_watch() {
  local target="$1" mode="$2" started run_id attempt
  started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  if test "$mode" = dry-run; then
    gh workflow run "$workflow" --repo "$repo" --ref main -f dry_run=true -f expected_sha="$target"
  else
    gh workflow run "$workflow" --repo "$repo" --ref main -f dry_run=false -f expected_sha="$target" -f release_confirmation=PUBLISH_OPENKUBES_ORG
  fi
  run_id=""
  for attempt in $(seq 1 30); do
    run_id="$(gh run list --repo "$repo" --workflow "$workflow" --event workflow_dispatch --json databaseId,headSha,createdAt --limit 30 --jq "[.[] | select(.headSha == \"$target\" and .createdAt >= \"$started\")] | sort_by(.createdAt) | reverse | .[0].databaseId // empty")"
    test -n "$run_id" && break
    sleep 2
  done
  test -n "$run_id" || fail "Cannot identify workflow run. Inspect GitHub Actions before retrying."
  echo "Watching https://github.com/$repo/actions/runs/$run_id"
  gh run watch "$run_id" --repo "$repo" --exit-status
  test "$(gh run view "$run_id" --repo "$repo" --json conclusion --jq .conclusion)" = success ||
    fail "Workflow did not succeed."
  if test "$mode" = production; then
    test "$(gh run view "$run_id" --repo "$repo" --json jobs --jq '[.jobs[] | select(.name == "publish" and .conclusion == "success")] | length')" = 1 ||
      fail "Production publish job did not succeed."
  else
    test "$(gh run view "$run_id" --repo "$repo" --json jobs --jq '[.jobs[] | select(.name == "build" and .conclusion == "success")] | length')" = 1 ||
      fail "Dry-run build did not succeed."
  fi
}
publish() {
  local target="$1" dry_run="${2:-false}" enabled confirmation
  verify_remote_revision "$target"
  verify_preview_ancestry "$target"
  if test "$dry_run" = true; then
    echo "Validating the reviewed commit with a GitHub Pages dry run ..."
    dispatch_and_watch "$target" dry-run
    verify_remote_revision "$target"
    verify_preview_ancestry "$target"
  fi
  echo "Ready to publish main commit $target to https://openkubes.org/"
  printf 'Type OK to continue: '
  IFS= read -r confirmation </dev/tty || fail "Interactive confirmation required."
  test "$confirmation" = OK || fail "Publication cancelled."
  verify_remote_revision "$target"
  enabled="$(gh variable get OK196_PAGES_RELEASE_ENABLED --repo "$repo" 2>/dev/null || true)"
  test "$enabled" = false || fail "Repository release switch must be false before starting (got '$enabled')."
  # Reset the gate even when dispatching or watching the workflow fails.
  (
    trap 'gh variable set OK196_PAGES_RELEASE_ENABLED --repo "$repo" --body false || echo "WARNING: Reset the release variable manually!" >&2' EXIT
    gh variable set OK196_PAGES_RELEASE_ENABLED --repo "$repo" --body true
    dispatch_and_watch "$target" production
  )
  echo "Production deploy completed. Verify https://openkubes.org/"
}
case "${1:-}" in
  preview)
    fetch_refs
    target="$(main_sha)"
    preview "$target"
    ;;
  release)
    fetch_refs
    target="$(main_sha)"
    preview "$target"
    publish "$target" true
    ;;
  publish)
    fetch_refs
    target="$(main_sha)"
    publish "$target" false
    ;;
  status)
    fetch_refs
    target="$(main_sha)"
    printf 'Remote main: %s\nPreview branch: %s\n' "$target" "$(git rev-parse refs/remotes/origin/website-preview)"
    got="$(curl --fail --silent --show-error --location --max-time 15 -H 'Cache-Control: no-cache' "$preview_url" || true)"
    printf 'Cloudflare deployed main: %s\n' "${got:-unavailable}"
    if test "$got" = "$target"; then echo "Preview matches main."; else echo "Preview does not match main."; fi
    gh run list --repo "$repo" --workflow "$workflow" --limit 5
    ;;
  *)
    echo "Usage: $0 preview|release|publish|status" >&2
    exit 2
    ;;
esac
