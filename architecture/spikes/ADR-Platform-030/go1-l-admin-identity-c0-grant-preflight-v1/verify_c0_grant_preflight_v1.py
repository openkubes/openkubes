#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
HARNESS = SPIKE / "harness"
PREFLIGHT = HERE / "c0-grant-preflight-v1.yaml"
DIGEST = HERE / "c0-grant-preflight-v1.sha256"
SOURCES = {
    "sourceCandidate": "sha256:3ed89d8f9792e53068f424d23f609ba3cad31620d7ce4f1a8001a9bf3089db89",
    "sourceAcceptance": "sha256:1bedab96f582b3ca31f67c81b948263560c36fd0a113ec317442cb9c65d25fed",
}


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


V4 = load_module("ok141_phase_r_v4_c0_grant_preflight", HARNESS / "ok141_phase_r_v4.py")
V1 = V4.V1


class GrantPreflightError(ValueError):
    pass


def sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def expect(actual, expected, context):
    if actual != expected:
        raise GrantPreflightError(f"{context}: expected {expected!r}, got {actual!r}")


def resolve(requested: str) -> Path:
    path = (HERE / requested).resolve()
    if SPIKE.resolve() not in path.parents or not path.is_file():
        raise GrantPreflightError(f"invalid source path: {requested}")
    return path


def validate(document: dict) -> str:
    expect(document["apiVersion"], "authorization.openkubes.io/v1alpha1", "apiVersion")
    expect(document["kind"], "LocalCredentialInspectionGrantPreflight", "kind")
    spec = document["spec"]
    expect(spec["state"], "TECHNICALLY-COMPLETE-WINDOW-UNRESOLVED-NO-GO", "state")
    for source_name, digest in SOURCES.items():
        source = spec[source_name]
        expect(sha(resolve(source["path"])), digest, f"{source_name} source")
        expect(source["digest"], digest, f"{source_name} binding")
    requested = spec["requestedAuthority"]
    expect(requested["authority"], "github:arashkaffamanesh", "authority")
    expect(requested["scope"], "inspect-two-local-admin-kubeconfig-identities", "scope")
    expect(requested["singleRun"], True, "single-run")
    expect(requested["maximumWindowMinutes"], 10, "maximum window")
    expect((requested["windowStart"], requested["windowEnd"], requested["grantReady"]), ("UNRESOLVED", "UNRESOLVED", False), "window state")
    template = spec["runtimeGrantTemplate"]
    expect(template["decision"], "GO", "template decision")
    expect(template["credentialInspectionGranted"], True, "template inspection scope")
    expect(template["clusterContactGranted"], False, "template cluster contact")
    expect(template["mutationAuthorized"], False, "template mutation")
    expect(template["candidateDigest"], SOURCES["sourceCandidate"], "template candidate")
    expect((template["grantID"], template["issuedAt"], template["expiresAt"]), ("UNRESOLVED", "UNRESOLVED", "UNRESOLVED"), "template runtime fields")
    boundary = spec["executionBoundary"]
    expect(boundary["localKubeconfigInspectionOnly"], True, "local-only boundary")
    if any(boundary[key] for key in ("kubectlOrKubernetesClientAllowed", "networkDNSOrTCPContactAllowed", "credentialCopyModificationRotationRevocationAllowed", "preflightOrSubmissionAllowed", "mutationAllowed")):
        raise GrantPreflightError("execution boundary permits out-of-scope action")
    authorization = spec["authorization"]
    expect(authorization["decision"], "NO-GO", "authorization decision")
    expect(authorization["grantIDs"], [], "grant IDs")
    expect(authorization["authorizedDigest"], None, "authorized digest")
    if any(value for key, value in authorization.items() if key.endswith("Granted")):
        raise GrantPreflightError("preflight artifact grants authority")
    conclusions = spec["conclusions"]
    expect(conclusions["technicalScopeComplete"], True, "technical conclusion")
    for key in ("windowResolved", "grantCandidateComplete", "c0ReadyForDecision", "credentialInspected", "clusterContacted", "mutationAuthorized"):
        expect(conclusions[key], False, key)
    return sha(PREFLIGHT)


def main() -> int:
    try:
        document = V1.read_yaml_or_json(PREFLIGHT)
        actual = validate(document)
        if DIGEST.exists():
            expect(DIGEST.read_text().strip(), actual, "digest file")
        print(json.dumps({
            "preflightDigest": actual,
            "state": document["spec"]["state"],
            "windowResolved": False,
            "c0Granted": False,
            "credentialInspected": False,
            "clusterContacted": False,
            "mutationAuthorized": False,
        }, sort_keys=True))
        return 0
    except (GrantPreflightError, KeyError, OSError, TypeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
