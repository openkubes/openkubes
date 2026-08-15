#!/usr/bin/env python3
"""Fail-closed verifier for the inert durable-correlation checkpoint."""

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


SOURCE = _load("ok141_publisher_durable_source", SPIKE / "ghcr-publisher-offline-prototype" / "verify_publisher_offline_prototype.py")
V1 = SOURCE.V1
SOURCE_DIGEST = "sha256:82c45f3901cc8347940ec61735a720f3d18a5b00540f17361b84480eaf3db91f"
COMPONENT_DIGESTS = {
    "candidateWorkflow": "sha256:3de106067f2fdb70add382c1fa63a2749e032dda9f83442f9880d6e672a3aab2",
    "correlatedPlannerAndVerifier": "sha256:988f7abf0ac7c53fe2539d20cfde76ac66359d6444a431168278a8bef7a80f16",
}


def _expect(actual: Any, expected: Any, claim: str) -> None:
    if actual != expected:
        raise V1.HarnessError(f"GHCR publisher durable-correlation {claim} mismatch")


def validate(document: dict[str, Any], path: Path) -> str:
    V1.normalize(document, json.loads((HERE / "publisher-durable-correlation-v1.schema.json").read_text()))
    spec = document["spec"]
    _expect(spec["state"], "IMPLEMENTED-OFFLINE-INERT-BLOCKED-NO-GO", "state")
    source = spec["sourceAmendment"]
    source_path = (path.parent / source["path"]).resolve()
    _expect(source["digest"], SOURCE_DIGEST, "source digest")
    _expect(V1.sha256_bytes(source_path.read_bytes()), SOURCE_DIGEST, "source raw digest")

    components = spec["components"]
    for name, expected_digest in COMPONENT_DIGESTS.items():
        component = components[name]
        component_path = (path.parent / component["path"]).resolve()
        _expect(component["digest"], expected_digest, f"{name} digest")
        _expect(V1.sha256_bytes(component_path.read_bytes()), expected_digest, f"{name} raw digest")

    candidate = components["candidateWorkflow"]
    _expect(candidate["futureDeploymentPathPresent"], False, "active workflow absence")
    if (REPO / candidate["futureDeploymentPath"]).exists():
        raise V1.HarnessError("publisher workflow is unexpectedly active")
    workflow_path = (path.parent / candidate["path"]).resolve()
    workflow = yaml.safe_load(workflow_path.read_text())
    _expect(set(workflow["on"]), {"workflow_dispatch"}, "trigger")
    publish = workflow["jobs"]["publish"]
    _expect(publish["if"], "github.ref == 'refs/heads/main'", "source-ref guard")
    _expect(publish["environment"], "ok-141-evidence-publish", "environment")
    _expect(len(publish["steps"]), 10, "step count")
    candidate_text = workflow_path.read_text()
    for phrase in (
        'str(d["id"])==os.environ["SOURCE_RUN_ID"]',
        'd["bindings"]["protocolDigest"]',
        '--source-run "$RUNNER_TEMP/source-run.json"',
        '--correlation "$RUNNER_TEMP/source-run-correlation.json"',
        'ghcr-publisher-durable-correlation/publish_evidence_v2.py verify-receipt',
    ):
        if phrase not in candidate_text:
            raise V1.HarnessError(f"durable-correlation workflow behavior missing: {phrase}")

    contract = spec["correlationContract"]
    _expect(contract["embeddedTransportPath"], "source-run-correlation.json", "transport path")
    for field in ("sourceRunValidatedBeforeDownload", "evidenceBindingsValidatedBeforeTransport", "transportDigestBindsCorrelation", "receiptPreservesCorrelationDigest"):
        _expect(contract[field], True, f"correlation {field}")
    proof = spec["proof"]
    _expect(proof["offlineTestsPassed"], 9, "test count")
    _expect(proof["durableCorrelationEmbedded"], True, "durable correlation")
    _expect(proof["activeWorkflowPresent"], False, "active workflow proof")
    _expect(proof["livePublicationPerformed"], False, "live publication proof")
    authorization = spec["authorization"]
    _expect(authorization["decision"], "NO-GO", "authorization")
    for field, value in authorization.items():
        if field != "decision":
            _expect(value, False, f"authorization {field}")
    return V1.sha256_bytes(path.read_bytes())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--digest-file", type=Path)
    args = parser.parse_args()
    try:
        path = args.checkpoint.resolve()
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
