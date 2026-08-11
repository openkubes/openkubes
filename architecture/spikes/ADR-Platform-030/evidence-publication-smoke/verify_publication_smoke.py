#!/usr/bin/env python3
"""Fail-closed verifier for the non-authorizing evidence publication smoke."""

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


SOURCE = _load("ok141_publication_smoke_source", SPIKE / "ghcr-publisher-offline-prototype" / "verify_publisher_offline_prototype.py")
V1 = SOURCE.V1
COLLECTOR_DIGEST = "sha256:5b7f6e021f951d8f460283caeed895c8ae4664abee2b363fb87af6d23d03bc15"
PUBLISHER_DIGEST = "sha256:3de106067f2fdb70add382c1fa63a2749e032dda9f83442f9880d6e672a3aab2"


def _expect(actual: Any, expected: Any, claim: str) -> None:
    if actual != expected:
        raise V1.HarnessError(f"evidence publication smoke {claim} mismatch")


def validate(document: dict[str, Any], path: Path) -> str:
    V1.normalize(document, json.loads((HERE / "publication-smoke-v1.schema.json").read_text()))
    spec = document["spec"]
    _expect(spec["state"], "READY-FOR-C1-P0-DECISION-NO-GO", "state")
    bindings = spec["bindings"]
    _expect(bindings["fixtureDigest"], "sha256:a2ae3437645db5a83426b89d36d00693d2600e4ef20dc1aba2650dcda7f936f6", "fixture")
    _expect(bindings["decisionInputDigest"], "sha256:4b618081517eb96ef1896b40a7f9f5556054ab2d029fbbf706e8630bb6b42c5c", "decision input")
    _expect(bindings["environment"], {"name": "ok-141-evidence-publish", "id": 19690057278}, "environment")
    _expect(bindings["collector"]["digest"], COLLECTOR_DIGEST, "collector digest")
    _expect(bindings["publisher"]["digest"], PUBLISHER_DIGEST, "publisher digest")
    for name, expected in (("collector", COLLECTOR_DIGEST), ("publisher", PUBLISHER_DIGEST)):
        active = REPO / bindings[name]["path"]
        _expect(V1.sha256_bytes(active.read_bytes()), expected, f"active {name} digest")
    scope = spec["scope"]
    _expect(scope["intakePath"], "architecture/spikes/ADR-Platform-030/evidence/intake/ok141-publication-smoke", "intake path")
    for field in ("clusterAccess", "clusterCredential", "infrastructureMutation"):
        _expect(scope[field], False, field)
    _expect(scope["syntheticEvidenceOnly"], True, "synthetic evidence")
    _expect(scope["publicGitRetentionAccepted"], True, "public retention")
    _expect((scope["maximumActionsRuns"], scope["maximumArtifacts"], scope["maximumGHCRPackages"], scope["maximumAttestations"]), (2, 1, 1, 1), "maximum boundary")
    phases = spec["phases"]
    _expect([phase["id"] for phase in phases], ["C1", "P0"], "phase order")
    _expect([phase["status"] for phase in phases], ["NOT-GRANTED", "NOT-GRANTED"], "phase status")
    authorization = spec["authorization"]
    _expect(authorization["decision"], "NO-GO", "authorization")
    for field, value in authorization.items():
        if field != "decision":
            _expect(value, False, f"authorization {field}")
    return V1.sha256_bytes(path.read_bytes())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--digest-file", type=Path)
    args = parser.parse_args()
    try:
        path = args.protocol.resolve()
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
