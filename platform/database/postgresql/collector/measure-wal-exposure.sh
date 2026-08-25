#!/usr/bin/env bash
# Parse CNPG's default Prometheus exposition and emit the measurement fields written to the
# per-Database collector observation ConfigMap. The runtime adds the name-scoped Cluster UID.
#
# Default CNPG metrics expose backlog count but not the age of the oldest remaining .ready file.
# A recent successful archive can leave an already-queued successor, so pending age is deliberately
# unproven. With no backlog, archive_timeout caps open-segment exposure. This needs no custom SQL,
# superuser grant, pod exec, or management token.
#
# Usage: measure-wal-exposure.sh <prometheus-metrics-file>
set -Eeuo pipefail
[[ $# -eq 1 ]] || { echo 'usage: measure-wal-exposure.sh <prometheus-metrics-file>' >&2; exit 2; }
metrics=$1
[[ -f "$metrics" ]] || { printf 'ERROR: metrics file not found: %s\n' "$metrics" >&2; exit 2; }
python3 - "$metrics" <<'PY'
import datetime, hashlib, json, math, pathlib, sys
metrics_path = pathlib.Path(sys.argv[1])
wanted = {
    'cnpg_collector_pg_wal_archive_status{value="ready"}',
    'cnpg_pg_stat_archiver_last_archived_time',
    'cnpg_pg_stat_archiver_seconds_since_last_archival',
    'cnpg_pg_settings_setting{name="archive_timeout"}',
}
found = {}
for raw in metrics_path.read_text().splitlines():
    if not raw or raw.startswith('#'):
        continue
    parts = raw.rsplit(None, 1)
    if len(parts) != 2 or parts[0] not in wanted:
        continue
    if parts[0] in found:
        raise SystemExit(f'duplicate metric: {parts[0]}')
    value = float(parts[1])
    if not math.isfinite(value) or value < 0:
        raise SystemExit(f'invalid metric {parts[0]}={parts[1]}')
    found[parts[0]] = value
missing = wanted - found.keys()
if missing:
    raise SystemExit('missing metrics: ' + ', '.join(sorted(missing)))
integer_metrics = [
    'cnpg_collector_pg_wal_archive_status{value="ready"}',
    'cnpg_pg_settings_setting{name="archive_timeout"}',
]
if any(found[name] != math.floor(found[name]) for name in integer_metrics):
    raise SystemExit('count and timeout metrics must be integral')
pending = int(found['cnpg_collector_pg_wal_archive_status{value="ready"}'])
since = found['cnpg_pg_stat_archiver_seconds_since_last_archival']
timeout = int(found['cnpg_pg_settings_setting{name="archive_timeout"}'])
last_epoch = found['cnpg_pg_stat_archiver_last_archived_time']
if timeout <= 0:
    raise SystemExit('incoherent WAL exposure metrics')
exposure = 0 if pending else min(math.ceil(since), timeout)
observed = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
last = datetime.datetime.fromtimestamp(last_epoch, datetime.timezone.utc).replace(microsecond=0)
method = 'exposure = pending>0 ? unproven : min(ceil(seconds_since_last_archive), archive_timeout); sources: CNPG default pg_wal_archive_status/pg_stat_archiver/pg_settings metrics'
digest = 'sha256:' + hashlib.sha256(method.encode()).hexdigest()
print(json.dumps({
    'observedAt': observed.isoformat().replace('+00:00', 'Z'),
    'walLagSeconds': str(exposure),
    'pendingWalCount': str(pending),
    'lastArchivedWalTime': last.isoformat().replace('+00:00', 'Z'),
    'archiveTimeoutSeconds': str(timeout),
    'probeDigest': digest,
    'verifierVersion': 'wal-exposure-metrics-collector/0.2.0',
}, separators=(',', ':')))
PY
