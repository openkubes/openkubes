#!/usr/bin/env python3
"""Verify the redacted GO-1 v6 preflight v2 closure against local evidence."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import yaml


HERE = Path(__file__).resolve().parent
CLOSURE = HERE / "preflight-v2-redacted-closure-candidate.yaml"


class VerificationError(ValueError):
    pass


def sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def read_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text())
    if not isinstance(value, dict):
        raise VerificationError(f"expected mapping: {path}")
    return value


def expect(actual: Any, expected: Any, context: str) -> None:
    if actual != expected:
        raise VerificationError(f"{context}: expected {expected!r}, got {actual!r}")


def verify() -> dict[str, Any]:
    closure = read_yaml(CLOSURE)["spec"]
    expect(closure["state"], "COMPLETE-LOCALLY-PUBLICATION-NOT-GRANTED", "state")
    expect(closure["transportCorrection"]["v2CandidateDigest"], sha(HERE / "go1-v6-preflight-candidate-v2.yaml"), "v2 candidate")
    expect(closure["credentialIdentity"]["candidateDigest"], sha(HERE.parent / "go1-v6-credential-identity-v1" / "go1-v6-credential-identity-candidate-v1.yaml"), "C0 candidate")
    expect(closure["credentialIdentity"]["remediationReceiptDigest"], sha(HERE.parent / "go1-v6-credential-identity-v1" / "credential-mode-remediation-receipt-20260814-01.yaml"), "remediation receipt")
    expect(closure["credentialIdentity"]["identityClosureDigest"], sha(HERE.parent / "go1-v6-credential-identity-v1" / "credential-identity-closure-v1.yaml"), "identity closure")
    expect(closure["preflight"]["grantCandidateDigest"], sha(HERE / "preflight-grant-candidate-20260814-01.yaml"), "preflight grant candidate")
    expect(closure["preflight"]["grantDigest"], sha(HERE / "preflight-grant-20260814-01.yaml"), "preflight grant")
    raw_path = Path(closure["preflight"]["rawLocalEvidence"]["path"])
    expect(sha(raw_path), closure["preflight"]["rawLocalEvidence"]["digest"], "raw local evidence")
    raw = json.loads(raw_path.read_text())["spec"]
    expect(raw["candidateDigest"], closure["transportCorrection"]["v2CandidateDigest"], "raw candidate")
    expect(raw["protocolDigest"], closure["protocolDigest"], "raw protocol")
    expect(raw["client"]["digest"], closure["client"]["digest"], "raw client")
    expect(raw["result"], closure["preflight"]["result"], "raw result")
    expect(raw["observedAt"], closure["preflight"]["observedAt"], "observedAt")
    expect(raw["freshUntil"], closure["preflight"]["freshUntil"], "freshUntil")
    expect(len(raw["absence"]), closure["preflight"]["absenceQueriesPassed"], "absence query count")
    expect(len(raw["absenceClaims"]), closure["preflight"]["logicalAbsenceClaims"], "absence claim count")
    expect(sum(item["plane"] == "ok-mgmt" for item in raw["readiness"]), closure["preflight"]["caaphReadinessPassed"], "CAAPH readiness")
    expect(sum(item["plane"] == "ok-shared" for item in raw["readiness"]), closure["preflight"]["argoReadinessPassed"], "Argo readiness")
    expect(raw["secretBodiesRetained"], False, "secret boundary")
    expect(raw["mutationPerformed"], False, "mutation boundary")
    redaction = closure["redaction"]
    if any(redaction.values()):
        raise VerificationError("closure includes forbidden raw or secret-bearing fields")
    conclusions = closure["conclusions"]
    expect(conclusions["historicalPreflightExpiredByDesign"], True, "freshness boundary")
    expect(conclusions["freshPreflightRequiredImmediatelyBeforeGO1L"], True, "future preflight")
    expect(conclusions["publicationGranted"], False, "publication boundary")
    expect(conclusions["go1LGranted"], False, "GO1-L boundary")
    expect(conclusions["go1Granted"], False, "GO-1 boundary")
    return {
        "state": closure["state"],
        "result": closure["preflight"]["result"],
        "physicalQueries": closure["preflight"]["physicalQueries"],
        "logicalAbsenceClaims": closure["preflight"]["logicalAbsenceClaims"],
        "publicationGranted": False,
        "go1LGranted": False,
        "go1Granted": False,
    }


def main() -> int:
    try:
        print(json.dumps(verify(), indent=2, sort_keys=True))
        return 0
    except (VerificationError, OSError, KeyError, TypeError, ValueError, json.JSONDecodeError, yaml.YAMLError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
