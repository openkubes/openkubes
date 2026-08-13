#!/usr/bin/env python3
"""Fail-closed verifier for the local/redacted OK-141 M0b v2.2 closure."""

from __future__ import annotations

import argparse
import hashlib
import stat
import sys
from pathlib import Path
from typing import Any

import yaml


HERE = Path(__file__).resolve().parent
FILES = {
    "m0b-v2-installation-grant-v1.yaml": "sha256:f01757496a4b6b4c3af088b20ec901702e53b7f90114431311f6b877f84ea37e",
    "evaluate_m0b_readiness_v2_2.py": "sha256:ef8467930470d0d197edf938905917d2900af82ed85e9c4c34a6a4e34b1d0476",
    "m0b-v2-2-readiness-candidate.yaml": "sha256:28f787bbeacf68345392826a0f651540591b6fd42d6c17f96071d3ec9bfd976a",
    "m0b-v2-2-readiness-observation-grant-candidate.yaml": "sha256:1356f4c4be1912b32df2558cbe0602d0ce86478dfc770482227e757cda0f84ad",
    "m0b-v2-2-default-project-risk-acceptance-v1.yaml": "sha256:2ec1617e08e79f6047dd65d974135a26ec65c4bc591cbcc3dcec04d879a338fb",
    "m0b-v2-2-readiness-observation-grant-v1.yaml": "sha256:cfa5ebb924bbc5268d6730f5df5b89e280c9a95dcf58f7f4cd4f05598f1d9f40",
    "m0b-v2-runtime-evidence-redacted-v1.yaml": "sha256:cbb4902fef1b34b88a9acbb7453bafc916f7b6a0239245184acd1b56cc42bdc0",
    "m0b-v2-runtime-closure-v1.yaml": "sha256:48d9d43c1c51338982a6143d7e6f04e77256682424172531ce0cdb224355f8ba",
}
RAW = {
    "/private/tmp/ok141-m0b-v2-execution-evidence-20260813.json": "sha256:3d32e197f4cedcf8a11b66c595bb00ec76893fdf6a60e30f76d7f83f00dfdecc",
    "/private/tmp/ok141-m0b-v2-readiness-evidence-20260813.json": "sha256:edc0fda2e7db92071a41f177eef2dd4a072296929061548b31c00b07e5b71115",
    "/private/tmp/ok141-m0b-v2-2-readiness-evidence-20260813.json": "sha256:7901c18015df5a6498b56afd9f0f374408447f71dc76b6b98d7fd2a4fcc1735f",
}


class VerificationError(ValueError):
    pass


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text())
    if not isinstance(value, dict):
        raise VerificationError(f"expected mapping in {path}")
    return value


def expect(actual: Any, expected: Any, claim: str) -> None:
    if actual != expected:
        raise VerificationError(f"{claim}: expected {expected!r}, got {actual!r}")


def verify(directory: Path = HERE, with_raw: bool = False) -> str:
    for name, expected in FILES.items():
        expect(digest(directory / name), expected, name)
    redacted = read(directory / "m0b-v2-runtime-evidence-redacted-v1.yaml")["spec"]
    closure = read(directory / "m0b-v2-runtime-closure-v1.yaml")["spec"]
    risk = read(directory / "m0b-v2-2-default-project-risk-acceptance-v1.yaml")["spec"]
    grant = read(directory / "m0b-v2-2-readiness-observation-grant-v1.yaml")["spec"]

    expect(redacted["bindings"]["readinessCandidateDigest"], FILES["m0b-v2-2-readiness-candidate.yaml"], "readiness binding")
    expect(redacted["bindings"]["defaultProjectRiskAcceptanceDigest"], FILES["m0b-v2-2-default-project-risk-acceptance-v1.yaml"], "risk binding")
    expect(redacted["readiness"]["reviewedObjectsPresent"], 54, "object count")
    expect((redacted["readiness"]["crdsEstablished"], redacted["readiness"]["deploymentsReady"], redacted["readiness"]["statefulSetsReady"], redacted["readiness"]["podsReady"]), (3, 6, 1, 7), "runtime readiness")
    expect(redacted["targetState"]["openKubesSubmittedObjects"], 0, "submitted target state")
    expect(redacted["targetState"]["nativeDefaultProject"]["wildcardBoundaryAccepted"], True, "default project acceptance")
    if any(redacted["redaction"].values()):
        raise VerificationError("redacted evidence contains a forbidden data class")
    expect(redacted["authorization"]["evidencePublicationGranted"], False, "publication boundary")

    expect(risk["state"], "ACCEPTED-BOUNDARY-NO-MUTATION", "risk state")
    expect(risk["readinessCandidateDigest"], FILES["m0b-v2-2-readiness-candidate.yaml"], "risk candidate")
    expect(grant["grantCandidateDigest"], FILES["m0b-v2-2-readiness-observation-grant-candidate.yaml"], "observation grant candidate")
    expect(grant["maximumRuns"], 1, "observation run budget")
    expect(grant["authorization"]["mutationAuthorized"], False, "observation mutation boundary")

    expect(closure["state"], "COMPLETE-LOCALLY-PUBLICATION-NOT-GRANTED", "closure state")
    expect(closure["redactedEvidence"]["digest"], FILES["m0b-v2-runtime-evidence-redacted-v1.yaml"], "closure evidence")
    expect(closure["conclusions"]["m0bInstallationComplete"], True, "M0b installation closure")
    expect(closure["conclusions"]["m0bTargetRegistrationComplete"], False, "target registration boundary")
    expect(closure["authorization"]["evidencePublicationGranted"], False, "closure publication boundary")

    if with_raw:
        for name, expected in RAW.items():
            path = Path(name)
            expect(digest(path), expected, name)
            expect(stat.S_IMODE(path.stat().st_mode), 0o600, f"{name} mode")
    return FILES["m0b-v2-runtime-closure-v1.yaml"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, default=HERE)
    parser.add_argument("--with-raw", action="store_true")
    args = parser.parse_args()
    try:
        print(verify(args.directory.resolve(), args.with_raw))
        return 0
    except (VerificationError, OSError, KeyError, TypeError, yaml.YAMLError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

