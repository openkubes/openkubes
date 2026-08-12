#!/usr/bin/env python3
"""Verify the accepted but non-authorizing M0a v2 risk record."""

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
    expect(spec["state"], "ACCEPTED-NON-AUTHORIZING", "state")
    expect(spec["acceptedBy"], "github:arashkaffamanesh", "authority")
    for reference in spec["references"].values():
        resolve(reference)
    expect(spec["decision"]["outcome"], "ACCEPTED-DEV-ONLY", "risk outcome")
    expect(spec["decision"]["acceptedRisks"], [
        "M0A-V2-CREATE-CONTENT-BOUNDARY",
        "M0A-V2-ADMISSION-BOOTSTRAP-BOUNDARY",
        "M0A-V2-REVOCATION-BOUNDARY",
    ], "accepted risks")
    statement = spec["decision"]["exactStatement"]
    for phrase in (
        "sha256:f11b48b98f8d27b46b47966d00f373f067b6e55776d1320dfc4ce9e82b07d07c",
        "keine Freigabe für Credentials",
        "GO-1",
        "Failure Injection",
    ):
        if phrase not in statement:
            raise VerificationError(f"acceptance statement missing: {phrase}")
    expect(spec["claimBoundaries"], {
        "environment": "DEV",
        "completePayloadProvenByRbacOrAdmission": False,
        "immediateTokenRevocationProven": False,
        "productionUseAllowed": False,
        "retryAllowed": False,
    }, "claim boundaries")
    expected = {"decision": "NO-GO"}
    expected.update({key: False for key in spec["authorization"] if key != "decision"})
    expect(spec["authorization"], expected, "authorization boundary")
    return sha(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--acceptance", type=Path, required=True)
    parser.add_argument("--digest-file", type=Path)
    args = parser.parse_args()
    try:
        result = verify(args.acceptance.resolve())
        if args.digest_file:
            expect(args.digest_file.read_text().strip(), result, "digest file")
        print(result)
        return 0
    except (OSError, KeyError, TypeError, ValueError, VerificationError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
