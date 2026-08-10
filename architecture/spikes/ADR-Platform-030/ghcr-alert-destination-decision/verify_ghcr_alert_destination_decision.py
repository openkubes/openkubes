#!/usr/bin/env python3
"""Fail-closed verifier for the OK-141 GHCR alert-destination decision."""

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


MONITORING = _load(
    "ok141_alert_source_monitoring",
    SPIKE / "ghcr-deletion-monitoring-decision" / "verify_ghcr_deletion_monitoring_decision.py",
)
V1 = MONITORING.V1
SOURCE_DIGEST = "sha256:95230100078e0159d3f8a5c7a8abbeb349b4a87705fd420dcfb7dfa98e0aa1c6"


def _expect(actual: Any, expected: Any, claim: str) -> None:
    if actual != expected:
        raise V1.HarnessError(f"GHCR alert-destination decision {claim} mismatch")


def validate(document: dict[str, Any], decision_path: Path) -> str:
    schema = json.loads((HERE / "ghcr-alert-destination-decision-v1.schema.json").read_text())
    V1.normalize(document, schema)
    spec = document["spec"]
    _expect(spec["state"], "ACCEPTED-DESTINATION-IMPLEMENTATION-BLOCKED-NO-GO", "state")

    source = spec["sourceMonitoringDecision"]
    source_path = (decision_path.parent / source["path"]).resolve()
    if SPIKE.resolve() not in source_path.parents or not source_path.is_file():
        raise V1.HarnessError("GHCR alert source is missing or outside spike")
    _expect(source, {"path": "../ghcr-deletion-monitoring-decision/ghcr-deletion-monitoring-decision-v1.yaml", "digest": SOURCE_DIGEST, "state": "ACCEPTED-INTERVAL-IMPLEMENTATION-BLOCKED-NO-GO"}, "source")
    _expect(V1.sha256_bytes(source_path.read_bytes()), SOURCE_DIGEST, "source raw digest")
    MONITORING.validate(V1.read_yaml_or_json(source_path), source_path)

    _expect(
        spec["decision"],
        {
            "outcome": "ACCEPTED",
            "acceptedBy": "github:arashkaffamanesh",
            "acceptanceInput": "fine, weiter bitte.",
            "interpretedDecision": "Use a failed GitHub Actions run and its job summary as the DEV alert surface without an additional write-capable alert integration.",
            "scope": "OK-141-DEV-EVIDENCE-ALERT-DESTINATION",
        },
        "accepted decision",
    )

    _expect(
        spec["alertPolicy"],
        {
            "platform": "GitHub-Actions",
            "repository": "openkubes/openkubes",
            "primarySignal": "FAILED-WORKFLOW-RUN",
            "detailSurface": "GITHUB-ACTIONS-JOB-SUMMARY",
            "accountableRecipient": "github:arashkaffamanesh",
            "observerStartedRunFailureCoverage": True,
            "missedOrNeverStartedRunCoverage": False,
            "notificationDeliveryGuaranteed": False,
            "acknowledgementRequired": False,
            "issueCreationAllowed": False,
            "pullRequestCreationAllowed": False,
            "externalWebhookAllowed": False,
            "emailIntegrationClaimAllowed": False,
            "packageWritePermissionAllowed": False,
            "packageDeletePermissionAllowed": False,
            "additionalAPIMutationRequired": False,
            "boundary": "A failed started run is the alert surface; the same workflow cannot prove or alert on a scheduled run that never started.",
        },
        "alert policy",
    )
    _expect(spec["requiredJobSummaryFields"], ["observationStatus", "intendedObservationTimeUTC", "actualStartTimeUTC", "actualCompletionTimeUTC", "ociManifestDigest", "repository", "workflowSourceRevision", "remediationAuthority"], "job summary fields")
    _expect(
        spec["failClosedOutcomes"],
        {
            "digestMissing": "FAILED-RUN",
            "digestMismatch": "FAILED-RUN",
            "packageReadDenied": "FAILED-RUN",
            "evidenceUnverifiable": "FAILED-RUN",
            "observerStartedThenFailed": "FAILED-RUN",
            "observerLateOrNeverStarted": "UNKNOWN-REQUIRES-INDEPENDENT-FRESHNESS-EVALUATION",
        },
        "fail-closed outcomes",
    )
    _expect(
        spec["operationalState"],
        {"observerWorkflowImplemented": False, "observerWorkflowDeployed": False, "jobSummaryImplemented": False, "failedRunAlertProven": False, "recipientObservationProven": False, "missedRunDetectionImplemented": False, "packageReadAccessProven": False},
        "operational state",
    )
    _expect(len(spec["remainingBlockers"]), 8, "remaining blocker count")

    authorization = spec["authorization"]
    _expect(authorization["decision"], "NO-GO", "authorization decision")
    for field in authorization:
        if field != "decision":
            _expect(authorization[field], False, f"authorization {field}")
    _expect(spec["summary"], {"alertDestinationSelected": True, "additionalWriteIntegrationSelected": False, "notificationGuaranteed": False, "missedRunDetectionSolved": False, "implementationProven": False, "installationGatesGranted": 0}, "summary")

    rules = " ".join(spec["rules"]).lower()
    for phrase in (
        "creates no workflow schedule notification issue webhook credential or package",
        "not guaranteed human notification delivery",
        "cannot report its own absence",
        "may not repair restore republish write or delete packages",
        "requires a separate explicit decision and mutation gate",
        "remain no-go",
    ):
        if phrase not in rules:
            raise V1.HarnessError(f"GHCR alert safety rule missing: {phrase}")
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
