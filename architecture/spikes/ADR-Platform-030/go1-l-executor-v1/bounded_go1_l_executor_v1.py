#!/usr/bin/env python3
"""Exact-client executor for the five reviewed GO1-L operations."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
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
CANDIDATE = HERE / "go1-l-executor-candidate-v1.yaml"
CLIENT = Path("/private/tmp/ok141-kubectl-v1.34.1-darwin-amd64")
CLIENT_DIGEST = "sha256:bb211f2b31f2b3bc60562b44cc1e3b712a16a98e9072968ba255beb04cefcfdf"
FIXTURE_DIGEST = "sha256:7536456a762880a78a37dcba76a5f3f0628140bd37b55d5fd62273c64e4cc3eb"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


V3 = load_module("ok141_submitter_v3_for_executor", SPIKE / "go1-l-submitter-v3" / "bounded_go1_l_submitter_v3.py")
MAT = load_module("ok141_provider_access_v1_for_executor", SPIKE / "go1-l-provider-access-v1" / "bounded_provider_access_materializer_v1.py")
PF = load_module("ok141_preflight_v2_for_executor", SPIKE / "go1-v6-preflight-v2" / "bounded_go1_v6_preflight_v2.py")


class ExecutorError(ValueError):
    pass


def sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def read_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text())
    if not isinstance(value, dict):
        raise ExecutorError(f"expected mapping: {path}")
    return value


def expect(actual: Any, expected: Any, context: str) -> None:
    if actual != expected:
        raise ExecutorError(f"{context}: expected {expected!r}, got {actual!r}")


def resolve(candidate_path: Path, requested: str) -> Path:
    path = (candidate_path.parent / requested).resolve()
    if SPIKE.resolve() not in path.parents or not path.is_file():
        raise ExecutorError(f"reference missing or outside spike root: {requested}")
    return path


def validate_candidate(candidate_path: Path = CANDIDATE) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    candidate = read_yaml(candidate_path)
    expect(candidate.get("apiVersion"), "execution.openkubes.io/v1alpha1", "apiVersion")
    expect(candidate.get("kind"), "GO1LExecutorCandidate", "kind")
    spec = candidate["spec"]
    expect(spec["version"], "ok141-go1-l-executor/v1", "version")
    expect(spec["state"], "OFFLINE-PROVEN-BLOCKED-NO-GO", "state")
    expected_bindings = {
        "protocol": "sha256:e45e5f6b8254e666226aa874810bf2ca51f76f2411e0316adb52a7ce51254885",
        "preflight": "sha256:ef4b09a8835f187605a0120bdd19616d6d078b9ed19a3796a47b9cbbfc7a4fb2",
        "credentialIdentityClosure": "sha256:26c840ac3e1c5eb879f107801740edb0db73a717fea9c00123ad1e36b3fdc008",
        "staticSubmitter": "sha256:ef6869cbe35008a79934eeab1a99106d6e73ab5ee4aae08f88f41ca2116f5cd5",
        "providerAccessMaterializer": "sha256:6b9b072f8daab315f46de0d6ded642cbcf75618b1c1629c020bdfba60a2aa1d5",
    }
    for name, digest in expected_bindings.items():
        binding = spec[name]
        expect(binding["digest"], digest, f"{name} digest")
        expect(sha(resolve(candidate_path, binding["path"])), digest, f"{name} source")
    submitter_path = resolve(candidate_path, spec["staticSubmitter"]["path"])
    submitter = V3.load_candidate(submitter_path)
    reviewed = V3.validate_candidate(submitter, submitter_path)
    materializer_path = resolve(candidate_path, spec["providerAccessMaterializer"]["path"])
    materializer = MAT.load_candidate(materializer_path)
    MAT.validate_candidate(materializer, materializer_path)
    expect(spec["client"]["path"], str(CLIENT), "client path")
    expect(spec["client"]["digest"], CLIENT_DIGEST, "client digest")
    expect(spec["client"]["version"], "v1.34.1", "client version")
    expect(spec["client"]["platform"], "darwin/amd64", "client platform")
    expect(spec["client"]["requiredMode"], "0700", "client mode")
    expect(spec["client"]["PATHLookupAllowed"], False, "PATH boundary")
    expect(sha(resolve(candidate_path, spec["tool"]["path"])), spec["tool"]["digest"], "tool binding")
    expected_operations = [
        ("provider-prerequisites", 1, "static", "ok-infra", 3, 0),
        ("management-namespace", 2, "static", "ok-mgmt", 1, 1),
        ("provider-access-secret", 3, "provider-access", "ok-mgmt", 1, 2),
        ("capi-lifecycle", 4, "static", "ok-mgmt", 7, 2),
        ("helmchartproxy", 5, "static", "ok-mgmt", 1, 1),
    ]
    expect([(o["id"], o["order"], o["executor"], o["targetPlane"], o["objectCount"], o["predecessorEvidenceCount"]) for o in spec["operations"]], expected_operations, "operation inventory")
    for item in spec["operations"]:
        if item["executor"] == "static":
            operation = reviewed[item["id"]]
            expect((operation.target_plane, len(operation.documents), operation.predecessor_evidence_count), (item["targetPlane"], item["objectCount"], item["predecessorEvidenceCount"]), f"{item['id']} inheritance")
    expect(spec["credentialPaths"], {"ok-infra": "/Users/arash/.kube/ok-infra.yaml", "ok-mgmt": "/Users/arash/.kube/ok-mgmt.yaml"}, "credential paths")
    authorization = spec["authorization"]
    expect(authorization["decision"], "NO-GO", "authorization")
    expect(authorization["grantIDs"], [], "grant IDs")
    if any(value for key, value in authorization.items() if key.endswith("Granted")):
        raise ExecutorError("candidate grants authority")
    expect(spec["conclusions"]["clusterContacted"], False, "cluster contact")
    expect(spec["conclusions"]["mutationAuthorized"], False, "mutation authority")
    return candidate, reviewed, materializer


def verify_client(runner: Callable[..., Any] = subprocess.run) -> None:
    if not CLIENT.is_file() or CLIENT.is_symlink() or stat.S_IMODE(CLIENT.stat().st_mode) != 0o700:
        raise ExecutorError("exact client file or mode differs")
    expect(sha(CLIENT), CLIENT_DIGEST, "live client digest")
    completed = runner([str(CLIENT), "version", "--client", "--output=json"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if completed.returncode != 0:
        raise ExecutorError("client version inspection failed")
    version = json.loads(completed.stdout)["clientVersion"]
    expect((version["gitVersion"], version["platform"]), ("v1.34.1", "darwin/amd64"), "live client identity")


def validate_file(path: Path, role: str) -> None:
    if not path.is_file() or path.is_symlink() or path.stat().st_size == 0:
        raise ExecutorError(f"{role} must be a regular non-symlink file")
    if stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise ExecutorError(f"{role} mode must be 0600")
    if REPOSITORY.resolve() in path.resolve().parents:
        raise ExecutorError(f"{role} must remain outside the repository")


def validate_preflight(path: Path, expected_digest: str, now: dt.datetime, require_fresh: bool) -> dict[str, Any]:
    expect(sha(path), expected_digest, "preflight evidence digest")
    spec = json.loads(path.read_text())["spec"]
    expect(spec["candidateDigest"], "sha256:ef4b09a8835f187605a0120bdd19616d6d078b9ed19a3796a47b9cbbfc7a4fb2", "preflight candidate")
    expect(spec["result"], "PASS-FRESH-BASELINE-AND-PREREQUISITES", "preflight result")
    expect(spec["mutationPerformed"], False, "preflight mutation")
    expect(spec["secretBodiesRetained"], False, "preflight Secret boundary")
    if require_fresh and now > V3.V2.parse_time(spec["freshUntil"]):
        raise ExecutorError("preflight evidence is stale for the first operation")
    return spec


def validate_receipt(receipt: dict[str, Any], receipt_path: Path, expected_digest: str, operation: str, plane: str, now: dt.datetime, grant_expires: dt.datetime) -> None:
    expect(sha(receipt_path), expected_digest, "credential receipt digest")
    expect(receipt.get("apiVersion"), "evidence.openkubes.io/v1alpha1", "receipt apiVersion")
    expect(receipt.get("kind"), "CredentialReceipt", "receipt kind")
    if V3.V2.contains_secret_field(receipt):
        raise ExecutorError("credential receipt contains a secret-bearing field")
    spec = receipt["spec"]
    expect(spec["operation"], operation, "receipt operation")
    expect(spec["targetPlane"], plane, "receipt target plane")
    expect(spec["tokenBytesPersisted"], False, "credential persistence")
    expect(spec["tokenBytesEmitted"], False, "credential emission")
    if V3.V2.parse_time(spec["issuedAt"]) > now or not now <= V3.V2.parse_time(spec["expiresAt"]) <= grant_expires:
        raise ExecutorError("credential receipt is outside the operation grant")


def validate_predecessors(paths: list[Path], expected: list[str], count: int) -> None:
    expect(len(paths), count, "predecessor path count")
    expect([sha(path) for path in paths], expected, "predecessor evidence")


def validate_common(candidate_path: Path, operation_id: str, grant: dict[str, Any], preflight_path: Path, predecessor_paths: list[Path], now: dt.datetime) -> tuple[dict[str, Any], dt.datetime]:
    candidate, _, _ = validate_candidate(candidate_path)
    expect(grant.get("apiVersion"), "authorization.openkubes.io/v1alpha1", "grant apiVersion")
    expect(grant.get("kind"), "SingleOperationGrant", "grant kind")
    spec = grant["spec"]
    expect(spec["decision"], "GO", "grant decision")
    expect(spec["mutationAuthorized"], True, "mutation authority")
    expect(spec["go1LGranted"], True, "GO1-L authority")
    expect(spec["operationGranted"], operation_id, "operation grant")
    expect(spec["candidateDigest"], sha(candidate_path), "executor candidate")
    expect(spec["protocolDigest"], candidate["spec"]["protocol"]["digest"], "protocol grant")
    expect(spec["fixtureDigest"], FIXTURE_DIGEST, "fixture grant")
    expect(spec["preflightCandidateDigest"], candidate["spec"]["preflight"]["digest"], "preflight candidate grant")
    expect(spec["clientDigest"], CLIENT_DIGEST, "client grant")
    provider_authority = (
        spec.get("sourceCredentialReadGranted", False),
        spec.get("destinationCredentialUseGranted", False),
        spec.get("secretMaterializationGranted", False),
    )
    if operation_id == "provider-access-secret":
        expect(provider_authority, (True, True, True), "provider-access authority")
    elif any(provider_authority):
        raise ExecutorError("static operation grant contains provider-access authority")
    if V3.V2.contains_secret_field(grant):
        raise ExecutorError("grant contains a secret-bearing field")
    if not spec.get("grantID") or spec.get("singleRun") is not True:
        raise ExecutorError("single-run grant identity is missing")
    issued, expires = V3.V2.parse_time(spec["issuedAt"]), V3.V2.parse_time(spec["expiresAt"])
    if not issued <= now <= expires or expires - issued > dt.timedelta(minutes=20):
        raise ExecutorError("grant is outside its maximum 20-minute window")
    operation = next((item for item in candidate["spec"]["operations"] if item["id"] == operation_id), None)
    if operation is None:
        raise ExecutorError("unsupported operation")
    validate_preflight(preflight_path, spec["preflightEvidenceDigest"], now, operation["order"] == 1)
    validate_predecessors(predecessor_paths, spec["predecessorEvidenceDigests"], operation["predecessorEvidenceCount"])
    return operation, expires


def execute_static(candidate_path: Path, operation_id: str, grant_path: Path, receipt_path: Path, credential_path: Path, preflight_path: Path, predecessor_paths: list[Path], now: dt.datetime, runner: Callable[..., Any] = subprocess.run) -> dict[str, Any]:
    candidate, reviewed, _ = validate_candidate(candidate_path)
    operation = next(item for item in candidate["spec"]["operations"] if item["id"] == operation_id and item["executor"] == "static")
    grant, receipt = read_yaml(grant_path), read_yaml(receipt_path)
    _, expires = validate_common(candidate_path, operation_id, grant, preflight_path, predecessor_paths, now)
    validate_receipt(receipt, receipt_path, grant["spec"]["credentialReceiptDigest"], operation_id, operation["targetPlane"], now, expires)
    expect(credential_path.resolve(), Path(candidate["spec"]["credentialPaths"][operation["targetPlane"]]).resolve(), "credential path")
    validate_file(credential_path, "operation credential")
    verify_client(runner)
    reviewed_operation = reviewed[operation_id]
    completed = runner([str(CLIENT), "--kubeconfig", str(credential_path), "create", "--filename", "-"], input=reviewed_operation.payload, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if completed.returncode != 0:
        raise ExecutorError(f"create-only transport failed for {operation_id}")
    return {"operation": operation_id, "targetPlane": operation["targetPlane"], "objectCount": operation["objectCount"], "semanticDigest": reviewed_operation.semantic_digest, "transportExitCode": 0, "credentialBytesEmitted": False, "retryPerformed": False, "rollbackOrCleanupPerformed": False}


def execute_provider(candidate_path: Path, grant_path: Path, source_receipt_path: Path, destination_receipt_path: Path, destination_credential: Path, preflight_path: Path, predecessor_paths: list[Path], now: dt.datetime, runner: Callable[..., Any] = subprocess.run, source_reader: Callable[[Path], bytes] = MAT.default_source_reader) -> dict[str, Any]:
    candidate, _, materializer = validate_candidate(candidate_path)
    grant = read_yaml(grant_path)
    _, expires = validate_common(candidate_path, "provider-access-secret", grant, preflight_path, predecessor_paths, now)
    source_receipt, destination_receipt = read_yaml(source_receipt_path), read_yaml(destination_receipt_path)
    validate_receipt(source_receipt, source_receipt_path, grant["spec"]["sourceCredentialReceiptDigest"], "provider-access-source", "ok-infra", now, expires)
    validate_receipt(destination_receipt, destination_receipt_path, grant["spec"]["destinationCredentialReceiptDigest"], "provider-access-secret", "ok-mgmt", now, expires)
    expect(source_receipt["spec"]["sourcePath"], materializer["spec"]["sourceCredential"]["path"], "source credential receipt path")
    expect(destination_credential.resolve(), Path(candidate["spec"]["credentialPaths"]["ok-mgmt"]).resolve(), "destination credential path")
    validate_file(destination_credential, "destination credential")
    verify_client(runner)
    materializer_spec = MAT.validate_candidate(materializer, resolve(candidate_path, candidate["spec"]["providerAccessMaterializer"]["path"]))
    raw = source_reader(Path(materializer_spec["sourceCredential"]["path"]))
    payload = MAT.build_secret_payload(materializer_spec, raw)
    completed = runner([str(CLIENT), "--kubeconfig", str(destination_credential), "create", "--filename", "-"], input=payload, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if completed.returncode != 0:
        raise ExecutorError("create-only provider Secret transport failed")
    metadata = materializer_spec["secretTemplate"]["metadata"]
    return {"operation": "provider-access-secret", "targetPlane": "ok-mgmt", "secretIdentity": f"v1|Secret|{metadata['namespace']}|{metadata['name']}", "dataKeys": [materializer_spec["secretTemplate"]["dataKey"]], "transportExitCode": 0, "sourceCredentialBytesEmitted": False, "sourceContentDigestEmitted": False, "secretPayloadPersisted": False, "retryPerformed": False, "rollbackOrCleanupPerformed": False}


def plan(candidate_path: Path = CANDIDATE) -> dict[str, Any]:
    candidate, reviewed, _ = validate_candidate(candidate_path)
    operations = []
    for item in candidate["spec"]["operations"]:
        semantic = reviewed[item["id"]].semantic_digest if item["executor"] == "static" else "dynamic-secret-from-bound-template"
        operations.append({**item, "semanticDigest": semantic, "client": str(CLIENT)})
    return {"candidateDigest": sha(candidate_path), "protocolDigest": candidate["spec"]["protocol"]["digest"], "operations": operations, "credentialUseGranted": False, "mutationAuthorized": False, "clusterContacted": False}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "plan"))
    parser.add_argument("--candidate", type=Path, default=CANDIDATE)
    args = parser.parse_args()
    try:
        candidate_path = args.candidate.resolve()
        candidate, _, _ = validate_candidate(candidate_path)
        result = plan(candidate_path)
        result["state"] = candidate["spec"]["state"]
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (ExecutorError, V3.SubmitterError, V3.V2.SubmitterError, MAT.MaterializerError, PF.PreflightV2Error, OSError, KeyError, TypeError, ValueError, yaml.YAMLError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
