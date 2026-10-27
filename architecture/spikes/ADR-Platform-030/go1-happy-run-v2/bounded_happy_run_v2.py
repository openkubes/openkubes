#!/usr/bin/env python3
"""Additive v2 adapter for the GO1-L preflight identity view."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
CANDIDATE = HERE / "happy-run-candidate-v2.yaml"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(value)
    return value


V1 = load_module("ok141_happy_run_v1_for_v2", SPIKE / "go1-happy-run-v1" / "bounded_happy_run_v1.py")
V1_CANDIDATE = SPIKE / "go1-happy-run-v1" / "happy-run-candidate-v1.yaml"
V1_CANDIDATE_DIGEST = "sha256:2792206fca811633ec7f30cc5fd04814802fe4cf20645bb888cb9e13aca784e6"
GO1L_PLANES = {"ok-infra", "ok-mgmt"}


class HappyRunV2Error(ValueError):
    pass


def sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text())
    if not isinstance(value, dict):
        raise HappyRunV2Error(f"expected mapping: {path}")
    return value


def expect(actual: Any, expected: Any, context: str) -> None:
    if actual != expected:
        raise HappyRunV2Error(f"{context}: expected {expected!r}, got {actual!r}")


def write_exclusive(path: Path, value: Any) -> None:
    raw = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)


def validate_candidate(candidate_path: Path = CANDIDATE) -> dict[str, Any]:
    candidate = read(candidate_path)
    expect(candidate.get("kind"), "GO1HappyRunCandidate", "kind")
    spec = candidate["spec"]
    expect(spec["version"], "ok141-go1-happy-run/v2", "version")
    expect(spec["state"], "OFFLINE-PROVEN-BLOCKED-NO-GO", "state")
    expect(sha(V1_CANDIDATE), V1_CANDIDATE_DIGEST, "v1 candidate")
    expect(spec["supersedes"]["digest"], V1_CANDIDATE_DIGEST, "v1 binding")
    V1.validate_candidate(V1_CANDIDATE)
    expect(sha(HERE / spec["tool"]["path"]), spec["tool"]["digest"], "v2 tool")
    expect(spec["amendment"]["sourceCredentialPlanes"], ["ok-infra", "ok-mgmt", "ok-shared"], "source planes")
    expect(spec["amendment"]["go1LProjectionPlanes"], ["ok-infra", "ok-mgmt"], "projection planes")
    if any(spec["authorization"].get(key) for key in spec["authorization"] if key.endswith("Granted")):
        raise HappyRunV2Error("candidate grants authority")
    return candidate


def validate_grant(candidate_path: Path, grant_path: Path) -> dict[str, Any]:
    validate_candidate(candidate_path)
    grant = read(grant_path)
    adapted = deepcopy(grant)
    adapted["spec"]["candidateDigest"] = V1_CANDIDATE_DIGEST
    V1.validate_grant(V1_CANDIDATE, _temporary_json(adapted, "grant-validation"))
    expect(grant["spec"]["candidateDigest"], sha(candidate_path), "v2 grant candidate")
    return grant


def _temporary_json(value: dict[str, Any], label: str) -> Path:
    identity = hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:16]
    path = Path(f"/private/tmp/ok141-happy-v2-{label}-{identity}.json")
    if not path.exists():
        write_exclusive(path, value)
    return path


def project_preflight(source: Path, destination: Path) -> Path:
    value = json.loads(source.read_text())
    identities = value["spec"]["credentialIdentityDigests"]
    if set(identities) != {"ok-infra", "ok-mgmt", "ok-shared"}:
        raise HappyRunV2Error("source preflight identity planes mismatch")
    projected = deepcopy(value)
    projected["spec"]["credentialIdentityDigests"] = {key: identities[key] for key in sorted(GO1L_PLANES)}
    projected["spec"]["sourceEvidenceDigest"] = sha(source)
    projected["spec"]["projection"] = "ok141-go1l-preflight-identity-view/v1"
    if destination.exists():
        existing = json.loads(destination.read_text())
        if existing != projected:
            raise HappyRunV2Error("existing projected preflight differs")
    else:
        write_exclusive(destination, projected)
    return destination


def amended_stage_grant(source: Path, projected_preflight: Path, destination: Path) -> Path:
    value = json.loads(source.read_text())
    value["spec"]["preflightEvidenceDigest"] = sha(projected_preflight)
    write_exclusive(destination, value)
    return destination


def execute(candidate_path: Path, grant_path: Path, capability_script: Path) -> dict[str, Any]:
    outer = validate_grant(candidate_path, grant_path)
    adapted = deepcopy(outer); adapted["spec"]["candidateDigest"] = V1_CANDIDATE_DIGEST
    adapted_path = _temporary_json(adapted, "adapted-outer-grant")
    run_id = outer["spec"]["runID"]
    projection_path = Path(f"/private/tmp/ok141-go1l-preflight-view-{run_id}.json")
    original_g1, original_g3 = V1.RUNTIME.execute_g1, V1.RUNTIME.execute_g3

    def execute_g1(candidate, stage_grant, preflight, now):
        projected = project_preflight(preflight, projection_path)
        amended = amended_stage_grant(stage_grant, projected, Path(f"/private/tmp/ok141-g1-amended-grant-{run_id}.json"))
        return original_g1(candidate, amended, projected, now)

    def execute_g3(candidate, stage_grant, preflight, lifecycle, now):
        projected = project_preflight(preflight, projection_path)
        amended = amended_stage_grant(stage_grant, projected, Path(f"/private/tmp/ok141-g3-amended-grant-{run_id}.json"))
        return original_g3(candidate, amended, projected, lifecycle, now)

    V1.RUNTIME.execute_g1, V1.RUNTIME.execute_g3 = execute_g1, execute_g3
    try:
        result = V1.execute(V1_CANDIDATE, adapted_path, capability_script)
    finally:
        V1.RUNTIME.execute_g1, V1.RUNTIME.execute_g3 = original_g1, original_g3
    result["candidateDigest"] = sha(candidate_path)
    result["preflightProjectionDigest"] = sha(projection_path)
    result["supersededCandidateDigest"] = V1_CANDIDATE_DIGEST
    return result


def plan(candidate_path: Path = CANDIDATE) -> dict[str, Any]:
    candidate = validate_candidate(candidate_path)
    return {"candidateDigest": sha(candidate_path), "supersedes": V1_CANDIDATE_DIGEST, "amendment": candidate["spec"]["amendment"], "authorization": "NO-GO", "clusterContacted": False}


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("command", choices=("verify", "verify-grant", "run")); parser.add_argument("--candidate", type=Path, default=CANDIDATE); parser.add_argument("--grant", type=Path); parser.add_argument("--capability-script", type=Path); parser.add_argument("--execute", action="store_true"); args = parser.parse_args()
    try:
        if args.command == "verify": print(json.dumps(plan(args.candidate.resolve()), indent=2, sort_keys=True))
        elif args.command == "verify-grant":
            if args.grant is None: raise HappyRunV2Error("grant required")
            validate_grant(args.candidate.resolve(), args.grant.resolve()); print(sha(args.grant.resolve()))
        else:
            if not args.execute or args.grant is None or args.capability_script is None: raise HappyRunV2Error("run requires --execute, grant and capability script")
            print(json.dumps(execute(args.candidate.resolve(), args.grant.resolve(), args.capability_script.resolve()), indent=2, sort_keys=True))
        return 0
    except Exception as error:
        print(f"ERROR: {type(error).__name__}: {error}", file=sys.stderr); return 2


if __name__ == "__main__": raise SystemExit(main())
