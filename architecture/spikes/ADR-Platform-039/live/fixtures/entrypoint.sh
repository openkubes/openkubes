#!/usr/bin/env bash
set -Eeuo pipefail
repo=/srv/git/workspace-fixture.git
if [[ ! -d "$repo" ]]; then
  work=$(mktemp -d)
  trap 'rm -rf "$work"' EXIT
  git init --quiet "$work"
  git -C "$work" config user.name 'OK-174 fixture'
  git -C "$work" config user.email 'fixture@example.invalid'
  printf 'developer workspace fixture\n' >"$work/README.md"
  printf '%s\n' '#!/bin/sh' 'cd "$(dirname "$0")"' "grep -qx 'developer workspace fixture modified by agent' README.md" >"$work/verify.sh"
  git -C "$work" add README.md verify.sh
  GIT_AUTHOR_DATE='2024-01-01T00:00:00Z' GIT_COMMITTER_DATE='2024-01-01T00:00:00Z' git -C "$work" commit --quiet -m fixture
  git clone --quiet --bare "$work" "$repo"
  git --git-dir="$repo" rev-parse HEAD >/srv/git/KNOWN_COMMIT
fi
exec python3 /usr/local/bin/server.py
