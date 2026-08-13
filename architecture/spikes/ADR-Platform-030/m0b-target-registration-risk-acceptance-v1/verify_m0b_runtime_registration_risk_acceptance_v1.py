#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import yaml


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
RECORD = HERE / "m0b-runtime-registration-risk-acceptance-v1.yaml"
DIGEST = HERE / "m0b-runtime-registration-risk-acceptance-v1.sha256"
EXPECTED_SECURITY = "sha256:3def094077184842e0d1f73292043b8d882e9ad7ba73d09e086ca8f291c1ff81"
EXPECTED_RISKS = 8


class AcceptanceError(ValueError):
    pass


def sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def expect(actual: Any, expected: Any, context: str) -> None:
    if actual != expected:
        raise AcceptanceError(f"{context}: expected {expected!r}, got {actual!r}")


def resolve(ref: dict[str, str]) -> Path:
    path = (RECORD.parent / ref["path"]).resolve()
    if SPIKE.resolve() not in path.parents or not path.is_file():
        raise AcceptanceError(f"invalid reference: {ref['path']}")
    expect(sha(path), ref["digest"], ref["path"])
    return path


def verify(record: dict[str, Any] | None = None) -> dict[str, Any]:
    root = record or yaml.safe_load(RECORD.read_text())
    spec = root["spec"]
    expect(spec["state"], "ACCEPTED-NON-AUTHORIZING", "state")
    expect(spec["acceptedBy"], "github:arashkaffamanesh", "acceptedBy")
    candidate = yaml.safe_load(resolve(spec["references"]["acceptanceCandidate"]).read_text())["spec"]
    security = resolve(spec["references"]["securityBoundary"])
    resolve(spec["references"]["runtimeProtocol"])
    expect(sha(security), EXPECTED_SECURITY, "security digest")
    expect(spec["decision"]["exactStatement"], candidate["acceptanceText"], "statement")
    expect(spec["decision"]["acceptedRisks"], candidate["risks"], "risks")
    expect(len(spec["decision"]["acceptedRisks"]), EXPECTED_RISKS, "risk count")
    expect(spec["authorization"], candidate["authorization"], "authorization")
    expect(spec["authorization"]["decision"], "NO-GO", "decision")
    expect(spec["authorization"]["mutationAuthorized"], False, "mutation")
    if any(value for key, value in spec["authorization"].items() if key.endswith("Granted")):
        raise AcceptanceError("all grants must remain false")
    boundaries = spec["claimBoundaries"]
    expect(boundaries["environment"], "DEV", "environment")
    expect(boundaries["nativeArgoTokenRotation"], False, "native rotation")
    expect(boundaries["tokenMaximumExpirationSeconds"], 10800, "token maximum")
    expect(boundaries["crossPlaneSubmissionAtomic"], False, "atomicity")
    expect(boundaries["productionUseAllowed"], False, "production use")
    if any(boundaries[key] for key in (
        "automaticRetryAllowed", "automaticRollbackAllowed", "cleanupAllowed",
        "exactTargetCompatibilityExecutionProven", "materializerSecretSafetyExecutionProven"
    )):
        raise AcceptanceError("an unproven or unauthorized claim became true")
    return {
        "state": spec["state"],
        "securityCandidateDigest": EXPECTED_SECURITY,
        "acceptedRisks": EXPECTED_RISKS,
        "mutationAuthorized": False,
        "clusterContacted": False,
    }


def negative_controls() -> list[str]:
    failures = []
    base = yaml.safe_load(RECORD.read_text())
    cases = []
    mutated = copy.deepcopy(base)
    mutated["spec"]["authorization"]["registrationGranted"] = True
    cases.append(("registration-grant", mutated))
    mutated = copy.deepcopy(base)
    mutated["spec"]["claimBoundaries"]["nativeArgoTokenRotation"] = True
    cases.append(("rotation-claim", mutated))
    mutated = copy.deepcopy(base)
    mutated["spec"]["decision"]["acceptedRisks"].pop()
    cases.append(("missing-risk", mutated))
    mutated = copy.deepcopy(base)
    mutated["spec"]["decision"]["exactStatement"] += " changed"
    cases.append(("changed-statement", mutated))
    for name, candidate in cases:
        try:
            verify(candidate)
        except (AcceptanceError, KeyError, OSError, TypeError, yaml.YAMLError):
            continue
        failures.append(f"negative control did not fail closed: {name}")
    return failures


def main() -> int:
    try:
        result = verify()
        failures = negative_controls()
        if failures:
            raise AcceptanceError("; ".join(failures))
        expect(DIGEST.read_text().strip(), sha(RECORD), "record digest")
        result["negativeControls"] = 4
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    except (AcceptanceError, KeyError, OSError, TypeError, yaml.YAMLError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
