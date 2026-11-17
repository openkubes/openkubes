#!/usr/bin/env bash
#
# OK-211 — secret scan over everything Git can see in the spike directory
# (adapted from OK-167 scripts/scan-secrets.sh).
#
# Run before every commit (BRIEF B14). Scans tracked, staged and untracked
# (not ignored) files in the spike directory, working copies and index blobs
# independently: a staged secret stays in scope even after the working file is
# cleaned. Files under .local/ are gitignored and never in scope; the script
# reads a few of them only to learn which literal values must never appear
# elsewhere, and never prints those values.
#
# Usage: scripts/scan-secrets.sh [--history <rev-range>]
#   --history  additionally scan every added line in `git log -p <rev-range>`
#              (B15: no secrets in the branch history)
#
# Checks
#   Known values — credential material this spike holds in .local/: the
#                  embedded client key, client certificate and token of
#                  .local/kubeconfig, and KEY=value lines of .local/credentials.env.
#                  Matched literally. Any hit is a real leak.
#   Patterns     — shapes that are credentials regardless of origin: PEM private
#                  keys with a body, Authorization headers with a payload,
#                  kubeconfig credential fields with data, opaque values assigned
#                  to credential-looking keys.
#   Paths        — .local/ content, key/cert/kubeconfig files and sockets must
#                  never be tracked.
#
# Portability: bash 3.2. Findings are counted in a file, not a variable, because
# a `cmd | while read` loop runs in a subshell whose updates are lost (OK-167 C2).
#
# Exit codes
#   0  clean
#   1  findings (printed with file and line, never with the value)
#   2  prerequisite missing

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPIKE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=./lib.sh
. "$SCRIPT_DIR/lib.sh"

ok211::require_tool git
ok211::require_tool grep

HISTORY_RANGE=""
case "${1:-}" in
  --history) HISTORY_RANGE="${2:-}"; [ -n "$HISTORY_RANGE" ] || ok211::die "usage: $0 [--history <rev-range>]" 2 ;;
  '') : ;;
  *) ok211::die "usage: $0 [--history <rev-range>]" 2 ;;
esac

cd "$SPIKE_ROOT"

umask 077
WORK_DIR="$SPIKE_ROOT/.local/tmp"
mkdir -p "$WORK_DIR"
SCAN_ROOT="$(mktemp -d "$WORK_DIR/scan.XXXXXX")"
INDEX_ROOT="$SCAN_ROOT/index"
HIST_ROOT="$SCAN_ROOT/history"
mkdir -p "$INDEX_ROOT" "$HIST_ROOT"
FINDINGS_FILE="$SCAN_ROOT/findings"
FILE_LIST="$SCAN_ROOT/files"
KNOWN_FILE="$SCAN_ROOT/known"
: > "$FINDINGS_FILE"
: > "$FILE_LIST"
: > "$KNOWN_FILE"
trap 'rm -rf "$SCAN_ROOT"' EXIT

source_path() {
  case "$1" in
    "$INDEX_ROOT/"*) printf '%s' "${1#"$INDEX_ROOT/"}" ;;
    "$HIST_ROOT/"*)  printf '%s' "${1#"$HIST_ROOT/"}" ;;
    *) printf '%s' "$1" ;;
  esac
}

report() {
  # report <file> <line-number> <rule> <detail>
  local label
  case "$1" in
    "$INDEX_ROOT/"*) label="index/$(source_path "$1")" ;;
    "$HIST_ROOT/"*)  label="history/$(source_path "$1")" ;;
    *) label="worktree/$1" ;;
  esac
  ok211::error "$label:$2  [$3] $4"
  printf '%s\n' "$label:$2:$3" >> "$FINDINGS_FILE"
}

# grep across every in-scope file. /dev/null keeps the filename prefix even
# when only one file is in scope.
grep_files() {
  tr '\n' '\0' < "$FILE_LIST" \
    | xargs -0 grep -an "$@" /dev/null 2>/dev/null || true
}

check_name() {
  case "$1" in
    *$'\n'*|*$'\t'*|*:*) ok211::die "unsupported filename delimiter in scan input" 2 ;;
  esac
}

# ---------------------------------------------------------------------------
# Scope
# ---------------------------------------------------------------------------
while IFS= read -r -d '' f; do
  check_name "$f"
  [ -f "$f" ] || continue
  [ ! -L "$f" ] || ok211::die "refusing to follow a worktree symlink while scanning: $f" 2
  printf '%s\n' "$f" >> "$FILE_LIST"
