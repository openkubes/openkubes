#!/usr/bin/env bash
#
# OK-167 — secret scan over everything Git can see.
#
# Run before every commit (BRIEF B14). Scans files that are tracked or staged in
# the spike directory. Files under .local/ are gitignored and therefore never in
# scope — that is the point of .local/, and this script deliberately does not
# read their contents except to learn which literal values must never appear
# elsewhere.
#
# Two classes of check:
#
#   Known values  — the actual credentials this spike generated (.local/credentials.env,
#                   .local/htpasswd). Matched literally. Any hit is a real leak.
#
#   Patterns      — shapes that are credentials regardless of origin: full bcrypt
#                   hashes, PEM private keys with a real body, basic-auth headers,
#                   and opaque values assigned to credential-looking keys.
#
# Documented placeholders are not findings. Upstream Helm charts ship commented
# examples such as `password: my-password` and `password: ""`, and the chart
# reference dumps under evidence/raw/ contain them verbatim. A scanner that
# flags those is a scanner nobody reads, so placeholders are recognised and
# skipped — see is_placeholder() below.
#
# Portability: macOS ships bash 3.2, so no mapfile, no associative arrays, and
# no `readarray`. Findings are counted in a file rather than a variable, because
# a `cmd | while read` loop runs in a subshell whose variable updates are lost —
# a counter kept in a variable there would make this script exit 0 while
# printing findings, which is the one failure mode a secret scanner must not have.
#
# Exit codes
#   0  clean
#   1  findings (printed, with file and line)
#   2  prerequisite missing

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPIKE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# shellcheck source=./lib.sh
# shellcheck disable=SC1091
. "$SCRIPT_DIR/lib.sh"

ok167::require_tool git
ok167::require_tool grep

cd "$SPIKE_ROOT"

WORK_DIR="$SPIKE_ROOT/.local/tmp"
mkdir -p "$WORK_DIR"
FINDINGS_FILE="$WORK_DIR/scan-findings.$$"
FILE_LIST="$WORK_DIR/scan-files.$$"
: > "$FINDINGS_FILE"
: > "$FILE_LIST"
trap 'rm -f "$FINDINGS_FILE" "$FILE_LIST"' EXIT

report() {
  # report <file> <line-number> <rule> <detail>
  ok167::error "$1:$2  [$3] $4"
  printf '%s\n' "$1:$2:$3" >> "$FINDINGS_FILE"
}

# grep across every in-scope file, NUL-delimited so filenames with spaces are
# safe and the argument list cannot overflow. /dev/null is appended so grep
# always sees at least two files and therefore always prefixes its output with
# the filename — with a single file it would print `12:match` instead of
# `path:12:match` and every caller's parsing would silently shift by one field.
grep_files() {
  tr '\n' '\0' < "$FILE_LIST" \
    | xargs -0 grep -n "$@" /dev/null 2>/dev/null || true
}

# ---------------------------------------------------------------------------
# Scope: tracked + staged files in the spike directory
# ---------------------------------------------------------------------------
# `git ls-files` lists tracked files; --others --exclude-standard adds new files
# that are not ignored, i.e. what a `git add` would pick up next.
{
  git ls-files -- . 2>/dev/null || true
  git ls-files --others --exclude-standard -- . 2>/dev/null || true
  git diff --cached --name-only --diff-filter=ACM -- . 2>/dev/null \
    | sed "s|^architecture/spikes/ADR-Platform-011/OK-167-gitless-gitops/||" || true
} | sort -u | while IFS= read -r f; do
  [ -n "$f" ] || continue
  [ -f "$f" ] || continue
  # Text files only; a binary would produce meaningless matches.
  if LC_ALL=C grep -qI . "$f" 2>/dev/null; then
    printf '%s\n' "$f" >> "$FILE_LIST"
  fi
done

FILE_COUNT=$(wc -l < "$FILE_LIST" | tr -d ' ')
if [ "$FILE_COUNT" -eq 0 ]; then
  ok167::warn "no tracked or staged files to scan yet"
  exit 0
