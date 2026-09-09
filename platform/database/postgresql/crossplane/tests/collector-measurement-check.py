#!/usr/bin/env python3
"""Exercise the WAL-exposure metrics parser, including the unsafe proxy it replaced."""

from __future__ import annotations

import json
import pathlib
import re
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "collector/measure-wal-exposure.sh"
COMPOSITION = ROOT / "crossplane/composition.yaml"

BASE = {
    'cnpg_collector_pg_wal_archive_status{value="ready"}': '0',
    'cnpg_pg_stat_archiver_last_archived_time': '1787533506.416559',
    'cnpg_pg_stat_archiver_seconds_since_last_archival': '36663.048332',
    'cnpg_pg_settings_setting{name="archive_timeout"}': '300',
}


class MeasurementError(ValueError):
    pass


def run(samples: dict[str, str], duplicate: str | None = None) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory(prefix="wal-exposure-") as directory:
        path = pathlib.Path(directory) / "metrics"
        lines = ["# synthetic CNPG Prometheus exposition"]
        lines.extend(f"{name} {value}" for name, value in samples.items())
        if duplicate:
            lines.append(f"{duplicate} {samples[duplicate]}")
        path.write_text("\n".join(lines) + "\n")
        return subprocess.run([str(SCRIPT), str(path)], check=False, capture_output=True, text=True)


def require_failure(name: str, samples: dict[str, str], expected: str, duplicate: str | None = None) -> None:
    result = run(samples, duplicate)
    if result.returncode == 0 or expected not in result.stderr:
        raise MeasurementError(
            f"{name} did not fail for {expected!r}: rc={result.returncode}, stderr={result.stderr!r}"
        )
    print(f"NEGATIVE CONTROL PASS: {name}: {expected}")


def main() -> int:
    source = COMPOSITION.read_text()
    match = re.search(r'\$collectorImage := "([^"]+@sha256:[a-f0-9]{64})"', source)
    if not match:
        raise MeasurementError("collector image must be digest-pinned in the Composition")
    image_check = subprocess.run(
        [
            "docker", "run", "--rm", "--entrypoint", "/bin/sh", match.group(1), "-c",
            "command -v bash >/dev/null && command -v curl >/dev/null && "
            "command -v python3 >/dev/null && command -v kubectl >/dev/null",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if image_check.returncode:
        raise MeasurementError(
            f"pinned collector image lacks a runtime dependency: {image_check.stderr.strip()}"
        )
    print("PASS pinned collector image supplies bash, curl, python3 and kubectl")

    idle = run(BASE)
    if idle.returncode:
        raise MeasurementError(idle.stderr)
    idle_data = json.loads(idle.stdout)
    if idle_data["walLagSeconds"] != "300" or idle_data["pendingWalCount"] != "0":
        raise MeasurementError(f"idle exposure must cap at archive_timeout: {idle_data}")
    print("PASS idle exposure: capped at archive_timeout instead of growing with idle time")

    pending_samples = dict(BASE)
    pending_samples.update({
        'cnpg_collector_pg_wal_archive_status{value="ready"}': '2',
        'cnpg_pg_stat_archiver_seconds_since_last_archival': '600.25',
    })
    pending = run(pending_samples)
    if pending.returncode:
        raise MeasurementError(pending.stderr)
    pending_data = json.loads(pending.stdout)
    if pending_data["walLagSeconds"] != "0" or pending_data["pendingWalCount"] != "2":
        raise MeasurementError("pending backlog must be published as age-unproven: " + pending.stdout)
    print("PASS pending backlog: count is measured while age remains deliberately unproven")

    missing = dict(BASE)
    missing.pop('cnpg_collector_pg_wal_archive_status{value="ready"}')
    require_failure("missing pending-count metric", missing, "missing metrics")
    require_failure(
        "duplicate metric", BASE, "duplicate metric", 'cnpg_pg_stat_archiver_last_archived_time'
    )
    fractional = dict(BASE)
    fractional['cnpg_collector_pg_wal_archive_status{value="ready"}'] = '1.5'
    require_failure("fractional count", fractional, "must be integral")
    negative = dict(BASE)
    negative['cnpg_pg_stat_archiver_seconds_since_last_archival'] = '-1'
    require_failure("negative sample", negative, "invalid metric")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
