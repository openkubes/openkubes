#!/usr/bin/env python3
"""Point-of-use credential identity amendment for the GO1-L executor."""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

import yaml


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
CANDIDATE = HERE / "go1-l-executor-candidate-v2.yaml"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


V1 = load_module("ok141_go1_l_executor_v1_for_v2", SPIKE / "go1-l-executor-v1" / "bounded_go1_l_executor_v1.py")


class ExecutorV2Error(ValueError):
    pass


def expect(actual: Any, expected: Any, context: str) -> None:
    if actual != expected:
        raise ExecutorV2Error(f"{context}: expected {expected!r}, got {actual!r}")


def resolve(candidate_path: Path, requested: str) -> Path:
    path = (candidate_path.parent / requested).resolve()
    if SPIKE.resolve() not in path.parents or not path.is_file():
        raise ExecutorV2Error(f"reference missing or outside spike root: {requested}")
    return path


def validate_candidate(candidate_path: Path = CANDIDATE) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    candidate = V1.read_yaml(candidate_path)
    expect(candidate.get("apiVersion"), "execution.openkubes.io/v1alpha1", "apiVersion")
    expect(candidate.get("kind"), "GO1LExecutorCandidate", "kind")
    spec = candidate["spec"]
    expect(spec["version"], "ok141-go1-l-executor/v2", "version")
    expect(spec["state"], "OFFLINE-PROVEN-BLOCKED-NO-GO", "state")
    predecessor_ref = spec["supersedes"]
    predecessor_path = resolve(candidate_path, predecessor_ref["path"])
    expect(V1.sha(predecessor_path), predecessor_ref["digest"], "v1 digest")
    predecessor, reviewed, materializer = V1.validate_candidate(predecessor_path)
    expect(predecessor_ref["historicalEvidencePreserved"], True, "v1 preservation")
    expect(predecessor_ref["v1AllowedForFutureExecution"], False, "v1 execution boundary")

    closure_ref = spec["credentialIdentityClosure"]
    closure_path = resolve(candidate_path, closure_ref["path"])
    expect(V1.sha(closure_path), closure_ref["digest"], "identity closure digest")
    closure = V1.read_yaml(closure_path)
    identities = {plane: value["identityDigest"] for plane, value in closure["spec"]["identities"].items() if plane in ("ok-infra", "ok-mgmt")}
    expect(identities, closure_ref["expectedIdentityDigests"], "identity closure values")
    binding = spec["pointOfUseBinding"]
    expect((binding["currentCredentialInspectionRequired"], binding["receiptPathRequired"], binding["receiptIdentityDigestRequired"], binding["preflightIdentityCorrelationRequired"]), (True, True, True, True), "point-of-use requirements")
    expect(binding["identityClaim"], "HTTPS-API-ENDPOINT-AND-CA-ONLY", "identity claim")
    expect(binding["principalIdentityClaimAllowed"], False, "principal claim boundary")
    expect(V1.sha(resolve(candidate_path, spec["tool"]["path"])), spec["tool"]["digest"], "tool digest")
    if any(spec["tool"][key] for key in ("arbitraryCommandAllowed", "arbitraryManifestAllowed", "arbitraryCredentialPathAllowed")):
        raise ExecutorV2Error("v2 tool expands the reviewed execution surface")
    authorization = spec["authorization"]
    expect(authorization["decision"], "NO-GO", "authorization")
    expect(authorization["grantIDs"], [], "grant inventory")
    if any(value for key, value in authorization.items() if key.endswith("Granted")):
        raise ExecutorV2Error("candidate grants authority")
    expect(spec["conclusions"], {"payloadSemanticsChanged": False, "transportSemanticsChanged": False, "pointOfUseCredentialIdentityAdded": True, "clusterContacted": False, "mutationAuthorized": False}, "conclusions")
    return candidate, reviewed, materializer


def inspect_identity(path: Path) -> dict[str, str]:
    return V1.PF.V1.inspect_credential(path)


def validate_receipt_v2(receipt_path: Path, expected_digest: str, operation: str, plane: str, credential_path: Path, expected_identity: str, now: dt.datetime, grant_expires: dt.datetime) -> None:
    receipt = V1.read_yaml(receipt_path)
    V1.validate_receipt(receipt, receipt_path, expected_digest, operation, plane, now, grant_expires)
    spec = receipt["spec"]
    expect(Path(spec["credentialPath"]).resolve(), credential_path.resolve(), "receipt credential path")
    expect(spec["credentialIdentityDigest"], expected_identity, "receipt credential identity")


