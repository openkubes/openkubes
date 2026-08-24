#!/usr/bin/env bash
# Measure WAL-archive exposure and emit an ArchiveFreshness artifact (§13 bound 1's collector).
#
# WHAT IS MEASURED, and why it is not "time since the last archived WAL":
#   exposure = pending > 0 ? age of the OLDEST unarchived segment
#                          : min(time since last archive, archive_timeout)
# An idle database produces no WAL, so it has no RPO exposure. Measured on ok-robotics
# 2026-08-21: 747s since the last archive with ZERO pending segments and zero failures — under a
# 300s bound the naive measure reports Failed on a database with nothing whatsoever at risk. When
# nothing is pending the only data exposed is the still-open segment, which archive_timeout caps.
#
# Runs INSIDE the workload cluster, because the exposure lives in the primary's filesystem
# (archive_status/*.ready) and in pg_stat_archiver — neither is reachable from the management
# plane. Publication is a separate step with a separate image; this script only measures and
# writes the artifact to stdout.
#
# Every identity in the artifact is READ FROM THE CLUSTER, never passed in: clusterRef.uid from the
# CNPG Cluster, archive_timeout from pg_settings. Passing them as arguments would let a caller
# bind a measurement to a database it did not measure.
#
# Usage: measure-wal-exposure.sh <namespace> <cnpg-cluster>
# Exit:  0 artifact written, 1 measurement failed, 2 usage/plumbing
set -uo pipefail

NS="${1:?namespace required}"
CLUSTER="${2:?cnpg cluster required}"
VERIFIER="wal-exposure-collector/0.1.0"

command -v kubectl >/dev/null || { echo 'ERROR: kubectl not found' >&2; exit 2; }

primary="$(kubectl -n "$NS" get pods -l "cnpg.io/cluster=$CLUSTER,cnpg.io/instanceRole=primary" \
  -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)"
[[ -n "$primary" ]] || { printf 'ERROR: no primary pod for cluster %s/%s\n' "$NS" "$CLUSTER" >&2; exit 1; }

cluster_uid="$(kubectl -n "$NS" get cluster.postgresql.cnpg.io "$CLUSTER" -o jsonpath='{.metadata.uid}' 2>/dev/null)"
[[ -n "$cluster_uid" ]] || { echo 'ERROR: could not read the CNPG Cluster uid' >&2; exit 1; }

# databaseRef is deliberately NOT part of ArchiveFreshness: the measurement describes a CNPG
# cluster's archiving, and the Composition binds it by clusterRef. Nothing here needs the XR.

# THREE separate execs, one quoting level each. An earlier version nested
# kubectl exec -> bash -c -> psql -c "...to_char(...,'YYYY-MM-DD\"T\"...')..." and the escaping
# did not survive: it failed with exit 2 and no message at all. Splitting is not a style choice —
# each call below has exactly one layer of quotes, so there is nothing to get wrong.

# 1. Filesystem: how much is queued, and how old is the oldest queued segment.
pending_line="$(kubectl -n "$NS" exec "$primary" -c postgres -- bash -c 'd="$PGDATA/pg_wal/archive_status"; n=$(ls -1 "$d"/*.ready 2>/dev/null | wc -l); if [ "$n" -gt 0 ]; then o=$(ls -1t "$d"/*.ready | tail -1); a=$(( $(date -u +%s) - $(stat -c %Y "$o") )); else a=0; fi; echo "$n|$a"' 2>/dev/null | tail -1)"
IFS='|' read -r pending oldest_age <<<"$pending_line"

# 2. Archiver state, as EPOCHS. Formatting a timestamp inside SQL needs double quotes around the
#    literal T and Z, which is exactly what broke before; the shell formats it instead.
archiver="$(kubectl -n "$NS" exec "$primary" -c postgres -- psql -U postgres -d postgres -X -A -t -F'|' \
  -c "SELECT coalesce(extract(epoch from last_archived_time)::bigint, -1), coalesce(extract(epoch from (now() - last_archived_time))::bigint, -1), coalesce(failed_count, 0) FROM pg_stat_archiver;" 2>/dev/null | tail -1)"
IFS='|' read -r last_epoch since failed <<<"$archiver"

# 3. The platform's own cap on open-segment exposure.
timeout="$(kubectl -n "$NS" exec "$primary" -c postgres -- psql -U postgres -d postgres -X -A -t \
  -c "SELECT setting::int FROM pg_settings WHERE name = 'archive_timeout';" 2>/dev/null | tail -1)"

for field in pending oldest_age last_epoch since timeout; do
  [[ "${!field}" =~ ^-?[0-9]+$ ]] || { printf 'ERROR: %s is not a number: %q\n' "$field" "${!field}" >&2; exit 1; }
done
(( last_epoch >= 0 )) || { echo 'ERROR: pg_stat_archiver reports no last_archived_time; nothing has been archived yet, so there is no exposure to measure' >&2; exit 1; }
(( timeout > 0 )) || { echo 'ERROR: archive_timeout is 0, so open-segment exposure is unbounded and this measure cannot bound it' >&2; exit 1; }
last_archived="$(date -u -d "@${last_epoch}" +%Y-%m-%dT%H:%M:%SZ)"

if (( pending > 0 )); then
  exposure="$oldest_age"
else
  exposure=$(( since < timeout ? since : timeout ))
fi

observed_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
name="$(printf '%s-%s' "$CLUSTER" "$(printf '%s' "$observed_at" | tr -d ':-' | tr 'TZ' 'tz')")"
# Digest of the METHOD, so a weaker measurement is distinguishable from this one in the record.
digest="$(printf 'exposure = pending>0 ? oldest_ready_age : min(since_last_archive, archive_timeout); sources: archive_status/*.ready, pg_stat_archiver, pg_settings.archive_timeout' | sha256sum | cut -d' ' -f1)"

cat <<YAML
apiVersion: evidence.platform.openkubes.ai/v1alpha1
kind: ArchiveFreshness
metadata:
  name: ${name}
  labels:
    platform.openkubes.ai/source-cluster: ${CLUSTER}
spec:
  clusterRef:
    apiVersion: postgresql.cnpg.io/v1
    kind: Cluster
    namespace: ${NS}
    name: ${CLUSTER}
    uid: ${cluster_uid}
  observed:
    walLagSeconds: ${exposure}
    pendingWalCount: ${pending}
    lastArchivedWalTime: "${last_archived}"
    archiveTimeoutSeconds: ${timeout}
  timing:
    observedAt: "${observed_at}"
  probeDigest: sha256:${digest}
  verifierVersion: ${VERIFIER}
YAML

printf 'MEASURED exposure=%ss pending=%s sinceLastArchive=%ss archiveTimeout=%ss failed=%s\n' \
  "$exposure" "$pending" "$since" "$timeout" "$failed" >&2
