#!/usr/bin/env python3
"""Verify the local, non-authorizing W1 publisher deployment record."""

from __future__ import annotations

import hashlib
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[3]
WORKFLOW = REPO / ".github/workflows/ok141-evidence-publisher.yaml"
RECORD = ROOT / "publisher-w1-evidence-v1.yaml"
EXPECTED = "sha256:6837271e8929eac133d1f5f6fb1bbaba3b83f61a772f27a856b51e79d673a27b"


spec = yaml.safe_load(RECORD.read_text())["spec"]
if spec["state"] != "W1-COMPLETE-OBSERVED-P1-NO-GO":
    raise SystemExit("wrong W1 state")
actual = "sha256:" + hashlib.sha256(WORKFLOW.read_bytes()).hexdigest()
if actual != EXPECTED or spec["deployment"]["workflowDigest"] != EXPECTED:
    raise SystemExit("active workflow digest mismatch")
if spec["deployment"]["workflowID"] != 332090718:
    raise SystemExit("workflow ID mismatch")
if spec["deployment"]["automaticRunObserved"] is not False:
    raise SystemExit("automatic run must not be claimed")

authorization = spec["authorization"]
if authorization["w1Complete"] is not True:
    raise SystemExit("W1 must be complete")
for key in (
    "publisherRetryAuthorized",
    "packageWriteAuthorized",
    "attestationWriteAuthorized",
    "go1Granted",
    "infrastructureMutationAuthorized",
    "failureInjectionAuthorized",
):
    if authorization[key] is not False:
        raise SystemExit(f"{key} must remain false")

print("PASS: W1 source is exact and active; no publisher retry is authorized")
