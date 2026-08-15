#!/usr/bin/env python3
"""Fail-closed verifier for the inert OK-141 evidence collector."""

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


SOURCE = _load("ok141_collector_source", SPIKE / "ghcr-publisher-offline-prototype" / "verify_publisher_offline_prototype.py")
V1 = SOURCE.V1
PUBLISHER_EVIDENCE_DIGEST = "sha256:7b72cefe9bbb8d4842ed21622ae856b576b69313205e43725949e22324444a02"
COMPONENT_DIGESTS = {
    "candidateWorkflow": "sha256:5b7f6e021f951d8f460283caeed895c8ae4664abee2b363fb87af6d23d03bc15",
    "bundlePreparer": "sha256:bb931d4115d7b7a5eb13f657da1770bfd927582ad5a847a5f059220896faec57",
}


def _expect(actual: Any, expected: Any, claim: str) -> None:
    if actual != expected:
        raise V1.HarnessError(f"evidence collector offline prototype {claim} mismatch")


def validate(document: dict[str, Any], path: Path) -> str:
    V1.normalize(document, json.loads((HERE / "collector-offline-prototype-v1.schema.json").read_text()))
    spec = document["spec"]
    _expect(spec["state"], "IMPLEMENTED-OFFLINE-INERT-NO-GO", "state")
    source = spec["sourcePublisherEvidence"]
    source_path = (path.parent / source["path"]).resolve()
    _expect(source["digest"], PUBLISHER_EVIDENCE_DIGEST, "publisher evidence digest")
    _expect(V1.sha256_bytes(source_path.read_bytes()), PUBLISHER_EVIDENCE_DIGEST, "publisher evidence raw digest")
    components = spec["components"]
    for name, expected in COMPONENT_DIGESTS.items():
        component = components[name]
        component_path = (path.parent / component["path"]).resolve()
        _expect(component["digest"], expected, f"{name} digest")
        _expect(V1.sha256_bytes(component_path.read_bytes()), expected, f"{name} raw digest")
    candidate = components["candidateWorkflow"]
    _expect(candidate["futureDeploymentPathPresent"], False, "deployment absence")
    if (REPO / candidate["futureDeploymentPath"]).exists():
        raise V1.HarnessError("collector workflow is unexpectedly active")
    workflow_path = (path.parent / candidate["path"]).resolve()
    workflow = yaml.safe_load(workflow_path.read_text())
    _expect(set(workflow["on"]), {"workflow_dispatch"}, "trigger")
    collect = workflow["jobs"]["collect"]
    _expect(collect["if"], "github.ref == 'refs/heads/main'", "main guard")
    _expect(collect["environment"], "ok-141-evidence-publish", "environment")
    _expect(workflow["permissions"], {"contents": "read"}, "permissions")
    _expect(len(collect["steps"]), 4, "step count")
    text = workflow_path.read_text()
    for phrase in (
        'git merge-base --is-ancestor "$INTAKE_COMMIT" "$GITHUB_SHA"',
        'architecture/spikes/ADR-Platform-030/evidence/intake/',
        '--run-id "$GITHUB_RUN_ID"',
        'name: ok141-evidence-bundle',
        'retention-days: 7',
    ):
        if phrase not in text:
            raise V1.HarnessError(f"collector workflow behavior missing: {phrase}")
    intake = spec["intakeContract"]
    _expect(intake["clusterCredentialsAccepted"], False, "cluster credentials")
    _expect(intake["secretsAccepted"], False, "secrets")
    _expect(intake["sourceDescriptorEmbeddedInBundle"], True, "source descriptor")
    proof = spec["proof"]
    _expect(proof["offlineTestsPassed"], 13, "test count")
    for field in ("workflowDeployed", "workflowDispatched", "artifactUploaded", "publisherDispatched"):
        _expect(proof[field], False, field)
    authorization = spec["authorization"]
    _expect(authorization["decision"], "NO-GO", "authorization")
    for field, value in authorization.items():
        if field != "decision":
            _expect(value, False, f"authorization {field}")
    return V1.sha256_bytes(path.read_bytes())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prototype", type=Path, required=True)
    parser.add_argument("--digest-file", type=Path)
    args = parser.parse_args()
    try:
        path = args.prototype.resolve()
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
