#!/usr/bin/env python3
"""Fail-closed verifier for the inert OK-141 publisher deployment preflight."""

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


SOURCE = _load(
    "ok141_publisher_deployment_source",
    SPIKE / "ghcr-publisher-offline-prototype" / "verify_publisher_offline_prototype.py",
)
V1 = SOURCE.V1
SOURCE_DIGEST = "sha256:023cfad2d496ec0145e212b9e5bb996e3ef200fba8947d521e6ad2b2fce3252c"
CANDIDATE_DIGEST = "sha256:ae6514766cdba993f3480d6445494d8134eefad447c7320c4b720ed57633de4e"


def _expect(actual: Any, expected: Any, claim: str) -> None:
    if actual != expected:
        raise V1.HarnessError(f"GHCR publisher deployment preflight {claim} mismatch")


def validate(document: dict[str, Any], path: Path) -> str:
    schema = json.loads((HERE / "publisher-deployment-preflight-v1.schema.json").read_text())
    V1.normalize(document, schema)
    spec = document["spec"]
    _expect(spec["state"], "PREPARED-OFFLINE-BLOCKED-NO-GO", "state")
    _expect(
        spec["baseline"],
        {
            "repository": "openkubes/openkubes",
            "commit": "23ecce974e6e5e79ebadc7af31068428222faa76",
            "release": "v0.15.0",
        },
        "baseline",
    )

    source = spec["sourcePrototype"]
    source_path = (path.parent / source["path"]).resolve()
    _expect(source["digest"], SOURCE_DIGEST, "source digest")
    _expect(V1.sha256_bytes(source_path.read_bytes()), SOURCE_DIGEST, "source raw digest")
    SOURCE.validate(V1.read_yaml_or_json(source_path), source_path)

    candidate = spec["candidate"]
    candidate_path = (path.parent / candidate["sourcePath"]).resolve()
    _expect(candidate["sourceDigest"], CANDIDATE_DIGEST, "candidate digest")
    _expect(V1.sha256_bytes(candidate_path.read_bytes()), CANDIDATE_DIGEST, "candidate raw digest")
    _expect(candidate["deploymentPath"], ".github/workflows/ok141-evidence-publisher.yaml", "deployment path")
    _expect(candidate["deploymentPathPresent"], False, "deployment absence")
    _expect(candidate["sourceRefGuard"], "MISSING-BLOCKS-W0", "source-ref blocker")
    _expect(candidate["sourceRunMetadataGuard"], "MISSING-BLOCKS-P0", "source-run blocker")
    if (REPO / candidate["deploymentPath"]).exists():
        raise V1.HarnessError("publisher workflow is unexpectedly active")

    workflow = yaml.safe_load(candidate_path.read_text())
    _expect(set(workflow["on"]), {"workflow_dispatch"}, "workflow triggers")
    _expect(workflow["jobs"]["publish"]["environment"], candidate["environment"], "workflow environment")
    _expect(
        workflow["permissions"],
        {
            "actions": "read",
            "artifact-metadata": "write",
            "attestations": "write",
            "contents": "read",
            "id-token": "write",
            "packages": "write",
        },
        "workflow permissions",
    )

    observation = spec["readOnlyObservation"]
    _expect(observation["repositoryVisibility"], "public", "repository visibility")
    _expect(observation["environmentState"], "ABSENT-404", "environment observation")
    _expect(observation["mainBranchProtection"]["present"], True, "branch protection")

    environment = spec["environmentCandidate"]
    _expect(environment["mustExistBeforeWorkflowDeployment"], True, "environment ordering")
    _expect(environment["creationByWorkflowForbidden"], True, "implicit environment creation")
    _expect(environment["reviewers"], [{"type": "User", "login": "arashkaffamanesh", "id": 1782605}], "reviewer")
    _expect(
        environment["deploymentBranchPolicy"],
        {"protectedBranches": False, "customBranchPolicies": True, "exactPattern": "main"},
        "branch policy",
    )
    _expect(environment["environmentSecretsRequired"], [], "environment secrets")

    gates = spec["gateSequence"]
    _expect([gate["id"] for gate in gates], ["E0", "W0", "P0"], "gate order")
    _expect([gate["status"] for gate in gates], ["NOT-GRANTED"] * 3, "gate status")
    _expect(gates[1]["dependsOn"], ["E0"], "W0 dependency")
    _expect(gates[2]["dependsOn"], ["E0", "W0"], "P0 dependency")

    for field, forbidden in spec["forbiddenByThisCheckpoint"].items():
        _expect(forbidden, True, f"forbidden mutation {field}")
    authorization = spec["authorization"]
    _expect(authorization["decision"], "NO-GO", "authorization")
    for field, value in authorization.items():
        if field != "decision":
            _expect(value, False, f"authorization {field}")
    rules = " ".join(spec["rules"]).lower()
    for phrase in (
        "not deployment authority",
        "before workflow deployment",
        "does not authorize workflow dispatch",
        "does not inherit authority",
        "explicit human authorization",
        "remain no-go",
    ):
        if phrase not in rules:
            raise V1.HarnessError(f"publisher deployment safety rule missing: {phrase}")
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
