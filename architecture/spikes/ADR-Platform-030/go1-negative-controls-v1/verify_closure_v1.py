#!/usr/bin/env python3
"""Verify the redacted OK-141 non-destructive negative-control closure."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import sys
from pathlib import Path

from verify_negative_controls_v1 import CANDIDATE, verify


ROOT = Path(__file__).resolve().parent
CLOSURE = ROOT / "closure-v1.json"
SHA = re.compile(r"^sha256:[0-9a-f]{64}$")


class ClosureVerificationError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ClosureVerificationError(message)


def evidence_digest(value: dict) -> str:
    material = copy.deepcopy(value)
    material.pop("evidenceDigest", None)
    raw = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def verify_closure(value: dict, candidate: dict) -> str:
    candidate_digest = verify(candidate)
    require(value.get("format") == "ok141-nondestructive-negative-controls-closure/v1", "wrong closure format")
    require(value.get("candidateDigest") == candidate_digest, "candidate binding differs")
    require(value.get("state") == "PASS", "closure is not PASS")
    require(value.get("projectedObjectCount") == 11, "projected object count differs")
    require(value.get("snapshotsEqual") is True, "snapshots are not equal")
    require(value.get("beforeSnapshotDigest") == value.get("afterSnapshotDigest"), "snapshot digests differ")
    require(SHA.fullmatch(value.get("beforeSnapshotDigest", "")) is not None, "snapshot digest invalid")
    require(value.get("clusterMutationPerformed") is False, "cluster mutation reported")
    require(value.get("credentialContentRetained") is False, "credential content retained")

    replay = value.get("terminalReplay", {})
    require(replay.get("wrongRRejected") is True, "wrong R was not rejected")
    require(replay.get("state") == "COMPLETED", "terminal replay not completed")
    require(replay.get("completedStages") == 12, "terminal replay stage count differs")
    require(replay.get("requiresAuthorization") is False, "terminal replay requests authorization")
    require(replay.get("mutationAllowed") is False, "terminal replay allows mutation")
    require(SHA.fullmatch(replay.get("decisionDigest", "")) is not None, "decision digest invalid")

    health = value.get("health", {})
    require(health.get("nodesReady") == health.get("nodesExpected") == 2, "Nodes not Ready")
    require(health.get("ciliumReady") == health.get("ciliumDesired") == 2, "Cilium not Ready")
    require(health.get("operatorAvailable", 0) >= 1, "Cilium operator unavailable")
    require(health.get("storageClassPresent") is True, "StorageClass missing")

    actual = evidence_digest(value)
    require(value.get("evidenceDigest") == actual, "evidence digest mismatch")
    return actual


def main() -> int:
    try:
        candidate = json.loads(CANDIDATE.read_text())
        closure = json.loads(CLOSURE.read_text())
        print(verify_closure(closure, candidate))
        return 0
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
