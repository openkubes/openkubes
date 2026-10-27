#!/usr/bin/env python3
"""Fail-closed verifier for the public OK-141 happy-run closure."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
CLOSURE = HERE / "capability-runtime-closure-v2.json"
CANDIDATE = HERE / "capability-runtime-candidate-v2.json"
AMENDMENT = HERE.parent / "go1-capability-name-boundary-amendment-v1/capability-name-boundary-amendment-v1.json"


def digest_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def semantic_digest(value) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def expect(actual, expected, claim: str) -> None:
    if actual != expected:
        raise RuntimeError(f"{claim} mismatch")


def main() -> None:
    document = json.loads(CLOSURE.read_text())
    expect(document["kind"], "OK141CapabilityRuntimeClosure", "kind")
    spec = document["spec"]
    expect(spec["state"], "PASS-HAPPY-RUN", "state")
    expect(digest_file(AMENDMENT), spec["identityAmendment"]["offlineAmendmentDigest"], "offline amendment")
    candidate = json.loads(CANDIDATE.read_text())
    expect(digest_file(CANDIDATE), spec["capabilityExecution"]["candidateDigest"], "candidate digest")
    expect(candidate["spec"]["identities"], {
        key: spec["identities"][key] for key in ("P", "R", "FixtureDigest")
    }, "candidate identities")
    expect(candidate["spec"]["sourceRevision"], spec["identities"]["sourceRevision"], "source revision")
    expect(candidate["spec"]["capability"]["scriptDigest"], spec["identities"]["capabilityScriptDigest"], "script digest")
    expect(spec["capabilityExecution"]["state"], "PASS-CAPABILITY", "capability state")
    expect(spec["capabilityExecution"]["exitCode"], 0, "capability exit")
    expect(set(spec["capabilityExecution"]["applications"].values()), {"Synced/Healthy/current-revision"}, "Application convergence")
    expect({
        spec["cleanupObservation"][key]
        for key in ("deployment", "service", "serviceMonitor", "logEmitterPod")
    }, {"ABSENT"}, "synthetic resource cleanup")
    expect(spec["architectureResult"]["requiresOpenKubesReconciler"], "none proven", "reconciler result")
    expect(spec["remainingGates"]["failureInjection"], "NO-GO", "failure gate")
    for forbidden in (
        "privateEvidencePublished",
        "rawCapabilityOutputPublished",
        "secretOrKubeconfigBytesPublished",
        "apiEndpointsPublished",
        "uidOrResourceVersionPublished",
    ):
        expect(spec["retention"][forbidden], False, forbidden)
    without_digest = copy.deepcopy(spec)
    declared = without_digest.pop("closureDigest")
    expect(semantic_digest(without_digest), declared, "closure digest")
    print(json.dumps({"state": "PASS", "closureDigest": declared}, sort_keys=True))


if __name__ == "__main__":
    main()
