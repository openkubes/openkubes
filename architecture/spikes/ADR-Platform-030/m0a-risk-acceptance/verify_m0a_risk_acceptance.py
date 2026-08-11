#!/usr/bin/env python3
"""Verify the non-authorizing OK-141 M0a risk acceptance."""

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


def resolve(reference: dict) -> None:
    path = (HERE / reference["path"]).resolve()
    if SPIKE not in path.parents or not path.is_file():
        raise VerificationError(f"reference missing or outside spike root: {path}")
    expect(sha(path), reference["digest"], f"digest for {reference['path']}")


def verify(path: Path) -> str:
    spec = yaml.safe_load(path.read_text())["spec"]
    expect(spec["state"], "ACCEPTED-NON-AUTHORIZING", "state")
    expect(spec["acceptedBy"], "github:arashkaffamanesh", "authority")
    for reference in spec["references"].values():
        resolve(reference)
    decisions = spec["decisions"]
    expect(set(decisions), {"compatibilityRisk", "controllerAndCredentialBoundary"}, "decision inventory")
    for decision in decisions.values():
        expect(decision["outcome"], "ACCEPTED-DEV-ONLY", "risk outcome")
    expect(spec["claimBoundaries"]["productionUseAllowed"], False, "production boundary")
    auth = spec["authorization"]
    expect(auth["decision"], "NO-GO", "authorization")
    for claim in ("mutationAuthorized", "credentialIssuanceGranted", "m0aInstallationGranted", "m0bInstallationGranted", "go1Granted"):
        expect(auth[claim], False, claim)
    rules = " ".join(spec["rules"])
    for phrase in ("grants no credential installation", "bounded window remain mandatory", "remain NO-GO"):
        if phrase not in rules:
            raise VerificationError(f"fail-closed rule missing: {phrase}")
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
    except (OSError, KeyError, TypeError, VerificationError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
