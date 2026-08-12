#!/usr/bin/env python3
"""Verify the offline-only M0a v3 authorization and expiry boundary."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import sys
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


def resolve(reference: str, expected_digest: str) -> Path:
    target = (HERE / reference).resolve()
    if SPIKE.resolve() not in target.parents or not target.is_file():
        raise VerificationError(f"reference missing or outside spike root: {reference}")
    expect(sha(target), expected_digest, f"digest for {reference}")
    return target


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location("ok141_m0a_v3_probe", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def verify(candidate_path: Path) -> str:
    candidate = yaml.safe_load(candidate_path.read_text())["spec"]
    expect(candidate["version"], "ok141-m0a-security-boundary/v3", "version")
    expect(candidate["state"], "BLOCKED-OFFLINE-CANDIDATE", "state")
    expect(candidate["cause"]["firstRunResult"], "STOP-NOT-SUCCESS", "runtime result")
    expect(candidate["cause"]["grantConsumed"], True, "grant consumption")
    expect(candidate["cause"]["classification"], "invalid-kubectl-subresource-authorization-probe", "cause")
    expect(candidate["cause"]["confidence"], "PROVEN", "cause confidence")

    evidence_path = resolve(candidate["cause"]["evidencePath"], candidate["cause"]["evidenceDigest"])
    evidence = yaml.safe_load(evidence_path.read_text())["spec"]
    expect(evidence["authorizationProbes"]["actualTokenRequestAuthorization"]["classification"], "NOT-PROVEN", "historical claim boundary")
    expect(evidence["conclusion"]["retryAllowed"], False, "historical retry")

    controls = candidate["retainedSecurityControls"]
    resolve(controls["rbacPath"], controls["rbacDigest"])
    resolve(controls["admissionPath"], controls["admissionDigest"])
    expect(controls["allowedObjectIdentities"], 19, "identity count")
    expect(controls["allowedInstallerVerbs"], ["create", "get"], "installer verbs")
    for claim in ("patchAllowed", "updateAllowed", "deleteAllowed", "listAllowed", "watchAllowed", "payloadContentProvenByAdmission"):
        expect(controls[claim], False, claim)

    proof = candidate["tokenRequestAuthorizationProof"]
    helper = load_module(resolve(proof["helperPath"], proof["helperDigest"]))
    expect(proof["oldFormMeaning"], "resource-serviceaccounts-name-token", "old syntax meaning")
    expect(proof["requiredResource"], "serviceaccounts", "subresource parent")
    expect(proof["requiredSubresource"], "token", "subresource")
    expect(proof["requiredVerb"], "create", "subresource verb")
    expect(proof["expectedInstallerDecision"], "deny", "installer decision")
    expect(proof["administratorIssuesBoundedToken"], True, "administrator TokenRequest")
    expect(proof["installerMayIssueToken"], False, "installer TokenRequest")
    expect(helper.token_request_denial_args(), proof["requiredForm"], "unambiguous command")
    if "--subresource" in proof["oldAmbiguousForm"]:
        raise VerificationError("historical ambiguous form unexpectedly contains a subresource flag")

    credential = candidate["credentialBoundary"]
    expect(credential["tokenRequestDurationMaximum"], "10m", "token duration")
    expect(credential["tokenMaterialPersisted"], False, "token persistence")
    expect(credential["temporaryKubeconfigPersisted"], False, "kubeconfig persistence")
    revocation = candidate["revocationBoundary"]
    expect(revocation["individualTokenRevocationAvailable"], False, "individual revocation")
    expect(revocation["immediateRejectionClaim"], False, "immediate rejection")
    expect(revocation["cleanupBeforeObservation"], True, "cleanup ordering")
    expect(revocation["observationDeadline"], "token-expirationTimestamp-plus-30s", "expiry deadline")
    expect(revocation["clockSkewToleranceSeconds"], 30, "clock skew tolerance")
    expect(revocation["failureOutcome"], "STOP-NOT-SUCCESS", "failure outcome")

    expect(candidate["authorization"], {
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
    return sha(candidate_path)


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
