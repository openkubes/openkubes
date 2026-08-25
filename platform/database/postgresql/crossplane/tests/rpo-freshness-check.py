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
MAKEFILE_PATH = CAPABILITY_DIR / "Makefile"
PRODUCTION_XR = TESTS_DIR / "xr-ok-robotics-production.yaml"
DEVELOPMENT_XR = TESTS_DIR / "xr-ok-robotics.yaml"
OBSERVED_PATH = TESTS_DIR / "observed-ok-robotics-valid.yaml"
CLUSTER_UID = "1c47d9d1-2cc2-4619-8265-a1598cb22274"
RFC3339 = "%Y-%m-%dT%H:%M:%SZ"


class RpoError(ValueError):
    pass


def stamp(moment: datetime) -> str:
    return moment.strftime(RFC3339)


def freshness(
    observed_at: datetime,
    lag: int,
    pending: int = 0,
    name: str = "ok-robotics-archive-freshness",
    archive_timeout: int = 300,
) -> dict:
    return {
        "apiVersion": "kubernetes.crossplane.io/v1alpha2",
        "kind": "Object",
        "metadata": {
            "name": "database-ok-robotics-collector-observation",
            "annotations": {"crossplane.io/composition-resource-name": "collector-observation"},
        },
        "status": {
            "atProvider": {
                "manifest": {
                    "apiVersion": "v1",
                    "kind": "ConfigMap",
                    "metadata": {"name": name, "namespace": "database-ok-robotics"},
                    "data": {
                        "clusterUid": CLUSTER_UID,
                        "observedAt": stamp(observed_at),
                        "walLagSeconds": str(lag),
                        "pendingWalCount": str(pending),
                        "lastArchivedWalTime": stamp(observed_at - timedelta(seconds=lag)),
                        "archiveTimeoutSeconds": str(archive_timeout),
                        "probeDigest": "sha256:904a29ee996692fe937f6ec8e4ef140b3d115f025250daf5cabac75baaca8ef5",
                        "verifierVersion": "wal-exposure-metrics-collector/0.2.0",
                    },
                }
            }
        },
    }


def observation_data(observation: dict[str, Any]) -> dict[str, str]:
    return observation["status"]["atProvider"]["manifest"]["data"]


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


def render(xr_path: Path, observations: list[dict] | None, now: datetime) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="ok-150-rpo-") as directory:
        work = Path(directory)
        observed_path = work / "observed.yaml"
        observed = healthy_observed(now)
        if observations:
            observed.extend(observations)
        observed_path.write_text(yaml.safe_dump_all(observed, sort_keys=False))
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
            f"--extra-resources={TESTS_DIR / 'target-ok-robotics.yaml'}",
        ]
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


def check_recovery_validity_is_its_own_quantity() -> None:
    """Restore-evidence age and backup age are different quantities (§11.1 says so explicitly).

    The Composition computed recovery expiry from $backupValidity, so production — where backups
    must be under 24h old — also demanded a completed restore drill every 24 hours. A drill
    provisions a whole recovery cluster and each artifact is admitted by a human under §7, so that
    made production unattainable rather than strict. Observed on ok-robotics: recovery went
    Stale/RestoreEvidenceExpired three days after a passing drill while backups were healthy.
    """
    source = COMPOSITION_PATH.read_text()
    assert "$recoveryValidity" in source, (
        "recovery expiry must derive from its own $recoveryValidity, not from $backupValidity"
    )
    import re as _re
    expiry = _re.search(r"\$recoveryExpiry := dateModify (\$[A-Za-z]+)", source)
    assert expiry, "could not find the recovery expiry derivation"
    assert expiry.group(1) == "$recoveryValidity", (
        f"recovery expiry still derives from {expiry.group(1)}: backup age and restore-evidence "
        "age are different quantities and §11.1 forbids reading one as the other"
    )
    print("PASS recovery validity: derived from $recoveryValidity, not from backup age")


