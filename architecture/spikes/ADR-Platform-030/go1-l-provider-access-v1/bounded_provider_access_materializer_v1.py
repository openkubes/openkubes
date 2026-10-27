#!/usr/bin/env python3
"""Secret-safe provider-access materializer. The merged candidate remains NO-GO."""

from __future__ import annotations

import argparse
import base64
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
CANDIDATE = HERE / "provider-access-materializer-candidate-v1.yaml"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    assert spec.loader is not None
    spec.loader.exec_module(result)
    return result


SUBMITTER = load_module("ok141_submitter_v3_for_provider_access", SPIKE / "go1-l-submitter-v3/bounded_go1_l_submitter_v3.py")
V2 = SUBMITTER.V2
V1 = SUBMITTER.V1


class MaterializerError(ValueError):
    pass


def expect(actual: Any, expected: Any, context: str) -> None:
    if actual != expected:
        raise MaterializerError(f"{context}: expected {expected!r}, got {actual!r}")


def resolve(candidate_path: Path, requested: str) -> Path:
    path = (candidate_path.parent / requested).resolve()
    if SPIKE.resolve() not in path.parents or not path.is_file():
        raise MaterializerError(f"reference missing or outside spike root: {requested}")
    return path


def load_candidate(path: Path = CANDIDATE) -> dict[str, Any]:
    return V1.read_yaml_or_json(path)


def validate_candidate(candidate: dict[str, Any], candidate_path: Path = CANDIDATE) -> dict[str, Any]:
    expect(candidate.get("apiVersion"), "execution.openkubes.io/v1alpha1", "apiVersion")
    expect(candidate.get("kind"), "ProviderAccessMaterializerCandidate", "kind")
    spec = candidate["spec"]
    expect(spec["version"], "ok141-provider-access-materializer/v1", "version")
    expect(spec["state"], "OFFLINE-PROVEN-BLOCKED-NO-GO", "state")
    expect(spec["authorization"], {
        "decision": "NO-GO",
        "currentGrantBound": False,
        "sourceCredentialReadGranted": False,
        "destinationCredentialUseGranted": False,
        "secretMaterializationGranted": False,
        "recreationGranted": False,
        "go1LGranted": False,
        "retryGranted": False,
        "rollbackOrCleanupGranted": False,
    }, "authorization")

    preflight_ref = spec["sourcePreflight"]
    preflight_path = resolve(candidate_path, preflight_ref["path"])
    expect(V2.sha(preflight_path), preflight_ref["digest"], "preflight digest")
    preflight = V1.read_yaml_or_json(preflight_path)["spec"]
    expect(preflight["state"], "OFFLINE-PREPARED-BLOCKED-NO-GO", "preflight state")
    if any(preflight["authorization"].values()):
        raise MaterializerError("source preflight grants authority")

    fixture_ref = spec["fixture"]
    fixture_path = resolve(candidate_path, fixture_ref["path"])
    expect(V2.sha(fixture_path), fixture_ref["fileDigest"], "fixture file digest")
    fixture = V1.read_yaml_or_json(fixture_path)
    expect(fixture["fixtureDigest"], fixture_ref["fixtureDigest"], "FixtureDigest")
    expect(fixture["contract"]["R"], fixture_ref["R"], "R")
    expect(fixture["authorizationState"], "NO-GO", "fixture authorization")
    for key in ("fileDigest", "fixtureDigest", "R"):
        expect(fixture_ref[key], preflight["correctedFixture"][key], f"preflight fixture {key}")

    submitter_ref = spec["submitter"]
    submitter_path = resolve(candidate_path, submitter_ref["path"])
    expect(V2.sha(submitter_path), submitter_ref["digest"], "submitter digest")
    submitter = SUBMITTER.load_candidate(submitter_path)
    SUBMITTER.validate_candidate(submitter, submitter_path)
    expect(submitter["spec"]["state"], submitter_ref["state"], "submitter state")
    prerequisite = submitter["spec"]["externalPrerequisite"]

    template = spec["secretTemplate"]
    expect(template["apiVersion"], "v1", "Secret apiVersion")
    expect(template["kind"], "Secret", "Secret kind")
    expect(template["type"], "Opaque", "Secret type")
    expect(template["metadata"], {"name": prerequisite["secretRef"]["name"], "namespace": prerequisite["secretRef"]["namespace"], "annotations": {"openkubes.io/intent-revision": fixture_ref["R"], "openkubes.io/execution-fixture": fixture_ref["fixtureDigest"], "openkubes.io/provider-plane": "ok-infra"}}, "Secret metadata")
    expect(template["dataKey"], prerequisite["secretDataKey"], "Secret data key")
    expect(prerequisite["executedByThisTool"], False, "static submitter Secret boundary")

    source = spec["sourceCredential"]
    expect(source["path"], preflight["providerAccess"]["sourceCredentialPath"], "source credential path")
    expect(source["plane"], "ok-infra", "source plane")
    expect(source["readOnly"], True, "source read boundary")
    for key in ("bytesInRepositoryAllowed", "bytesInArgumentsAllowed", "bytesInEnvironmentAllowed", "bytesInLogsOrEvidenceAllowed", "contentDigestInPublicEvidenceAllowed"):
        expect(source[key], False, f"source boundary {key}")

    tool = spec["tool"]
    tool_path = resolve(candidate_path, tool["path"])
    expect(V2.sha(tool_path), tool["digest"], "materializer tool digest")
    expect(tool["arbitrarySourcePathAllowed"], False, "source path boundary")
    expect(tool["arbitrarySecretIdentityAllowed"], False, "Secret identity boundary")
    expect(tool["arbitraryCommandAllowed"], False, "command boundary")
    expect(spec["runtimeGrant"]["operation"], "provider-access-secret", "grant operation")
    expect(spec["runtimeGrant"]["predecessorEvidenceCount"], 2, "predecessor count")
    expect(spec["runtimeGrant"]["maximumMinutes"], 20, "grant duration")
    expect(spec["transport"], {"operation": "CreateExactProviderAccessSecret", "createOnly": True, "serverSideApply": False, "stdinPayloadOnly": True, "secretBytesInArguments": False, "secretBytesInEnvironment": False, "secretBytesInOutputOrEvidence": False, "automaticRetryAllowed": False, "automaticRollbackAllowed": False, "partialStateOnFailure": "STOP-PRESERVE-NO-CLEANUP"}, "transport")
    return spec


