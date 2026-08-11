#!/usr/bin/env python3
"""Fail-closed verifier for the recorded OK-141 E0 result."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import yaml


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
REPO = SPIKE.parents[2]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


SOURCE = _load("ok141_publisher_e0_source", SPIKE / "ghcr-publisher-offline-prototype" / "verify_publisher_offline_prototype.py")
V1 = SOURCE.V1
SOURCE_DIGEST = "sha256:69284a91386a82218a7a8cfb667d76e380867a2e7fa4177c24089e96230307f8"


def _expect(actual: Any, expected: Any, claim: str) -> None:
    if actual != expected:
        raise V1.HarnessError(f"GHCR publisher E0 evidence {claim} mismatch")


def validate(document: dict[str, Any], path: Path) -> str:
    V1.normalize(document, json.loads((HERE / "publisher-e0-evidence-v1.schema.json").read_text()))
    spec = document["spec"]
    _expect(spec["state"], "E0-COMPLETE-OBSERVED-W0-P0-NO-GO", "state")
    source = spec["sourcePreflight"]
    source_path = (path.parent / source["path"]).resolve()
    _expect(source["digest"], SOURCE_DIGEST, "source digest")
    _expect(V1.sha256_bytes(source_path.read_bytes()), SOURCE_DIGEST, "source raw digest")
    record = spec["authorizationRecord"]
    _expect(record["gate"], "E0", "authorization gate")
    _expect(record["grantedBy"], "github:arashkaffamanesh", "granting principal")
    _expect(record["w0Granted"], False, "W0 grant boundary")
    _expect(record["p0Granted"], False, "P0 grant boundary")
    _expect(spec["execution"]["environmentID"], 19690057278, "environment ID")
    _expect(spec["execution"]["mutationScopeExceeded"], False, "mutation scope")
    observed = spec["observedState"]
    _expect(observed["environmentName"], "ok-141-evidence-publish", "environment name")
    _expect(observed["environmentPresent"], True, "environment presence")
    _expect(observed["canAdminsBypass"], True, "admin bypass observation")
    _expect(observed["reviewer"], {"type": "User", "login": "arashkaffamanesh", "id": 1782605, "preventSelfReview": False}, "reviewer")
    _expect(observed["deploymentBranchPolicy"], {"protectedBranches": False, "customBranchPolicies": True, "totalCount": 1, "policyID": 57078674, "name": "main", "type": "branch"}, "branch policy")
    _expect(observed["environmentSecretsCount"], 0, "environment secrets")
    _expect(observed["activePublisherWorkflow"]["state"], "ABSENT-404", "active workflow")
    if (REPO / observed["activePublisherWorkflow"]["path"]).exists():
        raise V1.HarnessError("publisher workflow is unexpectedly active")
    for field in ("packageCreated", "attestationCreated", "workflowDispatched"):
        _expect(observed[field], False, field)
    boundaries = spec["claimBoundaries"]
    _expect(boundaries["adminBypassObserved"], True, "admin bypass boundary")
    _expect(boundaries["independentApprovalProven"], False, "independent approval boundary")
    _expect(boundaries["selfApprovalPrevented"], False, "self approval boundary")
    _expect([spec["nextGates"][name]["status"] for name in ("w0", "p0")], ["NOT-GRANTED", "NOT-GRANTED"], "next gates")
    authorization = spec["authorization"]
    _expect(authorization["decision"], "NO-GO", "authorization")
    for field, value in authorization.items():
        if field != "decision":
            _expect(value, False, f"authorization {field}")
    return V1.sha256_bytes(path.read_bytes())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--digest-file", type=Path)
    args = parser.parse_args()
    try:
        path = args.evidence.resolve()
        digest = validate(V1.read_yaml_or_json(path), path)
        if args.digest_file:
            _expect(digest.removeprefix("sha256:"), args.digest_file.read_text().split()[0], "raw digest")
        print(digest)
        return 0
    except (V1.HarnessError, OSError, ValueError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
