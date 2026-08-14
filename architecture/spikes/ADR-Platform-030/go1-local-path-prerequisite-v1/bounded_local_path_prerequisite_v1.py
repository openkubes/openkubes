#!/usr/bin/env python3
"""One-shot create-only local-path prerequisite for the OK-141 disposable cluster."""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import importlib.util
import json
import os
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

import yaml


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
CANDIDATE = HERE / "local-path-prerequisite-candidate-v1.yaml"
RENDERER_PATH = HERE / "render_local_path_prerequisite_v1.py"
BINDING_PATH = SPIKE / "go1-runtime-binding-v2" / "bounded_runtime_binding_v2.py"
BINDING_CANDIDATE = SPIKE / "go1-runtime-binding-v2" / "runtime-binding-candidate-v2.yaml"
DIAGNOSTIC_EVIDENCE = Path("/private/tmp/ok141-runtime-binding-diagnostic-v1-evidence.json")
EPHEMERAL = Path("/private/tmp/ok141-local-path-prerequisite-v1-kubeconfig.yaml")
OUTPUT = Path("/private/tmp/ok141-local-path-prerequisite-v1-evidence.json")


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


RENDERER = load_module("ok141_local_path_renderer", RENDERER_PATH)
BINDING = load_module("ok141_runtime_binding_for_local_path", BINDING_PATH)


class PrerequisiteError(ValueError):
    pass


