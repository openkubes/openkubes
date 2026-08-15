#!/usr/bin/env python3
"""Phase-R-v5-bound GO1-L submitter. The merged candidate remains NO-GO."""

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
CANDIDATE = HERE / "go1-l-submitter-candidate-v2.yaml"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


V5 = load_module("ok141_phase_r_v5_go1_l_submitter", HARNESS / "ok141_phase_r_v5.py")
V1 = V5.V1


class SubmitterError(ValueError):
    pass


@dataclass(frozen=True)
class ReviewedOperation:
    operation_id: str
    stage: str
    target_plane: str
    documents: list[dict[str, Any]]
    payload: bytes
    predecessor_evidence_count: int
    runtime_eligible: bool

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


def serialized(items: list[dict[str, Any]]) -> bytes:
    return yaml.safe_dump_all(items, sort_keys=False, explicit_start=True).encode()


def load_candidate(path: Path = CANDIDATE) -> dict[str, Any]:
    return V1.read_yaml_or_json(path)


def validate_candidate(candidate: dict[str, Any], candidate_path: Path = CANDIDATE) -> dict[str, ReviewedOperation]:
    expect(candidate.get("apiVersion"), "execution.openkubes.io/v1alpha1", "apiVersion")
    expect(candidate.get("kind"), "GO1LSubmitterCandidate", "kind")
    spec = candidate["spec"]
    expect(spec["version"], "ok141-go1-l-submitter/v2", "candidate version")
    expect(spec["state"], "OFFLINE-PROVEN-BLOCKED-NO-GO", "candidate state")

    authorization = spec["authorization"]
    expect(authorization, {
        "decision": "NO-GO",
        "currentGrantBound": False,
        "mutationAuthorized": False,
        "recreationGranted": False,
        "go1LGranted": False,
        "retryGranted": False,
        "rollbackOrCleanupGranted": False,
    }, "authorization")

    preflight_ref = spec["sourcePreflight"]
    preflight_path = resolve(candidate_path, preflight_ref["path"])
    expect(sha(preflight_path), preflight_ref["digest"], "recreation preflight digest")
    preflight = V1.read_yaml_or_json(preflight_path)["spec"]
    expect(preflight["state"], "OFFLINE-PREPARED-BLOCKED-NO-GO", "preflight state")
    if any(preflight["authorization"].values()):
        raise SubmitterError("source preflight grants authority")

    fixture_ref = spec["fixture"]
    fixture_path = resolve(candidate_path, fixture_ref["path"])
    expect(sha(fixture_path), fixture_ref["fileDigest"], "fixture file digest")
    fixture = V1.read_yaml_or_json(fixture_path)
    expect(fixture["fixtureVersion"], "phase-r-v5", "fixture version")
    expect(fixture["fixtureDigest"], fixture_ref["fixtureDigest"], "fixture digest")
    expect(fixture["contract"]["R"], fixture_ref["R"], "fixture R")
    expect(fixture["enablement"]["E"], fixture_ref["E"], "fixture E")
    expect(fixture["platform"]["P"], fixture_ref["P"], "fixture P")
    expect(fixture["authorizationState"], "NO-GO", "fixture authorization")
    preflight_fixture = preflight["correctedFixture"]
    for key in ("fileDigest", "fixtureDigest", "R", "E", "P"):
        expect(fixture_ref[key], preflight_fixture[key], f"preflight fixture {key}")

    tool = spec["tool"]
    tool_path = resolve(candidate_path, tool["path"])
    expect(sha(tool_path), tool["digest"], "submitter tool digest")
    expect(tool["arbitraryManifestPathAllowed"], False, "manifest-path boundary")
    expect(tool["arbitraryCommandAllowed"], False, "command boundary")

    expected_ids = ["provider-prerequisites", "management-namespace", "capi-lifecycle", "helmchartproxy"]
    operations = spec["operations"]
    expect([item["id"] for item in operations], expected_ids, "operation ordering")
    expect([item["sequence"] for item in operations], [1, 2, 4, 5], "operation sequence")
    expect([item["predecessorEvidenceCount"] for item in operations], [0, 1, 2, 1], "predecessor counts")

    reviewed: dict[str, ReviewedOperation] = {}
    source_documents: dict[Path, list[dict[str, Any]]] = {}
    selected_by_source: dict[Path, list[int]] = {}
    for operation in operations:
        source_path = resolve(candidate_path, operation["path"])
        expect(sha(source_path), operation["sourceRawDigest"], f"{operation['id']} source digest")
        all_docs = source_documents.setdefault(source_path, documents(source_path))
        indices = operation.get("documentIndices", list(range(len(all_docs))))
        if not indices or len(indices) != len(set(indices)) or any(not isinstance(i, int) or i < 0 or i >= len(all_docs) for i in indices):
            raise SubmitterError(f"{operation['id']} has invalid document indices")
        selected_by_source.setdefault(source_path, []).extend(indices)
        docs = [all_docs[index] for index in indices]
        payload = source_path.read_bytes() if indices == list(range(len(all_docs))) else serialized(docs)
        expect(len(docs), operation["objectCount"], f"{operation['id']} object count")
        expect(V1.semantic_revision(docs), operation["semanticDigest"], f"{operation['id']} semantic digest")
        expect(V1.sha256_bytes(payload), operation["payloadRawDigest"], f"{operation['id']} payload digest")
        expect([identity(item) for item in docs], operation["objectIdentities"], f"{operation['id']} identities")
        if any(item.get("kind") == "Secret" for item in docs):
            raise SubmitterError("static submitter operation contains a Secret")
        reviewed[operation["id"]] = ReviewedOperation(
            operation_id=operation["id"],
            stage=operation["stage"],
            target_plane=operation["targetPlane"],
            documents=docs,
            payload=payload,
            predecessor_evidence_count=operation["predecessorEvidenceCount"],
            runtime_eligible=operation["runtimeEligible"],
        )

    lifecycle_path = resolve(candidate_path, operations[1]["path"])
    expect(operations[2]["path"], operations[1]["path"], "lifecycle slice source")
    expect(sorted(selected_by_source[lifecycle_path]), list(range(8)), "lifecycle slice coverage")
    expect(len(selected_by_source[lifecycle_path]), 8, "lifecycle slice overlap")
    expect(V1.semantic_revision(source_documents[lifecycle_path]), spec["combinedManagementProjectionSemanticDigest"], "combined lifecycle semantic identity")
    kubevirt_cluster = next(item for item in reviewed["capi-lifecycle"].documents if item.get("kind") == "KubevirtCluster")
    expect(kubevirt_cluster["spec"]["infraClusterSecretRef"], spec["externalPrerequisite"]["secretRef"], "provider Secret reference")
    expect(spec["externalPrerequisite"]["sequence"], 3, "provider Secret sequence")
    expect(spec["externalPrerequisite"]["executedByThisTool"], False, "provider Secret tool boundary")

    current_r = fixture_ref["R"]
    expect(spec["hcpBoundary"]["expectedCurrentR"], current_r, "HCP expected R")
    expect(spec["hcpBoundary"]["expectedCurrentFixtureDigest"], fixture_ref["fixtureDigest"], "HCP expected fixture")
    for operation_id in ("provider-prerequisites", "management-namespace", "capi-lifecycle"):
        if any(item.get("metadata", {}).get("annotations", {}).get("openkubes.io/intent-revision") != current_r for item in reviewed[operation_id].documents):
            raise SubmitterError(f"{operation_id} lacks current R carrier")
    hcp = reviewed["helmchartproxy"].documents[0]
    expect(hcp["metadata"]["annotations"]["openkubes.io/enablement-revision"], fixture_ref["E"], "HCP E carrier")
    expect(hcp["metadata"]["annotations"]["openkubes.io/intent-revision"], spec["hcpBoundary"]["observedHistoricalR"], "HCP observed R")
    expect(hcp["metadata"]["annotations"]["openkubes.io/execution-fixture"], spec["hcpBoundary"]["observedHistoricalFixtureDigest"], "HCP observed fixture")
    if hcp["metadata"]["annotations"]["openkubes.io/intent-revision"] == current_r:
        raise SubmitterError("HCP historical-carrier negative control no longer holds")
    if hcp["metadata"]["annotations"]["openkubes.io/execution-fixture"] == fixture_ref["fixtureDigest"]:
        raise SubmitterError("HCP historical-fixture negative control no longer holds")
    expect(reviewed["helmchartproxy"].runtime_eligible, False, "stale HCP runtime boundary")
    expect(spec["hcpBoundary"]["closure"], "ADDITIVE-CURRENT-R-HCP-REQUIRED", "HCP closure")

    expect(reviewed["provider-prerequisites"].target_plane, "ok-infra", "provider authority")
    for operation_id in ("management-namespace", "capi-lifecycle", "helmchartproxy"):
        expect(reviewed[operation_id].target_plane, "ok-mgmt", f"{operation_id} authority")
    expect(spec["transport"], {
        "operation": "CreateReviewedObjectSet",
        "createOnly": True,
        "serverSideApply": False,
        "stdinPayloadOnly": True,
        "freeFormArgumentsAllowed": False,
        "automaticRetryAllowed": False,
        "automaticRollbackAllowed": False,
        "partialStateOnFailure": "STOP-PRESERVE-NO-CLEANUP",
    }, "transport")
    return reviewed