fi

# ---------------------------------------------------------------------------
# Placeholder recognition
# ---------------------------------------------------------------------------
# A value is a placeholder if it is empty, bracketed, a shell/Helm/Actions
# expansion, or one of the conventional dummy words. These appear in templates
# and upstream chart documentation and are not secrets.
is_placeholder() {
  local v="$1"
  v="$(printf '%s' "$v" | sed -E 's/^[[:space:]]*["'"'"']?//; s/["'"'"']?[[:space:]]*$//')"
  [ -z "$v" ] && return 0
  # shellcheck disable=SC2016  # these are literal markers, not expansions
  case "$v" in
    '<'*'>'|'${'*'}'|'{{'*'}}'|'$('*')') return 0 ;;
  esac
  # A bare `$name` is a reference, not a value. Argo CD uses exactly this for
  # secret indirection (`clientSecret: $dex.github.clientSecret`,
  # `$<secret-name>:<key>`), which is what the Secret Contract in ADR-011 asks
  # for — Git holds the reference, never the value. A bcrypt hash also starts
  # with `$`, so it is excluded here; rule 2a catches it on its own anyway.
  # shellcheck disable=SC2016  # literal bcrypt prefixes, not expansions
  case "$v" in
    '$2a$'*|'$2b$'*|'$2y$'*) : ;;
    '$'?*) return 0 ;;
  esac
  if printf '%s' "$v" | grep -qiE '^(changeme|change-me|my-password|my-secret|password|secret|token|example|examplepass|redacted|placeholder|dummy|foo|bar|test|xxx+|\.\.\.|none|null|true|false|from-secret-store|set-by-makefile|generated-at-runtime)$'; then
    return 0
  fi
  return 1
}

# ---------------------------------------------------------------------------
# Check 1 — literal values of secrets this spike actually generated
# ---------------------------------------------------------------------------
# Values are read from .local/ but never printed. A match reports only the
# variable name that leaked, never the value itself.
check_known_values() {
  local creds="$SPIKE_ROOT/.local/credentials.env"
  local key value hit line f ln

  if [ -f "$creds" ]; then
    while IFS='=' read -r key value; do
      case "$key" in ''|\#*) continue ;; esac
      value="$(printf '%s' "$value" | sed -E 's/^["'"'"']//; s/["'"'"']$//')"
      # A short value would match everywhere and say nothing.
      [ "${#value}" -ge 12 ] || continue

      hit="$(grep_files -F -- "$value")"
      if [ -n "$hit" ]; then
        while IFS= read -r line; do
          [ -n "$line" ] || continue
          f="${line%%:*}"
          ln="$(printf '%s' "$line" | cut -d: -f2)"
          report "$f" "$ln" "known-value" "literal value of \$$key from .local/credentials.env"
        done <<< "$hit"
      fi
    done < "$creds"
  fi

  # htpasswd hashes.
  local hf="$SPIKE_ROOT/.local/htpasswd"
  if [ -f "$hf" ]; then
    local hashline hash
    while IFS= read -r hashline; do
      [ -n "$hashline" ] || continue
      hash="${hashline#*:}"
      [ "${#hash}" -ge 20 ] || continue
      hit="$(grep_files -F -- "$hash")"
      if [ -n "$hit" ]; then
        while IFS= read -r line; do
          [ -n "$line" ] || continue
          report "${line%%:*}" "$(printf '%s' "$line" | cut -d: -f2)" \
                 "known-value" "htpasswd hash from .local/htpasswd"
        done <<< "$hit"
      fi
    done < "$hf"
  fi
}