done < <(git ls-files -z --cached --others --exclude-standard -- .)
while IFS= read -r -d '' entry; do
  header="${entry%%$'\t'*}"
  f="${entry#*$'\t'}"
  check_name "$f"
  read -r _mode oid stage <<< "$header"
  [ "$stage" = "0" ] || ok211::die "resolve unmerged index entries before scanning" 2
  mkdir -p "$INDEX_ROOT/$(dirname "$f")"
  git cat-file blob "$oid" > "$INDEX_ROOT/$f"
  printf '%s\n' "$INDEX_ROOT/$f" >> "$FILE_LIST"
done < <(git ls-files -z --stage -- .)

# History: every added line of every commit in the range, one file per commit.
if [ -n "$HISTORY_RANGE" ]; then
  while IFS= read -r sha; do
    [ -n "$sha" ] || continue
    git show --no-color --format= --unified=0 "$sha" -- . \
      | sed -n 's/^+//p' | grep -v '^++ ' > "$HIST_ROOT/commit-$sha.patch" || true
    printf '%s\n' "$HIST_ROOT/commit-$sha.patch" >> "$FILE_LIST"
  done < <(git rev-list "$HISTORY_RANGE" -- .)
fi

FILE_COUNT=$(wc -l < "$FILE_LIST" | tr -d ' ')
if [ "$FILE_COUNT" -eq 0 ]; then
  ok211::warn "no files to scan yet"
  exit 0
fi

# ---------------------------------------------------------------------------
# Placeholder recognition
# ---------------------------------------------------------------------------
is_placeholder() {
  local v="$1"
  v="$(printf '%s' "$v" | sed -E 's/^[[:space:]]*["'"'"']?//; s/["'"'"']?[[:space:]]*$//')"
  [ -z "$v" ] && return 0
  case "$v" in
    '<redacted>'|'<from-secret-store>'|'<generated-at-runtime>'|'<set-by-makefile>') return 0 ;;
  esac
  local path
  path="$(source_path "${2:-}")"
  case "$path" in
    *.sh|Makefile)
      # Shell and make variable references are interpreted only in these files.
      # shellcheck disable=SC2016  # literal reference syntax
      if printf '%s' "$v" | grep -qE '^\$(\{[A-Za-z_][A-Za-z0-9_]*\}|\([A-Za-z_][A-Za-z0-9_]*\)|[A-Za-z_][A-Za-z0-9_]*)(/[A-Za-z0-9._/-]+)?$'; then
        return 0
      fi ;;
  esac
  if printf '%s' "$v" | grep -qiE '^(changeme|change-me|password|secret|token|example|redacted|placeholder|dummy|test|xxx+|\.\.\.|none|null|true|false|enabled|disabled)$'; then
    return 0
  fi
  return 1
}

# ---------------------------------------------------------------------------
# Check 1 — literal values this spike actually holds
# ---------------------------------------------------------------------------
# Values are read from .local/ but never printed. A match reports only where
# the value came from.
collect_known_values() {
  local kc="$SPIKE_ROOT/.local/kubeconfig" creds="$SPIKE_ROOT/.local/credentials.env" key value
  if [ -f "$kc" ] && command -v yq >/dev/null 2>&1; then
    # Embedded data fields: base64 of the client key, client cert and the CA.
    # The CA certificate is public, but its presence in a tracked file still
    # means a kubeconfig was copied, so it is in scope too.
    yq -N '.users[].user["client-key-data"], .users[].user["client-certificate-data"], .users[].user.token, .clusters[].cluster["certificate-authority-data"]' "$kc" 2>/dev/null \
      | while IFS= read -r value; do
          [ "${#value}" -ge 24 ] || continue
          # A 64-character slice is enough for an unambiguous literal match and
          # also catches a value that was wrapped across lines.
          printf 'kubeconfig\t%s\n' "${value:0:64}"
        done >> "$KNOWN_FILE"
  fi
  if [ -f "$creds" ]; then
    while IFS='=' read -r key value; do
      case "$key" in ''|\#*) continue ;; esac
      value="$(printf '%s' "$value" | sed -E 's/^["'"'"']//; s/["'"'"']$//')"
      [ "${#value}" -ge 12 ] || continue
      printf 'credentials.env:%s\t%s\n' "$key" "$value" >> "$KNOWN_FILE"
    done < "$creds"
  fi
}

check_known_values() {
  local origin value hit line
  while IFS=$'\t' read -r origin value; do
    [ -n "$value" ] || continue
    hit="$(grep_files -F -- "$value")"
    [ -n "$hit" ] || continue
    while IFS= read -r line; do
      [ -n "$line" ] || continue
      report "${line%%:*}" "$(printf '%s' "$line" | cut -d: -f2)" "known-value" "literal value from .local/ ($origin)"
    done <<< "$hit"
  done < "$KNOWN_FILE"
}

