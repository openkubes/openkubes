#!/usr/bin/env python3
"""Additive submitter binding for the Phase-R-v5 HCP. Remains NO-GO."""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

import yaml


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
REPOSITORY = SPIKE.parents[2]
CANDIDATE = HERE / "go1-l-submitter-candidate-v3.yaml"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    assert spec.loader is not None
    spec.loader.exec_module(result)
    return result


V2 = load_module("ok141_go1_l_submitter_v2_for_v3", SPIKE / "go1-l-submitter-v2/bounded_go1_l_submitter_v2.py")
HCPA = load_module("ok141_hcp_phase_r_v5_for_submitter_v3", SPIKE / "go1-l-hcp-v1/verify_hcp_phase_r_v5_amendment_v1.py")
V1 = V2.V1
ReviewedOperation = V2.ReviewedOperation


class SubmitterError(ValueError):
    pass


def expect(actual: Any, expected: Any, context: str) -> None:
    if actual != expected:
        raise SubmitterError(f"{context}: expected {expected!r}, got {actual!r}")


def resolve(candidate_path: Path, requested: str) -> Path:
    path = (candidate_path.parent / requested).resolve()
    if SPIKE.resolve() not in path.parents or not path.is_file():
        raise SubmitterError(f"reference missing or outside spike root: {requested}")
    return path


def load_candidate(path: Path = CANDIDATE) -> dict[str, Any]:
    return V1.read_yaml_or_json(path)


def validate_candidate(candidate: dict[str, Any], candidate_path: Path = CANDIDATE) -> dict[str, ReviewedOperation]:
    expect(candidate.get("apiVersion"), "execution.openkubes.io/v1alpha1", "apiVersion")
    expect(candidate.get("kind"), "GO1LSubmitterCandidate", "kind")
    spec = candidate["spec"]
    expect(spec["version"], "ok141-go1-l-submitter/v3", "version")
    expect(spec["state"], "OFFLINE-PROVEN-BLOCKED-NO-GO", "state")
    expect(spec["authorization"], {
        "decision": "NO-GO",
        "currentGrantBound": False,
        "mutationAuthorized": False,
        "recreationGranted": False,
        "go1LGranted": False,
        "retryGranted": False,
        "rollbackOrCleanupGranted": False,
    }, "authorization")

    predecessor_ref = spec["supersedes"]
    predecessor_path = resolve(candidate_path, predecessor_ref["path"])
    expect(V2.sha(predecessor_path), predecessor_ref["digest"], "v2 candidate digest")
    predecessor = V2.load_candidate(predecessor_path)
    predecessor_reviewed = V2.validate_candidate(predecessor, predecessor_path)
    expect(predecessor["spec"]["state"], predecessor_ref["state"], "v2 state")
    expect(predecessor_ref["historicalEvidencePreserved"], True, "v2 preservation")

    expect(spec["sourcePreflight"], predecessor["spec"]["sourcePreflight"], "preflight binding")
    expect(spec["fixture"], predecessor["spec"]["fixture"], "fixture binding")
    expect(spec["transport"], predecessor["spec"]["transport"], "transport boundary")
    expect(spec["combinedManagementProjectionSemanticDigest"], predecessor["spec"]["combinedManagementProjectionSemanticDigest"], "management projection")
    expect(spec["externalPrerequisite"], predecessor["spec"]["externalPrerequisite"], "external Secret boundary")
    expect(spec["credentialContract"], predecessor["spec"]["credentialContract"], "credential boundary")

    tool = spec["tool"]
    tool_path = resolve(candidate_path, tool["path"])
    expect(V2.sha(tool_path), tool["digest"], "v3 tool digest")
    expect(tool["arbitraryManifestPathAllowed"], False, "manifest path boundary")
    expect(tool["arbitraryCommandAllowed"], False, "command boundary")

    operations = spec["operations"]
    expect([item["id"] for item in operations], ["provider-prerequisites", "management-namespace", "capi-lifecycle", "helmchartproxy"], "operation order")
    expect(operations[:3], predecessor["spec"]["operations"][:3], "inherited static operations")
    hcp_operation = operations[3]
    expect(hcp_operation["sequence"], 5, "HCP sequence")
    expect(hcp_operation["stage"], "G3", "HCP stage")
    expect(hcp_operation["targetPlane"], "ok-mgmt", "HCP authority")
    expect(hcp_operation["predecessorEvidenceCount"], 1, "HCP predecessor")
    expect(hcp_operation["runtimeEligible"], True, "HCP runtime eligibility")

    amendment_ref = spec["hcpAmendment"]
    amendment_path = resolve(candidate_path, amendment_ref["path"])
    expect(V2.sha(amendment_path), amendment_ref["digest"], "HCP amendment digest")
    amendment = V1.read_yaml_or_json(amendment_path)
    current_hcp = HCPA.validate(amendment, amendment_path)
    expect(amendment["spec"]["state"], amendment_ref["state"], "HCP amendment state")
    current_ref = amendment["spec"]["currentHCP"]
    hcp_path = resolve(candidate_path, hcp_operation["path"])
    expected_hcp_path = (amendment_path.parent / current_ref["path"]).resolve()
    expect(hcp_path, expected_hcp_path, "current HCP path")
    expect(V2.sha(hcp_path), hcp_operation["sourceRawDigest"], "current HCP raw digest")
    expect(hcp_operation["sourceRawDigest"], current_ref["rawDigest"], "amendment HCP raw digest")
    expect(hcp_operation["payloadRawDigest"], current_ref["rawDigest"], "HCP payload digest")
    expect(hcp_operation["semanticDigest"], current_ref["semanticDigest"], "HCP semantic digest")
    expect(hcp_operation["objectCount"], 1, "HCP object count")
    expect(hcp_operation["objectIdentities"], [current_ref["objectIdentity"]], "HCP identity")
    annotations = current_hcp["metadata"]["annotations"]
    expect(annotations["openkubes.io/intent-revision"], spec["fixture"]["R"], "HCP R")
    expect(annotations["openkubes.io/enablement-revision"], spec["fixture"]["E"], "HCP E")
    expect(annotations["openkubes.io/execution-fixture"], spec["fixture"]["fixtureDigest"], "HCP FixtureDigest")

    reviewed = {key: predecessor_reviewed[key] for key in ("provider-prerequisites", "management-namespace", "capi-lifecycle")}
    payload = hcp_path.read_bytes()
    reviewed["helmchartproxy"] = ReviewedOperation(
        operation_id="helmchartproxy",
        stage="G3",
        target_plane="ok-mgmt",
        documents=[current_hcp],
        payload=payload,
        predecessor_evidence_count=1,
        runtime_eligible=True,
    )
    if any(not item.runtime_eligible for item in reviewed.values()):
        raise SubmitterError("v3 contains a non-runtime-eligible static operation")
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