# ---------------------------------------------------------------------------
# Check 2 — credential shapes, regardless of where they came from
# ---------------------------------------------------------------------------
check_patterns() {
  local f ln rest value hit

  while IFS= read -r f; do
    [ -n "$f" ] || continue

    # 2a — a complete bcrypt hash: $2<a|b|y>$<cost>$<22 salt + 31 hash>.
    # The length is part of the pattern, so a redacted
    # `admin:<redacted-bcrypt-hash>` correctly does not match.
    # shellcheck disable=SC2016  # a literal regex, not an expansion
    while IFS= read -r hit; do
      [ -n "$hit" ] || continue
      report "$f" "${hit%%:*}" "bcrypt" "complete bcrypt hash"
    done < <(grep -nE '\$2[aby]\$[0-9]{2}\$[A-Za-z0-9./]{53}' "$f" 2>/dev/null || true)

    # 2b — a PEM private key with an actual body. The BEGIN marker alone is not
    # enough: upstream docs show it in comments with no key behind it.
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

    # 2c — an auth header carrying a real-looking payload.
    while IFS= read -r hit; do
      [ -n "$hit" ] || continue
      rest="${hit#*:}"
      # shellcheck disable=SC2016  # literal markers
      case "$rest" in *'<redacted>'*|*'${'*|*'{{'*) continue ;; esac
      report "$f" "${hit%%:*}" "auth-header" "Authorization header with a payload"
    done < <(grep -nE 'Authorization:[[:space:]]*(Basic|Bearer)[[:space:]]+[A-Za-z0-9+/=._-]{16,}' "$f" 2>/dev/null || true)

    # 2d — an opaque value assigned to a credential-looking key.
    while IFS= read -r hit; do
      [ -n "$hit" ] || continue
      ln="${hit%%:*}"
      rest="${hit#*:}"
      # Extract the value in three steps rather than one greedy substitution.
      # `s/.*[:=]//` would cut at the LAST separator on the line, so a trailing
      # comment such as
      #     clientSecret: $dex.github.clientSecret # or $<secret>:dex....
      # would yield `dex....` and lose the leading `$` that marks it a
      # reference. Strip the comment marker, split on the FIRST separator, then
      # drop any trailing comment.
      value="$(printf '%s' "$rest" \
        | sed -E 's/^[[:space:]]*#*[[:space:]]*//' \
        | sed -E 's/^[^:=]*[:=][[:space:]]*//' \
        | sed -E 's/[[:space:]]+#.*$//' \
        | sed -E 's/[[:space:]]+$//')"
      is_placeholder "$value" && continue
      # Only opaque, secret-length values qualify. `true`, a path, or a URL is
      # configuration, not a credential.
      printf '%s' "$value" | grep -qE '^["'"'"']?[A-Za-z0-9+/=_.-]{16,}["'"'"']?$' || continue
      printf '%s' "$value" | grep -qE '^["'"'"']?(/|\./|https?://)' && continue
      report "$f" "$ln" "assignment" "opaque value assigned to a credential key"
    done < <(grep -nEi '(password|passwd|token|secret|apikey|api_key|authheader)[[:space:]]*[:=][[:space:]]*[^[:space:]]+' "$f" 2>/dev/null || true)

  done < "$FILE_LIST"
}

# ---------------------------------------------------------------------------
# Check 3 — files that must never be tracked at all
# ---------------------------------------------------------------------------
check_forbidden_paths() {
  local f
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    case "$f" in
      .local/*|*/.local/*)
        report "$f" 1 "forbidden-path" ".local/ content must never be tracked"
        continue
        ;;
    esac
    # Documentation and templates about credential files are fine; the files
    # themselves are not.
    case "$f" in
      *.template.yaml|*.md) continue ;;
    esac
    case "$f" in
      *.key|*.pem|*htpasswd*|*credentials.env|*kubeconfig)
        report "$f" 1 "forbidden-path" "credential material must live in .local/"
        ;;
    esac
  done < "$FILE_LIST"
}

# ---------------------------------------------------------------------------
ok167::info "scanning $FILE_COUNT tracked/staged files for secrets"

check_known_values
check_patterns
check_forbidden_paths

FINDINGS=$(wc -l < "$FINDINGS_FILE" | tr -d ' ')
if [ "$FINDINGS" -gt 0 ]; then
  ok167::error "secret scan found $FINDINGS issue(s) — nothing may be committed"
  exit 1
fi

ok167::ok "secret scan clean ($FILE_COUNT files)"