# ---------------------------------------------------------------------------
# Check 2 — credential shapes
# ---------------------------------------------------------------------------
check_patterns() {
  local f ln rest value hit
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    LC_ALL=C grep -qI . "$f" 2>/dev/null || continue

    # 2a — a PEM private key with an actual body (the marker alone is not enough).
    while IFS= read -r ln; do
      [ -n "$ln" ] || continue
      report "$f" "$ln" "private-key" "PEM private key with a base64 body"
    done < <(awk '
        /-----BEGIN[A-Z ]*PRIVATE KEY-----/ { marker = NR; next }
        marker && NR <= marker + 3 {
          line = $0
          gsub(/^[[:space:]#\/-]*/, "", line)
          if (line ~ /^[A-Za-z0-9+\/=]{40,}$/) { print marker; marker = 0 }
        }
      ' "$f" 2>/dev/null || true)

    # 2b — an auth header carrying a real-looking payload.
    while IFS= read -r hit; do
      [ -n "$hit" ] || continue
      report "$f" "${hit%%:*}" "auth-header" "Authorization header with a payload"
    done < <(grep -nE 'Authorization:[[:space:]]*(Basic|Bearer)[[:space:]]+[A-Za-z0-9+/=._-]{16,}' "$f" 2>/dev/null || true)

    # 2c — kubeconfig credential fields with data (K3s embeds base64 PEM).
    while IFS= read -r hit; do
      [ -n "$hit" ] || continue
      report "$f" "${hit%%:*}" "kubeconfig-data" "embedded kubeconfig credential"
    done < <(grep -nE '(client-key-data|client-certificate-data|certificate-authority-data)[[:space:]]*:[[:space:]]*["'"'"']?[A-Za-z0-9+/=]{40,}' "$f" 2>/dev/null || true)

    # 2d — an opaque value assigned to a credential-looking key.
    while IFS= read -r hit; do
      [ -n "$hit" ] || continue
      ln="${hit%%:*}"
      rest="${hit#*:}"
      # Split on the FIRST separator, then drop a trailing comment (OK-167).
      value="$(printf '%s' "$rest" \
        | sed -E 's/^[[:space:]]*#*[[:space:]]*//' \
        | sed -E 's/^[^:=]*[:=][[:space:]]*//' \
        | sed -E 's/[[:space:]]+#.*$//' \
        | sed -E 's/[[:space:]]+$//')"
      is_placeholder "$value" "$f" && continue
      printf '%s' "$value" | grep -qE '^["'"'"']?[A-Za-z0-9+/=_.!@$%<>:-]{16,}["'"'"']?$' || continue
      printf '%s' "$value" | grep -qE '^["'"'"']?(/|\./|https?://)' && continue
      report "$f" "$ln" "assignment" "opaque value assigned to a credential key"
    done < <(grep -nEi '(password|passwd|token|secret|apikey|api_key|authheader)[[:space:]]*[:=][[:space:]]*[^[:space:]]+' "$f" 2>/dev/null || true)
  done < "$FILE_LIST"
}

# ---------------------------------------------------------------------------
# Check 3 — files that must never be tracked
# ---------------------------------------------------------------------------
check_forbidden_paths() {
  local f path
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    path="$(source_path "$f")"
    case "$path" in
      commit-*.patch) continue ;;
      .local/*|*/.local/*)
        report "$f" 1 "forbidden-path" ".local/ content must never be tracked"
        continue ;;
    esac
    case "$path" in
      *.template.yaml|*.md) continue ;;
    esac
    case "$path" in
      *.key|*.pem|*.crt|*.sock|*credentials.env|*kubeconfig|*known_hosts|*id_rsa*|*id_ed25519*)
        report "$f" 1 "forbidden-path" "credential material must live in .local/" ;;
    esac
  done < "$FILE_LIST"
}

# ---------------------------------------------------------------------------
ok211::info "scanning $FILE_COUNT files for secrets${HISTORY_RANGE:+ (including history $HISTORY_RANGE)}"

collect_known_values
check_known_values
check_patterns
check_forbidden_paths

FINDINGS=$(wc -l < "$FINDINGS_FILE" | tr -d ' ')
if [ "$FINDINGS" -gt 0 ]; then
  ok211::error "secret scan found $FINDINGS issue(s) — nothing may be committed"
  exit 1
fi
ok211::ok "secret scan clean ($FILE_COUNT files, $(wc -l < "$KNOWN_FILE" | tr -d ' ') known values checked)"
