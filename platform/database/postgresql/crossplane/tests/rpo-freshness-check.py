#!/usr/bin/env python3
"""Prove production protection needs a MEASURED WAL lag, not a proxy (§13 bound 1).

`ContinuousArchiving=True` means archiving is not currently failing. It says nothing about how
far behind the archive is, so a slow or stalled-but-not-failed archiver satisfies it. Before this
bound, production could therefore reach `ProtectionReady=Valid` on that condition alone — an RPO
claim the ADR explicitly disclaims (§10).

The three states are deliberately different, and mixing them up is the whole failure mode:

    no measurement / aged out   -> Unknown   (we cannot see the lag)
    lag beyond the bound        -> Failed    (we looked; the archive is behind)
    lag within the bound        -> Valid

`no-observation-cannot-be-valid` is the case that was broken. `expired-observation-is-unknown`
guards the other direction: an old measurement is not a current claim, and must not be reused as
one — but it is also not a counter-proof, because §11.1 forbids treating inability to observe as
evidence of failure.
"""

from __future__ import annotations

import argparse
import copy
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

TESTS_DIR = Path(__file__).resolve().parent
CAPABILITY_DIR = TESTS_DIR.parent.parent
COMPOSITION_PATH = CAPABILITY_DIR / "crossplane/composition.yaml"
PRODUCTION_XR = TESTS_DIR / "xr-ok-robotics-production.yaml"
DEVELOPMENT_XR = TESTS_DIR / "xr-ok-robotics.yaml"
OBSERVED_PATH = TESTS_DIR / "observed-ok-robotics-valid.yaml"
CLUSTER_UID = "1c47d9d1-2cc2-4619-8265-a1598cb22274"
RFC3339 = "%Y-%m-%dT%H:%M:%SZ"


class RpoError(ValueError):
    pass


def stamp(moment: datetime) -> str:
    return moment.strftime(RFC3339)


def freshness(observed_at: datetime, lag: int, pending: int = 0, uid: str = CLUSTER_UID) -> dict:
    return {
        "apiVersion": "evidence.platform.openkubes.ai/v1alpha1",
        "kind": "ArchiveFreshness",
        "metadata": {
            "name": "af-" + stamp(observed_at).lower().replace(":", "").replace("-", ""),
            "labels": {"platform.openkubes.ai/source-cluster": "ok-robotics"},
        },
        "spec": {
            "clusterRef": {
                "apiVersion": "postgresql.cnpg.io/v1",
                "kind": "Cluster",
                "namespace": "database-ok-robotics",
                "name": "ok-robotics",
                "uid": uid,
            },
            "observed": {
                "walLagSeconds": lag,
                "pendingWalCount": pending,
                "lastArchivedWalTime": stamp(observed_at - timedelta(seconds=lag)),
            },
            "timing": {"observedAt": stamp(observed_at)},
            "probeDigest": "sha256:" + "2" * 64,
            "verifierVersion": "wal-lag-probe/0.1.0",
        },
    }


def healthy_observed(now: datetime) -> list[dict[str, Any]]:
    """Observed state where everything EXCEPT rpo is satisfied, so rpo is what decides."""
    docs = copy.deepcopy([d for d in yaml.safe_load_all(OBSERVED_PATH.read_text()) if d])
    for doc in docs:
        manifest = doc.get("status", {}).get("atProvider", {}).get("manifest", {})
        if manifest.get("kind") == "Backup":
            manifest["status"].update(stoppedAt=stamp(now - timedelta(hours=1)))
        elif manifest.get("kind") == "ObjectStore":
            manifest["status"] = {
                "serverRecoveryWindow": {
                    "ok-robotics": {
                        "firstRecoverabilityPoint": stamp(now - timedelta(days=2)),
                        "lastSuccessfulBackupTime": stamp(now - timedelta(minutes=30)),
                    }
                }
            }
    return docs


def render(xr_path: Path, extras: list[dict] | None, now: datetime) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="ok-150-rpo-") as directory:
        work = Path(directory)
        observed_path = work / "observed.yaml"
        observed_path.write_text(yaml.safe_dump_all(healthy_observed(now), sort_keys=False))
        command = [
            "crossplane",
            "composition",
            "render",
            str(xr_path),
            str(COMPOSITION_PATH),
            str(TESTS_DIR / "functions.yaml"),
            "--crossplane-version=v2.3.3",
            "--include-full-xr",
            f"--observed-resources={observed_path}",
        ]
        if extras:
            extra_path = work / "extra.yaml"
            extra_path.write_text(yaml.safe_dump_all(extras, sort_keys=False))
            command.append(f"--extra-resources={extra_path}")
        result = subprocess.run(
            command, cwd=CAPABILITY_DIR, check=False, capture_output=True, text=True
        )
        if result.returncode != 0:
            raise RpoError(f"render failed ({result.returncode}): {result.stderr.strip()}")
        databases = [
            d
            for d in yaml.safe_load_all(result.stdout)
            if isinstance(d, dict) and d.get("kind") == "Database" and "status" in d
        ]
        if len(databases) != 1:
            raise RpoError(f"expected one rendered Database, got {len(databases)}")
        return databases[0]["status"]


