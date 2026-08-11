#!/usr/bin/env python3
"""Fail-closed verifier for the non-executing OK-141 P1 retry protocol."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[3]
RECORD = ROOT / "p1-retry-v1.yaml"
WORKFLOW = REPO / ".github/workflows/ok141-evidence-publisher.yaml"
WORKFLOW_DIGEST = "sha256:6837271e8929eac133d1f5f6fb1bbaba3b83f61a772f27a856b51e79d673a27b"
ORIGINAL_PROTOCOL = "sha256:c3db4493e52c07425f323e22d10c572bd1320295c10f3a001bcc4852b67cbc29"


spec = yaml.safe_load(RECORD.read_text())["spec"]
if spec["state"] != "READY-FOR-P1-DECISION-NO-GO":
    raise SystemExit("wrong protocol state")
actual = "sha256:" + hashlib.sha256(WORKFLOW.read_bytes()).hexdigest()
if actual != WORKFLOW_DIGEST or spec["publisher"]["workflowDigest"] != WORKFLOW_DIGEST:
    raise SystemExit("publisher workflow digest mismatch")
if spec["source"]["publisherInputProtocolDigest"] != ORIGINAL_PROTOCOL:
    raise SystemExit("immutable source bundle protocol binding changed")
if spec["scope"]["maximumPublisherRuns"] != 1:
    raise SystemExit("retry run cap must be exactly one")
if spec["scope"]["maximumGHCRArtifacts"] != 1 or spec["scope"]["maximumAttestations"] != 1:
    raise SystemExit("publication object caps must be exactly one")
if spec["scope"]["clusterAccess"] or spec["scope"]["clusterCredential"] or spec["scope"]["infrastructureMutation"]:
    raise SystemExit("cluster and infrastructure access must remain false")

correlation = spec["authorizationCorrelation"]
if correlation["bundleProtocolDigestCarriedByWorkflow"] is not True:
    raise SystemExit("bundle protocol must be enforced in workflow")
if correlation["p1ProtocolDigestCarriedByWorkflow"] is not False:
    raise SystemExit("P1 carrier boundary must remain explicit")
if correlation["finalEvidenceMustRetainBothDigests"] is not True:
    raise SystemExit("both protocol identities must be retained")

for key, value in spec["authorization"].items():
    if key == "decision":
        if value != "NO-GO":
            raise SystemExit("decision must remain NO-GO")
    elif value is not False:
        raise SystemExit(f"{key} must remain false")

for value in (
    spec["source"]["bundleDigest"],
    spec["source"]["publisherInputProtocolDigest"],
    spec["publisher"]["workflowDigest"],
):
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
        raise SystemExit("invalid digest")

print("PASS: P1 retry is exact, bounded, correlated and not authorized")
