#!/usr/bin/env bash
# Publish the reviewed main commit to Cloudflare preview or GitHub Pages production.
set -euo pipefail
cd "$(dirname "$0")/../.."

fail() { echo "ERROR: $*" >&2; exit 1; }
require() { command -v "$1" >/dev/null 2>&1 || fail "Missing required command: $1"; }
require git
require gh
require curl

repo="openkubes/openkubes"
preview_url="https://preview.openkubes.org/.well-known/ok196-preview-main-sha.txt"
workflow="ok196-pages-release.yml"

clean_tree() {
  test -z "$(git status --porcelain)" || fail "Working tree must be clean."
}
current_main() {
  git fetch origin main website-preview
  local sha
  sha="$(git rev-parse origin/main)"
  test "$(git rev-parse main)" = "$sha" || fail "Local main is not at origin/main."
  printf '%s' "$sha"
}
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
  fail "Cloudflare preview did not serve the expected main commit; production blocked."
}
case "${1:-}" in
  preview)
    clean_tree
    original="$(git branch --show-current)"
    test -n "$original" || fail "Detached HEAD not supported."
    target="$(current_main)"
    test "$original" = "main" || test "$original" = "website-preview" || fail "Run from main or website-preview."
    git switch website-preview
    git pull --ff-only origin website-preview
    git merge --no-edit origin/main
    # Preview metadata is committed so Cloudflare serves a trustworthy, build-specific marker.
    mkdir -p website
    printf '%s\n' "$target" > website/preview-main-sha.txt
    git add website/preview-main-sha.txt
    if ! git diff --cached --quiet; then
      git commit -m "chore(website): record previewed main revision"
    fi
    git push origin website-preview
    check_preview "$target"
    git switch "$original"
    echo "Preview is live: https://preview.openkubes.org/"
    ;;
  publish)
    clean_tree
    test "$(git branch --show-current)" = "main" || fail "Switch to main before publishing."
    target="$(current_main)"
    test "$(git rev-parse origin/website-preview)" != "" || fail "Preview branch missing."
    git merge-base --is-ancestor "$target" origin/website-preview || fail "Preview branch does not contain the current main commit."
    check_preview "$target"
    echo "Ready to publish main commit $target to https://openkubes.org/"
    printf 'Type PUBLISH_OPENKUBES_ORG to continue: '
    IFS= read -r confirmation </dev/tty || fail "Interactive confirmation required."
    test "$confirmation" = "PUBLISH_OPENKUBES_ORG" || fail "Publication cancelled."
    # A pre-existing enabled switch is not taken as authorization.
    enabled="$(gh variable get OK196_PAGES_RELEASE_ENABLED --repo "$repo" 2>/dev/null || true)"
    test "$enabled" = "false" || fail "Repository release switch must be false before starting (got '$enabled')."
    reset_switch() { gh variable set OK196_PAGES_RELEASE_ENABLED --repo "$repo" --body false || echo "WARNING: Disable release variable manually!" >&2; }
    trap reset_switch EXIT
    gh variable set OK196_PAGES_RELEASE_ENABLED --repo "$repo" --body true
    started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    gh workflow run "$workflow" --repo "$repo" --ref main -f dry_run=false -f expected_sha="$target" -f release_confirmation=PUBLISH_OPENKUBES_ORG
    run_id=""
    for attempt in $(seq 1 30); do
      run_id="$(gh run list --repo "$repo" --workflow "$workflow" --event workflow_dispatch --json databaseId,headSha,createdAt --limit 20 --jq "[.[] | select(.headSha == \"$target\" and .createdAt >= \"$started\")] | sort_by(.createdAt) | reverse | .[0].databaseId // empty")"
      test -n "$run_id" && break
      sleep 2
    done
    test -n "$run_id" || fail "Could not identify dispatched workflow; inspect GitHub Actions."
    echo "Watching https://github.com/$repo/actions/runs/$run_id"
    gh run watch "$run_id" --repo "$repo" --exit-status
    test "$(gh run view "$run_id" --repo "$repo" --json conclusion --jq .conclusion)" = "success" || fail "Release not successful."
    echo "Production deploy completed. Validate https://openkubes.org/"
    ;;
  *)
    echo "Usage: $0 preview|publish" >&2
    exit 2
    ;;
esac