def build_plan(candidate: dict[str, Any], candidate_path: Path, operation_id: str, credential_file: Path | None = None) -> dict[str, Any]:
    reviewed = validate_candidate(candidate, candidate_path)
    if operation_id not in reviewed:
        raise SubmitterError("unsupported operation")
    operation = reviewed[operation_id]
    return {
        "operation": operation.operation_id,
        "stage": operation.stage,
        "targetPlane": operation.target_plane,
        "objectCount": len(operation.documents),
        "semanticDigest": operation.semantic_digest,
        "rawDigest": operation.raw_digest,
        "predecessorEvidenceCount": operation.predecessor_evidence_count,
        "runtimeEligible": operation.runtime_eligible,
        "command": ["kubectl", "--kubeconfig", str(credential_file) if credential_file else f"RUNTIME-CREDENTIAL-FILE:{operation.target_plane}", "create", "--filename", "-"],
        "mutationAuthorized": False,
        "clusterContacted": False,
    }


def parse_time(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise SubmitterError("timestamp must include a timezone")
    return parsed


def contains_secret_field(value: Any) -> bool:
    forbidden = {"token", "kubeconfig", "clientkey", "clientkeydata", "clientcertificatedata", "certificateauthoritydata", "password", "secretdata", "stringdata", "data"}
    if isinstance(value, dict):
        return any(str(key).lower().replace("-", "").replace("_", "") in forbidden or contains_secret_field(item) for key, item in value.items())
    if isinstance(value, list):
        return any(contains_secret_field(item) for item in value)
    return False


def validate_runtime_authority(candidate: dict[str, Any], candidate_path: Path, operation_id: str, grant: dict[str, Any], receipt: dict[str, Any], receipt_path: Path, credential_file: Path, now: dt.datetime) -> None:
    reviewed = validate_candidate(candidate, candidate_path)
    if operation_id not in reviewed or not reviewed[operation_id].runtime_eligible:
        raise SubmitterError("operation is not runtime eligible")
    operation = reviewed[operation_id]
    grant_spec = grant["spec"]
    expect(grant_spec["decision"], "GO", "grant decision")
    expect(grant_spec["mutationAuthorized"], True, "grant mutation authority")
    expect(grant_spec["go1LGranted"], True, "grant GO1-L authority")
    expect(grant_spec["operationGranted"], operation_id, "grant operation")
    expect(grant_spec["candidateDigest"], sha(candidate_path), "grant candidate")
    expect(grant_spec["fixtureDigest"], candidate["spec"]["fixture"]["fixtureDigest"], "grant fixture")
    expect(grant_spec["preflightDigest"], candidate["spec"]["sourcePreflight"]["digest"], "grant preflight")
    if contains_secret_field(grant) or contains_secret_field(receipt):
        raise SubmitterError("grant or receipt contains a secret-bearing field")
    if not grant_spec.get("grantID") or grant_spec.get("singleRun") is not True:
        raise SubmitterError("grant identity or single-run boundary is missing")
    issued, expires = parse_time(grant_spec["issuedAt"]), parse_time(grant_spec["expiresAt"])
    if not issued <= now <= expires or expires - issued > dt.timedelta(minutes=20):
        raise SubmitterError("grant is outside its maximum 20-minute window")
    predecessors = grant_spec["predecessorEvidenceDigests"]
    if len(predecessors) != operation.predecessor_evidence_count or any(not item.startswith("sha256:") for item in predecessors):
        raise SubmitterError("predecessor evidence count or digest is invalid")
    expect(sha(receipt_path), grant_spec["credentialReceiptDigest"], "credential receipt binding")
    receipt_spec = receipt["spec"]
    expect(receipt_spec["targetPlane"], operation.target_plane, "credential target")
    expect(receipt_spec["operation"], operation_id, "credential operation")
    expect(receipt_spec["tokenBytesPersisted"], False, "credential persistence")
    expect(receipt_spec["tokenBytesEmitted"], False, "credential emission")
    if parse_time(receipt_spec["issuedAt"]) > now or not now <= parse_time(receipt_spec["expiresAt"]) <= expires:
        raise SubmitterError("credential outlives its operation grant")
    if not credential_file.is_file() or credential_file.is_symlink() or credential_file.stat().st_size == 0:
        raise SubmitterError("credential file must be a regular non-symlink file")
    if stat.S_IMODE(credential_file.stat().st_mode) != 0o600:
        raise SubmitterError("credential file mode must be 0600")
    if REPOSITORY.resolve() in credential_file.resolve().parents:
        raise SubmitterError("credential file must remain outside the repository")


def execute_once(candidate: dict[str, Any], candidate_path: Path, operation_id: str, grant: dict[str, Any], receipt: dict[str, Any], receipt_path: Path, credential_file: Path, now: dt.datetime, runner: Callable[..., Any] = subprocess.run) -> dict[str, Any]:
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
    parser.add_argument("--operation", choices=("provider-prerequisites", "management-namespace", "capi-lifecycle", "helmchartproxy"))
    args = parser.parse_args()
    try:
        path = args.candidate.resolve()
        candidate = load_candidate(path)
        reviewed = validate_candidate(candidate, path)
        if args.command == "verify":
            result = {"candidateDigest": sha(path), "state": candidate["spec"]["state"], "operations": len(reviewed), "objects": sum(len(item.documents) for item in reviewed.values()), "runtimeEligibleOperations": sum(item.runtime_eligible for item in reviewed.values()), "mutationAuthorized": False, "clusterContacted": False}
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