def check_storage_is_protection_independent() -> None:
    """Capacity must not follow the protection class (§6 orthogonality).

    This is not a style rule. While storage was a protection-class attribute, switching a live
    Database to `production` composed a 20Gi PVC against a 5Gi volume on `local-path`, whose
    allowVolumeExpansion is unset — so the resize could not succeed and production was
    unreachable on this platform for a reason that had nothing to do with protection. Capacity
    belongs to `performance`.
    """
    source = COMPOSITION_PATH.read_text()
    assert "$performanceStorage" in source, (
        "storage size must derive from a performance-class registry, not from the protection class"
    )
    for forbidden in ('{{- $storageSize = "', "$storageSize = "):
        assert forbidden not in source, (
            "storage size is being REASSIGNED after its initial derivation; the only reassignment "
            "this ever had was the production override that made capacity follow protection"
        )
    print("PASS storage independence: capacity derives from performance.class, never reassigned")


def check_install_gate_text() -> None:
    """The install gate must not tell an operator the opposite of what the code does.

    That text is what someone reads while deciding to accept the open bounds, and it drifted
    exactly this way once: it still said "ProtectionReady is NOT an RPO bound" and "pgvector needs
    the ImageVolume feature gate" after both had stopped being true. It is prose, so nothing
    misbehaves — which is precisely why nothing catches it. This does.
    """
    text = MAKEFILE_PATH.read_text()
    marker = 'ACCEPT_PROTOTYPE_LIMITS)" = yes'
    if marker not in text:
        raise RpoError(
            "could not find the ACCEPT_PROTOTYPE_LIMITS gate in the Makefile; if it was renamed, "
            "this guard needs updating rather than deleting"
        )
    start = text.index(marker)
    gate = text[start : text.index("Rerun with ACCEPT_PROTOTYPE_LIMITS", start)]

    if "ProtectionReady is NOT an RPO bound" in gate:
        raise RpoError(
            "the install gate still claims ProtectionReady is not an RPO bound, but production "
            "now requires a measured WAL lag — an operator would go fix the wrong thing"
        )
    if "needs the ImageVolume feature gate" in gate and "containerd" not in gate:
        raise RpoError(
            "the install gate names the ImageVolume gate as the capability prerequisite without "
            "containerd >= 2.1.0; the gate alone is necessary but not sufficient"
        )
    if "nothing publishes" in gate:
        raise RpoError("the install gate still claims the now-composed collector does not exist")
    # The two human acts remain explicit: approving the method is separate from installation,
    # and an existing consumer must move off the owner role before it becomes NOLOGIN.
    for needle, why in (
        ("approve-verification-profile", "method approval must not be manufactured by setup"),
        ("NOLOGIN", "the app role stops being a login role and consumers must be repointed"),
    ):
        if needle not in gate:
            raise RpoError(f"the install gate does not mention {needle}: {why}")
    print("PASS install gate: names explicit method approval, the NOLOGIN cutover and containerd")


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

    # THE case measured on ok-robotics: an idle database, 0 pending, exposure capped by
    # archive_timeout. The original semantics ("seconds since last archived WAL") reported 747s
    # here and would have failed a database with nothing at risk.
    idle = render(
        PRODUCTION_XR,
        [freshness(now - timedelta(minutes=1), lag=300, pending=0, archive_timeout=300)],
        now,
    )
    if rpo_of(idle)[0] != "Valid":
        raise RpoError(
            f"an idle database with no pending segments must not fail its RPO bound; exposure is "
            f"capped by archive_timeout. Got {rpo_of(idle)}"
        )
    print(f"PASS idle database: {rpo_of(idle)[1]} (exposure capped by archive_timeout, not idle time)")

    # A class bound tighter than archive_timeout is unsatisfiable by construction, and blaming the
    # database for a configuration decision would be the wrong verdict.
    tight = render(
        PRODUCTION_XR,
        [freshness(now - timedelta(minutes=1), lag=60, pending=0, archive_timeout=900)],
        now,
    )
    if rpo_of(tight) != ("Failed", "RPOArchiveTimeoutExceedsBound"):
        raise RpoError(
            f"archive_timeout wider than the class bound must be named as such, got {rpo_of(tight)}"
        )
    print(f"PASS archive_timeout wider than bound: {rpo_of(tight)[1]}")

    pending = render(
        PRODUCTION_XR,
        [freshness(now - timedelta(minutes=1), lag=0, pending=4, archive_timeout=300)],
        now,
    )
    if rpo_of(pending) != ("Unknown", "RPOPendingWALAgeUnproven"):
        raise RpoError(
            f"NEGATIVE CONTROL FAILED: pending WAL with unmeasured age must be Unknown, got {rpo_of(pending)}"
        )
    if protection_of(pending)[0] == "Valid":
        raise RpoError("NEGATIVE CONTROL FAILED: production protection is Valid with pending WAL age unproven")
    print("NEGATIVE CONTROL PASS: pending WAL count cannot be converted into invented age")

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
        PRODUCTION_XR,
        [freshness(now - timedelta(minutes=1), lag=30, name="another-db-archive-freshness")],
        now,
    )
    if rpo_of(other) != ("Unknown", "RPOFreshnessUnproven"):
        raise RpoError(
            f"NEGATIVE CONTROL FAILED: a measurement bound to another cluster was used, got "
            f"{rpo_of(other)}"
        )
    print(f"NEGATIVE CONTROL PASS: measurement for another cluster: {rpo_of(other)[1]}")

    replaced_cluster = freshness(now - timedelta(minutes=1), lag=30)
    observation_data(replaced_cluster)["clusterUid"] = "replaced-cluster-uid"
    replaced_status = render(PRODUCTION_XR, [replaced_cluster], now)
    if rpo_of(replaced_status) != ("Unknown", "RPOFreshnessUnproven"):
        raise RpoError(f"NEGATIVE CONTROL FAILED: pre-replacement observation was reused: {rpo_of(replaced_status)}")
    print("NEGATIVE CONTROL PASS: observation bound to a replaced Cluster UID is not admitted")

    malformed = freshness(now - timedelta(minutes=1), lag=30)
    observation_data(malformed)["walLagSeconds"] = "not-a-number"
    malformed_status = render(PRODUCTION_XR, [malformed], now)
    if rpo_of(malformed_status) != ("Unknown", "RPOFreshnessUnproven"):
        raise RpoError(f"NEGATIVE CONTROL FAILED: malformed numeric data was used: {rpo_of(malformed_status)}")
    print("NEGATIVE CONTROL PASS: malformed observation fails closed without breaking reconciliation")

    incoherent = freshness(now - timedelta(minutes=1), lag=900, pending=0, archive_timeout=300)
    incoherent_status = render(PRODUCTION_XR, [incoherent], now)
    if rpo_of(incoherent_status) != ("Unknown", "RPOFreshnessUnproven"):
        raise RpoError(f"NEGATIVE CONTROL FAILED: idle lag beyond archive_timeout was used: {rpo_of(incoherent_status)}")
    print("NEGATIVE CONTROL PASS: incoherent idle exposure is not admitted")

    wrong_method = freshness(now - timedelta(minutes=1), lag=30)
    observation_data(wrong_method)["probeDigest"] = "sha256:" + "0" * 64
    wrong_method_status = render(PRODUCTION_XR, [wrong_method], now)
    if rpo_of(wrong_method_status) != ("Unknown", "RPOFreshnessUnproven"):
        raise RpoError(f"NEGATIVE CONTROL FAILED: unreviewed measurement method was used: {rpo_of(wrong_method_status)}")
    print("NEGATIVE CONTROL PASS: unreviewed collector method is not admitted")

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
            check_recovery_validity_is_its_own_quantity()
            check_storage_is_protection_independent()
            check_install_gate_text()
            positive()
    except RpoError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
