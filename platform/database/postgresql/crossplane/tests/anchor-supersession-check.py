#!/usr/bin/env python3
"""Prove protection evidence follows the SCHEDULE, not the fixed anchor (§13 bound 3).

The evidence `Backup` is a fixed anchor because a static provider-kubernetes Object cannot
enumerate generated-name Backup CRs. Retention therefore prunes the anchor out of the moving
recovery window while scheduled backups are perfectly healthy, and the old logic read that as
`Failed/BackupUnavailable` — a counter-proof drawn from the age of our own bookmark rather than
from the state of the backups. Per §11.1 that is the most dangerous misreading in the model,
because staleness invites waiting while absence demands acting.

`anchor-pruned-while-backups-healthy` is the case that was wrong. The controls guard the other
direction — that this is a correction and not a suppression: an incoherent window, an unreadable
window and a failing archiver must all still refuse to read Valid.

Worth stating because it surprised this test: `Failed/BackupUnavailable` is NOT reachable from
recovery-window times alone. A coherent window has first <= last, so first > stoppedAt forces
last > stoppedAt and a newer success always exists. Total absence therefore surfaces as an
unreadable window, which §11.1 requires be Unknown rather than a counter-proof. Recovering a real
absence verdict needs Backup enumeration — the same residual gap that leaves backupId
unavailable here.
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
XR_PATH = TESTS_DIR / "xr-ok-robotics.yaml"
OBSERVED_PATH = TESTS_DIR / "observed-ok-robotics-valid.yaml"
SERVER = "ok-robotics"
RFC3339 = "%Y-%m-%dT%H:%M:%SZ"


class AnchorError(ValueError):
    pass


class RenderedYamlLoader(yaml.SafeLoader):
    """Keep date-time fields as strings so deliberately odd controls survive parsing."""


RenderedYamlLoader.yaml_implicit_resolvers = {
    key: [r for r in resolvers if r[0] != "tag:yaml.org,2002:timestamp"]
    for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def stamp(moment: datetime) -> str:
    return moment.strftime(RFC3339)


def observed(anchor_stopped: str, first_point: str, last_success: str) -> list[dict[str, Any]]:
    """The shared fixture with the anchor's stoppedAt and the recovery window driven directly."""
    docs = copy.deepcopy([d for d in yaml.safe_load_all(OBSERVED_PATH.read_text()) if d])
    for doc in docs:
        manifest = doc.get("status", {}).get("atProvider", {}).get("manifest", {})
        kind = manifest.get("kind")
        if kind == "Backup":
            manifest["status"]["stoppedAt"] = anchor_stopped
        elif kind == "ObjectStore":
            manifest["status"] = {
                "serverRecoveryWindow": {
                    SERVER: {
                        "firstRecoverabilityPoint": first_point,
                        "lastSuccessfulBackupTime": last_success,
                    }
                }
            }
    return docs


