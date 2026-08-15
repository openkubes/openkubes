#!/usr/bin/env python3
"""Reproducibly verify the explicit OK-141 M0A-C1 + M0a-I grant record."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import sys
from datetime import datetime
from pathlib import Path

import yaml


HERE = Path(__file__).resolve().parent


def _load():
    path = HERE.parent / "m0a-execution" / "controlled_m0a_execution.py"
    spec = importlib.util.spec_from_file_location("ok141_m0a_grant_execution", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader
    spec.loader.exec_module(module)
    return module


EXECUTION = _load()


class VerificationError(ValueError):
    pass


def sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def expect(actual, expected, claim: str) -> None:
    if actual != expected:
        raise VerificationError(f"{claim}: expected {expected!r}, got {actual!r}")


def verify(path: Path) -> str:
    document = yaml.safe_load(path.read_text())
    spec = document["spec"]
    candidate = (path.parent / spec["candidatePath"]).resolve()
    expect(sha(candidate), spec["candidateDigest"], "candidate digest")
    decided = datetime.fromisoformat(spec["decidedAt"].replace("Z", "+00:00"))
    EXECUTION.verify_grant(candidate, path, now=decided)
    expect(spec["credentialGrant"]["maximumRuns"], 1, "credential run count")
    expect(spec["installationGrant"]["maximumRuns"], 1, "installation run count")
    for claim in (
        "rollbackGranted",
        "targetConvergenceGranted",
        "helmChartProxyGranted",
        "helmReleaseProxyGranted",
        "ciliumConvergenceGranted",
        "m0bInstallationGranted",
        "go1Granted",
        "evidencePublicationGranted",
        "failureInjectionGranted",
    ):
        expect(spec[claim], False, claim)
    return sha(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--grant", type=Path, required=True)
    parser.add_argument("--digest-file", type=Path)
    args = parser.parse_args()
    try:
        result = verify(args.grant.resolve())
        if args.digest_file:
            expect(args.digest_file.read_text().strip(), result, "grant digest file")
        print(result)
        return 0
    except (OSError, KeyError, TypeError, ValueError, VerificationError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
