#!/usr/bin/env python3
"""Fail-closed verifier for the inert OK-141 publisher candidate amendment."""

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


SOURCE = _load("ok141_publisher_v2_source", SPIKE / "ghcr-publisher-offline-prototype" / "verify_publisher_offline_prototype.py")
V1 = SOURCE.V1
SOURCE_DIGEST = "sha256:023cfad2d496ec0145e212b9e5bb996e3ef200fba8947d521e6ad2b2fce3252c"
PREFLIGHT_DIGEST = "sha256:f8a4b743f8af81ba22d780726260edde2b9a6f197544cd8ff8b9b00d58a132ce"


def _expect(actual: Any, expected: Any, claim: str) -> None:
    if actual != expected:
        raise V1.HarnessError(f"GHCR publisher candidate amendment {claim} mismatch")


def validate(document: dict[str, Any], path: Path) -> str:
    V1.normalize(document, json.loads((HERE / "publisher-candidate-amendment-v1.schema.json").read_text()))
    spec = document["spec"]
    _expect(spec["state"], "IMPLEMENTED-OFFLINE-INERT-BLOCKED-NO-GO", "state")
    for field, expected in (("sourcePrototype", SOURCE_DIGEST), ("sourcePreflight", PREFLIGHT_DIGEST)):
        source = spec[field]
        source_path = (path.parent / source["path"]).resolve()
        _expect(source["digest"], expected, f"{field} digest")
        _expect(V1.sha256_bytes(source_path.read_bytes()), expected, f"{field} raw digest")

    candidate = spec["candidate"]
    candidate_path = (path.parent / candidate["path"]).resolve()
    _expect(V1.sha256_bytes(candidate_path.read_bytes()), candidate["digest"], "candidate digest")
    _expect(candidate["futureDeploymentPathPresent"], False, "active workflow absence")
    if (REPO / candidate["futureDeploymentPath"]).exists():
        raise V1.HarnessError("publisher workflow is unexpectedly active")
    workflow = yaml.safe_load(candidate_path.read_text())
    _expect(set(workflow["on"]), {"workflow_dispatch"}, "trigger")
    _expect(set(workflow["on"]["workflow_dispatch"]["inputs"]), set(candidate["requiredInputs"]), "input membership")
    publish = workflow["jobs"]["publish"]
    _expect(candidate["jobSourceRefGuard"], "refs/heads/main", "declared source-ref guard")
    _expect(publish["if"], "github.ref == 'refs/heads/main'", "source-ref guard")
    _expect(publish["environment"], "ok-141-evidence-publish", "environment")
    _expect(len(publish["steps"]), 10, "step count")
    text = candidate_path.read_text()
    for phrase in (
        'repos/openkubes/openkubes/actions/runs/$SOURCE_RUN_ID',
        'd["repository"]["full_name"]',
        '"event":"workflow_dispatch"',
        '"head_branch":"main"',
        '"status":"completed"',
        '"conclusion":"success"',
        'd["protocolDigest"]==os.environ["PROTOCOL_DIGEST"]',
    ):
        if phrase not in text:
            raise V1.HarnessError(f"publisher v2 guard missing: {phrase}")
    _expect(spec["resolvedBlockers"], {"sourceRefGuard": "IMPLEMENTED-OFFLINE", "sourceRunMetadataGuard": "IMPLEMENTED-OFFLINE"}, "resolved blockers")
    _expect(candidate["sourceMetadataPersistedInOCIPayload"], False, "durable correlation boundary")
    authorization = spec["authorization"]
    _expect(authorization["decision"], "NO-GO", "authorization")
    for field, value in authorization.items():
        if field != "decision":
            _expect(value, False, f"authorization {field}")
    return V1.sha256_bytes(path.read_bytes())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--amendment", type=Path, required=True)
    parser.add_argument("--digest-file", type=Path)
    args = parser.parse_args()
    try:
        path = args.amendment.resolve()
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
