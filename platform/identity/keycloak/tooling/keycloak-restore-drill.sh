#!/usr/bin/env bash
# OK-81 — restore a custom-format dump into a unique scratch database, assert realm/client rows,
# then drop the scratch database without ever touching the live Keycloak database.
set -Eeuo pipefail

: "${KUBECTL:?KUBECTL is required}"
: "${KUBECONFIG:?KUBECONFIG is required}"
: "${NAMESPACE:?NAMESPACE is required}"
: "${CNPG_CLUSTER:?CNPG_CLUSTER is required}"
: "${DB_NAME:?DB_NAME is required}"
: "${DB_USERNAME:?DB_USERNAME is required}"
: "${DB_SECRET:?DB_SECRET is required}"

[ "${APPROVE_RESTORE_DRILL:-}" = yes ] || {
  echo "ERROR: restore-drill creates and drops a scratch database on the live server." >&2
  echo "       Review the sequence, then rerun with APPROVE_RESTORE_DRILL=yes." >&2
  exit 2
}
[ -t 0 ] || {
  echo "ERROR: restore-drill must be run attended from a terminal" >&2
  exit 2
}

[ "$#" -eq 1 ] || { echo "ERROR: usage: keycloak-restore-drill.sh <backup.dump>" >&2; exit 2; }
RESTORE_FILE="$1"
[ -r "$RESTORE_FILE" ] || { echo "ERROR: backup is not readable: $RESTORE_FILE" >&2; exit 2; }
[ -s "$RESTORE_FILE" ] || { echo "ERROR: backup is empty: $RESTORE_FILE" >&2; exit 2; }

[[ "$DB_USERNAME" =~ ^[a-z_][a-z0-9_]*$ ]] || {
  echo "ERROR: DB_USERNAME is not a safe PostgreSQL identifier: $DB_USERNAME" >&2
  exit 2
}

DB_POD="${CNPG_CLUSTER}-1"
DB_HOST="${CNPG_CLUSTER}-rw"
SCRATCH_DB="kc_restore_$(date -u +%Y%m%d%H%M%S)_$$_${RANDOM}"
CREATED=0

die() { printf 'FAIL: %s\n' "$1" >&2; exit 1; }

umask 077
_d="$(mktemp -d)"
printf 'work dir: %s\n' "$_d"
printf 'scratch database: %s\n' "$SCRATCH_DB"

# Administrative SQL uses the CNPG pod's local postgres identity and travels over stdin. The
# password-authenticated application role is used for pg_restore and the row-count assertions.
admin_sql() {
  "$KUBECTL" --kubeconfig "$KUBECONFIG" exec -i -n "$NAMESPACE" "$DB_POD" -c postgres -- \
    psql -X -v ON_ERROR_STOP=1 -qAt --dbname=postgres
}

