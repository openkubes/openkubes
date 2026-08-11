#!/usr/bin/env python3
"""Verify the fail-closed M0a v2 risk-acceptance candidate."""

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


def resolve(reference: dict[str, str]) -> Path:
    path = (HERE / reference["path"]).resolve()
    if SPIKE.resolve() not in path.parents or not path.is_file():
        raise VerificationError(f"reference missing or outside spike root: {path}")
    expect(sha(path), reference["digest"], f"digest for {reference['path']}")
    return path


def verify(path: Path) -> str:
    spec = yaml.safe_load(path.read_text())["spec"]
    expect(spec["state"], "AWAITING-EXPLICIT-ACCEPTANCE", "candidate state")
    expect(spec["authority"], "github:arashkaffamanesh", "acceptance authority")
    boundary = yaml.safe_load(resolve(spec["references"]["securityBoundary"]).read_text())["spec"]
    evidence = yaml.safe_load(resolve(spec["references"]["firstRunEvidence"]).read_text())["spec"]
    expect(boundary["state"], "BLOCKED-OFFLINE-CANDIDATE", "security boundary state")
    expect(evidence["execution"]["runsConsumed"], 1, "historical run consumption")
    expect(evidence["execution"]["retryAuthorized"], False, "historical retry boundary")
    expect(
        [item["id"] for item in spec["risks"]],
        [
            "M0A-V2-CREATE-CONTENT-BOUNDARY",
            "M0A-V2-ADMISSION-BOOTSTRAP-BOUNDARY",
            "M0A-V2-REVOCATION-BOUNDARY",
        ],
        "risk inventory",
    )
    expect(spec["acceptance"], {
        "accepted": False,
        "acceptedBy": None,
        "acceptedAt": None,
        "acceptedCandidateDigest": None,
    }, "acceptance state")
    expected_authorization = {"decision": "NO-GO"}
    expected_authorization.update({key: False for key in spec["authorization"] if key != "decision"})
    expect(spec["authorization"], expected_authorization, "authorization boundary")
    if "grants no" not in spec["acceptanceText"]:
        raise VerificationError("acceptance text does not preserve the authority boundary")
    return sha(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--digest-file", type=Path)
    args = parser.parse_args()
    try:
        result = verify(args.candidate.resolve())
        if args.digest_file:
            expect(args.digest_file.read_text().strip(), result, "candidate digest")
        print(result)
        return 0
    except (OSError, KeyError, TypeError, ValueError, VerificationError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
