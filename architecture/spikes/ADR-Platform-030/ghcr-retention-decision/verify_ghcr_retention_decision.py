#!/usr/bin/env python3
"""Fail-closed verifier for the accepted OK-141 DEV retention decision."""

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


PREFLIGHT = _load(
    "ok141_retention_source_preflight",
    SPIKE / "ghcr-observer-preflight" / "verify_ghcr_observer_preflight.py",
)
V1 = PREFLIGHT.V1
SOURCE_DIGEST = "sha256:ca3a11f82458c5668440c1a55db7caf69728779aad5298d9f18751e3b7ca4344"
DECISION_STATEMENT = (
    "Ich akzeptiere für OK-141 das 90-tägige "
    "DEV-BEST-EFFORT-NON-WORM-Retention-Modell mit den dokumentierten "
    "Lösch- und Verfügbarkeitsgrenzen."
)


def _expect(actual: Any, expected: Any, claim: str) -> None:
    if actual != expected:
        raise V1.HarnessError(f"GHCR retention decision {claim} mismatch")


def validate(document: dict[str, Any], decision_path: Path) -> str:
    schema = json.loads((HERE / "ghcr-retention-decision-v1.schema.json").read_text())
    V1.normalize(document, schema)
    spec = document["spec"]
    _expect(spec["state"], "ACCEPTED-POLICY-IMPLEMENTATION-BLOCKED-NO-GO", "state")

    source = spec["sourcePreflight"]
    source_path = (decision_path.parent / source["path"]).resolve()
    if SPIKE.resolve() not in source_path.parents or not source_path.is_file():
        raise V1.HarnessError("GHCR retention source is missing or outside spike")
    _expect(source, {"path": "../ghcr-observer-preflight/ghcr-observer-preflight-v1.yaml", "digest": SOURCE_DIGEST, "state": "OBSERVED-BLOCKED-NO-GO"}, "source")
    _expect(V1.sha256_bytes(source_path.read_bytes()), SOURCE_DIGEST, "source raw digest")
    PREFLIGHT.validate(V1.read_yaml_or_json(source_path), source_path)

    decision = spec["decision"]
    _expect(
        decision,
        {
            "outcome": "ACCEPTED",
            "acceptedBy": "github:arashkaffamanesh",
            "statement": DECISION_STATEMENT,
            "scope": "OK-141-DEV-EVIDENCE-ONLY",
        },
        "accepted decision",
    )

    policy = spec["retentionPolicy"]
    _expect((policy["model"], policy["minimumRetentionDaysAfterOK141Closure"], policy["retentionAnchor"], policy["retentionAnchorStatus"]), ("DEV-BEST-EFFORT-NON-WORM", 90, "OK141-CLOSURE-TIMESTAMP", "NOT-YET-AVAILABLE"), "retention basis")
    _expect(policy["primaryCopy"], {"type": "GHCR-OCI-ARTIFACT", "repository": "ghcr.io/openkubes/ok141-evidence", "identity": "OCI-MANIFEST-DIGEST"}, "primary copy")
    _expect(
        policy["secondaryIndex"],
        {
            "type": "REVIEWED-GIT-COMMIT",
            "repository": "openkubes/openkubes",
            "retainedFields": ["internalBundleDigest", "ociManifestDigest", "attestationSubjectDigest", "attestationSignerIdentity", "workflowRunURL"],
            "fullEvidencePayloadRetained": False,
        },
        "secondary index",
    )
    _expect(
        (
            policy["integrityClaim"],
            policy["availabilityClaim"],
            policy["immutabilityClaim"],
            policy["administratorDeletionPossible"],
            policy["conditionalRestoreWindowDays"],
            policy["restoreGuaranteed"],
            policy["productionRetentionClaimAllowed"],
            policy["disasterRecoveryClaimAllowed"],
        ),
        ("CONTENT-INTEGRITY-VERIFIABLE-BY-DIGEST", "BEST-EFFORT-NOT-GUARANTEED", "NOT-WORM", True, 30, False, False, False),
        "claim boundaries",
    )

    monitoring = spec["deletionMonitoring"]
    _expect(
        (
            monitoring["required"],
            monitoring["status"],
            monitoring["observer"],
            monitoring["lookupIdentity"],
            monitoring["interval"],
            monitoring["onMissing"],
            monitoring["automaticRepairAllowed"],
            monitoring["automaticRepublishAllowed"],
            monitoring["deletePermissionAllowed"],
        ),
        (True, "NOT-IMPLEMENTED", "ok-141-evidence-observer", "OCI-MANIFEST-DIGEST", "UNDECIDED", "ALERT-AND-FAIL-CLOSED", False, False, False),
        "deletion monitoring",
    )
    for phrase in ("neither restores nor republishes", "no package mutation authority"):
        if phrase not in monitoring["boundary"]:
            raise V1.HarnessError(f"GHCR retention monitoring boundary missing: {phrase}")

    expiry = spec["expirySemantics"]
    _expect(
        expiry,
        {
            "calculation": "closure timestamp plus 90 complete 24-hour periods",
            "earlyDeletionAllowed": False,
            "deletionAtExpiryRequired": False,
            "extensionAllowedWithoutNewGate": True,
            "shorteningRequiresNewDecision": True,
            "boundary": "The policy defines a minimum not a mandatory deletion date.",
        },
        "expiry semantics",
    )

    operational = spec["operationalState"]
    expected_operational = {
        "packageExists": False,
        "packageReadAccessProven": False,
        "publishEnvironmentExists": False,
        "observerWorkflowDeployed": False,
        "deletionMonitoringDeployed": False,
        "publicationCredentialAuthorized": False,
        "firstPublishPullbackProven": False,
        "currentClockEvidenceReusable": False,
    }
    _expect(operational, expected_operational, "operational state")
    _expect(len(spec["remainingBlockers"]), 8, "remaining blocker count")

    authorization = spec["authorization"]
    _expect(authorization["decision"], "NO-GO", "authorization decision")
    for field in (
        "externalWriteAuthorized",
        "packageCreationAuthorized",
        "environmentCreationAuthorized",
        "workflowDeploymentAuthorized",
        "credentialMutationAuthorized",
        "infrastructureMutationAuthorized",
        "m0aInstallationGranted",
        "m0bInstallationGranted",
        "go1Granted",
    ):
        _expect(authorization[field], False, f"authorization {field}")

    _expect(
        spec["summary"],
        {
            "retentionDecisionAccepted": True,
            "minimumRetentionDays": 90,
            "wormClaimAllowed": False,
            "availabilityGuaranteed": False,
            "monitoringImplemented": False,
            "installationGatesGranted": 0,
        },
        "summary",
    )

    rules = " ".join(spec["rules"]).lower()
    for phrase in (
        "does not prove or create its implementation",
        "minimum retention period",
        "no worm availability production retention or disaster recovery guarantee",
        "may not delete restore republish or mutate packages",
        "requires a new explicit decision",
        "remain no-go",
    ):
        if phrase not in rules:
            raise V1.HarnessError(f"GHCR retention safety rule missing: {phrase}")
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