def sha_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def sha(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def read(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text())
    if not isinstance(value, dict):
        raise PrerequisiteError(f"expected mapping: {path}")
    return value


def expect(actual: Any, expected: Any, context: str) -> None:
    if actual != expected:
        raise PrerequisiteError(f"{context}: expected {expected!r}, got {actual!r}")


def parse_time(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise PrerequisiteError("timestamp lacks timezone")
    return parsed.astimezone(dt.timezone.utc)


def safe_file(path: Path, mode: int = 0o600) -> None:
    if path.is_symlink() or not path.is_file() or stat.S_IMODE(path.stat().st_mode) != mode:
        raise PrerequisiteError(f"unsafe runtime file: {path}")


def write_exclusive(path: Path, raw: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)


def object_id(value: dict[str, Any]) -> str:
    return {
        "Namespace": "namespace",
        "ServiceAccount": "serviceaccount",
        "Role": "role",
        "ClusterRole": "clusterrole",
        "RoleBinding": "rolebinding",
        "ClusterRoleBinding": "clusterrolebinding",
        "ConfigMap": "configmap",
        "StorageClass": "storageclass",
        "Deployment": "deployment",
    }[value["kind"]]


def projected_objects(candidate: dict[str, Any]) -> dict[str, dict[str, Any]]:
    projection = HERE / candidate["spec"]["projection"]["path"]
    expect(sha(projection), candidate["spec"]["projection"]["digest"], "projection digest")
    values = list(yaml.safe_load_all(projection.read_text()))
    expect(RENDERER.canonical_digest(values), candidate["spec"]["projection"]["semanticDigest"], "projection semantics")
    mapped = {object_id(value): value for value in values}
    expect(set(mapped), {item["id"] for item in candidate["spec"]["objects"]}, "projection object set")
    return mapped


def validate_candidate(path: Path = CANDIDATE) -> dict[str, Any]:
    value = read(path)
    expect(value.get("kind"), "GO1LocalPathPrerequisiteCandidate", "kind")
    spec = value["spec"]
    expect(spec["version"], "ok141-local-path-prerequisite/v1", "version")
    expect((spec["state"], spec["failureSemantics"]), ("OFFLINE-PROVEN-BLOCKED-NO-GO", "STOP-PRESERVE-NO-RETRY"), "state")
    expect(spec["source"]["openKubesWorkflow"], {"repository": "openkubes/ok-cluster", "commit": "c4bb72e368bdedb92d75485ce9972d86e8a75210", "makeTarget": "install-storage"}, "OpenKubes workflow")
    expect((spec["source"]["repository"], spec["source"]["tag"], spec["source"]["commit"]), ("rancher/local-path-provisioner", "v0.0.30", "c4fdcada94c2e632cd7d9231e73406d554eb40e2"), "upstream identity")
    expect(sha(HERE / spec["source"]["path"]), spec["source"]["digest"], "source digest")
    expect(sha(RENDERER_PATH), spec["tool"]["rendererDigest"], "renderer digest")
    expect(sha(HERE / spec["tool"]["executorPath"]), spec["tool"]["executorDigest"], "executor digest")
    rendered = RENDERER.render()
    expect(RENDERER.canonical_digest(rendered), spec["projection"]["semanticDigest"], "rendered semantics")
    projected = projected_objects(value)
    expect(len(projected), spec["projection"]["objectCount"], "object count")
    expect(projected["deployment"]["spec"]["template"]["spec"]["containers"][0]["image"], spec["projection"]["provisionerImage"], "provisioner image")
    helper = yaml.safe_load(projected["configmap"]["data"]["helperPod.yaml"])
    expect(helper["spec"]["containers"][0]["image"], spec["projection"]["helperImage"], "helper image")
    expect(spec["authorization"]["decision"], "NO-GO", "authorization")
    if any(item for key, item in spec["authorization"].items() if key.endswith("Granted")):
        raise PrerequisiteError("candidate grants authority")
    return value


TRUE = (
    "riskAcceptanceGranted", "clusterContactGranted", "managementCredentialUseGranted",
    "exactSecretReadGranted", "ephemeralCredentialMaterializationGranted",
    "workloadCredentialUseGranted", "exactAbsencePreflightGranted",
    "exactCreateOnlyGranted", "readinessObservationGranted",
)
FALSE = (
    "runtimeBindingGranted", "happyRunResumeGranted", "retryGranted",
    "rollbackOrCleanupGranted", "evidencePublicationGranted", "failureInjectionGranted",
)


def validate_diagnostic(grant_spec: dict[str, Any]) -> dict[str, Any]:
    path = Path(grant_spec["diagnosticEvidencePath"])
    expect(path, DIAGNOSTIC_EVIDENCE, "diagnostic path")
    safe_file(path)
    expect(sha(path), grant_spec["diagnosticEvidenceDigest"], "diagnostic digest")
    value = read(path)
    expect((value.get("kind"), value.get("finding")), ("GO1RuntimeBindingDiagnosticEvidence", "LOCAL-PATH-ABSENT"), "diagnostic result")
    expect((value.get("workloadIdentityValidated"), value.get("persistentMutationPerformed"), value.get("happyRunResumed")), (True, False, False), "diagnostic boundary")
    expect(value.get("workloadTargetIdentityDigest"), grant_spec["workloadTargetIdentityDigest"], "target identity")
    return value


def validate_grant(candidate_path: Path, grant_path: Path, now: dt.datetime | None = None):
    validate_candidate(candidate_path)
    grant = read(grant_path)
    expect(grant.get("kind"), "GO1LocalPathPrerequisiteGrant", "grant kind")
    spec = grant["spec"]
    expect((spec.get("decision"), spec.get("authority"), spec.get("singleRun"), spec.get("consumed")), ("GO", "github:arashkaffamanesh", True, False), "grant identity")
    expect(spec.get("candidateDigest"), sha(candidate_path), "candidate digest")
    expect(spec.get("riskAcceptance"), "DEV-LOCAL-PATH-BOUNDARY-ACCEPTED", "risk acceptance")
    if any(spec.get(key) is not True for key in TRUE) or any(spec.get(key) is not False for key in FALSE):
        raise PrerequisiteError("grant incomplete or overbroad")
    current = now or dt.datetime.now(dt.timezone.utc)
    issued, expires = parse_time(spec["issuedAt"]), parse_time(spec["expiresAt"])
    if not issued <= current <= expires or expires - issued > dt.timedelta(minutes=30):
        raise PrerequisiteError("grant inactive or exceeds 30 minutes")
    expect(spec["rawEvidencePath"], str(OUTPUT), "evidence path")
    return grant, validate_diagnostic(spec)


def invoke(client: Path, kubeconfig: Path, arguments: list[str], runner: Callable[..., Any], payload: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    return runner([str(client), "--kubeconfig", str(kubeconfig), *arguments], input=payload, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


def get_exact(client: Path, kubeconfig: Path, uri: str, runner: Callable[..., Any], allow_not_found: bool = False) -> dict[str, Any] | None:
    completed = invoke(client, kubeconfig, ["get", "--raw", uri], runner)
    if completed.returncode != 0:
        if allow_not_found and b"NotFound" in completed.stderr:
            return None
        raise PrerequisiteError("bounded exact GET failed")
    value = json.loads(completed.stdout)
    if not isinstance(value, dict):
        raise PrerequisiteError("bounded exact GET returned non-object")
    return value


def create_exact(client: Path, kubeconfig: Path, uri: str, value: dict[str, Any], runner: Callable[..., Any]) -> dict[str, Any]:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    completed = invoke(client, kubeconfig, ["create", "--raw", uri, "--filename", "-"], runner, payload)
    if completed.returncode != 0:
        raise PrerequisiteError("bounded exact create failed")
    created = json.loads(completed.stdout)
    if not isinstance(created, dict) or not created.get("metadata", {}).get("uid") or not created.get("metadata", {}).get("resourceVersion"):
        raise PrerequisiteError("created object lacks immutable identity")
    return created


def readiness(client: Path, kubeconfig: Path, candidate: dict[str, Any], runner: Callable[..., Any], sleeper: Callable[[float], None]) -> dict[str, Any]:
    spec = candidate["spec"]
    endpoints = {item["id"]: item["get"] for item in spec["objects"]}
    for attempt in range(1, spec["readiness"]["maximumPolls"] + 1):
        deployment = get_exact(client, kubeconfig, endpoints["deployment"], runner)
        storage = get_exact(client, kubeconfig, endpoints["storageclass"], runner)
        namespace = get_exact(client, kubeconfig, endpoints["namespace"], runner)
        deployment_ready = deployment.get("status", {}).get("availableReplicas", 0) >= spec["readiness"]["deploymentAvailableReplicas"] and deployment.get("status", {}).get("observedGeneration", 0) >= deployment.get("metadata", {}).get("generation", 1)
        storage_ready = (storage.get("provisioner"), storage.get("volumeBindingMode"), storage.get("reclaimPolicy"), storage.get("metadata", {}).get("annotations", {}).get("storageclass.kubernetes.io/is-default-class")) == (spec["readiness"]["storageClassProvisioner"], spec["readiness"]["volumeBindingMode"], spec["readiness"]["reclaimPolicy"], "true")
        namespace_ready = all(namespace.get("metadata", {}).get("labels", {}).get(key) == value for key, value in RENDERER.PSA.items())
        if deployment_ready and storage_ready and namespace_ready:
            return {"attempts": attempt, "deploymentAvailable": True, "storageClassReady": True, "privilegedNamespaceLabelsReady": True}
        if attempt < spec["readiness"]["maximumPolls"]:
            sleeper(spec["readiness"]["intervalSeconds"])
    raise PrerequisiteError("local-path readiness timeout")


def execute(candidate_path: Path, grant_path: Path, runner: Callable[..., Any] = subprocess.run, sleeper: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    candidate = validate_candidate(candidate_path)
    grant, diagnostic = validate_grant(candidate_path, grant_path)
    spec = candidate["spec"]
    binding = BINDING.validate_candidate(BINDING_CANDIDATE)["spec"]
    if OUTPUT.exists() or EPHEMERAL.exists():
        raise PrerequisiteError("exclusive runtime path already exists")
    management_client = Path(binding["management"]["clientPath"])
    workload_client = Path(binding["workload"]["clientPath"])
    expect(sha(management_client), binding["management"]["clientDigest"], "management client")
    expect(sha(workload_client), binding["workload"]["clientDigest"], "workload client")
    management_kubeconfig = Path(binding["management"]["credentialPath"])
    safe_file(management_kubeconfig)
    expect(BINDING.EXECUTOR.inspect_identity(management_kubeconfig)["identityDigest"], binding["management"]["credentialIdentityDigest"], "management identity")
    evidence: dict[str, Any] = {
        "apiVersion": "evidence.openkubes.io/v1alpha1", "kind": "GO1LocalPathPrerequisiteEvidence",
        "candidateDigest": sha(candidate_path), "grantID": grant["spec"]["grantID"],
        "runID": grant["spec"]["runID"], "diagnosticEvidenceDigest": sha(DIAGNOSTIC_EVIDENCE),
        "workloadTargetIdentityDigest": diagnostic["workloadTargetIdentityDigest"],
        "result": "STARTED", "created": [], "persistentMutationAttempted": False,
        "retryPerformed": False, "cleanupPerformed": False, "happyRunResumed": False,
        "secretPayloadRetained": False,
    }
    try:
        secret = get_exact(management_client, management_kubeconfig, binding["management"]["secretRawURI"], runner)
        raw = base64.b64decode(secret["data"]["value"], validate=True)
        write_exclusive(EPHEMERAL, raw)
        expect(BINDING.EXECUTOR.inspect_identity(EPHEMERAL)["identityDigest"], grant["spec"]["workloadTargetIdentityDigest"], "workload identity")
        objects = projected_objects(candidate)
        for item in spec["objects"]:
            if get_exact(workload_client, EPHEMERAL, item["get"], runner, allow_not_found=True) is not None:
                raise PrerequisiteError("absence preflight found existing object")
        evidence["absencePreflight"] = {"result": "PASS-ALL-NINE-ABSENT", "objects": 9}
        evidence["persistentMutationAttempted"] = True
        for item in spec["objects"]:
            created = create_exact(workload_client, EPHEMERAL, item["post"], objects[item["id"]], runner)
            evidence["created"].append({"id": item["id"], "uid": created["metadata"]["uid"], "resourceVersion": created["metadata"]["resourceVersion"]})
        evidence["readiness"] = readiness(workload_client, EPHEMERAL, candidate, runner, sleeper)
        evidence["result"] = "SUCCESS-STORAGE-PREREQUISITE-READY"
        return evidence
    except Exception as error:
        evidence["result"] = "STOP-PRESERVE-NO-RETRY"
        evidence["failureType"] = type(error).__name__
        evidence["failure"] = str(error)
        raise
    finally:
        EPHEMERAL.unlink(missing_ok=True)
        evidence["ephemeralKubeconfigRemoved"] = not EPHEMERAL.exists()
        evidence["secretPayloadRetained"] = False
        write_exclusive(OUTPUT, (json.dumps(evidence, sort_keys=True, separators=(",", ":")) + "\n").encode())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "verify-grant", "execute"))
    parser.add_argument("--candidate", type=Path, default=CANDIDATE)
    parser.add_argument("--grant", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "verify":
            validate_candidate(args.candidate.resolve())
            print(sha(args.candidate.resolve()))
        elif args.command == "verify-grant":
            if args.grant is None:
                raise PrerequisiteError("grant is required")
            validate_grant(args.candidate.resolve(), args.grant.resolve())
            print(sha(args.grant.resolve()))
        else:
            if args.grant is None or not args.execute:
                raise PrerequisiteError("execute requires --grant and --execute")
            result = execute(args.candidate.resolve(), args.grant.resolve())
            print(json.dumps({"result": result["result"], "outputPath": str(OUTPUT)}, sort_keys=True))
        return 0
    except (PrerequisiteError, OSError, KeyError, TypeError, ValueError, yaml.YAMLError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
