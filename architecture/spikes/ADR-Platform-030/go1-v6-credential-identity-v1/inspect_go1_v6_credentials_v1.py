#!/usr/bin/env python3
"""Local-only credential identity inspection for the GO-1 v6 preflight."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any

import yaml


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
CANDIDATE = HERE / "go1-v6-credential-identity-candidate-v1.yaml"
PREFLIGHT_TOOL = SPIKE / "go1-v6-preflight-v1" / "bounded_go1_v6_preflight_v1.py"
EXPECTED_PREFLIGHT_DIGEST = "sha256:5b1eb87734b16e84fdd395368b4bf8cc0aa498ff9620241b2b36f6fc9530721f"
EXPECTED_PATHS = [
    ("ok-infra", "/Users/arash/.kube/ok-infra.yaml"),
    ("ok-mgmt", "/Users/arash/.kube/ok-mgmt.yaml"),
    ("ok-shared", "/Users/arash/.kube/ok-shared.yaml"),
]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


PREFLIGHT = load_module("ok141_go1_v6_preflight_for_c0", PREFLIGHT_TOOL)


class InspectionError(ValueError):
    pass


def sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text())
    if not isinstance(value, dict):
        raise InspectionError(f"expected mapping: {path}")
    return value


def expect(actual: Any, expected: Any, context: str) -> None:
    if actual != expected:
        raise InspectionError(f"{context}: expected {expected!r}, got {actual!r}")


def resolve(candidate_path: Path, requested: str) -> Path:
    path = (candidate_path.parent / requested).resolve()
    if SPIKE.resolve() not in path.parents or not path.is_file():
        raise InspectionError(f"reference missing or outside spike root: {requested}")
    return path


def validate_candidate(candidate_path: Path = CANDIDATE) -> dict[str, Any]:
    candidate = read(candidate_path)
    expect(candidate.get("apiVersion"), "security.openkubes.io/v1alpha1", "apiVersion")
    expect(candidate.get("kind"), "GO1V6CredentialIdentityCandidate", "kind")
    spec = candidate["spec"]
    expect(spec["version"], "ok141-go1-v6-credential-identity/v1", "version")
    expect(spec["state"], "OFFLINE-PROVEN-BLOCKED-NO-GO", "state")
    expect(spec["sourcePreflight"]["digest"], EXPECTED_PREFLIGHT_DIGEST, "preflight digest")
    expect(sha(resolve(candidate_path, spec["sourcePreflight"]["path"])), EXPECTED_PREFLIGHT_DIGEST, "preflight binding")
    expect(sha(resolve(candidate_path, spec["tool"]["path"])), spec["tool"]["digest"], "tool binding")
    expect(spec["tool"]["kubectlIncluded"], False, "kubectl boundary")
    expect(spec["tool"]["networkClientIncluded"], False, "network boundary")
    expect(spec["tool"]["arbitraryPathAllowed"], False, "path boundary")
    expect([(item["targetPlane"], item["path"]) for item in spec["credentialFiles"]], EXPECTED_PATHS, "credential inventory")
    if any(item["identityState"] != "UNRESOLVED" for item in spec["credentialFiles"]):
        raise InspectionError("candidate preclaims a credential identity")
    contract = spec["inspectionContract"]
    expect(contract["scope"], "inspect-three-local-kubeconfig-identities", "scope")
    expect(contract["maximumGrantMinutes"], 15, "maximum grant")
    expect(contract["singleRun"], True, "single-run boundary")
    authorization = spec["authorization"]
    expect(authorization["decision"], "NO-GO", "authorization")
    expect(authorization["grantIDs"], [], "grant inventory")
    expect(authorization["authorizedDigest"], None, "authorized digest")
    if any(value for key, value in authorization.items() if key.endswith("Granted")):
        raise InspectionError("candidate grants authority")
    expect(spec["conclusions"]["clusterContacted"], False, "cluster contact")
    expect(spec["conclusions"]["mutationAuthorized"], False, "mutation authority")
    return candidate


def parse_time(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise InspectionError("timestamp must include timezone")
    return parsed


def validate_grant(candidate_path: Path, grant: dict[str, Any], now: dt.datetime) -> None:
    expect(grant.get("apiVersion"), "authorization.openkubes.io/v1alpha1", "grant apiVersion")
    expect(grant.get("kind"), "GO1V6CredentialIdentityGrant", "grant kind")
    spec = grant["spec"]
    expect(spec["decision"], "GO", "grant decision")
    expect(spec["candidateDigest"], sha(candidate_path), "candidate binding")
    expect(spec["scope"], "inspect-three-local-kubeconfig-identities", "grant scope")
    expect(spec["singleRun"], True, "single-run grant")
    expect(spec["credentialInspectionGranted"], True, "credential inspection grant")
    expect(spec["clusterContactGranted"], False, "cluster contact grant")
    expect(spec["mutationAuthorized"], False, "mutation grant")
    if not spec.get("grantID"):
        raise InspectionError("grant ID is missing")
    issued, expires = PREFLIGHT.parse_time(spec["issuedAt"]), PREFLIGHT.parse_time(spec["expiresAt"])
    if not issued <= now <= expires or expires - issued > dt.timedelta(minutes=15):
        raise InspectionError("grant is outside its maximum 15-minute window")


def write_exclusive(path: Path, value: dict[str, Any]) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, json.dumps(value, indent=2, sort_keys=True).encode() + b"\n")
    finally:
        os.close(fd)


def inspect(candidate_path: Path, grant_path: Path, now: dt.datetime) -> dict[str, Any]:
    candidate = validate_candidate(candidate_path)
    grant = read(grant_path)
    validate_grant(candidate_path, grant, now)
    identities = []
    for item in candidate["spec"]["credentialFiles"]:
        identity = PREFLIGHT.inspect_credential(Path(item["path"]))
        identities.append({
            "targetPlane": item["targetPlane"],
            "server": identity["server"],
            "caFingerprint": identity["caFingerprint"],
            "identityDigest": identity["identityDigest"],
        })
    evidence = {
        "apiVersion": "evidence.openkubes.io/v1alpha1",
        "kind": "GO1V6CredentialIdentityEvidence",
        "spec": {
            "version": "ok141-go1-v6-credential-identity-evidence/v1",
            "candidateDigest": sha(candidate_path),
            "grantID": grant["spec"]["grantID"],
            "observedAt": now.isoformat().replace("+00:00", "Z"),
            "identities": identities,
            "credentialBytesEmitted": False,
            "contextClusterOrUserNamesEmitted": False,
            "clusterContacted": False,
            "mutationPerformed": False,
            "result": "PASS-LOCAL-IDENTITIES-REDACTED",
        },
    }
    write_exclusive(Path(candidate["spec"]["evidence"]["rawLocalPath"]), evidence)
    return evidence


def plan(candidate_path: Path = CANDIDATE) -> dict[str, Any]:
    candidate = validate_candidate(candidate_path)
    return {
        "candidateDigest": sha(candidate_path),
        "scope": [item["targetPlane"] for item in candidate["spec"]["credentialFiles"]],
        "credentialInspectionGranted": False,
        "clusterContacted": False,
        "mutationAuthorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "plan", "run"))
    parser.add_argument("--candidate", type=Path, default=CANDIDATE)
    parser.add_argument("--grant", type=Path)
    args = parser.parse_args()
    try:
        path = args.candidate.resolve()
        if args.command in {"verify", "plan"}:
            result = plan(path)
            result["state"] = validate_candidate(path)["spec"]["state"]
        else:
            if args.grant is None:
                raise InspectionError("run requires a separate C0 grant")
            result = inspect(path, args.grant.resolve(), dt.datetime.now(dt.timezone.utc))
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (InspectionError, PREFLIGHT.PreflightError, OSError, KeyError, TypeError, ValueError, yaml.YAMLError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
