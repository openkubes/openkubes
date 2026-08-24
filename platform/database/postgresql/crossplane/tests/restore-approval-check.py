#!/usr/bin/env python3
"""Prove RecoveryAssured requires an APPROVED verification method (§7, as amended under OK-150).

The authority act moved from admitting each artifact to approving the method that produces them.
That is only an improvement if the approval is load-bearing, so this asserts both directions:

  matching VerificationProfile        -> recovery Valid/RestoreVerified
  no profile / non-matching digest    -> recovery Unknown/RestoreProfileUnapproved

`RestoreProfileUnapproved` is deliberately distinct from `VerificationPending`. "Nobody has
verified this backup" and "someone verified it with a method nobody approved" call for different
actions — run a drill, versus review and approve the method — and collapsing them would leave an
operator guessing which.

Proven by render rather than by deleting the live approval: the control has to be repeatable, and
revoking a real operator approval to watch a status change is not a test, it is an outage.
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
RESTORE_FIXTURE = TESTS_DIR / "restoreverified-ok-robotics.yaml"
OBSERVED_PATH = TESTS_DIR / "observed-ok-robotics-valid.yaml"
PROFILE_EXAMPLE = CAPABILITY_DIR / "crossplane/examples/verificationprofile-restore-drill.yaml"
RFC3339 = "%Y-%m-%dT%H:%M:%SZ"


class ApprovalError(ValueError):
    pass


def restore_artifact() -> dict[str, Any]:
    """The admitted RestoreVerified, re-stamped to now so the test does not depend on the date."""
    docs = [d for d in yaml.safe_load_all(RESTORE_FIXTURE.read_text()) if d]
    artifact = copy.deepcopy(docs[0])
    completed = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=1)
    artifact["spec"]["timing"]["startedAt"] = (completed - timedelta(minutes=2)).strftime(RFC3339)
    artifact["spec"]["timing"]["completedAt"] = completed.strftime(RFC3339)
    return artifact


def profile_for(artifact: dict[str, Any]) -> dict[str, Any]:
    """A profile approving exactly the method that produced `artifact`.

    Built from the real example so the shape under test is the shape an operator writes, with only
    the digests re-pointed at the fixture's method.
    """
    profile = copy.deepcopy(yaml.safe_load(PROFILE_EXAMPLE.read_text()))
    profile["spec"]["checkProfileDigest"] = artifact["spec"]["checkProfileDigest"]
    profile["spec"]["verifierVersion"] = artifact["spec"]["verifierVersion"]
    profile["spec"]["checks"] = [c["name"] for c in artifact["spec"]["checks"]]
    return profile


def render(extras: list[dict[str, Any]]) -> tuple[str, str]:
    with tempfile.TemporaryDirectory(prefix="ok-150-approval-") as directory:
        work = Path(directory)
        extra_path = work / "extra.yaml"
        extra_path.write_text(yaml.safe_dump_all(extras, sort_keys=False))
        # Observed state is required, not optional scaffolding: recovery admissibility binds the
        # observed Backup uid, the Cluster uid and the source system identifier. Rendering without
        # it fails every identity term, so the artifact reads VerificationPending and the approval
        # under test is never reached — a green control that proves nothing.
        observed_path = work / "observed.yaml"
        observed_path.write_text(OBSERVED_PATH.read_text())
        result = subprocess.run(
            [
                "crossplane",
                "composition",
                "render",
                str(XR_PATH),
                str(COMPOSITION_PATH),
                str(TESTS_DIR / "functions.yaml"),
                "--crossplane-version=v2.3.3",
                f"--extra-resources={extra_path}",
                f"--observed-resources={observed_path}",
            ],
            cwd=CAPABILITY_DIR,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise ApprovalError(f"render failed ({result.returncode}): {result.stderr.strip()}")
        databases = [
            d
            for d in yaml.safe_load_all(result.stdout)
            if isinstance(d, dict) and d.get("kind") == "Database" and "status" in d
        ]
        if len(databases) != 1:
            raise ApprovalError(f"expected one rendered Database, got {len(databases)}")
        recovery = databases[0]["status"]["evidence"]["recovery"]
        return recovery.get("state", ""), recovery.get("reason", "")


def positive() -> None:
    artifact = restore_artifact()
    state, reason = render([artifact, profile_for(artifact)])
    if (state, reason) != ("Valid", "RestoreVerified"):
        raise ApprovalError(
            f"an artifact whose method IS approved must be admissible, got {state}/{reason}"
        )
    print(f"PASS approved method: {state}/{reason}")


def negative_controls() -> None:
    artifact = restore_artifact()

    # The case that makes the approval load-bearing at all.
    state, reason = render([artifact])
    if reason != "RestoreProfileUnapproved":
        raise ApprovalError(
            f"NEGATIVE CONTROL FAILED: with no approved profile the artifact must read "
            f"RestoreProfileUnapproved, got {state}/{reason}"
        )
    if state == "Valid":
        raise ApprovalError("NEGATIVE CONTROL FAILED: unapproved evidence was admitted")
    print(f"NEGATIVE CONTROL PASS: no approved profile: {state}/{reason}")

    # A changed check set changes the digest, which is how §11.2's "a weakened profile invalidates
    # older evidence" becomes mechanical rather than aspirational.
    weakened = profile_for(artifact)
    weakened["spec"]["checkProfileDigest"] = "sha256:" + "b" * 64
    state, reason = render([artifact, weakened])
    if reason != "RestoreProfileUnapproved":
        raise ApprovalError(
            f"NEGATIVE CONTROL FAILED: a profile with a different checkProfileDigest must not "
            f"approve this artifact, got {state}/{reason}"
        )
    print(f"NEGATIVE CONTROL PASS: different check profile: {state}/{reason}")

    # Same checks, different runner. The code decides what "PASS" meant, so a different verifier
    # is a different method even when the probe names match.
    other_runner = profile_for(artifact)
    other_runner["spec"]["verifierVersion"] = "sha256:" + "c" * 64
    state, reason = render([artifact, other_runner])
    if reason != "RestoreProfileUnapproved":
        raise ApprovalError(
            f"NEGATIVE CONTROL FAILED: a different verifierVersion must not approve this artifact, "
            f"got {state}/{reason}"
        )
    print(f"NEGATIVE CONTROL PASS: different verifier, same checks: {state}/{reason}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--negative-controls", action="store_true")
    args = parser.parse_args()
    try:
        if args.negative_controls:
            negative_controls()
        else:
            positive()
    except ApprovalError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
