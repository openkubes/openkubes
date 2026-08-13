#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
HARNESS = SPIKE / "harness"
CANDIDATE = HERE / "c0-grant-candidate-v1.yaml"
DIGEST = HERE / "c0-grant-candidate-v1.sha256"
SOURCES = {
    "sourcePreflight": "sha256:0b1495ed3c216eb3246d9a43e98ce76eb664a9c6ed81241d866c4df33118b037",
    "sourceInspectionCandidate": "sha256:3ed89d8f9792e53068f424d23f609ba3cad31620d7ce4f1a8001a9bf3089db89",
    "sourceRiskAcceptance": "sha256:1bedab96f582b3ca31f67c81b948263560c36fd0a113ec317442cb9c65d25fed",
}


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


V4 = load_module("ok141_phase_r_v4_c0_grant", HARNESS / "ok141_phase_r_v4.py")
V1 = V4.V1


class GrantCandidateError(ValueError):
    pass


def sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def expect(actual, expected, context):
    if actual != expected:
        raise GrantCandidateError(f"{context}: expected {expected!r}, got {actual!r}")


def resolve(requested: str) -> Path:
    path = (HERE / requested).resolve()
    if SPIKE.resolve() not in path.parents or not path.is_file():
        raise GrantCandidateError(f"invalid source path: {requested}")
    return path


def timestamp(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise GrantCandidateError(f"invalid timestamp: {value}") from error


def validate(document: dict) -> str:
    expect(document["apiVersion"], "authorization.openkubes.io/v1alpha1", "apiVersion")
    expect(document["kind"], "LocalCredentialInspectionGrantCandidate", "kind")
    spec = document["spec"]
    expect(spec["state"], "READY-FOR-C0-DECISION-NO-GO", "state")
    for source_name, digest in SOURCES.items():
        source = spec[source_name]
        expect(sha(resolve(source["path"])), digest, f"{source_name} source")
        expect(source["digest"], digest, f"{source_name} binding")
    grant = spec["requestedGrant"]
    expect(grant["authority"], "github:arashkaffamanesh", "authority")
    expect(grant["decision"], "GO", "requested decision")
    expect(grant["grantID"], "ok141-go1-l-c0-20260813-01", "grant ID")
    expect(grant["scope"], "inspect-two-local-admin-kubeconfig-identities", "scope")
    expect(grant["singleRun"], True, "single-run")
    expect(grant["maximumWindowMinutes"], 10, "maximum window")
    expect((timestamp(grant["expiresAt"]) - timestamp(grant["issuedAt"])).total_seconds(), 600.0, "window duration")
    expect(grant["credentialInspectionGranted"], True, "requested inspection")
    expect(grant["clusterContactGranted"], False, "requested cluster contact")
    expect(grant["mutationAuthorized"], False, "requested mutation")
    boundary = spec["executionBoundary"]
    expect(boundary["localKubeconfigInspectionOnly"], True, "local-only boundary")
    if any(boundary[key] for key in ("kubectlOrKubernetesClientAllowed", "networkDNSOrTCPContactAllowed", "credentialCopyModificationRotationRevocationAllowed", "preflightOrSubmissionAllowed", "mutationAllowed")):
        raise GrantCandidateError("execution boundary permits out-of-scope action")
    authorization = spec["authorization"]
    expect(authorization["decision"], "NO-GO", "authorization decision")
    expect(authorization["authorizedCandidateDigest"], None, "authorized digest")
    expect(authorization["authorityStatement"], None, "authority statement")
    if any(value for key, value in authorization.items() if key.endswith("Granted")):
        raise GrantCandidateError("candidate artifact grants authority")
    conclusions = spec["conclusions"]
    for key in ("windowResolved", "grantCandidateComplete", "c0ReadyForDecision"):
        expect(conclusions[key], True, key)
    for key in ("credentialInspected", "clusterContacted", "mutationAuthorized"):
        expect(conclusions[key], False, key)
    return sha(CANDIDATE)


def main() -> int:
    try:
        document = V1.read_yaml_or_json(CANDIDATE)
        actual = validate(document)
        if DIGEST.exists():
            expect(DIGEST.read_text().strip(), actual, "digest file")
        print(json.dumps({
            "grantCandidateDigest": actual,
            "state": document["spec"]["state"],
            "grantID": document["spec"]["requestedGrant"]["grantID"],
            "windowStart": document["spec"]["requestedGrant"]["issuedAt"],
            "windowEnd": document["spec"]["requestedGrant"]["expiresAt"],
            "c0Granted": False,
            "credentialInspected": False,
            "clusterContacted": False,
            "mutationAuthorized": False,
        }, sort_keys=True))
        return 0
    except (GrantCandidateError, KeyError, OSError, TypeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
