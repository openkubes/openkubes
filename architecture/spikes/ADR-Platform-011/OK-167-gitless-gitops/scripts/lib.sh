#!/usr/bin/env bash
# OK-167 — shared shell helpers.
#
# Sourced, never executed. Provides logging with UTC timestamps, strict-mode
# error handling and a few small utilities the spike scripts share.
#
# Deliberately free of anything that touches a cluster: scripts/guard.sh is the
# only place that decides whether a cluster may be touched at all.

# Guard against double-sourcing.
if [ -n "${OK167_LIB_SOURCED:-}" ]; then
  return 0
fi
OK167_LIB_SOURCED=1

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
# All timestamps are UTC so evidence from different runs can be ordered without
# worrying about the host's timezone or DST.

ok167::timestamp() {
  date -u +%Y-%m-%dT%H:%M:%SZ
}

# Epoch seconds — used by the measurement script.
ok167::epoch() {
  date -u +%s
}

# Colours only when stderr is a terminal, so redirected output stays clean.
if [ -t 2 ]; then
  OK167_C_RED=$'\033[31m'
  OK167_C_YELLOW=$'\033[33m'
  OK167_C_GREEN=$'\033[32m'
  OK167_C_DIM=$'\033[2m'
  OK167_C_RESET=$'\033[0m'
else
  OK167_C_RED=''
  OK167_C_YELLOW=''
  OK167_C_GREEN=''
  OK167_C_DIM=''
  OK167_C_RESET=''
fi

ok167::log() {
  printf '%s%s%s %s\n' "$OK167_C_DIM" "$(ok167::timestamp)" "$OK167_C_RESET" "$*" >&2
}

ok167::info() {
  printf '%s%s%s %s\n' "$OK167_C_DIM" "$(ok167::timestamp)" "$OK167_C_RESET" "$*" >&2
}

ok167::ok() {
  printf '%s%s%s %sPASS%s %s\n' \
    "$OK167_C_DIM" "$(ok167::timestamp)" "$OK167_C_RESET" \
    "$OK167_C_GREEN" "$OK167_C_RESET" "$*" >&2
}

ok167::warn() {
  printf '%s%s%s %sWARN%s %s\n' \
    "$OK167_C_DIM" "$(ok167::timestamp)" "$OK167_C_RESET" \
    "$OK167_C_YELLOW" "$OK167_C_RESET" "$*" >&2
}

ok167::error() {
  printf '%s%s%s %sFAIL%s %s\n' \
    "$OK167_C_DIM" "$(ok167::timestamp)" "$OK167_C_RESET" \
    "$OK167_C_RED" "$OK167_C_RESET" "$*" >&2
}

# Exit codes are part of each script's contract; see the header of the caller.
ok167::die() {
  local code="${2:-1}"
  ok167::error "$1"
  exit "$code"
}

# ---------------------------------------------------------------------------
# Preconditions
# ---------------------------------------------------------------------------

# Every external tool is resolved through a variable so a container wrapper can
# be substituted later without touching call sites.
ok167::require_tool() {
  local tool="$1"
  local hint="${2:-}"
  if ! command -v "$tool" >/dev/null 2>&1; then
    if [ -n "$hint" ]; then
      ok167::die "required tool not found: $tool ($hint)" 2
    fi
    ok167::die "required tool not found: $tool" 2
  fi
}

ok167::require_file() {
  local path="$1"
  local what="${2:-file}"
  [ -f "$path" ] || ok167::die "required $what not found: $path" 2
}

ok167::require_dir() {
  local path="$1"
  local what="${2:-directory}"
  [ -d "$path" ] || ok167::die "required $what not found: $path" 2
}

# ---------------------------------------------------------------------------
# Secret hygiene
# ---------------------------------------------------------------------------

# Create a file that only the owner can read, before anything is written into
# it. Used for every file under .local/ that holds credentials (BRIEF B4 rule 4).
ok167::touch_private() {
  local path="$1"
  : > "$path"
  chmod 600 "$path"
}

# Assert a path really is mode 600. Cheap, and it catches an editor or a stray
# `cp` having loosened a credential file.
ok167::assert_private() {
  local path="$1"
  [ -f "$path" ] || ok167::die "expected a private file at $path" 2
  local mode
  mode=$(stat -f '%OLp' "$path" 2>/dev/null || stat -c '%a' "$path" 2>/dev/null)
  [ "$mode" = "600" ] || ok167::die "insecure permissions on $path: $mode, expected 600" 2
}

# Replace every known credential value in a stream with <redacted>, so evidence
# and logs can be written without leaking. Reads .local/credentials.env if it
# exists. Values are matched literally, never interpreted as patterns.
ok167::redact() {
  local creds="${OK167_CREDENTIALS_FILE:-.local/credentials.env}"
  if [ ! -f "$creds" ]; then
    cat
    return 0
  fi
  # Build a sed program of literal replacements, longest value first so a value
  # that contains another is not partially replaced.
  local sed_prog
  sed_prog=$(
    # shellcheck disable=SC2002
    cat "$creds" \
      | sed -n 's/^[A-Za-z_][A-Za-z0-9_]*=//p' \
      | sed 's/^"//; s/"$//' \
      | awk '{ print length, $0 }' \
      | sort -rn \
      | cut -d' ' -f2- \
      | while IFS= read -r value; do
          [ -n "$value" ] || continue
          # Escape every character that is special to sed's s/// left-hand side.
          printf 's|%s|<redacted>|g\n' \
            "$(printf '%s' "$value" | sed 's/[][\.*^$/|&]/\\&/g')"
        done
  )
  if [ -z "$sed_prog" ]; then
    cat
    return 0
  fi
  sed -f <(printf '%s\n' "$sed_prog")
}

# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------

# Absolute path to the spike root, regardless of the caller's working directory.
ok167::spike_root() {
  cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd
}

# Read a literal KEY=value credential without sourcing or evaluating the file.
# Values may contain shell metacharacters; only generated key names are accepted.
ok167::credential() {
  local wanted="$1" file="${2:-.local/credentials.env}" key value
  case "$wanted" in *[!A-Z0-9_]*|'') ok167::die "invalid credential key" 2 ;; esac
  ok167::require_file "$file" "credential file"
  while IFS='=' read -r key value; do
    if [ "$key" = "$wanted" ]; then printf '%s' "$value"; return 0; fi
  done < "$file"
  ok167::die "credential key is absent from the local file" 2
}
