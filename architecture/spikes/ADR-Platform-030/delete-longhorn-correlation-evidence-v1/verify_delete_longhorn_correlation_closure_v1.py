#!/usr/bin/env python3
"""Fail-closed verifier for redacted Longhorn correlation closure evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml


class ClosureError(ValueError):
    pass


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
    if spec.get("state") != "PASS-READ-ONLY-DIAGNOSTIC-NO-GO":
        errors.append("closure state mismatch")
    bindings = spec.get("bindings", {})
    expected = {
        "candidateDigest": "sha256:39a715ccfe16b366f3d7fb552c7edfb585f035b0b44afce5ee814a0f1fe4525d",
        "grantDigest": "sha256:2b2c9594f4b19749dcf3527cbe6f56b558bc8530b694ae8be14d0725eb6b2216",
        "privateEvidenceDigest": "sha256:5c6f386367c0c8576b24fa149bb5b9506ed8903195709a664ca6163131299623",
        "identityDigest": "sha256:7d2f0a78b6409be7a1742738a7bc31fb855f81d975ecad9978b3872736e48182",
    }
    if bindings != expected:
        errors.append("binding digest mismatch")
    observation = spec.get("observation", {})
    if observation.get("providerPVCount") != 2:
        errors.append("provider PV count mismatch")
    if observation.get("matchCounts") != {
        "volumeHandleToMetadataName": 2,
        "pvNameToMetadataName": 2,
        "kubernetesStatusTuple": 2,
    }:
        errors.append("correlation counts mismatch")
    if observation.get("verdict") != "MULTIPLE-EQUIVALENT-CORRELATIONS":
        errors.append("correlation verdict mismatch")
    conclusions = spec.get("conclusions", {})
    if conclusions.get("retainedLonghornStoragePresent") is not True or conclusions.get("missingStorageCauseDisproved") is not True:
        errors.append("storage conclusion mismatch")
    if conclusions.get("exactEarlierZeroCause") != "UNRESOLVED-TRANSIENT-OR-CONTEXT-DERIVATION":
        errors.append("closure overclaims exact root cause")
    execution = spec.get("execution", {})
    if execution != {"queryCount": 2, "mutationPerformed": False, "deletePerformed": False, "retryPerformed": False}:
        errors.append("execution boundary mismatch")
    redaction = spec.get("redaction", {})
    if any(value is not False for value in redaction.values()):
        errors.append("redaction boundary mismatch")
    auth = spec.get("authorization", {})
    if auth.get("decision") != "NO-GO" or any(value is not False for key, value in auth.items() if key.endswith("Granted")):
        errors.append("closure grants authority")
    forbidden = ('"uid":', '"resourceVersion":', '"endpoint":', '"kubeconfig":', '"token":', '"secretValue":')
    rendered = json.dumps(closure, sort_keys=True)
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
    print(json.dumps({"closureDigest": digest(args.closure.resolve()), "semanticDigest": canonical_digest(closure), "state": "PASS-LONGHORN-CORRELATION-CLOSURE-REDACTED-NO-GO"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ClosureError, OSError, ValueError) as error:
        print(f"ERROR: {error}", file=__import__("sys").stderr)
        raise SystemExit(1)
