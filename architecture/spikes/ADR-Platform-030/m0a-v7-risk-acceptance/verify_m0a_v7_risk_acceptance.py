#!/usr/bin/env python3
"""Verify the exact, non-authorizing M0a-v7 risk-acceptance record."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import yaml


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
RECORD = HERE / "m0a-v7-risk-acceptance-v1.yaml"
EXPECTED_SECURITY = "sha256:1f6afda15207c76d9562a8f95bc7422a7d2f23b528695c567c781abe9fdeb8a5"


class AcceptanceError(ValueError):
    pass


def sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def expect(actual: Any, expected: Any, claim: str) -> None:
    if actual != expected:
        raise AcceptanceError(f"{claim}: expected {expected!r}, got {actual!r}")


def resolve(reference: dict[str, str]) -> Path:
    path = (RECORD.parent / reference["path"]).resolve()
    if SPIKE.resolve() not in path.parents or not path.is_file():
        raise AcceptanceError(f"reference missing or outside spike root: {reference['path']}")
    expect(sha(path), reference["digest"], f"digest for {reference['path']}")
    return path


def verify() -> dict[str, Any]:
    record = yaml.safe_load(RECORD.read_text())["spec"]
    expect(record["version"], "ok141-m0a-v7-risk-acceptance-record/v1", "record version")
    expect(record["state"], "ACCEPTED-NON-AUTHORIZING", "record state")
    candidate_path = resolve(record["references"]["acceptanceCandidate"])
    security_path = resolve(record["references"]["securityBoundary"])
    expect(sha(security_path), EXPECTED_SECURITY, "accepted security candidate")
    candidate = yaml.safe_load(candidate_path.read_text())["spec"]
    expect(record["decision"]["exactStatement"], candidate["acceptanceText"], "exact acceptance statement")
    expect(record["decision"]["acceptedRisks"], candidate["risks"], "accepted risk inventory")
    expect(record["authorization"], candidate["authorization"], "non-authorizing boundary")
    expect(record["authorization"]["mutationAuthorized"], False, "mutation authorization")
    expect(record["authorization"]["evidencePublicationGranted"], False, "publication authorization")
    expect(record["claimBoundaries"]["automaticRetryAllowed"], False, "automatic retry")
    expect(record["claimBoundaries"]["automaticRollbackAllowed"], False, "automatic rollback")
    return {
        "state": record["state"],
        "acceptedBy": record["acceptedBy"],
        "securityCandidateDigest": EXPECTED_SECURITY,
        "acceptedRisks": len(record["decision"]["acceptedRisks"]),
        "mutationAuthorized": False,
        "evidencePublicationGranted": False,
        "clusterContacted": False,
    }


def main() -> int:
    try:
        print(json.dumps(verify(), sort_keys=True, separators=(",", ":")))
        return 0
    except (AcceptanceError, KeyError, OSError, TypeError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

