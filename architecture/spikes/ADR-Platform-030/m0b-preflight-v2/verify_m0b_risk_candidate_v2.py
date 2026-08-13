#!/usr/bin/env python3
"""Verify that the M0b v2 risk candidate remains exact and non-authorizing."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import yaml


HERE = Path(__file__).resolve().parent
CANDIDATE = HERE / "m0b-v2-risk-acceptance-candidate.yaml"
SECURITY_DIGEST = "sha256:4191096d70a0bb7d0ca60598cd4303ea7bf65be7d976d9d56ce53d706804d353"


class VerificationError(ValueError):
    pass


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def verify(path: Path = CANDIDATE) -> str:
    document = yaml.safe_load(path.read_text())
    spec = document["spec"]
    if spec["state"] != "AWAITING-EXPLICIT-DECISION-NO-GO":
        raise VerificationError("risk candidate state mismatch")
    if spec["securityCandidate"]["digest"] != SECURITY_DIGEST:
        raise VerificationError("security digest mismatch")
    security = (HERE / spec["securityCandidate"]["path"]).resolve()
    if digest(security) != SECURITY_DIGEST:
        raise VerificationError("security content mismatch")
    text = spec["acceptanceText"]
    required = (
        "system:masters", "nicht-atomare", "partiellem Argo-Zustand",
        "sieben Secret-Read-", "zwei Secret-Write-", "Ressourcen-Requests",
        "Remote-Source-Materialisierung", SECURITY_DIGEST,
        "keine Freigabe", "GO-1", "Failure Injection",
    )
    if any(value not in text for value in required):
        raise VerificationError("risk text is incomplete")
    if spec["decision"] != {"accepted": False, "acceptedBy": None, "acceptedAt": None}:
        raise VerificationError("risk candidate contains a decision")
    effects = spec["effects"]
    if any(value is not False for key, value in effects.items() if key != "permitsInstallationCandidatePreparation"):
        raise VerificationError("risk candidate grants authority")
    if effects["permitsInstallationCandidatePreparation"] is not True:
        raise VerificationError("offline preparation boundary mismatch")
    return digest(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, default=CANDIDATE)
    parser.add_argument("--digest-file", type=Path)
    args = parser.parse_args()
    try:
        value = verify(args.candidate.resolve())
        if args.digest_file and value.removeprefix("sha256:") != args.digest_file.read_text().split()[0]:
            raise VerificationError("risk candidate digest mismatch")
        print(value)
        return 0
    except (OSError, KeyError, TypeError, VerificationError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
