#!/usr/bin/env python3
"""Bounded Argo convergence and Observability capability observer for OK-141."""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

import yaml

HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
CANDIDATE = HERE / "platform-observer-candidate-v1.yaml"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


EXECUTOR = load_module("ok141_executor_for_platform_observer", SPIKE / "go1-l-executor-v2" / "bounded_go1_l_executor_v2.py")


class PlatformObserverError(ValueError):
    pass


def sha_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def digest(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def read_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text())
    if not isinstance(value, dict):
        raise PlatformObserverError(f"expected mapping: {path}")
    return value


def expect(actual: Any, expected: Any, context: str) -> None:
    if actual != expected:
        raise PlatformObserverError(f"{context}: expected {expected!r}, got {actual!r}")


def resolve(candidate_path: Path, requested: str) -> Path:
    path = (candidate_path.parent / requested).resolve()
    if SPIKE.resolve() not in path.parents or not path.is_file():
        raise PlatformObserverError(f"reference missing or outside spike root: {requested}")
    return path


def parse_time(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise PlatformObserverError("timestamp lacks timezone")
    return parsed.astimezone(dt.timezone.utc)


def validate_candidate(candidate_path: Path = CANDIDATE) -> dict[str, Any]:
    candidate = read_yaml(candidate_path)
    expect(candidate.get("kind"), "GO1PlatformObserverCandidate", "kind")
    spec = candidate["spec"]
    expect(spec["version"], "ok141-go1-platform-observer/v1", "version")
    expect(spec["state"], "OFFLINE-PROVEN-BLOCKED-NO-GO", "state")
    for key in ("protocol", "projection", "profile", "applications"):
        expect(digest(resolve(candidate_path, spec[key]["path"])), spec[key]["digest"], f"{key} digest")
    expect(digest(resolve(candidate_path, spec["tool"]["path"])), spec["tool"]["digest"], "tool digest")
    expect(spec["capability"]["scriptDigest"], "sha256:bd68328f35de960bfc291880dd7f85274021c0cce8d7b69ccecde0a459ead648", "capability script")
    expect(spec["capability"]["contractDigest"], "sha256:b6ef10a8ecf6daf42e6d44018d51e2263f380ed649445e5a70ff5c550c73415e", "capability contract")
    expect(spec["capability"]["alertAcceptance"], "firing-only", "alert boundary")
    expect(spec["argo"]["credentialIdentityDigest"], "sha256:790e5efe2af8f8b8703c1745b9e2643ec4ac14f254d52016ad2c2679a79bdefb", "ok-shared identity")
    if any(spec["authorization"].get(key) for key in spec["authorization"] if key.endswith("Granted")):
        raise PlatformObserverError("candidate grants authority")
    return candidate


def validate_grant(candidate_path: Path, grant_path: Path, now: dt.datetime | None = None) -> dict[str, Any]:
    candidate = validate_candidate(candidate_path)
    grant = read_yaml(grant_path)
    expect(grant.get("kind"), "GO1PlatformObserverGrant", "grant kind")
    spec = grant["spec"]
    expect(spec["decision"], "GO", "decision")
    expect(spec["candidateDigest"], digest(candidate_path), "candidate digest")
    for key in ("runtimeBindingDigest", "registrationEvidenceDigest", "credentialMaterializationEvidenceDigest", "applicationSubmissionEvidenceDigest", "credentialFileDigest"):
        value = spec.get(key, "")
        if not isinstance(value, str) or not value.startswith("sha256:") or len(value) != 71:
            raise PlatformObserverError(f"invalid {key}")
    required = ("clusterContactGranted", "credentialUseGranted", "secretReadGranted", "argoObservationGranted", "capabilityTestGranted", "capabilityTestCleanupGranted")
    forbidden = ("arbitraryMutationGranted", "applicationSubmissionGranted", "retryGranted", "go1Granted", "failureInjectionGranted")
    if any(spec.get(key) is not True for key in required) or any(spec.get(key) is not False for key in forbidden):
        raise PlatformObserverError("grant authority mismatch")
    current = now or dt.datetime.now(dt.timezone.utc)
    issued, expires = parse_time(spec["issuedAt"]), parse_time(spec["expiresAt"])
    if not issued <= current <= expires or expires - issued > dt.timedelta(minutes=50):
        raise PlatformObserverError("grant inactive or exceeds 50 minutes")
    if spec.get("singleRun") is not True or spec.get("consumed") is not False:
        raise PlatformObserverError("grant is not an unused single run")
    return grant


def run_raw(client: Path, kubeconfig: Path, uri: str, runner: Callable[..., Any]) -> dict[str, Any]:
    completed = runner([str(client), "--kubeconfig", str(kubeconfig), "get", "--raw", uri], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if completed.returncode != 0:
        raise PlatformObserverError("bounded raw GET failed")
    value = json.loads(completed.stdout)
    if not isinstance(value, dict):
        raise PlatformObserverError("bounded raw GET returned non-object")
    return value


def application_ready(obj: dict[str, Any], candidate: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    name = obj.get("metadata", {}).get("name")
    if name not in candidate["spec"]["argo"]["applicationNames"]:
        raise PlatformObserverError("unexpected Application identity")
    annotations = obj["metadata"].get("annotations", {})
    fixture = candidate["spec"]["fixture"]
    for key, expected in (("openkubes.io/intent-revision", fixture["R"]), ("openkubes.io/platform-revision", fixture["P"]), ("openkubes.io/execution-fixture", fixture["fixtureDigest"])):
        expect(annotations.get(key), expected, f"Application {name} {key}")
    status = obj.get("status", {})
    revision = status.get("sync", {}).get("revision")
    ready = status.get("sync", {}).get("status") == "Synced" and status.get("health", {}).get("status") == "Healthy" and revision == candidate["spec"]["argo"]["sourceRevision"]
    return ready, {"name": name, "uid": obj["metadata"].get("uid"), "sync": status.get("sync", {}).get("status"), "health": status.get("health", {}).get("status"), "revision": revision}


def verify_file(path: Path, expected: str, description: str) -> Any:
    if path.is_symlink() or not path.is_file() or digest(path) != expected:
        raise PlatformObserverError(f"{description} identity mismatch")
    return json.loads(path.read_text())


def write_exclusive(path: Path, value: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(value)


def execute(candidate_path: Path, grant_path: Path, runtime_binding_path: Path, registration_evidence_path: Path, credential_evidence_path: Path, application_evidence_path: Path, credential_file: Path, capability_script: Path, shared_client: Path, management_client: Path, workload_client: Path, runner: Callable[..., Any] = subprocess.run, sleeper: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    candidate = validate_candidate(candidate_path)
    grant = validate_grant(candidate_path, grant_path)
    spec, grant_spec = candidate["spec"], grant["spec"]
    binding = verify_file(runtime_binding_path, grant_spec["runtimeBindingDigest"], "runtime binding")
    registration = verify_file(registration_evidence_path, grant_spec["registrationEvidenceDigest"], "registration evidence")
    credential_evidence = verify_file(credential_evidence_path, grant_spec["credentialMaterializationEvidenceDigest"], "credential materialization evidence")
    applications_evidence = verify_file(application_evidence_path, grant_spec["applicationSubmissionEvidenceDigest"], "Application submission evidence")
    expect(registration.get("state"), "REGISTRATION-CREATED", "registration predecessor")
    expect(credential_evidence.get("state"), "PLATFORM-CREDENTIAL-SECRET-CREATED", "credential predecessor")
    expect(applications_evidence.get("state"), "APPLICATIONS-SUBMITTED", "Application predecessor")
    expect(binding["spec"]["fixtureDigest"], spec["fixture"]["fixtureDigest"], "binding fixture")
    expect(binding["spec"]["R"], spec["fixture"]["R"], "binding R")
    expect(binding["spec"]["P"], spec["fixture"]["P"], "binding P")
    if binding["spec"]["evidence"].get("NetworkReady") is not True:
        raise PlatformObserverError("runtime binding lacks NetworkReady")
    credentials = verify_file(credential_file, grant_spec["credentialFileDigest"], "credential file")
    expected_keys = set(spec["capability"]["credentialKeys"])
    if set(credentials) != expected_keys or any(not isinstance(value, str) or len(value) < 16 for value in credentials.values()):
        raise PlatformObserverError("credential file shape mismatch")
    for client, expected in ((shared_client, spec["argo"]["clientDigest"]), (management_client, spec["management"]["clientDigest"]), (workload_client, spec["workload"]["clientDigest"])):
        if digest(client) != expected:
            raise PlatformObserverError("kubectl digest mismatch")
    shared_kubeconfig, mgmt_kubeconfig = Path(spec["argo"]["credentialPath"]), Path(spec["management"]["credentialPath"])
    for kubeconfig, identity in ((shared_kubeconfig, spec["argo"]["credentialIdentityDigest"]), (mgmt_kubeconfig, spec["management"]["credentialIdentityDigest"])):
        if kubeconfig.is_symlink() or not kubeconfig.is_file() or (kubeconfig.stat().st_mode & 0o777) != 0o600:
            raise PlatformObserverError("unsafe administrator kubeconfig")
        expect(EXECUTOR.inspect_identity(kubeconfig)["identityDigest"], identity, "credential identity")
    if digest(capability_script) != spec["capability"]["scriptDigest"]:
        raise PlatformObserverError("capability script digest mismatch")
    output, ephemeral = Path(spec["outputPath"]), Path(spec["workload"]["ephemeralKubeconfigPath"])
    tool_dir = Path(spec["workload"]["ephemeralToolDirectory"])
    if output.exists() or ephemeral.exists() or tool_dir.exists():
        raise PlatformObserverError("exclusive runtime output already exists")
    history, app_details = [], []
    ready = False
    for iteration in range(1, spec["argo"]["maximumIterations"] + 1):
        app_details, ready = [], True
        for name in spec["argo"]["applicationNames"]:
            obj = run_raw(shared_client, shared_kubeconfig, f"/apis/argoproj.io/v1alpha1/namespaces/argocd/applications/{name}", runner)
            current, detail = application_ready(obj, candidate)
            app_details.append(detail); ready = ready and current
        history.append({"iteration": iteration, "ready": ready})
        if ready: break
        if iteration < spec["argo"]["maximumIterations"]: sleeper(spec["argo"]["intervalSeconds"])
    if not ready:
        raise PlatformObserverError("Applications did not converge")
    secret = run_raw(management_client, mgmt_kubeconfig, spec["management"]["secretRawURI"], runner)
    raw_kubeconfig = base64.b64decode(secret["data"]["value"], validate=True)
    write_exclusive(ephemeral, raw_kubeconfig)
    capability_completed = None
    try:
        workload_identity = EXECUTOR.inspect_identity(ephemeral)
        expect(workload_identity["server"], binding["spec"]["target"]["workloadAPIServer"], "workload API server")
        expect(workload_identity["caFingerprint"], binding["spec"]["target"]["workloadAPICAFingerprint"], "workload API CA")
        tool_dir.mkdir(mode=0o700)
        os.symlink(workload_client, tool_dir / "kubectl")
        env = os.environ.copy()
        env.update({"PATH": f"{tool_dir}:{env.get('PATH', '')}", "KUBECONFIG": str(ephemeral), "CONTRACT_TEST_NAMESPACE": "ok-observability", "CONTRACT_TEST_TIMEOUT": "240", "GRAFANA_USER": credentials["grafana-admin-user"], "GRAFANA_PASSWORD": credentials["grafana-admin-password"], "OPENSEARCH_USER": "admin", "OPENSEARCH_PASSWORD": credentials["opensearch-admin-password"], "CONTRACT_TEST_RECEIVER_CAPTURE_URL": ""})
        capability_completed = runner(["bash", str(capability_script)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, env=env, timeout=1800)
    finally:
        raw_kubeconfig = b""
        credentials = {key: "" for key in credentials}
        ephemeral.unlink(missing_ok=True)
        (tool_dir / "kubectl").unlink(missing_ok=True)
        try: tool_dir.rmdir()
        except FileNotFoundError: pass
        credential_file.unlink(missing_ok=True)
    if capability_completed is None or capability_completed.returncode != 0:
        raise PlatformObserverError("exact capability test failed; raw output suppressed")
    evidence = {"apiVersion": "evidence.openkubes.io/v1alpha1", "kind": "GO1PlatformReadyEvidence", "candidateDigest": digest(candidate_path), "grantID": grant_spec["grantID"], "fixtureDigest": spec["fixture"]["fixtureDigest"], "R": spec["fixture"]["R"], "P": spec["fixture"]["P"], "runtimeBindingDigest": grant_spec["runtimeBindingDigest"], "applications": app_details, "history": history, "PlatformReady": True, "capabilityContractDigest": spec["capability"]["contractDigest"], "capabilityScriptDigest": spec["capability"]["scriptDigest"], "capabilityStdoutDigest": sha_bytes(capability_completed.stdout), "capabilityStderrDigest": sha_bytes(capability_completed.stderr), "alertAcceptance": "firing-only", "credentialFileRemoved": not credential_file.exists(), "workloadKubeconfigRemoved": not ephemeral.exists(), "credentialBytesRetained": False, "rawCapabilityOutputRetained": False}
    evidence["semanticDigest"] = sha_bytes(json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode())
    write_exclusive(output, (json.dumps(evidence, sort_keys=True, separators=(",", ":")) + "\n").encode())
    return {"closureState": "PASS-PLATFORM-READY", "semanticDigest": evidence["semanticDigest"], "PlatformReady": True}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "verify-grant", "observe"))
    parser.add_argument("--candidate", type=Path, default=CANDIDATE)
    parser.add_argument("--grant", type=Path)
    parser.add_argument("--runtime-binding", type=Path)
    parser.add_argument("--registration-evidence", type=Path)
    parser.add_argument("--credential-evidence", type=Path)
    parser.add_argument("--application-evidence", type=Path)
    parser.add_argument("--credential-file", type=Path)
    parser.add_argument("--capability-script", type=Path)
    parser.add_argument("--shared-kubectl", type=Path)
    parser.add_argument("--management-kubectl", type=Path)
    parser.add_argument("--workload-kubectl", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "verify": validate_candidate(args.candidate.resolve()); print(digest(args.candidate.resolve()))
        elif args.command == "verify-grant":
            if args.grant is None: raise PlatformObserverError("grant required")
            validate_grant(args.candidate.resolve(), args.grant.resolve()); print(digest(args.grant.resolve()))
        else:
            needed = (args.grant, args.runtime_binding, args.registration_evidence, args.credential_evidence, args.application_evidence, args.credential_file, args.capability_script, args.shared_kubectl, args.management_kubectl, args.workload_kubectl)
            if not args.execute or any(value is None for value in needed): raise PlatformObserverError("observe requires --execute and all runtime inputs")
            print(json.dumps(execute(args.candidate.resolve(), args.grant.resolve(), args.runtime_binding.resolve(), args.registration_evidence.resolve(), args.credential_evidence.resolve(), args.application_evidence.resolve(), args.credential_file.resolve(), args.capability_script.resolve(), args.shared_kubectl.resolve(), args.management_kubectl.resolve(), args.workload_kubectl.resolve()), sort_keys=True))
        return 0
    except (PlatformObserverError, KeyError, OSError, TypeError, ValueError, yaml.YAMLError, json.JSONDecodeError, subprocess.SubprocessError) as error:
        print(f"ERROR: {error}", file=sys.stderr); return 2


if __name__ == "__main__":
    raise SystemExit(main())
