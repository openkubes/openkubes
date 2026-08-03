#!/usr/bin/env bash
# OK-81 — stream a restorable Keycloak database backup off the read-only CNPG pod.
#
# Custom format is intentional: it is compressed, pg_restore can validate its table of contents,
# and a future recovery can restore selectively. This is still only a LOCAL-DISK backup. The
# operator must copy it to durable storage outside this workspace; this profile has no object store.
set -Eeuo pipefail

: "${KUBECTL:?KUBECTL is required}"
: "${KUBECONFIG:?KUBECONFIG is required}"
: "${NAMESPACE:?NAMESPACE is required}"
: "${CNPG_CLUSTER:?CNPG_CLUSTER is required}"
: "${DB_NAME:?DB_NAME is required}"
: "${DB_USERNAME:?DB_USERNAME is required}"
: "${DB_SECRET:?DB_SECRET is required}"

DB_POD="${CNPG_CLUSTER}-1"
DB_HOST="${CNPG_CLUSTER}-rw"

die() { printf 'FAIL: %s\n' "$1" >&2; exit 1; }

umask 077
_d="$(mktemp -d)"
keep() {
  printf 'work dir RETAINED (mode 700, contains a plaintext database credential): %s\n' "$_d"
  if [ -n "${backup_file:-}" ] && { [ -e "$backup_file" ] || [ -L "$backup_file" ]; }; then
    printf 'backup artifact RETAINED (may be partial unless RESULT: PASS was printed): %s\n' "$backup_file"
  fi
  if [ -n "${partial_file:-}" ] && { [ -e "$partial_file" ] || [ -L "$partial_file" ]; }; then
    printf 'partial backup RETAINED (validation or publication did not complete): %s\n' "$partial_file"
  fi
}
trap keep EXIT
trap 'exit 130' INT TERM
printf 'work dir: %s\n' "$_d"

if [ -n "${BACKUP_DIR:-}" ]; then
  [ -d "$BACKUP_DIR" ] || die "BACKUP_DIR is not an existing directory: $BACKUP_DIR"
  [ -w "$BACKUP_DIR" ] || die "BACKUP_DIR is not writable: $BACKUP_DIR"
  artifact_dir="$BACKUP_DIR"
else
  artifact_dir="$_d"
fi

"$KUBECTL" --kubeconfig "$KUBECONFIG" get secret "$DB_SECRET" -n "$NAMESPACE" \
  -o jsonpath='{.data.password}' | base64 -d > "$_d/db-password"
[ -s "$_d/db-password" ] || die "Secret $DB_SECRET has no non-empty password"
[ "$(wc -l < "$_d/db-password")" -eq 0 ] || die "database password contains a newline and cannot use the stdin protocol safely"

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_file="$artifact_dir/keycloak-${stamp}-$$.dump"
partial_file="${backup_file}.partial"
[ ! -e "$backup_file" ] && [ ! -L "$backup_file" ] || die "refusing to overwrite existing backup: $backup_file"
[ ! -e "$partial_file" ] && [ ! -L "$partial_file" ] || die "refusing to overwrite existing partial backup: $partial_file"

printf 'backup artifact target: %s\n' "$backup_file"
printf 'streaming pg_dump -Fc from %s/%s (container postgres)\n' "$NAMESPACE" "$DB_POD"
# The password is read inside the container from stdin, assigned only after xtrace is disabled, and
# never appears in kubectl's argv. pg_dump writes its custom-format archive to stdout because the
# CNPG pod filesystem is read-only.
"$KUBECTL" --kubeconfig "$KUBECONFIG" exec -i -n "$NAMESPACE" "$DB_POD" -c postgres -- \
  env "PGHOST=$DB_HOST" PGPORT=5432 "PGUSER=$DB_USERNAME" "PGDATABASE=$DB_NAME" \
  sh -c 'set +x; IFS= read -r p || [ -n "$p" ]; export PGPASSWORD="$p"; exec pg_dump -w -Fc' \
  < "$_d/db-password" > "$partial_file"
[ -s "$partial_file" ] || die "pg_dump produced an empty artifact: $partial_file"
chmod 600 "$partial_file"

# pg_restore reads the archive from stdin and emits its table of contents to local disk. Nothing is
# written inside the pod, and this rejects a truncated/non-custom archive before reporting success.
"$KUBECTL" --kubeconfig "$KUBECONFIG" exec -i -n "$NAMESPACE" "$DB_POD" -c postgres -- \
  pg_restore --list < "$partial_file" > "$_d/restore-list"
[ -s "$_d/restore-list" ] || die "pg_restore produced no table of contents"

# The temporary artifact is in the destination directory, so rename publishes the already-validated
# bytes atomically without a cross-filesystem copy window. --no-clobber closes the race between the
# earlier existence guard and publication; GNU mv reports success when it skips, so assert effects.
mv --no-clobber -- "$partial_file" "$backup_file"
[ -f "$backup_file" ] && [ ! -L "$backup_file" ] && [ ! -e "$partial_file" ] && [ ! -L "$partial_file" ] || \
  die "atomic backup publication did not complete"

printf 'RESULT: PASS — custom-format backup is readable by pg_restore\n'
printf 'BACKUP_FILE=%s\n' "$backup_file"
printf 'WARNING: the backup is on local disk only and is NOT durable until copied off-host.\n'
printf 'WARNING: the dump itself is sensitive; it can contain client secrets and password hashes.\n'
printf 'WARNING: the retained work dir contains a plaintext database credential; delete it manually when safe.\n'
