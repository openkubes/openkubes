#!/usr/bin/env python3
"""Offline verification for the blocked OK-141 Argo runtime refresh candidate."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
CANDIDATE = HERE / "argo-runtime-refresh-candidate-v1.yaml"


def sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def verify(path: Path = CANDIDATE) -> dict:
    value = yaml.safe_load(path.read_text())
    spec = value["spec"]
    predecessor = (HERE / spec["predecessor"]["path"]).resolve()
    closure = json.loads(predecessor.read_text())

    require(value["kind"] == "GO1ArgoRuntimeRefreshCandidate", "kind mismatch")
    require(spec["state"] == "BLOCKED-NO-GO", "candidate must remain blocked")
    require(spec["authorization"]["decision"] == "NO-GO", "authorization mismatch")
    require(not any(v for k, v in spec["authorization"].items() if k != "decision"), "candidate grants authority")
    require(sha(predecessor) == spec["predecessor"]["digest"], "predecessor digest mismatch")
    require(closure["conclusion"]["faultBoundary"] == spec["predecessor"]["faultBoundary"], "fault boundary mismatch")
    require(closure["conclusion"]["thirdSyncAuthorized"] is False, "third sync boundary mismatch")
    require(spec["shared"]["requiredConfig"] == {"resource.respectRBAC": "strict"}, "Argo config mismatch")
    require(spec["shared"]["requiredStatefulSet"] == {
        "replicas": 1,
        "readyReplicas": 1,
        "image": "quay.io/argoproj/argocd:v3.4.2",
    }, "StatefulSet boundary mismatch")

    operation = spec["operation"]
    require(operation["gracefulPodDelete"] is True and operation["force"] is False, "delete boundary mismatch")
    require(operation["uidAndResourceVersionPreconditions"] is True, "concurrency boundary missing")
    require(operation["replacementPollIntervalSeconds"] == 5 and operation["replacementMaximumIterations"] == 60, "replacement bound mismatch")
    require(operation["applicationPollIntervalSeconds"] == 15 and operation["applicationMaximumIterations"] == 40, "observation bound mismatch")
    require(operation["automaticReconciliationMayOccur"] is True, "implicit retry risk missing")
    require(operation["explicitApplicationOperationSubmission"] is False, "explicit sync must remain excluded")

    exclusions = set(spec["exclusions"])
    require({"force-delete", "application-change", "explicit-sync", "credential-read", "target-read", "rollback", "general-cleanup", "further-retry", "failure-injection"} <= exclusions, "exclusions incomplete")
    return {
        "state": "PASS-OFFLINE-BLOCKED-CANDIDATE",
        "candidateDigest": sha(path),
        "predecessorDigest": sha(predecessor),
        "liveMutationAuthorized": False,
    }


if __name__ == "__main__":
    print(json.dumps(verify(), sort_keys=True))
