#!/usr/bin/env python3
"""Fail-closed verifier for OK-141 publisher deployment preflight v2."""

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


SOURCE = _load("ok141_publisher_preflight_v2_source", SPIKE / "ghcr-publisher-offline-prototype" / "verify_publisher_offline_prototype.py")
V1 = SOURCE.V1
SOURCE_DIGEST = "sha256:02d702cb629afc36094422a1e41c11553b1ba1a483183af184e902e72dec438a"
CANDIDATE_DIGEST = "sha256:3de106067f2fdb70add382c1fa63a2749e032dda9f83442f9880d6e672a3aab2"


def _expect(actual: Any, expected: Any, claim: str) -> None:
    if actual != expected:
        raise V1.HarnessError(f"GHCR publisher deployment preflight v2 {claim} mismatch")


def validate(document: dict[str, Any], path: Path) -> str:
    V1.normalize(document, json.loads((HERE / "publisher-deployment-preflight-v2.schema.json").read_text()))
    spec = document["spec"]
    _expect(spec["state"], "OFFLINE-COMPLETE-E0-BLOCKED-NO-GO", "state")
    source = spec["sourceCheckpoint"]
    source_path = (path.parent / source["path"]).resolve()
    _expect(source["digest"], SOURCE_DIGEST, "source digest")
    _expect(V1.sha256_bytes(source_path.read_bytes()), SOURCE_DIGEST, "source raw digest")
    candidate = spec["candidate"]
    candidate_path = (path.parent / candidate["sourcePath"]).resolve()
    _expect(candidate["sourceDigest"], CANDIDATE_DIGEST, "candidate digest")
    _expect(V1.sha256_bytes(candidate_path.read_bytes()), CANDIDATE_DIGEST, "candidate raw digest")
    _expect(candidate["deploymentPathPresent"], False, "deployment absence")
    if (REPO / candidate["deploymentPath"]).exists():
        raise V1.HarnessError("publisher workflow is unexpectedly active")
    workflow = yaml.safe_load(candidate_path.read_text())
    _expect(set(workflow["on"]), {"workflow_dispatch"}, "workflow triggers")
    _expect(workflow["jobs"]["publish"]["if"], "github.ref == 'refs/heads/main'", "source-ref guard")
    _expect(workflow["jobs"]["publish"]["environment"], "ok-141-evidence-publish", "environment")
    _expect(spec["readOnlyObservation"]["environmentState"], "ABSENT-404", "environment observation")
    _expect(spec["readOnlyObservation"]["mainBranchProtection"]["present"], True, "branch protection")
    closure = spec["offlineClosure"]
    _expect(set(closure.values()), {"PROVEN-IN-CANDIDATE", "PROVEN-IN-TRANSPORT", "PROVEN-OFFLINE", True}, "offline closure states")
    environment = spec["environmentCandidate"]
    _expect(environment["reviewers"], [{"type": "User", "login": "arashkaffamanesh", "id": 1782605}], "reviewer")
    _expect(environment["deploymentBranchPolicy"], {"protectedBranches": False, "customBranchPolicies": True, "exactPattern": "main"}, "branch policy")
    _expect(environment["environmentSecretsRequired"], [], "environment secrets")
    gates = spec["gateSequence"]
    _expect([gate["id"] for gate in gates], ["E0", "W0", "P0"], "gate order")
    _expect([gate["status"] for gate in gates], ["NOT-GRANTED"] * 3, "gate status")
    _expect(spec["nextDecision"], {"gate": "E0", "scope": "Create protect and observe only ok-141-evidence-publish.", "authorizesLaterGates": False, "authorizationRequired": True}, "next decision")
    for field, forbidden in spec["forbiddenByThisCheckpoint"].items():
        _expect(forbidden, True, f"forbidden mutation {field}")
    authorization = spec["authorization"]
    _expect(authorization["decision"], "NO-GO", "authorization")
    for field, value in authorization.items():
        if field != "decision":
            _expect(value, False, f"authorization {field}")
    return V1.sha256_bytes(path.read_bytes())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight", type=Path, required=True)
    parser.add_argument("--digest-file", type=Path)
    args = parser.parse_args()
    try:
        path = args.preflight.resolve()
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
