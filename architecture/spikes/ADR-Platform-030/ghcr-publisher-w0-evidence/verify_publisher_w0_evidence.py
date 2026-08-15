#!/usr/bin/env python3
"""Fail-closed verifier for the recorded OK-141 W0 result."""

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


SOURCE = _load("ok141_publisher_w0_evidence_source", SPIKE / "ghcr-publisher-offline-prototype" / "verify_publisher_offline_prototype.py")
V1 = SOURCE.V1
PREFLIGHT_DIGEST = "sha256:0846d51bada19fed015fa719c6e9d8d418cdbc2f3200cb214207ead10af5acd8"
WORKFLOW_DIGEST = "sha256:3de106067f2fdb70add382c1fa63a2749e032dda9f83442f9880d6e672a3aab2"


def _expect(actual: Any, expected: Any, claim: str) -> None:
    if actual != expected:
        raise V1.HarnessError(f"GHCR publisher W0 evidence {claim} mismatch")


def validate(document: dict[str, Any], path: Path) -> str:
    V1.normalize(document, json.loads((HERE / "publisher-w0-evidence-v1.schema.json").read_text()))
    spec = document["spec"]
    _expect(spec["state"], "W0-COMPLETE-OBSERVED-P0-NO-GO", "state")
    source = spec["sourcePreflight"]
    source_path = (path.parent / source["path"]).resolve()
    _expect(source["digest"], PREFLIGHT_DIGEST, "preflight digest")
    _expect(V1.sha256_bytes(source_path.read_bytes()), PREFLIGHT_DIGEST, "preflight raw digest")
    _expect(spec["authorizationRecord"]["gate"], "W0", "authorization gate")
    _expect(spec["authorizationRecord"]["p0Granted"], False, "P0 authorization boundary")
    _expect(spec["execution"]["pullRequest"], 121, "pull request")
    _expect(spec["execution"]["mergeCommit"], "022eafd970b6c0226184356a68df489284f1ca67", "merge commit")
    _expect(spec["execution"]["mutationScopeExceeded"], False, "mutation scope")
    workflow = spec["observedState"]["workflow"]
    _expect(workflow["id"], 332090718, "workflow ID")
    _expect(workflow["path"], ".github/workflows/ok141-evidence-publisher.yaml", "workflow path")
    _expect(workflow["digest"], WORKFLOW_DIGEST, "workflow digest")
    active_path = REPO / workflow["path"]
    _expect(V1.sha256_bytes(active_path.read_bytes()), WORKFLOW_DIGEST, "active workflow raw digest")
    _expect(workflow["trigger"], "workflow_dispatch", "trigger")
    _expect(workflow["environment"], "ok-141-evidence-publish", "environment")
    _expect(workflow["sourceRefGuard"], "refs/heads/main", "source-ref guard")
    observed = spec["observedState"]
    _expect(observed["workflowRunCount"], 0, "run count")
    for field in ("workflowDispatched", "packageCreated", "attestationCreated"):
        _expect(observed[field], False, field)
    _expect(spec["nextGate"]["status"], "NOT-GRANTED", "P0 status")
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