def validate_runtime_authority(candidate: dict[str, Any], candidate_path: Path, operation_id: str, grant: dict[str, Any], receipt: dict[str, Any], receipt_path: Path, credential_file: Path, now: dt.datetime) -> None:
    reviewed = validate_candidate(candidate, candidate_path)
    if operation_id not in reviewed or not reviewed[operation_id].runtime_eligible:
        raise SubmitterError("operation is not runtime eligible")
    operation = reviewed[operation_id]
    grant_spec = grant["spec"]
    V2.expect(grant_spec["decision"], "GO", "grant decision")
    V2.expect(grant_spec["mutationAuthorized"], True, "grant mutation authority")
    V2.expect(grant_spec["go1LGranted"], True, "grant GO1-L authority")
    V2.expect(grant_spec["operationGranted"], operation_id, "grant operation")
    V2.expect(grant_spec["candidateDigest"], V2.sha(candidate_path), "grant candidate")
    V2.expect(grant_spec["fixtureDigest"], candidate["spec"]["fixture"]["fixtureDigest"], "grant fixture")
    V2.expect(grant_spec["preflightDigest"], candidate["spec"]["sourcePreflight"]["digest"], "grant preflight")
    if V2.contains_secret_field(grant) or V2.contains_secret_field(receipt):
        raise SubmitterError("grant or receipt contains a secret-bearing field")
    if not grant_spec.get("grantID") or grant_spec.get("singleRun") is not True:
        raise SubmitterError("grant identity or single-run boundary is missing")
    issued, expires = V2.parse_time(grant_spec["issuedAt"]), V2.parse_time(grant_spec["expiresAt"])
    if not issued <= now <= expires or expires - issued > dt.timedelta(minutes=20):
        raise SubmitterError("grant is outside its maximum 20-minute window")
    predecessors = grant_spec["predecessorEvidenceDigests"]
    if len(predecessors) != operation.predecessor_evidence_count or any(not item.startswith("sha256:") for item in predecessors):
        raise SubmitterError("predecessor evidence count or digest is invalid")
    V2.expect(V2.sha(receipt_path), grant_spec["credentialReceiptDigest"], "credential receipt binding")
    receipt_spec = receipt["spec"]
    V2.expect(receipt_spec["targetPlane"], operation.target_plane, "credential target")
    V2.expect(receipt_spec["operation"], operation_id, "credential operation")
    V2.expect(receipt_spec["tokenBytesPersisted"], False, "credential persistence")
    V2.expect(receipt_spec["tokenBytesEmitted"], False, "credential emission")
    if V2.parse_time(receipt_spec["issuedAt"]) > now or not now <= V2.parse_time(receipt_spec["expiresAt"]) <= expires:
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
    completed = runner(["kubectl", "--kubeconfig", str(credential_file), "create", "--filename", "-"], input=reviewed.payload, check=True, capture_output=True)
    return {"operation": operation_id, "targetPlane": reviewed.target_plane, "objectCount": len(reviewed.documents), "semanticDigest": reviewed.semantic_digest, "transportExitCode": completed.returncode, "credentialBytesEmitted": False, "retryPerformed": False, "rollbackOrCleanupPerformed": False}


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
            result = {"candidateDigest": V2.sha(path), "state": candidate["spec"]["state"], "operations": len(reviewed), "objects": sum(len(item.documents) for item in reviewed.values()), "runtimeEligibleOperations": sum(item.runtime_eligible for item in reviewed.values()), "mutationAuthorized": False, "clusterContacted": False}
        else:
            if args.operation is None:
                raise SubmitterError("plan requires --operation")
            result = build_plan(candidate, path, args.operation)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (KeyError, OSError, SubmitterError, V2.SubmitterError, HCPA.AmendmentError, TypeError, ValueError, yaml.YAMLError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