def rpo_of(status: dict[str, Any]) -> tuple[str, str]:
    signal = status["evidence"]["protection"]["signals"].get("rpo")
    if not isinstance(signal, dict):
        raise RpoError("protection publishes no rpo signal at all")
    return signal.get("state", ""), signal.get("reason", "")


def protection_of(status: dict[str, Any]) -> tuple[str, str]:
    protection = status["evidence"]["protection"]
    return protection.get("state", ""), protection.get("reason", "")


def positive() -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)

    within = render(PRODUCTION_XR, [freshness(now - timedelta(minutes=1), lag=30)], now)
    if rpo_of(within) != ("Valid", "RPOWithinBound"):
        raise RpoError(f"a fresh in-bound measurement must be Valid/RPOWithinBound, got {rpo_of(within)}")
    if protection_of(within)[0] != "Valid":
        raise RpoError(
            f"production protection must be Valid once every signal is, got {protection_of(within)}"
        )
    print(f"PASS in-bound measurement: rpo {rpo_of(within)[1]}, protection Valid")

    # development must be untouched: requiring an observation nothing publishes yet would make
    # every dev Database unready, which is why the class distinction is deliberate.
    dev = render(DEVELOPMENT_XR, None, now)
    if rpo_of(dev) != ("Valid", "RPONotRequiredForClass"):
        raise RpoError(f"development must not require RPO evidence, got {rpo_of(dev)}")
    print(f"PASS development unaffected: {rpo_of(dev)[1]}")


def negative_controls() -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)

    # The case bound 1 is about: nothing measured, and production must NOT be Valid even though
    # ContinuousArchiving=True and every other signal is satisfied.
    none = render(PRODUCTION_XR, None, now)
    if rpo_of(none) != ("Unknown", "RPOFreshnessUnproven"):
        raise RpoError(
            f"NEGATIVE CONTROL FAILED: with no measurement rpo must be Unknown/"
            f"RPOFreshnessUnproven, got {rpo_of(none)}"
        )
    if protection_of(none)[0] == "Valid":
        raise RpoError(
            "NEGATIVE CONTROL FAILED: production protection reached Valid with no RPO measurement "
            "— that is ContinuousArchiving standing in for an RPO bound, the exact proxy this "
            "bound removes"
        )
    if none["serviceReady"] is not False:
        raise RpoError("NEGATIVE CONTROL FAILED: production serviceReady=true with no RPO evidence")
    print(
        f"NEGATIVE CONTROL PASS: no measurement: rpo {rpo_of(none)[1]}, "
        f"protection {protection_of(none)[1]}, serviceReady false"
    )

    over = render(PRODUCTION_XR, [freshness(now - timedelta(minutes=1), lag=3600)], now)
    if rpo_of(over) != ("Failed", "RPOBoundExceeded"):
        raise RpoError(
            f"NEGATIVE CONTROL FAILED: a lag past the bound is a counter-proof, got {rpo_of(over)}"
        )
    if protection_of(over) != ("Failed", "RPOBoundExceeded"):
        raise RpoError(
            f"NEGATIVE CONTROL FAILED: protection must fail on an exceeded RPO bound, got "
            f"{protection_of(over)}"
        )
    print(f"NEGATIVE CONTROL PASS: lag beyond bound: {protection_of(over)[1]} (a counter-proof)")

    # An old measurement is not a current claim — but it is not a counter-proof either.
    expired = render(PRODUCTION_XR, [freshness(now - timedelta(hours=2), lag=30)], now)
    if rpo_of(expired) != ("Unknown", "RPOObservationExpired"):
        raise RpoError(
            f"NEGATIVE CONTROL FAILED: an aged-out measurement must be Unknown/"
            f"RPOObservationExpired, got {rpo_of(expired)}"
        )
    print(f"NEGATIVE CONTROL PASS: aged-out measurement: {rpo_of(expired)[1]} (not Failed)")

    # A measurement for a different cluster must be invisible, not borrowed.
    other = render(
        PRODUCTION_XR, [freshness(now - timedelta(minutes=1), lag=30, uid="other-cluster-uid")], now
    )
    if rpo_of(other) != ("Unknown", "RPOFreshnessUnproven"):
        raise RpoError(
            f"NEGATIVE CONTROL FAILED: a measurement bound to another cluster was used, got "
            f"{rpo_of(other)}"
        )
    print(f"NEGATIVE CONTROL PASS: measurement for another cluster: {rpo_of(other)[1]}")

    # A future measurement is a broken clock, not freshness.
    future = render(PRODUCTION_XR, [freshness(now + timedelta(hours=1), lag=30)], now)
    if rpo_of(future)[0] == "Valid":
        raise RpoError("NEGATIVE CONTROL FAILED: a future-dated measurement was accepted")
    print(f"NEGATIVE CONTROL PASS: future-dated measurement: {rpo_of(future)[1]}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--negative-controls", action="store_true")
    args = parser.parse_args()
    try:
        if args.negative_controls:
            negative_controls()
        else:
            positive()
    except RpoError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
