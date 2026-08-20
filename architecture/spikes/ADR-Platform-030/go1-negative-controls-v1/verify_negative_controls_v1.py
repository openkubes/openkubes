#!/usr/bin/env python3
"""Fail-closed verifier for the OK-141 non-destructive negative-control candidate."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
CANDIDATE = ROOT / "negative-controls-v1.json"
SHA = re.compile(r"^sha256:[0-9a-f]{64}$")

EXPECTED_STAGES = [
    "provider-prerequisites",
    "cluster-lifecycle",
    "lifecycle-observation",
    "enablement",
    "network-observation",
    "runtime-binding",
    "target-access",
    "target-credential",
    "target-registration",
    "platform-applications",
    "platform-observation",
    "aggregate-evidence",
]

EXPECTED_CONTROLS = {
    "AUTHORIZATION-DENIED",
    "STALE-GENERATION-EVIDENCE",
    "DUPLICATE-SUBMISSION-IDEMPOTENCY",
    "EXECUTOR-RESTART-RECEIPT-RESUME",
    "WRONG-R-E-P-CORRELATION",
}

EXPECTED_ALLOWED = {
    "EXACT_GET_BEFORE",
    "LOCAL_REJECTION",
    "LOCAL_TERMINAL_REPLAY",
    "EXACT_GET_AFTER",
    "READ_ONLY_HEALTH_CHECK",
}

EXPECTED_FORBIDDEN = {
    "CREATE",
    "UPDATE",
    "PATCH",
    "APPLY",
    "REPLACE",
    "DELETE",
    "POD_EXEC",
    "LOG_READ",
    "SECRET_CONTENT_READ",
    "FAILURE_INJECTION",
}


class VerificationError(ValueError):
    pass


def canonical_digest(value: dict) -> str:
    material = copy.deepcopy(value)
    material.pop("candidateDigest", None)
    raw = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def verify(value: dict) -> str:
    require(value.get("format") == "ok141-nondestructive-negative-controls/v1", "wrong format")
    require(value.get("state") == "OFFLINE-PROVEN-LIVE-NO-WRITE-CLOSURE-PENDING", "wrong state")

    bindings = value.get("bindings", {})
    require(set(bindings) == {"R", "E", "P", "fixtureDigest", "planDigest", "planArtifactDigest"}, "wrong bindings")
    require(all(SHA.fullmatch(item or "") for item in bindings.values()), "invalid binding digest")

    implementation = value.get("implementation", {})
    require(re.fullmatch(r"[0-9a-f]{40}", implementation.get("okClusterCommit", "")) is not None, "invalid source commit")
    require(SHA.fullmatch(implementation.get("runnerBinaryDigest", "")) is not None, "invalid runner digest")
    require(implementation.get("targetedTestCount") == 15, "wrong targeted test count")
    require(implementation.get("targetedTestResult") == "PASS", "offline tests are not PASS")

    resume = value.get("resumeProof", {})
    require(resume.get("state") == "COMPLETED", "resume is not terminal complete")
    require(resume.get("completedStages") == 12, "resume stage count differs")
    require(resume.get("requiresAuthorization") is False, "terminal replay requests authorization")
    require(resume.get("mutationAllowed") is False, "terminal replay permits mutation")
    require(SHA.fullmatch(resume.get("evidenceDigest", "")) is not None, "invalid resume evidence digest")

    receipts = value.get("receiptPrefix", [])
    require([item.get("stage") for item in receipts] == EXPECTED_STAGES, "receipt prefix is incomplete or reordered")
    require(all(SHA.fullmatch(item.get("digest", "")) for item in receipts), "invalid receipt digest")
    require(len({item["digest"] for item in receipts}) == 12, "receipt digest reused")

    controls = value.get("controls", [])
    require({item.get("id") for item in controls} == EXPECTED_CONTROLS, "negative control set differs")
    require(all(str(item.get("result", "")).startswith("PASS") for item in controls), "negative control is not PASS")

    boundary = value.get("liveBoundary", {})
    require(boundary.get("mutationAllowed") is False, "live mutation allowed")
    require(boundary.get("clusterContactByNegativeOperation") is False, "negative operation contacts cluster")
    require(boundary.get("projectedObjectCount") == 11, "projected object count differs")
    require(set(boundary.get("allowedOperations", [])) == EXPECTED_ALLOWED, "allowed operation set differs")
    require(set(boundary.get("forbiddenOperations", [])) == EXPECTED_FORBIDDEN, "forbidden operation set differs")

    actual = canonical_digest(value)
    require(value.get("candidateDigest") == actual, "candidate digest mismatch")
    return actual


def main() -> int:
    try:
        value = json.loads(CANDIDATE.read_text())
        print(verify(value))
        return 0
    except (OSError, json.JSONDecodeError, VerificationError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
