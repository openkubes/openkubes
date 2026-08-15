#!/usr/bin/env python3
"""Bounded local-only identity inspection for two OK-141 admin kubeconfigs."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
CANDIDATE = HERE / "go1-l-admin-identity-c0-candidate-v1.yaml"
PRE_TOOL = SPIKE / "go1-l-admin-preflight-v1" / "bounded_admin_preflight_v1.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


PRE = load_module("ok141_admin_preflight_for_c0", PRE_TOOL)
V1 = PRE.V1


class InspectionError(ValueError):
    pass


def sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def expect(actual: Any, expected: Any, context: str) -> None:
    if actual != expected:
        raise InspectionError(f"{context}: expected {expected!r}, got {actual!r}")


def resolve(candidate_path: Path, requested: str) -> Path:
    path = (candidate_path.parent / requested).resolve()
    if SPIKE.resolve() not in path.parents or not path.is_file():
        raise InspectionError(f"reference missing or outside spike root: {requested}")
    return path


def load_candidate(path: Path = CANDIDATE) -> dict[str, Any]:
    return V1.read_yaml_or_json(path)


def validate_candidate(candidate: dict[str, Any], candidate_path: Path = CANDIDATE) -> None:
    expect(candidate["apiVersion"], "security.openkubes.io/v1alpha1", "apiVersion")
    expect(candidate["kind"], "GO1LAdminIdentityInspectionCandidate", "kind")
    spec = candidate["spec"]
    expect(spec["state"], "OFFLINE-PROVEN-BLOCKED-NO-GO", "state")
    sources = {
        "sourceAcceptance": "sha256:1bedab96f582b3ca31f67c81b948263560c36fd0a113ec317442cb9c65d25fed",
        "sourcePreflight": "sha256:3a3187c79779e048337fd2d6c35473a3c97f900330082721e3b318a5c9e6a12f",
    }
    for source_name, digest in sources.items():
        source = spec[source_name]
        expect(sha(resolve(candidate_path, source["path"])), digest, f"{source_name} source")
        expect(source["digest"], digest, f"{source_name} binding")
    expect(sha(resolve(candidate_path, spec["tool"]["path"])), spec["tool"]["digest"], "tool digest")
    expect(spec["tool"]["liveClusterClientIncluded"], False, "cluster client boundary")
    expected = [
        ("ok-infra", "/Users/arash/.kube/ok-infra.yaml"),
        ("ok-mgmt", "/Users/arash/.kube/ok-mgmt.yaml"),
    ]
    expect([(item["targetPlane"], item["path"]) for item in spec["credentialFiles"]], expected, "credential file scope")
    if any(item["identityState"] != "UNRESOLVED" or item["inspectionComplete"] for item in spec["credentialFiles"]):
        raise InspectionError("credential identity is preclaimed")
    auth = spec["authorization"]
    expect(auth["decision"], "NO-GO", "authorization decision")
    expect(auth["grantIDs"], [], "grant IDs")
    expect(auth["authorizedDigest"], None, "authorized digest")
    if any(value for key, value in auth.items() if key.endswith("Granted")):
        raise InspectionError("candidate grants identity inspection or execution")
    expect(spec["outputContract"]["secretBytesAllowed"], False, "secret output")
    expect(spec["outputContract"]["contextClusterOrUserNamesAllowed"], False, "name output")
    expect(spec["outputContract"]["clusterContactAllowed"], False, "cluster contact")
    expect(spec["outputContract"]["mutationAllowed"], False, "mutation")


def parse_time(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise InspectionError("timestamp must include timezone")
    return parsed


def validate_grant(candidate_path: Path, grant: dict[str, Any], now: dt.datetime) -> None:
    spec = grant["spec"]
    expect(spec["decision"], "GO", "grant decision")
    expect(spec["credentialInspectionGranted"], True, "inspection grant")
    expect(spec["clusterContactGranted"], False, "cluster contact grant")
    expect(spec["mutationAuthorized"], False, "mutation grant")
    expect(spec["candidateDigest"], sha(candidate_path), "candidate binding")
    expect(spec["scope"], "inspect-two-local-admin-kubeconfig-identities", "grant scope")
    if not spec.get("grantID") or spec.get("singleRun") is not True:
        raise InspectionError("single-run grant identity is missing")
    issued = parse_time(spec["issuedAt"])
    expires = parse_time(spec["expiresAt"])
    if not issued <= now <= expires or expires - issued > dt.timedelta(minutes=10):
        raise InspectionError("grant is outside its maximum 10-minute window")


def inspect(candidate: dict[str, Any], candidate_path: Path, grant: dict[str, Any], now: dt.datetime) -> dict[str, Any]:
    validate_candidate(candidate, candidate_path)
    validate_grant(candidate_path, grant, now)
    identities = []
    for item in candidate["spec"]["credentialFiles"]:
        identity = PRE.inspect_kubeconfig(Path(item["path"]))
        identities.append({
            "targetPlane": item["targetPlane"],
            "server": identity["server"],
            "caFingerprint": identity["caFingerprint"],
            "credentialIdentityDigest": identity["credentialIdentityDigest"],
        })
    return {
        "candidateDigest": sha(candidate_path),
        "grantID": grant["spec"]["grantID"],
        "observedAt": now.isoformat().replace("+00:00", "Z"),
        "identities": identities,
        "credentialBytesEmitted": False,
        "contextClusterOrUserNamesEmitted": False,
        "clusterContacted": False,
        "mutationPerformed": False,
    }


def plan(candidate: dict[str, Any], candidate_path: Path) -> dict[str, Any]:
    validate_candidate(candidate, candidate_path)
    return {
        "candidateDigest": sha(candidate_path),
        "scope": [item["targetPlane"] for item in candidate["spec"]["credentialFiles"]],
        "credentialInspectionGranted": False,
        "clusterContacted": False,
        "mutationAuthorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "plan"))
    parser.add_argument("--candidate", type=Path, default=CANDIDATE)
    args = parser.parse_args()
    try:
        path = args.candidate.resolve()
        candidate = load_candidate(path)
        result = plan(candidate, path)
        result["state"] = candidate["spec"]["state"]
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (InspectionError, KeyError, OSError, PRE.PreflightError, TypeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