cleanup() {
  rc=$?
  trap - EXIT INT TERM
  if [ "$CREATED" = 1 ]; then
    printf 'DROP DATABASE IF EXISTS "%s" WITH (FORCE);\n' "$SCRATCH_DB" > "$_d/drop.sql"
    dropped=0
    for attempt in 1 2 3; do
      if admin_sql < "$_d/drop.sql"; then
        printf 'SELECT count(*) FROM pg_database WHERE datname = '\''%s'\'';\n' "$SCRATCH_DB" > "$_d/check-dropped.sql"
        remaining="$(admin_sql < "$_d/check-dropped.sql" 2>/dev/null || true)"
        if [ "$remaining" = 0 ]; then
          printf 'cleanup: dropped scratch database %s\n' "$SCRATCH_DB"
          dropped=1
          break
        fi
      fi
      printf 'cleanup: drop attempt %s/3 failed for %s\n' "$attempt" "$SCRATCH_DB" >&2
    done
    if [ "$dropped" != 1 ]; then
      printf 'FAIL: could not prove scratch database %s was dropped; manual cleanup is required\n' "$SCRATCH_DB" >&2
      rc=1
    fi
  fi
  printf 'work dir RETAINED (mode 700, contains a plaintext database credential): %s\n' "$_d"
  printf 'WARNING: delete the retained work dir manually only after reviewing this result.\n'
  exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

"$KUBECTL" --kubeconfig "$KUBECONFIG" get secret "$DB_SECRET" -n "$NAMESPACE" \
  -o jsonpath='{.data.password}' | base64 -d > "$_d/db-password"
[ -s "$_d/db-password" ] || die "Secret $DB_SECRET has no non-empty password"
[ "$(wc -l < "$_d/db-password")" -eq 0 ] || die "database password contains a newline and cannot use the stdin protocol safely"

# Validate the archive before creating anything on the server.
"$KUBECTL" --kubeconfig "$KUBECONFIG" exec -i -n "$NAMESPACE" "$DB_POD" -c postgres -- \
  pg_restore --list < "$RESTORE_FILE" > "$_d/restore-list"
[ -s "$_d/restore-list" ] || die "pg_restore produced no table of contents"

# A stale scratch database means a prior drill did not prove cleanup. Refuse to pile another drill
# on top of that unresolved state, and enumerate the exact databases requiring human review.
printf "SELECT datname FROM pg_database WHERE left(datname, 11) = 'kc_restore_' ORDER BY datname;\n" > "$_d/check-stale.sql"
stale="$(admin_sql < "$_d/check-stale.sql")"
if [ -n "$stale" ]; then
  printf 'FAIL: stale restore-drill database(s) exist; refusing to create another:\n%s\n' "$stale" >&2
  exit 1
fi

printf 'SELECT count(*) FROM pg_database WHERE datname = '\''%s'\'';\n' "$SCRATCH_DB" > "$_d/check-before.sql"
before="$(admin_sql < "$_d/check-before.sql")"
[ "$before" = 0 ] || die "unique scratch database unexpectedly already exists: $SCRATCH_DB"

printf 'CREATE DATABASE "%s" OWNER "%s" TEMPLATE template0;\n' "$SCRATCH_DB" "$DB_USERNAME" > "$_d/create.sql"
CREATED=1
admin_sql < "$_d/create.sql"
printf 'created scratch database %s\n' "$SCRATCH_DB"

# Prepend one password line to the binary archive stream. The in-container shell consumes only that
# line, disables xtrace before assigning it, then pg_restore consumes the untouched remaining bytes.
# This accommodates the pod's read-only filesystem without putting the credential in argv.
{
  cat "$_d/db-password"
  printf '\n'
  cat "$RESTORE_FILE"
} | "$KUBECTL" --kubeconfig "$KUBECONFIG" exec -i -n "$NAMESPACE" "$DB_POD" -c postgres -- \
  env "PGHOST=$DB_HOST" PGPORT=5432 "PGUSER=$DB_USERNAME" "PGDATABASE=$SCRATCH_DB" \
  sh -c 'set +x; IFS= read -r p; export PGPASSWORD="$p"; exec pg_restore -w --single-transaction --exit-on-error --no-owner --no-privileges --dbname="$PGDATABASE"'

query_counts="SELECT (SELECT count(*) FROM realm), (SELECT count(*) FROM client), (SELECT count(*) FROM realm WHERE name = 'master');"
counts="$({ cat "$_d/db-password"; printf '\n'; } | \
  "$KUBECTL" --kubeconfig "$KUBECONFIG" exec -i -n "$NAMESPACE" "$DB_POD" -c postgres -- \
    env "PGHOST=$DB_HOST" PGPORT=5432 "PGUSER=$DB_USERNAME" "PGDATABASE=$SCRATCH_DB" \
    sh -c 'set +x; IFS= read -r p; export PGPASSWORD="$p"; exec psql -w -X -v ON_ERROR_STOP=1 -qAt -F "|" -c "$1"' sh "$query_counts")"
IFS='|' read -r realm_count client_count master_count <<< "$counts"
[[ "$realm_count" =~ ^[0-9]+$ ]] || die "realm row count is not numeric: $realm_count"
[[ "$client_count" =~ ^[0-9]+$ ]] || die "client row count is not numeric: $client_count"
[[ "$master_count" =~ ^[0-9]+$ ]] || die "master realm row count is not numeric: $master_count"
[ "$realm_count" -gt 0 ] || die "restored realm table has zero rows"
[ "$client_count" -gt 0 ] || die "restored client table has zero rows"
[ "$master_count" -eq 1 ] || die "restored database has $master_count rows for the master realm, expected exactly 1"

printf 'restored row counts: realm=%s client=%s master=%s\n' "$realm_count" "$client_count" "$master_count"
printf 'RESULT: PASS — dump restored into isolated scratch database; cleanup will now drop it\n'
