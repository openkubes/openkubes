#!/usr/bin/env python3
"""Verify the non-authorizing combined M0A-C1 + M0a-I execution candidate."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import sys
from pathlib import Path

import yaml


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]


def _load():
    path = HERE / "controlled_m0a_execution.py"
    spec = importlib.util.spec_from_file_location("ok141_controlled_m0a_verifier", path)
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
    document, _ = EXECUTION.verify_candidate(path)
    spec = document["spec"]
    evidence = spec["evidence"]
    for key in ("collectorWorkflow", "publisherWorkflow", "observerWorkflow"):
        reference = evidence[key]
        target = (path.parent / reference["path"]).resolve()
        if REPO.resolve() not in target.parents or not target.is_file():
            raise VerificationError(f"workflow reference missing or outside repository: {target}")
        expect(sha(target), reference["digest"], f"workflow digest {key}")
    expect(evidence["collectorDispatchAuthorized"], False, "collector dispatch boundary")
    expect(evidence["publicationAuthorized"], False, "publication boundary")
    expect(spec["installation"]["objectCount"], 19, "installation count")
    expect(spec["installation"]["controllerImageDigest"], EXECUTION.EXPECTED_CONTROLLER_IMAGE_DIGEST, "controller image digest")
    expect(spec["installation"]["targetResourcesAllowed"], False, "target-resource exclusion")
    expect(spec["failureBoundary"]["automaticCaaphRollbackAllowed"], False, "rollback exclusion")
    expect(spec["executionWindow"]["grantsRequired"], ["M0A-C1", "M0A-I"], "grant inventory")
    rules = " ".join(spec["rules"])
    for phrase in ("two distinct grant IDs", "refuses mutation", "automatic CAAPH rollback remains forbidden", "remain NO-GO"):
        if phrase not in rules:
            raise VerificationError(f"fail-closed rule missing: {phrase}")
    return sha(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--digest-file", type=Path)
    args = parser.parse_args()
    try:
        result = verify(args.candidate.resolve())
        if args.digest_file:
            expect(args.digest_file.read_text().strip(), result, "candidate digest file")
        print(result)
        return 0
    except (OSError, KeyError, TypeError, ValueError, VerificationError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
