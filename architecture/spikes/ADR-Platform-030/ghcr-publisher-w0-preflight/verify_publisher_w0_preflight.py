#!/usr/bin/env python3
"""Fail-closed verifier for the OK-141 W0 preflight."""

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


SOURCE = _load("ok141_publisher_w0_source", SPIKE / "ghcr-publisher-offline-prototype" / "verify_publisher_offline_prototype.py")
V1 = SOURCE.V1
E0_DIGEST = "sha256:a79a951265b1cb84df1fde6f657131f8f559b962011b94d3316aef2e8a1b93d9"
CANDIDATE_DIGEST = "sha256:3de106067f2fdb70add382c1fa63a2749e032dda9f83442f9880d6e672a3aab2"


def _expect(actual: Any, expected: Any, claim: str) -> None:
    if actual != expected:
        raise V1.HarnessError(f"GHCR publisher W0 preflight {claim} mismatch")


def validate(document: dict[str, Any], path: Path) -> str:
    V1.normalize(document, json.loads((HERE / "publisher-w0-preflight-v1.schema.json").read_text()))
    spec = document["spec"]
    _expect(spec["state"], "READY-FOR-W0-DECISION-NOT-GRANTED", "state")
    source = spec["sourceE0"]
    source_path = (path.parent / source["path"]).resolve()
    _expect(source["digest"], E0_DIGEST, "E0 digest")
    _expect(V1.sha256_bytes(source_path.read_bytes()), E0_DIGEST, "E0 raw digest")
    candidate = spec["candidate"]
    candidate_path = (path.parent / candidate["sourcePath"]).resolve()
    _expect(candidate["sourceDigest"], CANDIDATE_DIGEST, "candidate digest")
    _expect(V1.sha256_bytes(candidate_path.read_bytes()), CANDIDATE_DIGEST, "candidate raw digest")
    _expect(candidate["deploymentPathPresent"], False, "active workflow absence")
    _expect(candidate["automaticTriggerPresent"], False, "automatic trigger")
    if (REPO / candidate["deploymentPath"]).exists():
        raise V1.HarnessError("publisher workflow is unexpectedly active")
    observation = spec["readOnlyObservation"]
    _expect(observation["environment"], {"id": 19690057278, "present": True, "reviewerID": 1782605, "exactBranchPolicy": "main", "environmentSecretsCount": 0, "canAdminsBypass": True}, "environment")
    _expect(observation["activeWorkflowState"], "ABSENT-404", "active workflow observation")
    supply = spec["supplyChainObservation"]
    _expect(supply["checkout"]["fullCommitSHA"], "11d5960a326750d5838078e36cf38b85af677262", "checkout SHA")
    _expect(supply["checkout"]["commitSignatureVerified"], True, "checkout signature")
    _expect(supply["checkout"]["tagResolvesToExactCommit"], True, "checkout tag")
    _expect(supply["attestation"]["fullCommitSHA"], "1e69f48acb82d1966a394da916b4c1698aa569d6", "attestation SHA")
    _expect(supply["attestation"]["commitSignatureVerified"], True, "attestation signature")
    _expect(supply["attestation"]["tagResolvesToExactCommit"], True, "attestation tag")
    _expect(supply["oras"]["assetDigest"], "sha256:9ce999f8d2de03fc03968b29d743077a58783e545e5eaa53917ca177352d0e59", "ORAS digest")
    _expect(supply["oras"]["candidateDigestMatchesReleaseMetadata"], True, "ORAS metadata")
    scope = spec["w0Scope"]
    _expect(scope["activeWorkflowDigestRequired"], CANDIDATE_DIGEST, "deployment digest")
    for field in ("workflowDispatchAuthorized", "packageWriteAuthorized", "attestationWriteAuthorized", "p0Authorized"):
        _expect(scope[field], False, f"scope {field}")
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
