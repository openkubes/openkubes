#!/usr/bin/env python3
"""Fail-closed verifier for the inert OK-141 GHCR observer prototype."""

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


ALERT = _load(
    "ok141_observer_source_alert",
    SPIKE / "ghcr-alert-destination-decision" / "verify_ghcr_alert_destination_decision.py",
)
V1 = ALERT.V1
SOURCE_DIGEST = "sha256:d9efd41fd70147e99c912e747403470533e01b6548ccedbf6b9f709d2c7c4683"
COMPONENT_DIGESTS = {
    "candidateWorkflow": ("candidate/ok141-evidence-observer.workflow.yaml", "sha256:42a4bd4f775bc6b0a95e4b96e30b730c8e996887a02e03dbbe5099ad3aa7a951"),
    "evaluator": ("observe_ghcr_evidence.py", "sha256:e10f7ad4f96284552d99385850710b8b204866e045dfb2437ca1ea05205b4ffd"),
    "offlineIndexFixture": ("fixtures/active-index.json", "sha256:d419fdbe9840960d9e4c773a7abccf33c990a8ed5406c693e0ca5524b0ff6e71"),
    "offlineObservationFixture": ("fixtures/present-observation.json", "sha256:83b21e4e0ddd4071d87838282681cd68b80d58502178b67d46112a3a3b5750dc"),
}


def _expect(actual: Any, expected: Any, claim: str) -> None:
    if actual != expected:
        raise V1.HarnessError(f"GHCR observer offline prototype {claim} mismatch")


def validate(document: dict[str, Any], manifest_path: Path) -> str:
    schema = json.loads((HERE / "observer-offline-prototype-v1.schema.json").read_text())
    V1.normalize(document, schema)
    spec = document["spec"]
    _expect(spec["state"], "IMPLEMENTED-OFFLINE-INERT-NOT-DEPLOYED-NO-GO", "state")

    source = spec["sourceAlertDecision"]
    source_path = (manifest_path.parent / source["path"]).resolve()
    if SPIKE.resolve() not in source_path.parents or not source_path.is_file():
        raise V1.HarnessError("GHCR observer prototype source is missing or outside spike")
    _expect(source, {"path": "../ghcr-alert-destination-decision/ghcr-alert-destination-decision-v1.yaml", "digest": SOURCE_DIGEST, "state": "ACCEPTED-DESTINATION-IMPLEMENTATION-BLOCKED-NO-GO"}, "source")
    _expect(V1.sha256_bytes(source_path.read_bytes()), SOURCE_DIGEST, "source raw digest")
    ALERT.validate(V1.read_yaml_or_json(source_path), source_path)

    for name, (path, digest) in COMPONENT_DIGESTS.items():
        _expect(spec["components"][name], {"path": path, "digest": digest}, f"component {name}")
        component_path = (HERE / path).resolve()
        if HERE.resolve() not in component_path.parents or not component_path.is_file():
            raise V1.HarnessError(f"GHCR observer component missing or outside prototype: {name}")
        _expect(V1.sha256_bytes(component_path.read_bytes()), digest, f"component raw digest {name}")

    workflow = yaml.safe_load((HERE / COMPONENT_DIGESTS["candidateWorkflow"][0]).read_text())
    _expect(workflow["on"], {"workflow_dispatch": None, "schedule": [{"cron": "17 3 * * *"}]}, "candidate triggers")
    _expect(workflow["permissions"], {"contents": "read", "packages": "read"}, "candidate permissions")
    _expect(len(workflow["jobs"]["observe"]["steps"]), 2, "candidate step count")
    checkout = workflow["jobs"]["observe"]["steps"][0]
    _expect(checkout["uses"], "actions/checkout@11d5960a326750d5838078e36cf38b85af677262", "checkout pin")
    _expect(checkout["with"]["persist-credentials"], False, "checkout credential persistence")
    run_step = workflow["jobs"]["observe"]["steps"][1]
    _expect(set(run_step["env"]), {"GHCR_USERNAME", "GHCR_TOKEN"}, "runtime environment")
    for forbidden in ("issues: write", "packages: write", "delete", "curl", "docker push", "oras push"):
        if forbidden in (HERE / COMPONENT_DIGESTS["candidateWorkflow"][0]).read_text().lower():
            raise V1.HarnessError(f"GHCR observer candidate exposes forbidden operation: {forbidden}")

    contract = spec["workflowContract"]
    _expect((contract["futureDeploymentPathPresent"], contract["activeIndexPresent"], contract["packageMutationPermissionPresent"], contract["issueOrWebhookPermissionPresent"]), (False, False, False, False), "inert workflow boundary")
    _expect(contract["permissions"], {"contents": "read", "packages": "read"}, "bound permissions")
    _expect(contract["actions"], [{"repository": "actions/checkout", "fullCommitSHA": "11d5960a326750d5838078e36cf38b85af677262", "observedRef": "refs/tags/v4", "observedAt": "2026-08-10"}], "action pin observation")
    if (REPO / contract["futureDeploymentPath"]).exists():
        raise V1.HarnessError("GHCR observer candidate is unexpectedly deployed")
    if (REPO / contract["activeIndexPath"]).exists():
        raise V1.HarnessError("GHCR observer authoritative active index unexpectedly exists")

    evaluator = spec["evaluatorContract"]
    _expect((evaluator["authoritativeRepository"], evaluator["authoritativeIdentity"], evaluator["registryOperation"], evaluator["registryScope"], evaluator["trustedTokenRealm"], evaluator["successOutcome"], evaluator["failureExitCode"], evaluator["mutationOperationsExposed"]), ("ghcr.io/openkubes/ok141-evidence", "OCI-MANIFEST-DIGEST", "HEAD-MANIFEST-BY-DIGEST", "repository:openkubes/ok141-evidence:pull", "https://ghcr.io/token", "OBSERVED-PRESENT", 2, []), "evaluator boundary")
    _expect(spec["proof"], {"offlineTestsPassed": 9, "liveRegistryCallPerformed": False, "workflowDeployed": False, "scheduleCreated": False, "packageReadAccessProven": False, "failedRunAlertProven": False, "missedRunDetectionProven": False}, "proof")
    _expect(len(spec["remainingBlockers"]), 7, "remaining blocker count")

    authorization = spec["authorization"]
    _expect(authorization["decision"], "NO-GO", "authorization decision")
    for field in authorization:
        if field != "decision":
            _expect(authorization[field], False, f"authorization {field}")
    _expect(spec["summary"], {"evaluatorImplementedOffline": True, "inertWorkflowCandidatePresent": True, "activeWorkflowPresent": False, "activeIndexPresent": False, "liveReadProven": False, "installationGatesGranted": 0}, "summary")

    rules = " ".join(spec["rules"]).lower()
    for phrase in ("is inert", "missing active index is intentional", "not ghcr access", "no restore repair republish", "requires a separate reviewed mutation gate", "remain no-go"):
        if phrase not in rules:
            raise V1.HarnessError(f"GHCR observer prototype safety rule missing: {phrase}")
    return V1.sha256_bytes(manifest_path.read_bytes())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--digest-file", type=Path)
    args = parser.parse_args()
    try:
        path = args.manifest.resolve()
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
