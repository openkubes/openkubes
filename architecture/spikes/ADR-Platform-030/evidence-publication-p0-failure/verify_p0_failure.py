#!/usr/bin/env python3
"""Fail-closed verifier for the redacted OK-141 P0 failure checkpoint."""

from __future__ import annotations

import hashlib
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[3]
RECORD = ROOT / "p0-failure-v1.yaml"
WORKFLOW = REPO / ".github/workflows/ok141-evidence-publisher.yaml"

BASE_DIGEST = "sha256:3de106067f2fdb70add382c1fa63a2749e032dda9f83442f9880d6e672a3aab2"
CANDIDATE_DIGEST = "sha256:6837271e8929eac133d1f5f6fb1bbaba3b83f61a772f27a856b51e79d673a27b"


def digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


record = yaml.safe_load(RECORD.read_text())
spec = record["spec"]
require(spec["state"] == "P0-ATTEMPTED-FAILED-CLOSED-NO-RETRY", "wrong state")
require(spec["publisher"]["runID"] == 31517187028, "wrong publisher run")
require(spec["publisher"]["conclusion"] == "failure", "run must be failed")
require(spec["observations"]["packageObservedAfterRun"] is False, "package claim must be false")
require(spec["observations"]["infrastructureMutation"] is False, "infrastructure mutation forbidden")
require(spec["observations"]["clusterAccess"] is False, "cluster access forbidden")

gate = spec["gate"]
require(gate["originalMaximumActionsRuns"] == 2, "wrong original run cap")
require(gate["consumedActionsRuns"] == 2, "wrong consumed run count")
require(gate["retryAuthorized"] is False, "retry must not be authorized")
require(gate["amendmentDeploymentAuthorized"] is False, "deployment must not be authorized")
require(gate["packageCreated"] is False, "package must not be claimed")
require(gate["attestationCreated"] is False, "attestation must not be claimed")
require(gate["p0Complete"] is False, "P0 must not be complete")
require(gate["go1Granted"] is False, "GO-1 must remain false")

source = WORKFLOW.read_text()
require(digest(source.encode()) == BASE_DIGEST, "active workflow is not the observed v3 source")

login_and_push = (
    "          printf '%s' \"$GHCR_TOKEN\" | \"$RUNNER_TEMP/oras\" login ghcr.io "
    "--username \"$GHCR_USERNAME\" --password-stdin\n"
    "          \"$RUNNER_TEMP/oras\" push \\\n"
)
relative_workdir = login_and_push.replace(
    "          \"$RUNNER_TEMP/oras\" push \\\n",
    "          cd \"$RUNNER_TEMP\"\n          \"$RUNNER_TEMP/oras\" push \\\n",
)
absolute_layer = (
    "            \"$RUNNER_TEMP/evidence-bundle.tar:"
    "application/vnd.openkubes.ok141.evidence.bundle.v1+tar\" \\\n"
)
relative_layer = absolute_layer.replace("$RUNNER_TEMP/", "")
require(source.count(login_and_push) == 1, "push insertion point must be unique")
require(source.count(absolute_layer) == 1, "absolute layer path must be unique")
candidate = source.replace(login_and_push, relative_workdir).replace(absolute_layer, relative_layer)
require(digest(candidate.encode()) == CANDIDATE_DIGEST, "candidate digest mismatch")
require(spec["amendmentCandidate"]["candidateWorkflowDigest"] == CANDIDATE_DIGEST, "recorded candidate mismatch")

print("PASS: P0 failure is fail-closed and the relative-path amendment is exact and inert")
