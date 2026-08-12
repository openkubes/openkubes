#!/usr/bin/env python3
"""Verify the offline M0a v5 diagnostic boundary."""

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


def resolve(path: Path, reference: dict[str, str]) -> Path:
    target = (path.parent / reference["path"]).resolve()
    if SPIKE.resolve() not in target.parents or not target.is_file():
        raise VerificationError(f"reference missing or outside spike root: {target}")
    expect(sha(target), reference["digest"], f"digest for {reference['path']}")
    return target


def verify(path: Path) -> str:
    spec = yaml.safe_load(path.read_text())["spec"]
    expect(spec["version"], "ok141-m0a-security-boundary/v5", "version")
    expect(spec["state"], "BLOCKED-OFFLINE-CANDIDATE", "state")
    expect(spec["cause"]["firstRunResult"], "STOP-NOT-SUCCESS", "v4 result")
    expect(spec["cause"]["grantConsumed"], True, "v4 grant")
    expect(spec["cause"]["createFailureCause"], "UNKNOWN-NOT-RESPONSE-PROVEN", "v4 cause")
    expect(spec["cause"]["retainedCaaphObjects"], 0, "v4 objects")
    resolve(path, {"path": spec["cause"]["evidencePath"], "digest": spec["cause"]["evidenceDigest"]})
    resolve(path, spec["retainedAcceptedRisk"])
    tool_path = resolve(path, spec["toolchain"])
    tool = yaml.safe_load(tool_path.read_text())["spec"]
    expect(tool["release"], "v1.34.1", "kubectl release")
    expect(tool["gitCommit"], "93248f9ae092f571eb870b7664c534bfc7d00f03", "kubectl commit")
    expect(tool["binaryDigest"], "sha256:bb211f2b31f2b3bc60562b44cc1e3b712a16a98e9072968ba255beb04cefcfdf", "kubectl digest")
    expect(tool["binarySizeBytes"], 61851632, "kubectl size")
    expect(spec["toolchain"]["clientVersionMustEqualServerVersion"], True, "version equality")
    submission = spec["submissionBoundary"]
    expect(submission["reviewedObjectCount"], 19, "object count")
    expect(submission["positiveServerDryRunRequired"], True, "positive dry-run")
    expect(submission["positiveServerDryRunUsesExactPayload"], True, "dry-run payload")
    expect(submission["maximumRealSubmissions"], 1, "real submissions")
    expect(submission["idempotent"], False, "idempotency")
    expect(submission["atomic"], False, "atomicity")
    expect(submission["automaticRetryAllowed"], False, "retry")
    expect(submission["automaticRollbackAllowed"], False, "rollback")
    diagnostic = spec["diagnosticBoundary"]
    expect(diagnostic["stdoutMaximumBytes"], 4096, "stdout bound")
    expect(diagnostic["stderrMaximumBytes"], 4096, "stderr bound")
    expect(diagnostic["pathsRedacted"], True, "path redaction")
    expect(diagnostic["bearerTokensRedacted"], True, "token redaction")
    expect(diagnostic["kubeconfigContentRetained"], False, "kubeconfig retention")
    expect(diagnostic["submittedPayloadRetained"], False, "payload retention")
    credential = spec["credentialBoundary"]
    expect(credential["rejectionBoundarySecondsAfterExpiration"], 100, "rejection boundary")
    expect(credential["mandatoryFirstPostBoundaryProbe"], True, "post-boundary probe")
    expect(credential["probeNotBefore"], "expirationTimestamp-plus-100s", "probe timing")
    expect(credential["immediateRevocationClaim"], False, "revocation claim")
    expect(spec["authorization"], {
        "decision": "NO-GO",
        "mutationAuthorized": False,
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
