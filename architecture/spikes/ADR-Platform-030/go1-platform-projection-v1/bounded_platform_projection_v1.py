#!/usr/bin/env python3
"""Exact Phase-R v5 projection for the bounded OK-141 platform stages."""

from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import string
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
CANDIDATE = HERE / "platform-projection-candidate-v1.yaml"


class ProjectionError(ValueError):
    pass


def sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(value: Any) -> str:
    return "sha256:" + hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def read(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text())
    if not isinstance(value, dict):
        raise ProjectionError(f"expected mapping: {path}")
    return value


def docs(path: Path) -> list[dict[str, Any]]:
    values = [item for item in yaml.safe_load_all(path.read_text()) if item]
    if not values or any(not isinstance(item, dict) for item in values):
        raise ProjectionError(f"expected YAML documents: {path}")
    return values


def expect(actual: Any, expected: Any, context: str) -> None:
    if actual != expected:
        raise ProjectionError(f"{context}: expected {expected!r}, got {actual!r}")


def resolve(candidate_path: Path, requested: str) -> Path:
    path = (candidate_path.parent / requested).resolve()
    if SPIKE.resolve() not in path.parents or not path.is_file():
        raise ProjectionError(f"reference missing or outside spike root: {requested}")
    return path


def annotate(obj: dict[str, Any], fixture: dict[str, str]) -> None:
    annotations = obj.setdefault("metadata", {}).setdefault("annotations", {})
    annotations["openkubes.io/candidate-status"] = "runtime-bound-no-go"
    annotations["openkubes.io/intent-revision"] = fixture["R"]
    annotations["openkubes.io/platform-revision"] = fixture["P"]
    annotations["openkubes.io/execution-fixture"] = fixture["fixtureDigest"]


def validate_candidate(candidate_path: Path = CANDIDATE) -> dict[str, Any]:
    candidate = read(candidate_path)
    expect(candidate.get("kind"), "GO1PlatformProjectionCandidate", "kind")
    spec = candidate["spec"]
    expect(spec["version"], "ok141-go1-platform-projection/v1", "version")
    expect(spec["state"], "OFFLINE-PROVEN-BLOCKED-NO-GO", "state")
    for binding in spec["sources"].values():
        path = resolve(candidate_path, binding["path"])
        expect(sha(path), binding["digest"], f"source {binding['path']}")
    expect(sha(resolve(candidate_path, spec["tool"]["path"])), spec["tool"]["digest"], "tool")
    target = docs(resolve(candidate_path, spec["sources"]["targetAccess"]["path"]))
    expect(len(target), 8, "target access count")
    applications = docs(resolve(candidate_path, spec["sources"]["applications"]["path"]))
    expect([item["metadata"]["name"] for item in applications], spec["projection"]["applicationNames"], "applications")
    profile = json.loads(resolve(candidate_path, spec["sources"]["profile"]["path"]).read_text())
    expect(profile["requiredSecretContract"], spec["projection"]["requiredSecretContract"], "Secret contract")
    if any(spec["authorization"].get(key) for key in spec["authorization"] if key.endswith("Granted")):
        raise ProjectionError("candidate grants authority")
    return candidate


def target_access(candidate_path: Path = CANDIDATE) -> list[dict[str, Any]]:
    candidate = validate_candidate(candidate_path)
    source = resolve(candidate_path, candidate["spec"]["sources"]["targetAccess"]["path"])
    result = deepcopy(docs(source))
    for item in result:
        annotate(item, candidate["spec"]["fixture"])
    return result


def control_plane(candidate_path: Path = CANDIDATE) -> list[dict[str, Any]]:
    candidate = validate_candidate(candidate_path)
    spec = candidate["spec"]
    project = deepcopy(read(resolve(candidate_path, spec["sources"]["appProject"]["path"])))
    annotate(project, spec["fixture"])
    applications = deepcopy(docs(resolve(candidate_path, spec["sources"]["applications"]["path"])))
    app_digests = {item["name"]: item["applicationDigest"] for item in json.loads(resolve(candidate_path, spec["sources"]["profile"]["path"]).read_text())["requiredApplications"]}
    for item in applications:
        annotate(item, spec["fixture"])
        item["metadata"]["annotations"]["openkubes.io/application-identity"] = app_digests[item["metadata"]["name"]]
    return [project, *applications]


def credential_secret(candidate_path: Path, values: dict[str, str]) -> dict[str, Any]:
    candidate = validate_candidate(candidate_path)
    contract = candidate["spec"]["projection"]["requiredSecretContract"]
    if set(values) != set(contract["keys"]) or any(not isinstance(value, str) or len(value) < 16 for value in values.values()):
        raise ProjectionError("credential values do not satisfy the exact key/length boundary")
    result = {"apiVersion": "v1", "kind": "Secret", "metadata": {"name": contract["name"], "namespace": contract["namespace"]}, "type": "Opaque", "stringData": dict(values)}
    annotate(result, candidate["spec"]["fixture"])
    return result


def generate_credentials(candidate_path: Path = CANDIDATE) -> dict[str, str]:
    alphabet = string.ascii_letters + string.digits + "-_"
    keys = validate_candidate(candidate_path)["spec"]["projection"]["requiredSecretContract"]["keys"]
    result = {key: "".join(secrets.choice(alphabet) for _ in range(32)) for key in keys}
    result["grafana-admin-user"] = "ok141-admin-" + "".join(secrets.choice(string.ascii_lowercase) for _ in range(8))
    return result


def projection_summary(candidate_path: Path = CANDIDATE) -> dict[str, Any]:
    target = target_access(candidate_path)
    control = control_plane(candidate_path)
    synthetic = {key: "x" * 20 for key in validate_candidate(candidate_path)["spec"]["projection"]["requiredSecretContract"]["keys"]}
    secret = credential_secret(candidate_path, synthetic)
    return {"candidateDigest": sha(candidate_path), "targetAccess": {"objects": len(target), "semanticDigest": canonical(target)}, "controlPlane": {"objects": len(control), "semanticDigest": canonical(control)}, "credentialSecret": {"objects": 1, "semanticShapeDigest": canonical({**secret, "stringData": sorted(secret["stringData"])})}, "totalPersistentObjects": len(target) + len(control) + 2, "authorization": "NO-GO", "clusterContacted": False}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "render-redacted"))
    parser.add_argument("--candidate", type=Path, default=CANDIDATE)
    args = parser.parse_args()
    try:
        result = projection_summary(args.candidate.resolve())
        if args.command == "render-redacted":
            result["objectIdentities"] = [f"{item['kind']}/{item['metadata']['name']}" for item in target_access(args.candidate.resolve()) + control_plane(args.candidate.resolve())] + ["Secret/ok-observability-credentials", "Secret/disposable-ok141-cluster"]
        print(json.dumps(result, indent=2, sort_keys=True)); return 0
    except (ProjectionError, KeyError, OSError, TypeError, ValueError, yaml.YAMLError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr); return 2


if __name__ == "__main__":
    raise SystemExit(main())
