#!/usr/bin/env python3
"""Fail-closed verifier for the OK-141 GHCR deletion-monitoring interval decision."""

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


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


RETENTION = _load(
    "ok141_monitoring_source_retention",
    SPIKE / "ghcr-retention-decision" / "verify_ghcr_retention_decision.py",
)
V1 = RETENTION.V1
SOURCE_DIGEST = "sha256:b314ee48ad88337b7340f20daef606305b3bc16d70db7b6367e30e3d9477e40b"


def _expect(actual: Any, expected: Any, claim: str) -> None:
    if actual != expected:
        raise V1.HarnessError(f"GHCR deletion-monitoring decision {claim} mismatch")


def validate(document: dict[str, Any], decision_path: Path) -> str:
    schema = json.loads((HERE / "ghcr-deletion-monitoring-decision-v1.schema.json").read_text())
    V1.normalize(document, schema)
    spec = document["spec"]
    _expect(spec["state"], "ACCEPTED-INTERVAL-IMPLEMENTATION-BLOCKED-NO-GO", "state")

    source = spec["sourceRetentionDecision"]
    source_path = (decision_path.parent / source["path"]).resolve()
    if SPIKE.resolve() not in source_path.parents or not source_path.is_file():
        raise V1.HarnessError("GHCR monitoring source is missing or outside spike")
    _expect(source, {"path": "../ghcr-retention-decision/ghcr-retention-decision-v1.yaml", "digest": SOURCE_DIGEST, "state": "ACCEPTED-POLICY-IMPLEMENTATION-BLOCKED-NO-GO"}, "source")
    _expect(V1.sha256_bytes(source_path.read_bytes()), SOURCE_DIGEST, "source raw digest")
    RETENTION.validate(V1.read_yaml_or_json(source_path), source_path)

    _expect(
        spec["decision"],
        {
            "outcome": "ACCEPTED",
            "acceptedBy": "github:arashkaffamanesh",
            "acceptanceInput": "fine, bitte weiter",
            "interpretedDecision": "Use a 24-hour target interval for DEV deletion monitoring with alert-and-fail-closed behavior and no mutation authority.",
            "scope": "OK-141-DEV-EVIDENCE-DELETION-MONITORING",
        },
        "accepted decision",
    )

    policy = spec["monitoringPolicy"]
    _expect(
        policy,
        {
            "targetInterval": "PT24H",
            "intervalHours": 24,
            "lookupRepository": "ghcr.io/openkubes/ok141-evidence",
            "lookupIdentity": "OCI-MANIFEST-DIGEST",
            "expectedOutcomeWhenPresent": "OBSERVED-PRESENT",
            "outcomeWhenMissing": "ALERT-AND-FAIL-CLOSED",
            "outcomeWhenObserverLateOrUnavailable": "UNKNOWN-AND-FAIL-CLOSED",
            "maximumDetectionLatencyClaim": "BEST-EFFORT-APPROXIMATELY-24H",
            "detectionDeadlineGuaranteed": False,
            "continuousAvailabilityGuaranteed": False,
            "automaticRepairAllowed": False,
            "automaticRestoreAllowed": False,
            "automaticRepublishAllowed": False,
            "deletePermissionAllowed": False,
            "packageWritePermissionAllowed": False,
            "boundary": "The interval is a DEV observation target; delayed skipped or unavailable observations cannot establish continued evidence availability.",
        },
        "monitoring policy",
    )
    _expect(len(spec["evidenceRequirements"]), 6, "evidence requirement count")

    _expect(
        spec["operationalState"],
        {
            "monitoringWorkflowImplemented": False,
            "monitoringWorkflowDeployed": False,
            "scheduleConfigured": False,
            "packageReadAccessProven": False,
            "alertDestinationSelected": False,
            "alertDeliveryProven": False,
            "firstObservationCompleted": False,
            "missedRunDetectionProven": False,
        },
        "operational state",
    )
    _expect(len(spec["remainingBlockers"]), 8, "remaining blocker count")

    authorization = spec["authorization"]
    _expect(authorization["decision"], "NO-GO", "authorization decision")
    for field in (
        "workflowImplementationAuthorized",
        "workflowDeploymentAuthorized",
        "scheduleCreationAuthorized",
        "packageReadCredentialAuthorized",
        "packageWriteAuthorized",
        "packageDeleteAuthorized",
        "alertIntegrationMutationAuthorized",
        "externalWriteAuthorized",
        "infrastructureMutationAuthorized",
        "m0aInstallationGranted",
        "m0bInstallationGranted",
        "go1Granted",
    ):
        _expect(authorization[field], False, f"authorization {field}")

    _expect(spec["summary"], {"intervalDecisionAccepted": True, "targetIntervalHours": 24, "detectionGuaranteed": False, "monitoringImplemented": False, "alertDestinationSelected": False, "installationGatesGranted": 0}, "summary")
    rules = " ".join(spec["rules"]).lower()
    for phrase in (
        "creates no observer schedule workflow credential or alert integration",
        "not a guaranteed deletion-detection deadline",
        "produce unknown and fail closed",
        "may not restore repair republish write or delete packages",
        "requires a new explicit decision",
        "remain no-go",
    ):
        if phrase not in rules:
            raise V1.HarnessError(f"GHCR monitoring safety rule missing: {phrase}")
    return V1.sha256_bytes(decision_path.read_bytes())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--decision", type=Path, required=True)
    parser.add_argument("--digest-file", type=Path)
    args = parser.parse_args()
    try:
        path = args.decision.resolve()
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