def validate_runtime(candidate_path: Path, operation_id: str, grant_path: Path, preflight_path: Path, predecessor_paths: list[Path], receipt_bindings: list[tuple[Path, str, str, Path]], now: dt.datetime) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    candidate, reviewed, materializer = validate_candidate(candidate_path)
    predecessor_path = resolve(candidate_path, candidate["spec"]["supersedes"]["path"])
    predecessor = V1.read_yaml(predecessor_path)
    grant = V1.read_yaml(grant_path)
    expect(grant.get("apiVersion"), "authorization.openkubes.io/v1alpha1", "grant apiVersion")
    expect(grant.get("kind"), "SingleOperationGrantV2", "grant kind")
    spec = grant["spec"]
    expect(spec["decision"], "GO", "grant decision")
    expect(spec["mutationAuthorized"], True, "mutation authority")
    expect(spec["credentialUseGranted"], True, "credential-use authority")
    expect(spec["go1LGranted"], True, "GO1-L authority")
    expect((spec["go1Granted"], spec["retryGranted"], spec["rollbackOrCleanupGranted"], spec["evidencePublicationGranted"], spec["failureInjectionGranted"]), (False, False, False, False, False), "excluded authority")
    expect(spec["operationGranted"], operation_id, "operation")
    expect(spec["candidateDigest"], V1.sha(candidate_path), "v2 candidate")
    expect(spec["executorV1Digest"], candidate["spec"]["supersedes"]["digest"], "v1 executor")
    expect(spec["protocolDigest"], predecessor["spec"]["protocol"]["digest"], "protocol")
    expect(spec["fixtureDigest"], V1.FIXTURE_DIGEST, "fixture")
    expect(spec["preflightCandidateDigest"], predecessor["spec"]["preflight"]["digest"], "preflight candidate")
    expect(spec["clientDigest"], V1.CLIENT_DIGEST, "client")
    expect(spec["credentialIdentityClosureDigest"], candidate["spec"]["credentialIdentityClosure"]["digest"], "credential closure")
    expect(spec["authority"], "github:arashkaffamanesh", "authority")
    provider_authority = (spec.get("sourceCredentialReadGranted", False), spec.get("destinationCredentialUseGranted", False), spec.get("secretMaterializationGranted", False))
    if operation_id == "provider-access-secret":
        expect(provider_authority, (True, True, True), "provider authority")
    elif any(provider_authority):
        raise ExecutorV2Error("static operation grant contains provider-access authority")
    if V1.V3.V2.contains_secret_field(grant):
        raise ExecutorV2Error("grant contains a secret-bearing field")
    if not spec.get("grantID") or spec.get("singleRun") is not True:
        raise ExecutorV2Error("single-run grant identity is missing")
    issued, expires = V1.V3.V2.parse_time(spec["issuedAt"]), V1.V3.V2.parse_time(spec["expiresAt"])
    if not issued <= now <= expires or expires - issued > dt.timedelta(minutes=20):
        raise ExecutorV2Error("grant is outside its maximum 20-minute window")
    operation = next((item for item in predecessor["spec"]["operations"] if item["id"] == operation_id), None)
    if operation is None:
        raise ExecutorV2Error("unsupported operation")
    preflight = V1.validate_preflight(preflight_path, spec["preflightEvidenceDigest"], now, operation["order"] == 1)
    V1.validate_predecessors(predecessor_paths, spec["predecessorEvidenceDigests"], operation["predecessorEvidenceCount"])
    expected_identities = candidate["spec"]["credentialIdentityClosure"]["expectedIdentityDigests"]
    expect(preflight["credentialIdentityDigests"], expected_identities, "preflight credential identities")
    expected_receipts = spec["credentialReceiptDigests"]
    expect(len(receipt_bindings), len(expected_receipts), "receipt count")
    for receipt_path, receipt_operation, plane, credential_path in receipt_bindings:
        if plane not in expected_identities:
            raise ExecutorV2Error("receipt plane is outside the identity closure")
        expected_digest = expected_receipts.get(receipt_operation)
        if expected_digest is None:
            raise ExecutorV2Error("receipt operation is not grant-bound")
        validate_receipt_v2(receipt_path, expected_digest, receipt_operation, plane, credential_path, expected_identities[plane], now, expires)
        current = inspect_identity(credential_path)
        expect(current["identityDigest"], expected_identities[plane], f"current {plane} credential identity")
    return operation, reviewed, materializer


