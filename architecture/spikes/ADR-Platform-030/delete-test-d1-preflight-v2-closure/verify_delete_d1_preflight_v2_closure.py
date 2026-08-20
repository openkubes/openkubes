#!/usr/bin/env python3
"""Fail-closed verifier for redacted OK-141 D1-v2 preflight closure."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml


class ClosureError(ValueError):
    pass


EXPECTED_BINDINGS = {
    "d1CandidateDigest": "sha256:c5c78e4d82b689f645c63be3ccbb3a3c4c2f890b01d7004daad7915da6fa7276",
    "stoppedGrantDigest": "sha256:a6536caa77f6113eff65a0ac9a34fb975bbf61a93bdff09cff001bf6f69c083d",
    "registrationRefreshCandidateDigest": "sha256:d26835f07cf28f2639c6bc1e7ab1dfe7fb069ca7d9369d1552dba6ca0307bdda",
    "registrationRefreshEvidenceDigest": "sha256:94193067dc47bd8e23eb1ae0fa3fc119c7535590302805d70d9fb0f5b47fbe93",
    "freshD0CandidateDigest": "sha256:771c09a760940afa8c04a26a79e3e921c11d87d96ae949c1781f4fd7c846074b",
    "freshD0BindingDigest": "sha256:2b9003263fb6e5ee3a67b3e8e4009bafd626d6bfad31260514886874934ef31c",
    "freshD0EvidenceDigest": "sha256:858b65b9a865f215dbb8aaae4311d8b0f9b915f0a7f52b8068e5c5d563206f3e",
    "successfulGrantDigest": "sha256:082dec7ba3a416f154a094a10cb2bffa06060b1dfb29347ebb98682d0458eeaa",
    "privateBindingDigest": "sha256:c370c06b20b1d1dc42691c2dfbf383dfbbdc5192d0a672783484ce79f5b5333d",
    "privateEvidenceDigest": "sha256:d23bf4f21092bead626a8c0056c3470b04ce308281b816e8f0d8a0cd163f880e",
}


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_digest(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def read_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text())
    if not isinstance(value, dict):
        raise ClosureError("expected one YAML object")
    return value


def verify_closure(path: Path) -> dict[str, Any]:
    closure = read_yaml(path)
    spec = closure.get("spec", {})
    errors: list[str] = []
    if spec.get("state") != "PASS-D1-V2-PREFLIGHT-PRIVATE-BOUND-NO-GO":
        errors.append("closure state mismatch")
    if spec.get("bindings") != EXPECTED_BINDINGS:
        errors.append("binding digest mismatch")

    normalization = spec.get("normalization", {})
    if normalization != {
        "profile": "argocd-application-c14n/v1",
        "defaultsApplied": {"spec.source.directory.recurse": False},
        "normalizedApplicationCount": 3,
        "semanticMatchCount": 3,
    }:
        errors.append("normalization boundary mismatch")

    observation = spec.get("observation", {})
    expected_observation = {
        "sealedGetCount": 6,
        "deleteTargetCount": 5,
        "targetCorrelationPassed": True,
        "applicationImmutableIdentityPassed": True,
        "appProjectMetadataPassed": True,
        "registrationSecretMetadataPassed": True,
        "bindingLifetimeSeconds": 300,
    }
    if observation != expected_observation:
        errors.append("observation boundary mismatch")

    execution = spec.get("execution", {})
    expected_execution = {
        "initialV2AttemptStoppedFailClosed": True,
        "stopReasonClass": "PLATFORM-BASELINE-AUTHENTICATION",
        "registrationTokenRefreshPerformed": True,
        "registrationRefreshOptimisticConcurrencyUsed": True,
        "freshD0SnapshotPerformed": True,
        "diagnosisBasedSecondRunPerformed": True,
        "successfulD1PreflightRuns": 1,
        "d1PreflightMutationPerformed": False,
        "deletePerformed": False,
        "cleanupPerformed": False,
    }
    if execution != expected_execution:
        errors.append("execution boundary mismatch")

    if spec.get("conclusions") != {
        "d1v2PreflightPassed": True,
        "fiveDeleteTargetsPrivatelyBound": True,
        "semanticDefaultingGapClosed": True,
        "d1DeleteAuthorized": False,
        "d2OrD3Authorized": False,
    }:
        errors.append("conclusion boundary mismatch")

    redaction = spec.get("redaction", {})
    if not redaction or any(value is not False for value in redaction.values()):
        errors.append("redaction boundary mismatch")
    authorization = spec.get("authorization", {})
    if authorization.get("decision") != "NO-GO" or any(
        value is not False for key, value in authorization.items() if key.endswith("Granted")
    ):
        errors.append("closure grants authority")

    rendered = json.dumps(closure, sort_keys=True)
    forbidden = (
        '"uid":', '"resourceVersion":', '"endpoint":', '"kubeconfig":',
        '"token":', '"secretValue":',
    )
    if any(term in rendered for term in forbidden):
        errors.append("forbidden raw field marker present")
    if errors:
        raise ClosureError("; ".join(errors))
    return closure


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--closure", type=Path, required=True)
    args = parser.parse_args()
    closure = verify_closure(args.closure.resolve())
    print(json.dumps({
        "closureDigest": digest(args.closure.resolve()),
        "semanticDigest": canonical_digest(closure),
        "state": "PASS-D1-V2-PREFLIGHT-CLOSURE-REDACTED-NO-GO",
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ClosureError, OSError, ValueError) as error:
        print(f"ERROR: {error}", file=__import__("sys").stderr)
        raise SystemExit(1)
