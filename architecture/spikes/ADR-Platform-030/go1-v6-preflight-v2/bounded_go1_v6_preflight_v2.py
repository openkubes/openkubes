#!/usr/bin/env python3
"""GO-1 v6 preflight with an exact kubectl v1.34.1 transport binding."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

import yaml


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
CANDIDATE = HERE / "go1-v6-preflight-candidate-v2.yaml"
V1_TOOL = SPIKE / "go1-v6-preflight-v1" / "bounded_go1_v6_preflight_v1.py"
V1_CANDIDATE_DIGEST = "sha256:5b1eb87734b16e84fdd395368b4bf8cc0aa498ff9620241b2b36f6fc9530721f"
IDENTITY_CLOSURE_DIGEST = "sha256:26c840ac3e1c5eb879f107801740edb0db73a717fea9c00123ad1e36b3fdc008"
CLIENT_PATH = Path("/private/tmp/ok141-kubectl-v1.34.1-darwin-amd64")
CLIENT_DIGEST = "sha256:bb211f2b31f2b3bc60562b44cc1e3b712a16a98e9072968ba255beb04cefcfdf"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


V1 = load_module("ok141_go1_v6_preflight_v1_for_v2", V1_TOOL)


class PreflightV2Error(ValueError):
    pass


def sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text())
    if not isinstance(value, dict):
        raise PreflightV2Error(f"expected mapping: {path}")
    return value


def expect(actual: Any, expected: Any, context: str) -> None:
    if actual != expected:
        raise PreflightV2Error(f"{context}: expected {expected!r}, got {actual!r}")


def resolve(candidate_path: Path, requested: str) -> Path:
    path = (candidate_path.parent / requested).resolve()
    if SPIKE.resolve() not in path.parents or not path.is_file():
        raise PreflightV2Error(f"reference missing or outside spike root: {requested}")
    return path


def validate_candidate(candidate_path: Path = CANDIDATE) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    candidate = read(candidate_path)
    expect(candidate.get("apiVersion"), "test.openkubes.io/v1alpha1", "apiVersion")
    expect(candidate.get("kind"), "GO1V6PreflightCandidate", "kind")
    spec = candidate["spec"]
    expect(spec["version"], "ok141-go1-v6-preflight/v2", "version")
    expect(spec["state"], "OFFLINE-PROVEN-BLOCKED-NO-GO", "state")
    source = spec["supersedesTransportOnly"]
    expect(source["digest"], V1_CANDIDATE_DIGEST, "v1 digest")
    v1_path = resolve(candidate_path, source["path"])
    expect(sha(v1_path), V1_CANDIDATE_DIGEST, "v1 source")
    expect(source["queryAndAcceptanceContractUnchanged"], True, "query inheritance")
    expect(source["v1AllowedForFutureExecution"], False, "v1 execution boundary")
    v1 = V1.validate_candidate(v1_path)
    closure_binding = spec["credentialIdentityClosure"]
    expect(closure_binding["digest"], IDENTITY_CLOSURE_DIGEST, "identity closure digest")
    closure_path = resolve(candidate_path, closure_binding["path"])
    expect(sha(closure_path), IDENTITY_CLOSURE_DIGEST, "identity closure binding")
    closure = read(closure_path)
    expect(closure["spec"]["state"], closure_binding["requiredState"], "identity closure state")
    client = spec["client"]
    expect(client["path"], str(CLIENT_PATH), "client path")
    expect(client["digest"], CLIENT_DIGEST, "client digest")
    expect(client["version"], "v1.34.1", "client version")
    expect(client["platform"], "darwin/amd64", "client platform")
    expect(client["requiredMode"], "0700", "client mode")
    expect(client["PATHLookupAllowed"], False, "PATH boundary")
    expect(sha(resolve(candidate_path, spec["tool"]["path"])), spec["tool"]["digest"], "tool binding")
    authorization = spec["authorization"]
    expect(authorization["decision"], "NO-GO", "authorization")
    expect(authorization["grantIDs"], [], "grant IDs")
    expect(authorization["authorizedDigest"], None, "authorized digest")
    if any(value for key, value in authorization.items() if key.endswith("Granted")):
        raise PreflightV2Error("candidate grants authority")
    expect(spec["conclusions"]["clusterContacted"], False, "cluster contact")
    expect(spec["conclusions"]["mutationAuthorized"], False, "mutation authority")
    return candidate, v1, closure


def verify_client(runner: Callable[..., Any] = subprocess.run) -> dict[str, str]:
    if not CLIENT_PATH.is_file() or CLIENT_PATH.is_symlink():
        raise PreflightV2Error("bound client must be a regular non-symlink file")
    if stat.S_IMODE(CLIENT_PATH.stat().st_mode) != 0o700:
        raise PreflightV2Error("bound client mode must be 0700")
    expect(sha(CLIENT_PATH), CLIENT_DIGEST, "live client digest")
    completed = runner([str(CLIENT_PATH), "version", "--client", "--output=json"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if completed.returncode != 0:
        raise PreflightV2Error("bound client version inspection failed")
    version = json.loads(completed.stdout)["clientVersion"]
    expect(version["gitVersion"], "v1.34.1", "live client version")
    expect(version["platform"], "darwin/amd64", "live client platform")
    return {"path": str(CLIENT_PATH), "digest": CLIENT_DIGEST, "version": version["gitVersion"], "platform": version["platform"]}


def build_command(query: dict[str, Any], credential: str = "RUNTIME-BOUND-KUBECONFIG") -> list[str]:
    command = [str(CLIENT_PATH), "--kubeconfig", credential, "get", query["resource"], query["name"]]
    if query.get("namespace"):
        command.extend(["--namespace", query["namespace"]])
    command.extend(["--ignore-not-found=true", "--output=json"])
    return command


def plan(candidate_path: Path = CANDIDATE) -> dict[str, Any]:
    candidate, v1, _ = validate_candidate(candidate_path)
    queries = [
        {"class": query_class, "id": item["id"], "plane": item["plane"], "command": build_command(item)}
        for query_class, items in (("absence", v1["spec"]["absenceQueries"]), ("readiness", v1["spec"]["readinessQueries"]))
        for item in items
    ]
    return {
        "candidateDigest": sha(candidate_path),
        "sourceV1Digest": V1_CANDIDATE_DIGEST,
        "client": candidate["spec"]["client"],
        "queryCount": len(queries),
        "logicalAbsenceClaimCount": len(v1["spec"]["absenceClaims"]),
        "queries": queries,
        "credentialUseGranted": False,
        "clusterContacted": False,
        "mutationAuthorized": False,
    }


def validate_grant(candidate_path: Path, grant: dict[str, Any], identities: dict[str, dict[str, str]], now: dt.datetime) -> None:
    expect(grant.get("apiVersion"), "authorization.openkubes.io/v1alpha1", "grant apiVersion")
    expect(grant.get("kind"), "GO1V6PreflightGrantV2", "grant kind")
    spec = grant["spec"]
    expect(spec["decision"], "GO", "grant decision")
    expect(spec["candidateDigest"], sha(candidate_path), "grant candidate")
    expect(spec["protocolDigest"], V1.EXPECTED_PROTOCOL_DIGEST, "grant protocol")
    expect(spec["clientDigest"], CLIENT_DIGEST, "grant client")
    expect(spec["expectedCredentialIdentities"], identities, "credential identities")
    expect(spec["singleRun"], True, "single-run boundary")
    expect(spec["readOnly"], True, "read-only boundary")
    expect(spec["mutationAuthorized"], False, "mutation boundary")
    if not spec.get("grantID"):
        raise PreflightV2Error("grant ID is missing")
    issued, expires = V1.parse_time(spec["issuedAt"]), V1.parse_time(spec["expiresAt"])
    if not issued <= now <= expires or expires - issued > dt.timedelta(minutes=15):
        raise PreflightV2Error("grant is outside its maximum 15-minute window")


def get_exact(query: dict[str, Any], kubeconfig: Path, runner: Callable[..., Any]) -> bytes:
    completed = runner(build_command(query, str(kubeconfig)), stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if completed.returncode != 0:
        raise PreflightV2Error(f"exact GET failed for {query['id']}")
    return completed.stdout


def run_preflight(candidate_path: Path, grant_path: Path, now: dt.datetime, runner: Callable[..., Any] = subprocess.run) -> dict[str, Any]:
    candidate, v1, closure = validate_candidate(candidate_path)
    client = verify_client(runner)
    credential_paths = {item["plane"]: Path(item["path"]) for item in v1["spec"]["credentials"]}
    identities = {plane: V1.inspect_credential(path) for plane, path in credential_paths.items()}
    expect(identities, closure["spec"]["identities"], "current credential identities")
    grant = read(grant_path)
    validate_grant(candidate_path, grant, identities, now)
    evidence: dict[str, Any] = {
        "apiVersion": "evidence.openkubes.io/v1alpha1",
        "kind": "GO1V6PreflightEvidence",
        "spec": {
            "version": "ok141-go1-v6-preflight-evidence/v2",
            "candidateDigest": sha(candidate_path),
            "sourceV1Digest": V1_CANDIDATE_DIGEST,
            "protocolDigest": V1.EXPECTED_PROTOCOL_DIGEST,
            "client": client,
            "grantID": grant["spec"]["grantID"],
            "observedAt": now.isoformat().replace("+00:00", "Z"),
            "credentialIdentityDigests": {plane: value["identityDigest"] for plane, value in identities.items()},
            "mutationPerformed": False,
            "secretBodiesRetained": False,
            "result": "STARTED",
        },
    }
    try:
        absence_results, absent_claims = [], []
        for query in v1["spec"]["absenceQueries"]:
            payload = get_exact(query, credential_paths[query["plane"]], runner)
            if payload.strip():
                raise PreflightV2Error(f"create target is present: {query['id']}")
            absence_results.append({"id": query["id"], "plane": query["plane"], "result": "ABSENT", "proofRule": query["proofRule"]})
            absent_claims.extend(query["provesClaims"])
        readiness_results = []
        for query in v1["spec"]["readinessQueries"]:
            payload = get_exact(query, credential_paths[query["plane"]], runner)
            if not payload.strip():
                raise PreflightV2Error(f"prerequisite is absent: {query['id']}")
            result = V1.evaluate_readiness(json.loads(payload), query["rule"])
            readiness_results.append({"id": query["id"], "plane": query["plane"], **result})
        evidence["spec"].update({
            "absence": absence_results,
            "absenceClaims": [{"id": claim, "result": "ABSENT"} for claim in absent_claims],
            "readiness": readiness_results,
            "result": v1["spec"]["acceptance"]["successState"],
            "freshUntil": (now + dt.timedelta(minutes=candidate["spec"]["evidence"]["freshnessMinutes"])).isoformat().replace("+00:00", "Z"),
        })
        return evidence
    except Exception as error:
        evidence["spec"].update({"result": "STOP-FAIL-CLOSED", "failureType": type(error).__name__, "failure": str(error)})
        raise
    finally:
        V1.write_exclusive(Path(candidate["spec"]["evidence"]["rawLocalPath"]), evidence)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "plan", "run"))
    parser.add_argument("--candidate", type=Path, default=CANDIDATE)
    parser.add_argument("--grant", type=Path)
    args = parser.parse_args()
    try:
        candidate_path = args.candidate.resolve()
        if args.command == "verify":
            candidate, _, _ = validate_candidate(candidate_path)
            result = {"candidateDigest": sha(candidate_path), "state": candidate["spec"]["state"], "clusterContacted": False}
        elif args.command == "plan":
            result = plan(candidate_path)
        else:
            if args.grant is None:
                raise PreflightV2Error("run requires a separate v2 grant")
            result = run_preflight(candidate_path, args.grant.resolve(), dt.datetime.now(dt.timezone.utc))
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (PreflightV2Error, V1.PreflightError, OSError, KeyError, TypeError, ValueError, yaml.YAMLError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