def execute_static(candidate_path: Path, operation_id: str, grant_path: Path, receipt_path: Path, preflight_path: Path, predecessor_paths: list[Path], now: dt.datetime, runner: Callable[..., Any] = subprocess.run) -> dict[str, Any]:
    predecessor = V1.read_yaml(resolve(candidate_path, V1.read_yaml(candidate_path)["spec"]["supersedes"]["path"]))
    operation = next(item for item in predecessor["spec"]["operations"] if item["id"] == operation_id and item["executor"] == "static")
    credential = Path(predecessor["spec"]["credentialPaths"][operation["targetPlane"]])
    _, reviewed, _ = validate_runtime(candidate_path, operation_id, grant_path, preflight_path, predecessor_paths, [(receipt_path, operation_id, operation["targetPlane"], credential)], now)
    V1.verify_client(runner)
    selected = reviewed[operation_id]
    completed = runner([str(V1.CLIENT), "--kubeconfig", str(credential), "create", "--filename", "-"], input=selected.payload, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if completed.returncode != 0:
        raise ExecutorV2Error(f"create-only transport failed for {operation_id}")
    return {"operation": operation_id, "targetPlane": operation["targetPlane"], "objectCount": operation["objectCount"], "semanticDigest": selected.semantic_digest, "credentialIdentityVerifiedAtPointOfUse": True, "transportExitCode": 0, "retryPerformed": False, "rollbackOrCleanupPerformed": False}


def execute_provider(candidate_path: Path, grant_path: Path, source_receipt_path: Path, destination_receipt_path: Path, preflight_path: Path, predecessor_paths: list[Path], now: dt.datetime, runner: Callable[..., Any] = subprocess.run, source_reader: Callable[[Path], bytes] = V1.MAT.default_source_reader) -> dict[str, Any]:
    candidate = V1.read_yaml(candidate_path)
    predecessor = V1.read_yaml(resolve(candidate_path, candidate["spec"]["supersedes"]["path"]))
    materializer_path = resolve(resolve(candidate_path, candidate["spec"]["supersedes"]["path"]), predecessor["spec"]["providerAccessMaterializer"]["path"])
    materializer = V1.MAT.load_candidate(materializer_path)
    materializer_spec = V1.MAT.validate_candidate(materializer, materializer_path)
    source_credential = Path(materializer_spec["sourceCredential"]["path"])
    destination_credential = Path(predecessor["spec"]["credentialPaths"]["ok-mgmt"])
    _, _, materializer = validate_runtime(candidate_path, "provider-access-secret", grant_path, preflight_path, predecessor_paths, [(source_receipt_path, "provider-access-source", "ok-infra", source_credential), (destination_receipt_path, "provider-access-secret", "ok-mgmt", destination_credential)], now)
    V1.verify_client(runner)
    raw = source_reader(source_credential)
    payload = V1.MAT.build_secret_payload(materializer_spec, raw)
    completed = runner([str(V1.CLIENT), "--kubeconfig", str(destination_credential), "create", "--filename", "-"], input=payload, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if completed.returncode != 0:
        raise ExecutorV2Error("create-only provider Secret transport failed")
    metadata = materializer_spec["secretTemplate"]["metadata"]
    return {"operation": "provider-access-secret", "targetPlane": "ok-mgmt", "secretIdentity": f"v1|Secret|{metadata['namespace']}|{metadata['name']}", "credentialIdentitiesVerifiedAtPointOfUse": True, "transportExitCode": 0, "sourceCredentialBytesEmitted": False, "secretPayloadPersisted": False, "retryPerformed": False, "rollbackOrCleanupPerformed": False}


def plan(candidate_path: Path = CANDIDATE) -> dict[str, Any]:
    candidate, _, _ = validate_candidate(candidate_path)
    predecessor_path = resolve(candidate_path, candidate["spec"]["supersedes"]["path"])
    inherited = V1.plan(predecessor_path)
    return {**inherited, "candidateDigest": V1.sha(candidate_path), "supersededExecutorDigest": candidate["spec"]["supersedes"]["digest"], "pointOfUseCredentialIdentityRequired": True}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "plan"))
    parser.add_argument("--candidate", type=Path, default=CANDIDATE)
    args = parser.parse_args()
    try:
        result = plan(args.candidate.resolve())
        result["state"] = validate_candidate(args.candidate.resolve())[0]["spec"]["state"]
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (ExecutorV2Error, V1.ExecutorError, V1.V3.SubmitterError, V1.MAT.MaterializerError, OSError, KeyError, TypeError, ValueError, yaml.YAMLError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
