#!/usr/bin/env python3
"""Verify the non-authorizing M0a v4 risk-acceptance record."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
from typing import Any

import yaml


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent


class VerificationError(ValueError):
    pass


def sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def expect(actual: Any, expected: Any, claim: str) -> None:
    if actual != expected:
        raise VerificationError(f"{claim}: expected {expected!r}, got {actual!r}")


def verify(path: Path) -> str:
    spec = yaml.safe_load(path.read_text())["spec"]
    expect(spec["version"], "ok141-m0a-v4-risk-acceptance-record/v1", "version")
    expect(spec["state"], "ACCEPTED-NON-AUTHORIZING", "state")
    expect(spec["acceptedBy"], "github:arashkaffamanesh", "authority")
    for reference in spec["references"].values():
        target = (path.parent / reference["path"]).resolve()
        if SPIKE.resolve() not in target.parents or not target.is_file():
            raise VerificationError(f"reference missing or outside spike root: {target}")
        expect(sha(target), reference["digest"], f"digest for {reference['path']}")
    security_digest = spec["references"]["securityBoundary"]["digest"]
    if security_digest not in spec["decision"]["exactStatement"]:
        raise VerificationError("decision statement is not bound to the security digest")
    expect(set(spec["decision"]["acceptedRisks"]), {
        "M0A-V4-CREATE-ONLY-PARTIAL-STATE",
        "M0A-V4-EXPIRY-PLUS-100S-OBSERVATION",
        "M0A-V4-CREATE-CONTENT-BOUNDARY",
        "M0A-V4-ADMISSION-BOOTSTRAP-BOUNDARY",
    }, "accepted risks")
    expect(spec["claimBoundaries"], {
        "environment": "DEV",
        "submissionAtomic": False,
        "submissionIdempotent": False,
        "partialInstallationPossible": True,
        "automaticRetryAllowed": False,
        "automaticRollbackAllowed": False,
        "completePayloadProvenByRbacOrAdmission": False,
        "immediateTokenRevocationProven": False,
        "tokenRejectionMustBeObservedByExpiryDeadline": True,
        "productionUseAllowed": False,
    }, "claim boundaries")
    expect(spec["authorization"]["decision"], "NO-GO", "decision")
    if any(value for key, value in spec["authorization"].items() if key != "decision"):
        raise VerificationError("risk acceptance inferred execution authority")
    return sha(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--digest-file", type=Path)
    args = parser.parse_args()
    try:
        result = verify(args.evidence.resolve())
        if args.digest_file:
            expect(args.digest_file.read_text().strip(), result, "evidence digest")
        print(result)
        return 0
    except (OSError, KeyError, TypeError, ValueError, VerificationError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
