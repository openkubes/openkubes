#!/usr/bin/env python3
"""Verify that the received v5 grant is recorded as expired and non-authorizing."""

from __future__ import annotations

import argparse
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


class VerificationError(ValueError):
    pass


def sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def expect(actual: Any, expected: Any, claim: str) -> None:
    if actual != expected:
        raise VerificationError(f"{claim}: expected {expected!r}, got {actual!r}")


def utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo != timezone.utc:
        raise VerificationError("timestamp is not UTC")
    return parsed


def verify(path: Path) -> str:
    spec = yaml.safe_load(path.read_text())["spec"]
    expect(spec["version"], "ok141-m0a-expired-combined-grant/v5", "version")
    expect(spec["state"], "EXPIRED-NOT-RUN", "state")
    expect(spec["candidateDigest"], "sha256:a9c4a5e782b0d7a54d0dfb1f89a24914ad41d15d64977e07ab0a008c1bae2067", "candidate")
    expect(spec["authority"], "github:arashkaffamanesh", "authority")
    expect(spec["requestedDecision"], "GO", "requested decision")
    expect(spec["effectiveDecision"], "NO-GO", "effective decision")
    expect(spec["mutationAuthorized"], False, "mutation authority")
    expect(spec["expired"], True, "expired")
    expect(spec["reusable"], False, "reusability")
    expect(spec["maximumRuns"], 1, "maximum runs")
    expect(spec["actualRuns"], 0, "actual runs")
    expect(spec["evidenceCreated"], False, "evidence creation")
    if utc(spec["evaluatedAt"]) <= utc(spec["validUntil"]):
        raise VerificationError("grant was not expired when evaluated")
    ids = []
    for field, gate in (("credentialGrant", "M0A-C1-v5"), ("admissionGrant", "M0A-A1-v5"), ("installationGrant", "M0a-I-v5")):
        expect(spec[field]["gate"], gate, field)
        expect(spec[field]["runsConsumed"], 0, f"{field} runs")
        ids.append(spec[field]["grantID"])
    if len(set(ids)) != 3:
        raise VerificationError("grant IDs are not distinct")
    for field in ("retryGranted", "rollbackGranted", "targetConvergenceGranted", "m0bInstallationGranted", "go1Granted", "evidencePublicationGranted", "failureInjectionGranted"):
        expect(spec[field], False, field)
    return sha(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--record", type=Path, required=True)
    parser.add_argument("--digest-file", type=Path)
    args = parser.parse_args()
    try:
        result = verify(args.record.resolve())
        if args.digest_file:
            expect(args.digest_file.read_text().strip(), result, "record digest")
        print(result)
        return 0
    except (OSError, KeyError, TypeError, ValueError, VerificationError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
