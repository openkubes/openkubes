#!/usr/bin/env bash
#
# OK-167 — machine identities for the zot registry.
#
# Creates three distinct, least-scope machine identities, as ADR-028 §4.5
# requires ("These identities MUST remain separate: build, staging publisher,
# release promoter, cluster pull, air-gap exporter, scanner/verification,
# registry administrator, break-glass administrator"):
#
#   gitops-publisher  read/create/update on openkubes/machine/gitops/**  (the pipeline)
#   gitops-puller     read only                                          (Argo CD)
#   ok167-admin       adminPolicy                                        (trust key upload, cleanup)
#
# Produces, all at mode 600 under .local/ and all gitignored:
#   credentials.env      KEY=value, one per identity
#   htpasswd             bcrypt hashes for zot
#   netrc-<identity>     for `curl --netrc-file`, so no password is ever an argument
#
# Passwords are never passed on a command line (BRIEF B4 rule 5): htpasswd
# reads them from stdin with -i.
#
# Idempotent: an identity that already has a password keeps it. Delete
# .local/credentials.env to rotate everything.
#
# Exit codes
#   0  ok
#   2  prerequisite missing

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPIKE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# shellcheck source=./lib.sh
# shellcheck disable=SC1091
. "$SCRIPT_DIR/lib.sh"

# shellcheck disable=SC1091
[ -f "$SPIKE_ROOT/versions.env" ] && . "$SPIKE_ROOT/versions.env"

LOCAL_DIR="$SPIKE_ROOT/.local"
CREDS="$LOCAL_DIR/credentials.env"
HTPASSWD="$LOCAL_DIR/htpasswd"

OPENSSL="${OPENSSL:-openssl}"
ok167::require_tool "$OPENSSL"
ok167::require_tool htpasswd "Apache htpasswd, needs -B (bcrypt) and -i (stdin)"

# The identity list and the variable names they map to.
IDENTITIES="${IDENTITY_PUBLISHER:-gitops-publisher} ${IDENTITY_PULLER:-gitops-puller} ${IDENTITY_ADMIN:-ok167-admin}"

mkdir -p "$LOCAL_DIR"
chmod 700 "$LOCAL_DIR"

# Turn an identity name into a shell variable name: gitops-publisher -> GITOPS_PUBLISHER_PASSWORD
var_for() {
  printf 'OK167_%s_PASSWORD\n' "$(printf '%s' "$1" | tr 'a-z-' 'A-Z_')"
}

# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------
if [ ! -f "$CREDS" ]; then
  ok167::touch_private "$CREDS"
  {
    echo "# OK-167 machine identity passwords."
    echo "# Generated $(ok167::timestamp). Never commit; never echo."
  } >> "$CREDS"
fi
chmod 600 "$CREDS"

for identity in $IDENTITIES; do
  var="$(var_for "$identity")"
  if grep -q "^${var}=" "$CREDS" 2>/dev/null; then
    ok167::info "password for $identity already exists, keeping it"
    continue
  fi
  # 32 bytes of randomness, base64. `tr -d` removes characters that would
  # complicate netrc parsing and shell quoting; length stays well above any
  # brute-force concern.
  password="$("$OPENSSL" rand -base64 32 | tr -d '\n=+/' | cut -c1-32)"
  printf '%s=%s\n' "$var" "$password" >> "$CREDS"
  ok167::info "generated password for $identity"
  unset password
done
chmod 600 "$CREDS"

# shellcheck disable=SC1090
. "$CREDS"

# ---------------------------------------------------------------------------
# htpasswd — bcrypt, password via stdin, never as an argument
# ---------------------------------------------------------------------------
ok167::info "writing htpasswd (bcrypt)"
ok167::touch_private "$HTPASSWD"
for identity in $IDENTITIES; do
  var="$(var_for "$identity")"
  eval "password=\${$var}"
  # -n print to stdout, -i read password from stdin, -B bcrypt.
  # `grep .` drops the blank line htpasswd -n emits after each entry: the file
  # would otherwise be half empty lines, and zot's parser is not documented to
  # tolerate them. Not worth finding out the hard way.
  printf '%s' "$password" | htpasswd -niB "$identity" | grep . >> "$HTPASSWD"
  unset password
done
chmod 600 "$HTPASSWD"

# Verify the file has one bcrypt line per identity, without printing hashes.
expected=0
for identity in $IDENTITIES; do
  expected=$(( expected + 1 ))
done
# shellcheck disable=SC2016  # a literal bcrypt regex, not an expansion
actual=$(grep -c '^[a-z0-9-]*:\$2[aby]\$' "$HTPASSWD" || true)
[ "$actual" = "$expected" ] \
  || ok167::die "htpasswd has $actual bcrypt entries, expected $expected" 1

# ---------------------------------------------------------------------------
# netrc files — one per identity, for `curl --netrc-file`
# ---------------------------------------------------------------------------
# curl -u would put the password in the process list; --netrc-file does not.
for identity in $IDENTITIES; do
  var="$(var_for "$identity")"
  eval "password=\${$var}"
  netrc="$LOCAL_DIR/netrc-$identity"
  ok167::touch_private "$netrc"
  {
    printf 'machine localhost login %s password %s\n' "$identity" "$password"
    printf 'machine 127.0.0.1 login %s password %s\n'  "$identity" "$password"
  } >> "$netrc"
  chmod 600 "$netrc"
  unset password
done

# ---------------------------------------------------------------------------
ok167::assert_private "$CREDS"
ok167::assert_private "$HTPASSWD"
for identity in $IDENTITIES; do
  ok167::assert_private "$LOCAL_DIR/netrc-$identity"
done

ok167::ok "identities ready: $(printf '%s' "$IDENTITIES") (passwords in .local/, never printed)"
