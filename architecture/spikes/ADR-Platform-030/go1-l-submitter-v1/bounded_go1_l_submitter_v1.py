#!/usr/bin/env python3
"""Digest-bound GO1-L submitter. The merged candidate remains NO-GO."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import yaml


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
HARNESS = SPIKE / "harness"
REPOSITORY = SPIKE.parents[2]
CANDIDATE = HERE / "go1-l-submitter-candidate-v1.yaml"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


V4 = load_module("ok141_phase_r_v4_go1_l_submitter", HARNESS / "ok141_phase_r_v4.py")
V1 = V4.V1


class SubmitterError(ValueError):
    pass


@dataclass(frozen=True)
class ReviewedOperation:
    operation_id: str
    stage: str
    target_plane: str
    documents: list[dict[str, Any]]
    payload: bytes

    @property
    def semantic_digest(self) -> str:
        return V1.semantic_revision(self.documents)

    @property
    def raw_digest(self) -> str:
        return V1.sha256_bytes(self.payload)


def sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def expect(actual: Any, expected: Any, context: str) -> None:
    if actual != expected:
        raise SubmitterError(f"{context}: expected {expected!r}, got {actual!r}")


def resolve(candidate_path: Path, requested: str) -> Path:
    path = (candidate_path.parent / requested).resolve()
    if SPIKE.resolve() not in path.parents or not path.is_file():
        raise SubmitterError(f"reference missing or outside spike root: {requested}")
    return path


def documents(path: Path) -> list[dict[str, Any]]:
    try:
        return [item for item in yaml.load_all(path.read_text(), Loader=V1.UniqueKeyLoader) if item]
    except yaml.YAMLError as error:
        raise SubmitterError(f"cannot parse {path}: {error}") from error


def identity(item: dict[str, Any]) -> str:
    metadata = item.get("metadata", {})
    namespace = metadata.get("namespace", "_")
    return f"{item.get('apiVersion')}|{item.get('kind')}|{namespace}|{metadata.get('name')}"


def load_candidate(path: Path = CANDIDATE) -> dict[str, Any]:
    return V1.read_yaml_or_json(path)


def validate_candidate(candidate: dict[str, Any], candidate_path: Path = CANDIDATE) -> dict[str, ReviewedOperation]:
    expect(candidate.get("apiVersion"), "execution.openkubes.io/v1alpha1", "apiVersion")
    expect(candidate.get("kind"), "GO1LSubmitterCandidate", "kind")
    spec = candidate["spec"]
    expect(spec["version"], "ok141-go1-l-submitter/v1", "candidate version")
    expect(spec["state"], "OFFLINE-PROVEN-BLOCKED-NO-GO", "candidate state")
    authorization = spec["authorization"]
    expect(authorization["decision"], "NO-GO", "authorization decision")
    expect(authorization["currentGrantBound"], False, "current grant")
    expect(authorization["mutationAuthorized"], False, "mutation authority")
    expect(authorization["go1LGranted"], False, "GO1-L authority")
    expect(authorization["retryGranted"], False, "retry authority")
    expect(authorization["rollbackOrCleanupGranted"], False, "rollback authority")

    source = spec["sourceProtocol"]
    protocol_path = resolve(candidate_path, source["path"])
    expect(sha(protocol_path), source["digest"], "GO-1 protocol digest")
    protocol = V1.read_yaml_or_json(protocol_path)
    expect(protocol["spec"]["protocolState"], "BLOCKED", "GO-1 protocol state")
    expect(protocol["spec"]["authorization"]["decision"], "NO-GO", "GO-1 protocol decision")
    tool = spec["tool"]
    tool_path = resolve(candidate_path, tool["path"])
    expect(sha(tool_path), tool["digest"], "submitter tool digest")
    expect(tool["arbitraryManifestPathAllowed"], False, "manifest-path boundary")
    expect(tool["arbitraryCommandAllowed"], False, "command boundary")

    expected_order = ["provider-prerequisites", "capi-lifecycle", "helmchartproxy"]
    expect([item["id"] for item in spec["operations"]], expected_order, "operation ordering")
    expect([item["sequence"] for item in spec["operations"]], [1, 2, 3], "operation sequence")
    expect([item["stage"] for item in spec["operations"]], ["G1", "G1", "G3"], "operation stages")
    expect([item["predecessorEvidenceRequired"] for item in spec["operations"]], [False, True, True], "predecessor boundary")
    reviewed: dict[str, ReviewedOperation] = {}
    for operation in spec["operations"]:
        path = resolve(candidate_path, operation["path"])
        docs = documents(path)
        expect(len(docs), operation["objectCount"], f"{operation['id']} object count")
        expect(V1.semantic_revision(docs), operation["semanticDigest"], f"{operation['id']} semantic digest")
        if operation.get("rawDigest") is not None:
            expect(sha(path), operation["rawDigest"], f"{operation['id']} raw digest")
        expect(sorted(identity(item) for item in docs), sorted(operation["objectIdentities"]), f"{operation['id']} identities")
        if any(item.get("metadata", {}).get("annotations", {}).get("openkubes.io/intent-revision") != source["R"] for item in docs):
            raise SubmitterError(f"{operation['id']} lacks current R carrier")
        reviewed[operation["id"]] = ReviewedOperation(
            operation_id=operation["id"],
            stage=operation["stage"],
            target_plane=operation["targetPlane"],
            documents=docs,
            payload=path.read_bytes(),
        )

    expect(reviewed["provider-prerequisites"].target_plane, "ok-infra", "provider authority")
    expect(reviewed["capi-lifecycle"].target_plane, "ok-mgmt", "CAPI authority")
    expect(reviewed["helmchartproxy"].target_plane, "ok-mgmt", "HCP authority")
    expect(spec["transport"]["operation"], "CreateReviewedObjectSet", "transport operation")
    expect(spec["transport"]["createOnly"], True, "create-only boundary")
    expect(spec["transport"]["serverSideApply"], False, "apply boundary")
    expect(spec["transport"]["freeFormArgumentsAllowed"], False, "argument boundary")
    expect(spec["transport"]["automaticRetryAllowed"], False, "retry boundary")
    expect(spec["transport"]["automaticRollbackAllowed"], False, "rollback boundary")
    return reviewed


def build_plan(candidate: dict[str, Any], candidate_path: Path, operation_id: str, credential_file: Path | None = None) -> dict[str, Any]:
    reviewed = validate_candidate(candidate, candidate_path)
    if operation_id not in reviewed:
        raise SubmitterError("unsupported operation")
    operation = reviewed[operation_id]
    command = [
        "kubectl",
        "--kubeconfig",
        str(credential_file) if credential_file else f"RUNTIME-CREDENTIAL-FILE:{operation.target_plane}",
        "create",
        "--filename",
        "-",
    ]
    return {
        "operation": operation.operation_id,
        "stage": operation.stage,
        "targetPlane": operation.target_plane,
        "objectCount": len(operation.documents),
        "semanticDigest": operation.semantic_digest,
        "rawDigest": operation.raw_digest,
        "command": command,
        "mutationAuthorized": False,
        "clusterContacted": False,
    }


def parse_time(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise SubmitterError("timestamp must include a timezone")
    return parsed


def contains_secret_field(value: Any) -> bool:
    forbidden = {
        "token", "kubeconfig", "clientkey", "clientkeydata", "clientcertificatedata",
        "certificateauthoritydata", "password", "secretdata", "stringdata", "data",
    }
    if isinstance(value, dict):
        return any(
            str(key).lower().replace("-", "").replace("_", "") in forbidden or contains_secret_field(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(contains_secret_field(item) for item in value)
    return False


def validate_runtime_authority(
    candidate: dict[str, Any],
    candidate_path: Path,
    operation_id: str,
    grant: dict[str, Any],
    receipt: dict[str, Any],
    receipt_path: Path,
    credential_file: Path,
    now: dt.datetime,
) -> None:
    expected_candidate = sha(candidate_path)
    expected_protocol = candidate["spec"]["sourceProtocol"]["digest"]
    grant_spec = grant["spec"]
    expect(grant_spec["decision"], "GO", "grant decision")
    expect(grant_spec["mutationAuthorized"], True, "grant mutation authority")
    expect(grant_spec["go1LGranted"], True, "grant GO1-L authority")
    expect(grant_spec["operationGranted"], operation_id, "grant operation")
    expect(grant_spec["candidateDigest"], expected_candidate, "grant candidate")
    expect(grant_spec["protocolDigest"], expected_protocol, "grant protocol")
    if contains_secret_field(grant):
        raise SubmitterError("operation grant contains a secret-bearing field")
    if not grant_spec.get("grantID") or grant_spec.get("singleRun") is not True:
        raise SubmitterError("grant identity or single-run boundary is missing")
    issued = parse_time(grant_spec["issuedAt"])
    expires = parse_time(grant_spec["expiresAt"])
    if not issued <= now <= expires or expires - issued > dt.timedelta(minutes=20):
        raise SubmitterError("grant is outside its maximum 20-minute window")
    operation = next(item for item in candidate["spec"]["operations"] if item["id"] == operation_id)
    predecessors = grant_spec["predecessorEvidenceDigests"]
    if operation["predecessorEvidenceRequired"] and (len(predecessors) != 1 or not predecessors[0].startswith("sha256:")):
        raise SubmitterError("operation requires exactly one predecessor evidence digest")
    if not operation["predecessorEvidenceRequired"] and predecessors:
        raise SubmitterError("first operation cannot carry predecessor evidence")
    expect(sha(receipt_path), grant_spec["credentialReceiptDigest"], "credential receipt binding")
    receipt_spec = receipt["spec"]
    expect(receipt_spec["targetPlane"], operation["targetPlane"], "credential target")
    expect(receipt_spec["operation"], operation_id, "credential operation")
    expect(receipt_spec["tokenBytesPersisted"], False, "credential persistence")
    expect(receipt_spec["tokenBytesEmitted"], False, "credential emission")
    if parse_time(receipt_spec["issuedAt"]) > now or not now <= parse_time(receipt_spec["expiresAt"]) <= expires:
        raise SubmitterError("credential outlives its operation grant")
    if contains_secret_field(receipt):
        raise SubmitterError("credential receipt contains a secret-bearing field")
    if not credential_file.is_file() or credential_file.is_symlink() or credential_file.stat().st_size == 0:
        raise SubmitterError("credential file must be a regular non-symlink file")
    if stat.S_IMODE(credential_file.stat().st_mode) != 0o600:
        raise SubmitterError("credential file mode must be 0600")
    if REPOSITORY.resolve() in credential_file.resolve().parents:
        raise SubmitterError("credential file must remain outside the repository")


def execute_once(
    candidate: dict[str, Any],
    candidate_path: Path,
    operation_id: str,
    grant: dict[str, Any],
    receipt: dict[str, Any],
    receipt_path: Path,
    credential_file: Path,
    now: dt.datetime,
    runner: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    reviewed = validate_candidate(candidate, candidate_path)[operation_id]
    validate_runtime_authority(candidate, candidate_path, operation_id, grant, receipt, receipt_path, credential_file, now)
    command = ["kubectl", "--kubeconfig", str(credential_file), "create", "--filename", "-"]
    completed = runner(command, input=reviewed.payload, check=True, capture_output=True)
    return {
        "operation": operation_id,
        "targetPlane": reviewed.target_plane,
        "objectCount": len(reviewed.documents),
        "semanticDigest": reviewed.semantic_digest,
        "transportExitCode": completed.returncode,
        "credentialBytesEmitted": False,
        "retryPerformed": False,
        "rollbackOrCleanupPerformed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "plan"))
    parser.add_argument("--candidate", type=Path, default=CANDIDATE)
    parser.add_argument("--operation", choices=("provider-prerequisites", "capi-lifecycle", "helmchartproxy"))
    args = parser.parse_args()
    try:
        path = args.candidate.resolve()
        candidate = load_candidate(path)
        reviewed = validate_candidate(candidate, path)
        if args.command == "verify":
            result = {
                "candidateDigest": sha(path),
                "state": candidate["spec"]["state"],
                "operations": len(reviewed),
                "objects": sum(len(item.documents) for item in reviewed.values()),
                "mutationAuthorized": False,
                "clusterContacted": False,
            }
        else:
            if args.operation is None:
                raise SubmitterError("plan requires --operation")
            result = build_plan(candidate, path, args.operation)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (KeyError, OSError, SubmitterError, TypeError, ValueError, yaml.YAMLError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
