#!/usr/bin/env python3
"""Verify the offline-only M0a v4 create and expiry boundary."""

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


def resolve(base: Path, reference: str, expected_digest: str) -> Path:
    del base
    target = (HERE / reference).resolve()
    if SPIKE.resolve() not in target.parents or not target.is_file():
        raise VerificationError(f"reference missing or outside spike root: {reference}")
    expect(sha(target), expected_digest, f"digest for {reference}")
    return target


def verify(path: Path) -> str:
    spec = yaml.safe_load(path.read_text())["spec"]
    expect(spec["version"], "ok141-m0a-security-boundary/v4", "version")
    expect(spec["state"], "BLOCKED-OFFLINE-CANDIDATE", "state")
    expect(spec["cause"]["firstRunResult"], "STOP-NOT-SUCCESS", "runtime result")
    expect(spec["cause"]["grantConsumed"], True, "grant consumption")
    evidence_path = resolve(path, spec["cause"]["evidencePath"], spec["cause"]["evidenceDigest"])
    evidence = yaml.safe_load(evidence_path.read_text())["spec"]
    expect(evidence["installation"]["operation"], "server-side-apply-exact-19-object-set", "v3 operation")
    expect(evidence["installation"]["reviewedObjectsMaterialized"], 0, "v3 retained objects")
    expect(evidence["credential"]["expiryBoundRejectionProbe"]["toleranceSeconds"], 30, "v3 observation tolerance")
    expect(evidence["conclusion"]["retryAllowed"], False, "v3 retry")

    upstream_path = resolve(path, spec["upstreamSemantics"]["path"], spec["upstreamSemantics"]["digest"])
    upstream = yaml.safe_load(upstream_path.read_text())["spec"]
    expect(upstream["upstream"]["tag"], "v1.34.1", "upstream tag")
    expect(upstream["upstream"]["commit"], "93248f9ae092f571eb870b7664c534bfc7d00f03", "upstream commit")
    expect(upstream["serverSideApply"]["v3RolePatchAllowed"], False, "v3 patch permission")
    derived = upstream["derivedObservationBoundary"]
    expect(derived["jwtLeewaySeconds"], 60, "JWT leeway")
    expect(derived["successCacheSeconds"], 10, "auth cache")
    expect(derived["observationAndClockToleranceSeconds"], 30, "observation tolerance")
    expect(derived["rejectionDeadlineOffsetSeconds"], 100, "derived deadline")
    expect(derived["immediateRevocationClaim"], False, "immediate revocation")

    inputs = spec["immutableInputs"]
    resolve(path, inputs["installationProtocolPath"], inputs["installationProtocolDigest"])
    expect(inputs["objectCount"], 19, "object count")
    controls = spec["retainedSecurityControls"]
    resolve(path, controls["rbacPath"], controls["rbacDigest"])
    resolve(path, controls["admissionPath"], controls["admissionDigest"])
    expect(controls["allowedObjectIdentities"], 19, "identity count")
    expect(controls["allowedInstallerVerbs"], ["create", "get"], "installer verbs")
    for claim in ("patchAllowed", "updateAllowed", "deleteAllowed", "listAllowed", "watchAllowed", "payloadContentProvenByAdmission"):
        expect(controls[claim], False, claim)

    submission = spec["submissionBoundary"]
    expect(submission["operation"], "kubectl-create-exact-19-object-stream", "submission operation")
    expect(submission["verb"], "create", "submission verb")
    expect(submission["serverSideApply"], False, "server-side apply")
    expect(submission["precondition"], "all-19-reviewed-identities-absent", "absence precondition")
    expect(submission["maximumSubmissions"], 1, "submission limit")
    expect(submission["idempotent"], False, "create idempotency")
    expect(submission["fieldOwnershipEstablished"], False, "field ownership")
    expect(submission["partialMaterializationPossible"], True, "partial materialization")
    expect(submission["automaticRetryAllowed"], False, "automatic retry")
    expect(submission["automaticRollbackAllowed"], False, "automatic rollback")

    revocation = spec["revocationBoundary"]
    expect(revocation["jwtLeewaySeconds"], 60, "boundary JWT leeway")
    expect(revocation["successAuthenticationCacheSeconds"], 10, "boundary auth cache")
    expect(revocation["observationAndClockToleranceSeconds"], 30, "boundary tolerance")
    expect(revocation["observationDeadline"], "token-expirationTimestamp-plus-100s", "expiry deadline")
    expect(revocation["immediateRejectionClaim"], False, "immediate rejection")
    expect(revocation["failureOutcome"], "STOP-NOT-SUCCESS", "failure outcome")

    expect(spec["authorization"], {
        "decision": "NO-GO",
        "mutationAuthorized": False,
        "credentialGrantRequired": True,
        "admissionBootstrapGrantRequired": True,
        "installationGrantRequired": True,
        "retryGranted": False,
        "rollbackGranted": False,
        "evidencePublicationGranted": False,
        "m0bInstallationGranted": False,
        "go1Granted": False,
        "targetConvergenceGranted": False,
        "failureInjectionGranted": False,
    }, "authorization")
    return sha(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--digest-file", type=Path)
    args = parser.parse_args()
    try:
        result = verify(args.candidate.resolve())
        if args.digest_file:
            expect(args.digest_file.read_text().strip(), result, "candidate digest")
        print(result)
        return 0
    except (OSError, KeyError, TypeError, ValueError, VerificationError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
