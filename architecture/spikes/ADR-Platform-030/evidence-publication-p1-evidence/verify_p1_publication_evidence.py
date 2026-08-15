#!/usr/bin/env python3
"""Verify the redacted OK-141 P1 outcome without rewriting run history."""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parent
SPEC = yaml.safe_load((ROOT / "p1-publication-evidence-v1.yaml").read_text())["spec"]
RECEIPT = json.loads((ROOT / "publication-receipt-v2.json").read_text())
VERIFICATION = json.loads((ROOT / "publication-verification-v2.json").read_text())
DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")


def require(value: bool, message: str) -> None:
    if not value:
        raise SystemExit(message)


require(SPEC["state"] == "P1-OBJECTIVE-VERIFIED-WORKFLOW-FAILED-NO-RETRY", "wrong outcome state")
require(SPEC["run"]["conclusion"] == "failure", "run failure must remain explicit")
require(SPEC["run"]["failureClass"] == "GH-CLI-TOKEN-ENV-MISSING", "wrong failure class")

manifest = SPEC["publication"]["ociManifestDigest"]
require(DIGEST.fullmatch(manifest) is not None, "invalid OCI digest")
require(SPEC["attestation"]["verified"] is True, "attestation must be verified")
require(SPEC["attestation"]["subjectDigest"] == manifest, "attestation subject mismatch")
require(RECEIPT["ociManifestDigest"] == manifest, "receipt OCI mismatch")
require(RECEIPT["attestationSubjectDigest"] == manifest, "receipt attestation mismatch")

for field in ("transportDigest", "internalBundleDigest", "sourceCorrelationDigest"):
    require(DIGEST.fullmatch(SPEC["publication"][field]) is not None, f"invalid {field}")
    require(RECEIPT[field] == SPEC["publication"][field], f"receipt {field} mismatch")
    require(VERIFICATION[field] == SPEC["publication"][field], f"verification {field} mismatch")

require(RECEIPT["sourceRunId"] == "31516921145", "wrong source run")
require(VERIFICATION["sourceRunId"] == "31516921145", "wrong verified source run")
require(VERIFICATION["status"] == "VERIFIED-PULL-BACK-WITH-SOURCE-CORRELATION", "wrong verification status")
require(SPEC["authorization"]["p1ProtocolDigest"] == "sha256:4b215b1159ee07aa5a94b774f1487266f33e54e4353f1c1567bc27a4fb3edfdf", "wrong P1 protocol")

outcome = SPEC["outcome"]
require(outcome["publicationObjectiveVerified"] is True, "publication objective must be verified")
require(outcome["workflowHealthy"] is False, "workflow health must remain false")
require(outcome["p1RunBudgetConsumed"] is True, "P1 budget must be consumed")
for key in (
    "retryAuthorized",
    "packageRecreationAuthorized",
    "attestationRecreationAuthorized",
    "go1Granted",
    "infrastructureMutationAuthorized",
    "failureInjectionAuthorized",
):
    require(outcome[key] is False, f"{key} must remain false")

print("PASS: P1 publication objective verified; failed workflow conclusion and no-retry boundary preserved")
