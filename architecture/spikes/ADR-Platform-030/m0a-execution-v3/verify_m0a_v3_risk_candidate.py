#!/usr/bin/env python3
"""Verify that the M0a v3 risk candidate remains non-authorizing and bound."""

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


def resolve(path: Path, reference: dict[str, str]) -> Path:
    target = (path.parent / reference["path"]).resolve()
    if SPIKE.resolve() not in target.parents or not target.is_file():
        raise VerificationError(f"reference missing or outside spike root: {target}")
    expect(sha(target), reference["digest"], f"digest for {reference['path']}")
    return target


def verify(path: Path) -> str:
    spec = yaml.safe_load(path.read_text())["spec"]
    expect(spec["version"], "ok141-m0a-v3-risk-acceptance/v1", "version")
    expect(spec["state"], "AWAITING-EXPLICIT-ACCEPTANCE", "state")
    expect(spec["authority"], "github:arashkaffamanesh", "authority")
    security = resolve(path, spec["references"]["securityBoundary"])
    resolve(path, spec["references"]["v2RuntimeEvidence"])
    security_digest = sha(security)
    if security_digest not in spec["acceptanceText"]:
        raise VerificationError("acceptance text is not bound to the exact security digest")
    expect({risk["id"] for risk in spec["risks"]}, {
        "M0A-V3-EXPIRY-BOUND-REVOCATION-OBSERVATION",
        "M0A-V3-CREATE-CONTENT-BOUNDARY",
        "M0A-V3-ADMISSION-BOOTSTRAP-BOUNDARY",
    }, "risk set")
    expect(spec["acceptance"], {
        "accepted": False,
        "acceptedBy": None,
        "acceptedAt": None,
        "acceptedCandidateDigest": None,
    }, "acceptance state")
    expect(spec["authorization"]["decision"], "NO-GO", "decision")
    if any(value for key, value in spec["authorization"].items() if key != "decision"):
        raise VerificationError("risk candidate grants authority")
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