def build_plan(candidate: dict[str, Any], candidate_path: Path = CANDIDATE, destination_credential: Path | None = None) -> dict[str, Any]:
    spec = validate_candidate(candidate, candidate_path)
    metadata = spec["secretTemplate"]["metadata"]
    return {
        "operation": "provider-access-secret",
        "sourcePlane": "ok-infra",
        "targetPlane": "ok-mgmt",
        "secretIdentity": f"v1|Secret|{metadata['namespace']}|{metadata['name']}",
        "dataKeys": [spec["secretTemplate"]["dataKey"]],
        "command": ["kubectl", "--kubeconfig", str(destination_credential) if destination_credential else "RUNTIME-CREDENTIAL-FILE:ok-mgmt", "create", "--filename", "-"],
        "sourceCredentialBytesRead": False,
        "secretPayloadBuilt": False,
        "mutationAuthorized": False,
        "clusterContacted": False,
    }


def validate_file(path: Path, role: str) -> None:
    if not path.is_file() or path.is_symlink() or path.stat().st_size == 0:
        raise MaterializerError(f"{role} must be a regular non-symlink file")
    if stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise MaterializerError(f"{role} mode must be 0600")
    if REPOSITORY.resolve() in path.resolve().parents:
        raise MaterializerError(f"{role} must remain outside the repository")


def default_source_reader(path: Path) -> bytes:
    validate_file(path, "source credential")
    return path.read_bytes()


def validate_kubeconfig(raw: bytes) -> None:
    try:
        value = yaml.load(raw.decode("utf-8"), Loader=V1.UniqueKeyLoader)
    except (UnicodeDecodeError, yaml.YAMLError) as error:
        raise MaterializerError("source credential is not a valid UTF-8 kubeconfig") from error
    if not isinstance(value, dict) or value.get("apiVersion") != "v1" or value.get("kind") != "Config":
        raise MaterializerError("source credential is not a Kubernetes Config")
    contexts = {item.get("name"): item.get("context", {}) for item in value.get("contexts", []) if isinstance(item, dict)}
    clusters = {item.get("name") for item in value.get("clusters", []) if isinstance(item, dict)}
    users = {item.get("name") for item in value.get("users", []) if isinstance(item, dict)}
    current = value.get("current-context")
    if not current or current not in contexts:
        raise MaterializerError("source kubeconfig lacks a valid current-context")
    if contexts[current].get("cluster") not in clusters or contexts[current].get("user") not in users:
        raise MaterializerError("source kubeconfig current-context references are incomplete")


def build_secret_payload(spec: dict[str, Any], raw_kubeconfig: bytes) -> bytes:
    validate_kubeconfig(raw_kubeconfig)
    template = spec["secretTemplate"]
    secret = {"apiVersion": "v1", "kind": "Secret", "metadata": template["metadata"], "type": template["type"], "data": {template["dataKey"]: base64.b64encode(raw_kubeconfig).decode("ascii")}}
    return json.dumps(secret, sort_keys=True, separators=(",", ":")).encode("utf-8")


