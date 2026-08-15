#!/usr/bin/env python3
"""Verify redacted fail-closed evidence for the first M0a v2 execution."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import yaml


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent


class VerificationError(ValueError):
    pass


def sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def expect(actual, expected, claim: str) -> None:
    if actual != expected:
        raise VerificationError(f"{claim}: expected {expected!r}, got {actual!r}")


def verify(path: Path) -> str:
    spec = yaml.safe_load(path.read_text())["spec"]
    expect(spec["state"], "STOP-NOT-SUCCESS", "state")
    for reference in spec["references"].values():
        target = (path.parent / reference["path"]).resolve()
        if SPIKE.resolve() not in target.parents or not target.is_file():
            raise VerificationError(f"reference missing or outside spike root: {target}")
        expect(sha(target), reference["digest"], f"digest for {reference['path']}")
    expect(spec["execution"]["runsConsumed"], 1, "run consumption")
    expect(spec["execution"]["retryAuthorized"], False, "retry boundary")
    expect(spec["bootstrap"]["cleanupRemovedAllObjects"], True, "bootstrap cleanup")
    expect(spec["credential"]["boundedRejectionProbe"]["result"], "FAILED", "token rejection")
    expect(spec["authorizationProbes"]["result"], "STOPPED-ON-INVALID-SUBRESOURCE-PROBE", "probe result")
    expect(spec["authorizationProbes"]["actualTokenRequestAuthorization"]["classification"], "NOT-PROVEN", "token authorization boundary")
    expect(spec["installation"]["attempted"], False, "installation attempt")
    for claim in ("caaphSubmittedObjectCount", "hcpSubmittedObjectCount", "hrpSubmittedObjectCount"):
        expect(spec["installation"][claim], 0, claim)
    post = spec["postFailureObservation"]
    for claim in ("temporaryBootstrapObjects", "caaphCRDsPresent", "caaphInstallationObjectsPresent", "capiLifecycleObjects"):
        expect(post[claim], 0, claim)
    conclusion = spec["conclusion"]
    for claim in ("caaphInstalled", "partialInstallationPresent", "bootstrapObjectsRetained", "secretMaterialRetained", "grantReusable", "retryAllowed"):
        expect(conclusion[claim], False, claim)
    if any(spec["authorization"].values()):
        raise VerificationError("a follow-up authority was inferred from failure evidence")
    for claim, value in spec["redaction"].items():
        expect(value, False, claim)
    return sha(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--digest-file", type=Path)
    args = parser.parse_args()
    try:
        result = verify(args.evidence.resolve())
        if args.digest_file:
            expect(args.digest_file.read_text().strip(), result, "digest file")
        print(result)
        return 0
    except (OSError, KeyError, TypeError, ValueError, VerificationError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
