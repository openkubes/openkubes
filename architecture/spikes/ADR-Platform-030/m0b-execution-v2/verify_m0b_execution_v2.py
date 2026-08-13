#!/usr/bin/env python3
"""Offline verifier for the non-authorizing OK-141 M0b v2 execution checkpoint."""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path
from typing import Any

import yaml


HERE = Path(__file__).resolve().parent
EXECUTION_DIGEST = "sha256:2a3370b46fc70d7eeafb455dfa13fb4cbdf37d1189e801b581539e1ebec2ef3c"
PREFLIGHT_DIGEST = "sha256:6b58e3ddce017732155276288f028f6f1b7ac74155d4dddd52c78d02e495f6e3"
READINESS_DIGEST = "sha256:7a1ffffb41ca67b911b3a0d36b4ef5111467a48132b1089a5541e030ec9e195e"
GRANT_CANDIDATE_DIGEST = "sha256:72c375736a6061440a21a8c9ee891ef25ba482f2fc545a9ccf783a953063a9ee"


class VerificationError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text())
    if not isinstance(value, dict):
        raise VerificationError(f"expected mapping in {path}")
    return value


def expect(actual: Any, expected: Any, claim: str) -> None:
    if actual != expected:
        raise VerificationError(f"{claim}: expected {expected!r}, got {actual!r}")


def verify(directory: Path = HERE) -> str:
    execution_path = directory / "m0b-v2-execution-candidate.yaml"
    preflight_path = directory / "m0b-v2-final-live-preflight-v1.yaml"
    readiness_path = directory / "m0b-v2-readiness-candidate.yaml"
    grant_path = directory / "m0b-v2-installation-grant-candidate.yaml"
    expect(sha256_file(execution_path), EXECUTION_DIGEST, "execution candidate digest")
    expect(sha256_file(preflight_path), PREFLIGHT_DIGEST, "final preflight digest")
    expect(sha256_file(readiness_path), READINESS_DIGEST, "readiness candidate digest")
    expect(sha256_file(grant_path), GRANT_CANDIDATE_DIGEST, "grant candidate digest")

    execution = read(execution_path)["spec"]
    expect(execution["state"], "READY-FOR-FINAL-PREFLIGHT-NO-GO", "execution state")
    expect(execution["submission"]["operation"], "DIRECT-ADMIN-TWO-PHASE-CREATE-ONLY", "operation")
    expect((execution["submission"]["phase1"]["objectCount"], execution["submission"]["phase2"]["objectCount"]), (4, 50), "phase split")
    expect(execution["submission"]["updatePatchReplaceAllowed"], False, "mutation verbs")
    expect(execution["submission"]["retryAllowed"], False, "retry")
    expect(execution["submission"]["automaticRollbackAllowed"], False, "rollback")
    expect(execution["authorization"]["decision"], "NO-GO", "execution decision")
    if any(value is not False for key, value in execution["authorization"].items() if key != "decision"):
        raise VerificationError("execution candidate grants authority")

    preflight = read(preflight_path)["spec"]
    expect(preflight["candidateDigest"], EXECUTION_DIGEST, "preflight binding")
    expect(preflight["result"], "PASS-POINT-IN-TIME-NO-GO", "preflight result")
    expect(preflight["observations"]["cluster"]["existingReviewedTargetIdentities"], 0, "object absence")
    expect(len(preflight["observations"]["cluster"]["nodes"]), 4, "Node count")
    expect(preflight["observations"]["administrator"]["wildcardAuthorizationObserved"], True, "administrator authorization")
    expected_images = {item["reference"]: item["linuxAmd64Digest"] for item in execution["controllerImages"]}
    observed_images = {item["reference"]: item["digest"] for item in preflight["observations"]["images"]["identities"]}
    expect(observed_images, expected_images, "image identities")
    if any(preflight["authorization"].values()):
        raise VerificationError("preflight grants authority")

    readiness = read(readiness_path)["spec"]
    expect(readiness["references"]["executionCandidate"]["digest"], EXECUTION_DIGEST, "readiness execution binding")
    expect(readiness["references"]["finalLivePreflight"]["digest"], PREFLIGHT_DIGEST, "readiness preflight binding")
    expect(readiness["assertions"], {
        "reviewedObjectsPresent": 54,
        "establishedCRDs": 3,
        "readyWorkloads": 7,
        "readyPods": 7,
        "exactRuntimeImageIdentityRequired": True,
        "applicationsAcrossAllNamespaces": 0,
        "applicationSetsAcrossAllNamespaces": 0,
        "appProjectsAcrossAllNamespaces": 0,
    }, "readiness assertions")
    if any(readiness["authorization"].values()):
        raise VerificationError("readiness candidate grants authority")

    grant = read(grant_path)["spec"]
    expect(grant["state"], "READY-FOR-EXPLICIT-GRANT", "grant candidate state")
    expect(grant["references"]["executionCandidate"]["digest"], EXECUTION_DIGEST, "grant execution binding")
    expect(grant["references"]["finalLivePreflight"]["digest"], PREFLIGHT_DIGEST, "grant preflight binding")
    expect(grant["references"]["readinessCandidate"]["digest"], READINESS_DIGEST, "grant readiness binding")
    expect(grant["requestedOperation"]["maximumRuns"], 1, "run budget")
    expect(grant["explicitGrantFields"]["grantID"], None, "grant ID")
    expect(grant["explicitGrantFields"]["validFrom"], None, "grant start")
    expect(grant["explicitGrantFields"]["validUntil"], None, "grant end")
    expect(grant["authorization"]["decision"], "NO-GO", "grant decision")
    if any(value is not False for key, value in grant["authorization"].items() if key != "decision"):
        raise VerificationError("grant candidate grants authority")
    return GRANT_CANDIDATE_DIGEST


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, default=HERE)
    args = parser.parse_args()
    try:
        print(verify(args.directory.resolve()))
        return 0
    except (VerificationError, OSError, KeyError, TypeError, yaml.YAMLError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