def validate_runtime_authority(candidate: dict[str, Any], candidate_path: Path, grant: dict[str, Any], source_receipt: dict[str, Any], source_receipt_path: Path, destination_receipt: dict[str, Any], destination_receipt_path: Path, destination_credential: Path, now: dt.datetime) -> None:
    spec = validate_candidate(candidate, candidate_path)
    grant_spec = grant["spec"]
    expect(grant_spec["decision"], "GO", "grant decision")
    expect(grant_spec["sourceCredentialReadGranted"], True, "source read authority")
    expect(grant_spec["destinationCredentialUseGranted"], True, "destination credential authority")
    expect(grant_spec["secretMaterializationGranted"], True, "Secret authority")
    expect(grant_spec["go1LGranted"], True, "GO1-L authority")
    expect(grant_spec["operationGranted"], "provider-access-secret", "grant operation")
    expect(grant_spec["candidateDigest"], V2.sha(candidate_path), "grant candidate")
    expect(grant_spec["fixtureDigest"], spec["fixture"]["fixtureDigest"], "grant fixture")
    expect(grant_spec["submitterDigest"], spec["submitter"]["digest"], "grant submitter")
    if V2.contains_secret_field(grant) or V2.contains_secret_field(source_receipt) or V2.contains_secret_field(destination_receipt):
        raise MaterializerError("grant or receipt contains a secret-bearing field")
    if not grant_spec.get("grantID") or grant_spec.get("singleRun") is not True:
        raise MaterializerError("grant identity or single-run boundary is missing")
    issued, expires = V2.parse_time(grant_spec["issuedAt"]), V2.parse_time(grant_spec["expiresAt"])
    if not issued <= now <= expires or expires - issued > dt.timedelta(minutes=spec["runtimeGrant"]["maximumMinutes"]):
        raise MaterializerError("grant is outside its maximum window")
    predecessors = grant_spec["predecessorEvidenceDigests"]
    if len(predecessors) != spec["runtimeGrant"]["predecessorEvidenceCount"] or any(not item.startswith("sha256:") for item in predecessors):
        raise MaterializerError("predecessor evidence count or digest is invalid")
    expect(V2.sha(source_receipt_path), grant_spec["sourceCredentialReceiptDigest"], "source receipt binding")
    expect(V2.sha(destination_receipt_path), grant_spec["destinationCredentialReceiptDigest"], "destination receipt binding")
    source_spec, destination_spec = source_receipt["spec"], destination_receipt["spec"]
    expect(source_spec["operation"], "provider-access-source", "source receipt operation")
    expect(source_spec["targetPlane"], "ok-infra", "source receipt plane")
    expect(source_spec["sourcePath"], spec["sourceCredential"]["path"], "source receipt path")
    expect(destination_spec["operation"], "provider-access-secret", "destination receipt operation")
    expect(destination_spec["targetPlane"], "ok-mgmt", "destination receipt plane")
    for receipt_spec in (source_spec, destination_spec):
        expect(receipt_spec["tokenBytesPersisted"], False, "credential persistence")
        expect(receipt_spec["tokenBytesEmitted"], False, "credential emission")
        if V2.parse_time(receipt_spec["issuedAt"]) > now or not now <= V2.parse_time(receipt_spec["expiresAt"]) <= expires:
            raise MaterializerError("credential receipt outlives its grant")
    validate_file(destination_credential, "destination credential")
    if destination_credential.resolve() == Path(spec["sourceCredential"]["path"]).resolve():
        raise MaterializerError("source and destination credentials must be distinct")


def execute_once(candidate: dict[str, Any], candidate_path: Path, grant: dict[str, Any], source_receipt: dict[str, Any], source_receipt_path: Path, destination_receipt: dict[str, Any], destination_receipt_path: Path, destination_credential: Path, now: dt.datetime, runner: Callable[..., Any] = subprocess.run, source_reader: Callable[[Path], bytes] = default_source_reader) -> dict[str, Any]:
    validate_runtime_authority(candidate, candidate_path, grant, source_receipt, source_receipt_path, destination_receipt, destination_receipt_path, destination_credential, now)
    spec = validate_candidate(candidate, candidate_path)
    raw_kubeconfig = source_reader(Path(spec["sourceCredential"]["path"]))
    payload = build_secret_payload(spec, raw_kubeconfig)
    completed = runner(["kubectl", "--kubeconfig", str(destination_credential), "create", "--filename", "-"], input=payload, check=True, capture_output=True)
    metadata = spec["secretTemplate"]["metadata"]
    return {
        "operation": "provider-access-secret",
        "targetPlane": "ok-mgmt",
        "secretIdentity": f"v1|Secret|{metadata['namespace']}|{metadata['name']}",
        "dataKeys": [spec["secretTemplate"]["dataKey"]],
        "transportExitCode": completed.returncode,
        "sourceCredentialBytesEmitted": False,
        "sourceContentDigestEmitted": False,
        "secretPayloadPersisted": False,
        "retryPerformed": False,
        "rollbackOrCleanupPerformed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "plan"))
    parser.add_argument("--candidate", type=Path, default=CANDIDATE)
    args = parser.parse_args()
    try:
        path = args.candidate.resolve()
        candidate = load_candidate(path)
        spec = validate_candidate(candidate, path)
        result = {"candidateDigest": V2.sha(path), "state": spec["state"], "operation": "provider-access-secret", "sourceCredentialBytesRead": False, "secretPayloadBuilt": False, "mutationAuthorized": False, "clusterContacted": False} if args.command == "verify" else build_plan(candidate, path)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (KeyError, OSError, MaterializerError, SUBMITTER.SubmitterError, V2.SubmitterError, TypeError, ValueError, yaml.YAMLError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
