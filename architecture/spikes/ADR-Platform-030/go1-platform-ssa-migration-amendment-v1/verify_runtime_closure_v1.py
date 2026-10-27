#!/usr/bin/env python3
"""Verify the redacted OK-141 SSA migration runtime closure."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
CLOSURE = HERE / "runtime-closure-v1.json"
SYNC_CANDIDATE = HERE.parent / "go1-registration-token-refresh-v2/core-sync-after-ssa-migration-candidate-v3.json"
REFRESH_CANDIDATE = HERE / "prometheus-operator-api-refresh-candidate-v1.json"


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> None:
    value = json.loads(CLOSURE.read_text())
    spec = value["spec"]
    expect(value["kind"] == "OK141PlatformSSAMigrationRuntimeClosure", "closure kind")
    expect(spec["coreSync"]["candidateDigest"] == digest(SYNC_CANDIDATE), "Core candidate digest")
    expect(spec["operatorAPIRefresh"]["candidateDigest"] == digest(REFRESH_CANDIDATE), "refresh candidate digest")
    expect(spec["migrationAmendment"]["updatedObjectCount"] == 13, "amendment object count")
    expect(
        spec["migrationAmendment"]["coreSyncOptions"][-2:]
        == ["ServerSideApply=true", "ClientSideApplyMigration=false"],
        "Core apply options",
    )
    expect(spec["coreSync"]["successfulResourceCount"] == 94, "successful resource count")
    expect(spec["coreSync"]["failedResourceCount"] == 5, "failed resource count")
    expect(spec["coreSync"]["additionalSyncSubmitted"] is False, "no extra sync")
    expect(spec["operatorAPIRefresh"]["controllerRestartPerformed"] is True, "operator restart")
    expect(spec["operatorAPIRefresh"]["replacementReady"] is True, "replacement readiness")
    expect(spec["operatorAPIRefresh"]["prometheusStatusObserved"] is True, "Prometheus status")
    expect(spec["currentRuntime"]["prometheusAvailableReplicas"] == 1, "Prometheus available")
    expect(spec["currentRuntime"]["prometheusStatefulSetReadyReplicas"] == 1, "StatefulSet ready")
    expect(spec["remainingDiff"]["applicationHealth"] == "Healthy", "Application health")
    expect(spec["remainingDiff"]["applicationSync"] == "OutOfSync", "Application sync")
    expect(spec["remainingDiff"]["prunableAdmissionHookResourceCount"] == 5, "prunable hooks")
    expect(spec["remainingDiff"]["outOfSyncResourceCount"] == 1, "remaining drift count")
    boundary = spec["authorizationBoundary"]
    expect(boundary["state"] == "STOP-PRESERVE-NO-RETRY", "fail-closed state")
    expect(not any(boundary[key] for key in (
        "retryPerformedAfterFailedCoreOperation",
        "rollbackPerformed",
        "generalCleanupPerformed",
        "failureInjectionPerformed",
        "rawEvidencePublished",
    )), "closure exclusions")
    forbidden = {"token", "kubeconfig", "secretdata", "clientkeydata", "certificateauthoritydata"}
    expect(not (forbidden & {key.lower() for key in spec}), "top-level sensitive fields")
    print(json.dumps({"state": "PASS", "closureDigest": digest(CLOSURE)}, sort_keys=True))


if __name__ == "__main__":
    main()
