#!/usr/bin/env python3
"""Verify the redacted and non-authorizing first M0a v4 runtime record."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
from typing import Any

import yaml


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent


class VerificationError(ValueError):
    pass


def sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def expect(actual: Any, expected: Any, claim: str) -> None:
    if actual != expected:
        raise VerificationError(f"{claim}: expected {expected!r}, got {actual!r}")


def verify(path: Path) -> str:
    spec = yaml.safe_load(path.read_text())["spec"]
    expect(spec["version"], "ok141-m0a-execution-evidence/v4-redacted", "version")
    expect(spec["state"], "STOP-NOT-SUCCESS", "state")
    for reference in spec["references"].values():
        target = (path.parent / reference["path"]).resolve()
        if SPIKE.resolve() not in target.parents or not target.is_file():
            raise VerificationError(f"reference missing or outside spike root: {target}")
        expect(sha(target), reference["digest"], f"digest for {reference['path']}")
    execution = spec["execution"]
    expect(execution["maximumRuns"], 1, "maximum runs")
    expect(execution["runsConsumed"], 1, "consumed runs")
    expect(execution["retryAuthorized"], False, "retry authorization")
    expect(execution["result"], "STOP-NOT-SUCCESS", "execution result")
    expect(execution["rawLocalEvidencePublishable"], False, "raw publication boundary")
    expect(spec["preflight"]["source"]["exactIdentityAbsence"], 19, "preflight absence")
    expect(spec["authorizationProbes"]["result"], "PASS", "authorization probes")
    expect(spec["bootstrap"]["cleanupRemovedAllObjects"], True, "bootstrap cleanup")
    credential = spec["credential"]
    expect(credential["tokenMaterialRetained"], False, "token retention")
    expect(credential["temporaryKubeconfigRetained"], False, "kubeconfig retention")
    expect(credential["rejectionProbe"]["result"], "NOT-PROVEN", "rejection result")
    installation = spec["installation"]
    expect(installation["operation"], "create-exact-19-object-stream", "operation")
    expect(installation["submissionsConsumed"], 1, "submission count")
    expect(installation["result"], "FAILED", "installation result")
    expect(installation["responseBodyRetained"], False, "response retention")
    expect(installation["causeClassification"], "UNKNOWN-NOT-RESPONSE-PROVEN", "cause boundary")
    expect(installation["postSubmissionInventory"], {"expected": 19, "present": 0, "absent": 19}, "post-submit inventory")
    post_failure = spec["postFailureObservation"]
    expect(post_failure["readOnlyPreflightResult"], "PASS", "post-failure preflight")
    expect(post_failure["exactIdentityAbsence"], 19, "post-failure absence")
    expect(post_failure["temporaryBootstrapObjectsPresent"], 0, "post-failure bootstrap objects")
    conclusion = spec["conclusion"]
    expect(conclusion["partialInstallationPresent"], False, "partial installation")
    expect(conclusion["tokenRejectionProven"], False, "token rejection claim")
    expect(conclusion["tokenAuthenticationAfterConfiguredDeadlineProven"], False, "post-deadline auth claim")
    expect(conclusion["grantReusable"], False, "grant reuse")
    expect(conclusion["retryAllowed"], False, "retry")
    expect(conclusion["rollbackNeeded"], False, "rollback need")
    expect(spec["authorization"], {
        "evidencePublicationGranted": False,
        "retryGranted": False,
        "cleanupGranted": False,
        "rollbackGranted": False,
        "m0bInstallationGranted": False,
        "go1Granted": False,
        "targetConvergenceGranted": False,
        "failureInjectionGranted": False,
    }, "authorization")
    if any(spec["redaction"].values()):
        raise VerificationError("redacted checkpoint contains forbidden material")
    return sha(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--digest-file", type=Path)
    args = parser.parse_args()
    try:
        result = verify(args.evidence.resolve())
        if args.digest_file:
            expect(args.digest_file.read_text().strip(), result, "evidence digest")
        print(result)
        return 0
    except (OSError, KeyError, TypeError, ValueError, VerificationError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
