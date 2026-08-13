#!/usr/bin/env python3
"""Verify the exact non-authorizing OK-141 M0b v2 risk acceptance."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import yaml


HERE = Path(__file__).resolve().parent
ACCEPTANCE = HERE / "m0b-v2-risk-acceptance-v1.yaml"
CANDIDATE_DIGEST = "sha256:fc9afe142830be902196dfcf961fa7a0b1084bbe37c984a6cf2da5c5f8fbc273"
SECURITY_DIGEST = "sha256:4191096d70a0bb7d0ca60598cd4303ea7bf65be7d976d9d56ce53d706804d353"


class VerificationError(ValueError):
    pass


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def verify(path: Path = ACCEPTANCE) -> str:
    spec = yaml.safe_load(path.read_text())["spec"]
    if spec["state"] != "ACCEPTED-NON-AUTHORIZING":
        raise VerificationError("acceptance state mismatch")
    references = (
        (spec["candidate"], CANDIDATE_DIGEST),
        (spec["securityCandidate"], SECURITY_DIGEST),
    )
    for reference, expected in references:
        if reference["digest"] != expected:
            raise VerificationError("declared reference digest mismatch")
        if digest((HERE / reference["path"]).resolve()) != expected:
            raise VerificationError("reference content mismatch")
    decision = spec["decision"]
    if decision["accepted"] is not True or decision["acceptedBy"] != "github:arashkaffamanesh":
        raise VerificationError("acceptance authority mismatch")
    candidate_text = yaml.safe_load((HERE / spec["candidate"]["path"]).read_text())["spec"]["acceptanceText"]
    if decision["exactStatement"] != candidate_text:
        raise VerificationError("accepted statement differs from candidate")
    effects = spec["effects"]
    if effects["permitsInstallationCandidatePreparation"] is not True:
        raise VerificationError("candidate-preparation effect mismatch")
    if any(value is not False for key, value in effects.items() if key != "permitsInstallationCandidatePreparation"):
        raise VerificationError("risk acceptance grants mutation authority")
    return digest(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--acceptance", type=Path, default=ACCEPTANCE)
    parser.add_argument("--digest-file", type=Path)
    args = parser.parse_args()
    try:
        value = verify(args.acceptance.resolve())
        if args.digest_file and value.removeprefix("sha256:") != args.digest_file.read_text().split()[0]:
            raise VerificationError("acceptance digest mismatch")
        print(value)
        return 0
    except (OSError, KeyError, TypeError, VerificationError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
