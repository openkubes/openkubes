#!/usr/bin/env bash
# Wait for a populated Application, and optionally for an exact artifact digest.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./lib.sh
. "$SCRIPT_DIR/lib.sh"
APP="${1:?Application name required}"
EXPECTED_DIGEST="${2:-}"
TIMEOUT="${3:-300}"
DEADLINE=$(( $(ok167::epoch) + TIMEOUT ))
while [ "$(ok167::epoch)" -lt "$DEADLINE" ]; do
  DATA="$("${KUBECTL:-kubectl}" -n argocd get application "$APP" -o json 2>/dev/null || true)"
  # shellcheck disable=SC2016  # literal jq variables
  if printf '%s' "$DATA" | jq -e --arg digest "$EXPECTED_DIGEST" '
    .status.sync.status == "Synced" and .status.health.status == "Healthy" and
    ((.status.resources // []) | length) == 2 and
    (.status.sync.revision == $digest or $digest == "") and
    ((.status.conditions // []) | length) == 0' >/dev/null 2>&1; then
    printf '%s' "$DATA" | jq '{app:.metadata.name,source:.spec.source,
      sync:.status.sync.status,health:.status.health.status,revision:.status.sync.revision,
      resources:[.status.resources[]|{kind,name}],conditions:.status.conditions}'
    exit 0
  fi
  sleep 1
done
ok167::die "Application did not become populated, Synced and Healthy at the requested digest" 1
