#!/usr/bin/env python3
"""Fail-closed verifier for redacted OK-141 D0-v3 closure evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml


class ClosureError(ValueError):
    pass


EXPECTED_BINDINGS = {
    "d0CandidateDigest": "sha256:771c09a760940afa8c04a26a79e3e921c11d87d96ae949c1781f4fd7c846074b",
    "liveGrantCandidateDigest": "sha256:08043c9b26447e546864984d9533eb1d15342479b60f3497e56959ae293b8422",
    "grantDigest": "sha256:02e92ff9208d8f78fcda3b779aa9e6ef5a765cb4a935ee3fec5c190d1cc29810",
    "privateBindingDigest": "sha256:a4379888b6e176684348c302f840642092134021b4bf29a36c65d86f87bfd075",
    "privateEvidenceDigest": "sha256:aa79707da0d9c071843818500348c3e4617841b6820a1ce86f7c77f1eaaa4894",
}
EXPECTED_COUNTS = {"ok-shared": 8, "ok-mgmt": 18, "ok-infra": 16, "workload": 11}


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def read_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text())
    if not isinstance(value, dict):
        raise ClosureError("expected one YAML object")
    return value


def verify_closure(path: Path) -> dict[str, Any]:
    closure = read_yaml(path)
    spec = closure.get("spec", {})
    errors: list[str] = []
    if spec.get("state") != "PASS-D0-V3-PRIVATE-BOUND-NO-GO":
        errors.append("closure state mismatch")
    if spec.get("bindings") != EXPECTED_BINDINGS:
        errors.append("binding digest mismatch")

    observation = spec.get("observation", {})
    if observation.get("sealedGetCount") != 36:
        errors.append("sealed GET count mismatch")
    if observation.get("retainedObjectCounts") != EXPECTED_COUNTS:
        errors.append("retained object counts mismatch")
    if observation.get("retainedObjectTotal") != sum(EXPECTED_COUNTS.values()):
        errors.append("retained object total mismatch")
    if observation.get("bindingLifetimeSeconds") != 600:
        errors.append("binding lifetime mismatch")
    for key in ("allExpectedCountsMatched", "dataVolumeCorrelationPassed", "providerPVLonghornExactEqualityPassed"):
        if observation.get(key) is not True:
            errors.append(f"{key} is not proven")

    execution = spec.get("execution", {})
    expected_execution = {
        "snapshotRuns": 1, "retryPerformed": False, "mutationPerformed": False,
        "deletePerformed": False, "cleanupPerformed": False,
    }
    if execution != expected_execution:
        errors.append("execution boundary mismatch")

    conclusions = spec.get("conclusions", {})
    if conclusions != {
        "d0v3ReadBindingCreated": True,
        "storageCorrelationGapClosedForD0": True,
        "d1ThroughD3Authorized": False,
        "bindingReusableForD5": False,
    }:
        errors.append("conclusion boundary mismatch")

    redaction = spec.get("redaction", {})
    if not redaction or any(value is not False for value in redaction.values()):
        errors.append("redaction boundary mismatch")
    auth = spec.get("authorization", {})
    if auth.get("decision") != "NO-GO" or any(value is not False for key, value in auth.items() if key.endswith("Granted")):
        errors.append("closure grants authority")

    rendered = json.dumps(closure, sort_keys=True)
    forbidden = ('"uid":', '"resourceVersion":', '"endpoint":', '"kubeconfig":', '"token":', '"secretValue":')
    if any(term in rendered for term in forbidden):
        errors.append("forbidden raw field marker present")
    if errors:
        raise ClosureError("; ".join(errors))
    return closure


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--closure", type=Path, required=True)
    args = parser.parse_args()
    closure = verify_closure(args.closure.resolve())
    print(json.dumps({
        "closureDigest": digest(args.closure.resolve()),
        "semanticDigest": canonical_digest(closure),
        "state": "PASS-D0-V3-CLOSURE-REDACTED-NO-GO",
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ClosureError, OSError, ValueError) as error:
        print(f"ERROR: {error}", file=__import__("sys").stderr)
        raise SystemExit(1)