def render(docs: list[dict[str, Any]]) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="ok-150-anchor-") as directory:
        work = Path(directory)
        observed_path = work / "observed.yaml"
        observed_path.write_text(yaml.safe_dump_all(docs, sort_keys=False))
        result = subprocess.run(
            [
                "crossplane",
                "composition",
                "render",
                str(XR_PATH),
                str(COMPOSITION_PATH),
                str(TESTS_DIR / "functions.yaml"),
                "--crossplane-version=v2.3.3",
                "--include-full-xr",
                f"--observed-resources={observed_path}",
                f"--extra-resources={TESTS_DIR / 'target-ok-robotics.yaml'}",
            ],
            cwd=CAPABILITY_DIR,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise AnchorError(f"render failed ({result.returncode}): {result.stderr.strip()}")
        databases = [
            d
            for d in yaml.load_all(result.stdout, Loader=RenderedYamlLoader)
            if isinstance(d, dict) and d.get("kind") == "Database" and "status" in d
        ]
        if len(databases) != 1:
            raise AnchorError(f"expected one rendered Database, got {len(databases)}")
        return databases[0]["status"]["evidence"]


def parts(evidence: dict[str, Any]) -> dict[str, Any]:
    protection = evidence["protection"]
    return {
        "availability": (
            protection["signals"]["availability"]["state"],
            protection["signals"]["availability"]["reason"],
        ),
        "protection": (protection["state"], protection["reason"]),
        "backupId": protection.get("backupId"),
        "evidenceRef": protection.get("evidenceRef", ""),
        "validUntil": protection.get("validUntil", ""),
        "executionBackupId": protection["signals"]["execution"].get("backupId"),
    }


def anchor_pruned_while_healthy(now: datetime) -> dict[str, Any]:
    """Retention pruned the anchor; the window shows a backup from an hour ago."""
    return observed(
        anchor_stopped=stamp(now - timedelta(days=30)),
        first_point=stamp(now - timedelta(days=7)),
        last_success=stamp(now - timedelta(hours=1)),
    )


def positive() -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    result = parts(render(anchor_pruned_while_healthy(now)))

    if result["availability"] != ("Valid", "WindowSupersedesAnchor"):
        raise AnchorError(
            "an anchor pruned while backups are healthy must read Valid/WindowSupersedesAnchor, "
            f"got {result['availability'][0]}/{result['availability'][1]}"
        )
    if result["protection"][0] != "Valid":
        raise AnchorError(
            f"protection must stay Valid when the schedule is healthy, got "
            f"{result['protection'][0]}/{result['protection'][1]}"
        )
    # Freshness has to come from the superseding backup, or evidence still decays with the anchor
    # and the fix is cosmetic.
    if not result["validUntil"]:
        raise AnchorError("no validUntil was published for the superseding backup")
    valid_until = datetime.strptime(result["validUntil"], RFC3339).replace(tzinfo=timezone.utc)
    if valid_until <= now:
        raise AnchorError(
            f"validUntil {result['validUntil']} is already past: freshness is still tracking the "
            "30-day-old anchor rather than the one-hour-old backup"
        )
    # The window carries times, not identities. Naming an ID we never observed would be worse than
    # publishing none, so its ABSENCE is part of the contract.
    if result["backupId"]:
        raise AnchorError(
            f"backupId {result['backupId']!r} was published for a backup identified only by time; "
            "the recovery window carries no backup identity"
        )
    if "serverRecoveryWindow" not in result["evidenceRef"]:
        raise AnchorError(
            f"evidence must cite the recovery window it actually used, got {result['evidenceRef']!r}"
        )
    print(
        f"PASS anchor pruned while backups healthy: {result['availability'][1]}, "
        f"protection Valid, validUntil {result['validUntil']} from the superseding backup, "
        "no invented backupId"
    )

    # The case production exposed: the anchor is still INSIDE the window, but the schedule has
    # succeeded since. Freshness must come from that newer success, or a 24h validity expires
    # against a 3-day-old bookmark while backups are healthy.
    newer = parts(
        render(
            observed(
                anchor_stopped=stamp(now - timedelta(days=3)),
                first_point=stamp(now - timedelta(days=4)),
                last_success=stamp(now - timedelta(hours=13)),
            )
        )
    )
    if newer["availability"] != ("Valid", "BackupWindowContainsExecution"):
        raise AnchorError(
            f"a contained anchor must still read containment, got {newer['availability']}"
        )
    valid_until = datetime.strptime(newer["validUntil"], RFC3339).replace(tzinfo=timezone.utc)
    if valid_until <= now + timedelta(hours=1):
        raise AnchorError(
            f"validUntil {newer['validUntil']} is derived from the 3-day-old anchor, not the "
            "13-hour-old success in the window"
        )
    if newer["backupId"]:
        raise AnchorError(
            "freshness came from the window, so no backupId may be published for it: the window "
            f"carries times, not identities (got {newer['backupId']})"
        )
    print(
        f"PASS contained anchor, newer success: freshness from the window "
        f"(validUntil {newer['validUntil']}), no invented backupId"
    )

    # Regression: ordinary containment must be untouched.
    contained = parts(
        render(
            observed(
                anchor_stopped=stamp(now - timedelta(hours=2)),
                first_point=stamp(now - timedelta(days=7)),
                last_success=stamp(now - timedelta(hours=1)),
            )
        )
    )
    if contained["availability"] != ("Valid", "BackupWindowContainsExecution"):
        raise AnchorError(
            "a contained anchor must still read BackupWindowContainsExecution, got "
            f"{contained['availability'][0]}/{contained['availability'][1]}"
        )
    # protection.backupId is published only when protection's FRESHNESS derives from that anchor.
    # Here the window holds a newer success, so freshness comes from the window and the
    # protection-level id is correctly absent — citing an id whose timestamp is not the one that
    # set validUntil would describe two different backups as one. The observed identity is still
    # there on the execution signal, which is what it describes.
    if contained["backupId"]:
        raise AnchorError(
            "protection published a backupId while its freshness came from the window: that "
            f"conflates two backups (got {contained['backupId']})"
        )
    if not contained["executionBackupId"]:
        raise AnchorError(
            "the execution signal must still publish the anchor's observed backupId; that is the "
            "identity it describes"
        )
    print(
        f"PASS contained anchor unchanged: {contained['availability'][1]}, "
        f"execution backupId {contained['executionBackupId']}"
    )


def negative_controls() -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)

    # An INCOHERENT window — recoverability starting after the last success — is not a verdict
    # in either direction. This is also the reason the supersession branch's else cannot fire:
    # with a coherent window, first > stopped forces last >= first > stopped, so a newer success
    # always exists. Positive evidence that backups are entirely gone is therefore NOT observable
    # from window times alone, and pretending otherwise would be the counter-proof error in
    # reverse.
    incoherent = parts(
        render(
            observed(
                anchor_stopped=stamp(now - timedelta(hours=1)),
                first_point=stamp(now - timedelta(minutes=30)),
                last_success=stamp(now - timedelta(minutes=45)),
            )
        )
    )
    if incoherent["availability"][0] != "Unknown":
        raise AnchorError(
            "NEGATIVE CONTROL FAILED: an incoherent window must be Unknown, not a verdict; got "
            f"{incoherent['availability'][0]}/{incoherent['availability'][1]}"
        )
    if incoherent["protection"][0] == "Valid":
        raise AnchorError(
            "NEGATIVE CONTROL FAILED: protection must not be Valid on an incoherent window"
        )
    print(
        f"NEGATIVE CONTROL PASS: incoherent window: {incoherent['availability'][1]} "
        "(neither Valid nor a counter-proof)"
    )

    # An unreadable window is not a counter-proof either — §11.1's third case.
    unreadable = observed(
        anchor_stopped=stamp(now - timedelta(days=30)),
        first_point="",
        last_success="",
    )
    unknown = parts(render(unreadable))
    if unknown["availability"][0] != "Unknown":
        raise AnchorError(
            "NEGATIVE CONTROL FAILED: an unreadable window must be Unknown, not a verdict; got "
            f"{unknown['availability'][0]}/{unknown['availability'][1]}"
        )
    print(f"NEGATIVE CONTROL PASS: unreadable window: {unknown['availability'][1]} (not Failed)")

    # Supersession must not rescue a FAILING archiver: the dimensions are independent, and a
    # healthy backup window says nothing about WAL archiving.
    archiving_failed = anchor_pruned_while_healthy(now)
    for doc in archiving_failed:
        manifest = doc.get("status", {}).get("atProvider", {}).get("manifest", {})
        if manifest.get("kind") == "Cluster":
            for condition in manifest["status"]["conditions"]:
                if condition["type"] == "ContinuousArchiving":
                    condition["status"] = "False"
                    condition["reason"] = "ContinuousArchivingFailing"
    failed = parts(render(archiving_failed))
    if failed["protection"][0] != "Failed":
        raise AnchorError(
            "NEGATIVE CONTROL FAILED: a superseded anchor must not mask a failing archiver; got "
            f"{failed['protection'][0]}/{failed['protection'][1]}"
        )
    print(f"NEGATIVE CONTROL PASS: failing archiver still fails: {failed['protection'][1]}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--negative-controls", action="store_true")
    args = parser.parse_args()
    try:
        if args.negative_controls:
            negative_controls()
        else:
            positive()
    except AnchorError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
