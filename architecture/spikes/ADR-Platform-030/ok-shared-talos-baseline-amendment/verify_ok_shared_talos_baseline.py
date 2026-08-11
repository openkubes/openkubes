#!/usr/bin/env python3
"""Fail-closed verifier for the read-only OK-141 ok-shared Talos amendment."""

from __future__ import annotations

import hashlib
from pathlib import Path

import yaml


HERE = Path(__file__).resolve().parent
RECORD = HERE / "ok-shared-talos-baseline-v1.yaml"
DIGEST = HERE / "ok-shared-talos-baseline-v1.sha256"


class VerificationError(RuntimeError):
    pass


def _expect(actual: object, expected: object, label: str) -> None:
    if actual != expected:
        raise VerificationError(f"{label}: expected {expected!r}, got {actual!r}")


def verify() -> str:
    raw = RECORD.read_bytes()
    expected_digest = DIGEST.read_text(encoding="utf-8").strip()
    actual_digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    _expect(actual_digest, expected_digest, "record digest")

    record = yaml.safe_load(raw)
    spec = record["spec"]
    _expect(spec["state"], "SOURCE-BOUND-READ-ONLY-LIVE-REFRESH-REQUIRED-NO-GO", "state")
    _expect(spec["source"]["jira"]["commentId"], "13556", "Jira evidence")
    _expect(spec["source"]["jira"]["independentlyReobservedByOk141"], False, "live observation boundary")
    _expect(len(spec["source"]["repository"]["files"]), 5, "bound source files")

    runtime = spec["reportedRuntime"]
    _expect(runtime["expectedExistingNodes"], 4, "node count")
    _expect(len(set(runtime["nodes"])), 4, "unique node identities")
    _expect(runtime["trust"]["configuredOnExistingNodes"], "REPORTED-4-OF-4", "trust report")
    _expect(runtime["resolution"]["addressClass"], "PRIVATE-DATACENTER-LOADBALANCER", "address class")
    _expect(runtime["acceptance"]["uncachedKubeletPull"], "REPORTED-PASS", "pull evidence")

    recovery = spec["recovery"]
    _expect(recovery["replacementMachineInheritance"], "ABSENT", "replacement inheritance")
    _expect(recovery["fromScratchBootstrap"], "TWO-PHASE-REGISTRY-THEN-TRUST", "rebuild sequence")
    for forbidden in ("automaticAdoptionClaimAllowed", "productionRecoveryClaimAllowed", "lifecycleContinuityClaimAllowed"):
        _expect(recovery[forbidden], False, forbidden)

    impact = spec["ok141Impact"]
    _expect(impact["partOfPlatformRevisionP"], False, "P boundary")
    _expect(impact["fixtureIdentityChanged"], False, "fixture boundary")
    _expect(impact["m0bLiveRefreshRequired"], True, "M0b refresh")
    _expect(impact["externalWorkloadClustersOnly"], True, "placement scope")
    _expect(impact["okSharedSelfManagementAllowed"], False, "self-management boundary")

    authorization = spec["authorization"]
    _expect(authorization["decision"], "NO-GO", "authorization")
    for grant in ("mutationAuthorized", "m0bInstallationGranted", "go1Granted", "failureInjectionGranted"):
        _expect(authorization[grant], False, grant)

    return actual_digest


if __name__ == "__main__":
    print(f"PASS {verify()}")
