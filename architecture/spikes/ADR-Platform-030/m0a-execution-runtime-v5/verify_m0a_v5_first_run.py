#!/usr/bin/env python3
"""Verify the redacted, non-authorizing M0a-v5 runtime checkpoint."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
from typing import Any

import yaml


class VerificationError(ValueError):
    pass


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def expect(actual: Any, expected: Any, claim: str) -> None:
    if actual != expected:
        raise VerificationError(f"{claim}: expected {expected!r}, got {actual!r}")


def verify(path: Path) -> str:
    spec = yaml.safe_load(path.read_text())["spec"]
    expect(spec["version"], "ok141-m0a-execution-evidence/v5-redacted", "version")
    expect(spec["state"], "STOP-NOT-SUCCESS", "state")
    execution = spec["execution"]
    expect(execution["maximumRuns"], 1, "maximum runs")
    expect(execution["runsConsumed"], 1, "consumed runs")
    expect(execution["retryAuthorized"], False, "retry authority")
    expect(execution["result"], "STOP-NOT-SUCCESS", "result")
    expect(execution["rawLocalEvidencePublishable"], False, "raw publication")
    installation = spec["installation"]
    expect(installation["attempted"], True, "submission attempted")
    expect(installation["submissionsConsumed"], 1, "submissions consumed")
    expect(installation["result"], "FAILED", "installation result")
    expect(installation["causeClassification"], "ADMISSION-OPTIONAL-NAMESPACE-FIELD-ACCESS", "failure cause")
    expect(installation["postSubmissionInventory"], {"expected": 19, "present": 0, "absent": 19}, "inventory")
    probe = spec["credential"]["rejectionProbe"]
    expect(probe["result"], "NOT-PROVEN", "rejection result")
    expect(probe["apiContactAttempted"], False, "rejection API contact")
    expect(probe["causeClassification"], "LOCAL-SUBSECOND-BOUNDARY-RACE", "rejection cause")
    conclusion = spec["conclusion"]
    for claim in ("caaphInstalled", "partialInstallationPresent", "bootstrapObjectsRetained", "secretMaterialRetained", "tokenRejectionProven", "grantReusable", "retryAllowed", "rollbackNeeded"):
        expect(conclusion[claim], False, claim)
    expect(conclusion["newCandidateRequired"], True, "new candidate")
    for claim, value in spec["authorization"].items():
        expect(value, False, claim)
    for claim, value in spec["redaction"].items():
        expect(value, False, claim)
    return digest(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--digest-file", type=Path)
    args = parser.parse_args()
    try:
        value = verify(args.evidence.resolve())
        if args.digest_file:
            expect(args.digest_file.read_text().strip(), value, "evidence digest")
        print(value)
        return 0
    except (OSError, KeyError, TypeError, ValueError, VerificationError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
