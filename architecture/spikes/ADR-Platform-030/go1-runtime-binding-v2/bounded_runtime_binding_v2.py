#!/usr/bin/env python3
"""Materialize the Phase-R v5 runtime binding from current, bounded observations."""

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
from pathlib import Path
from typing import Any, Callable

import yaml

HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
CANDIDATE = HERE / "runtime-binding-candidate-v2.yaml"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


EXECUTOR = load_module("ok141_executor_v2_for_runtime_binding", SPIKE / "go1-l-executor-v2" / "bounded_go1_l_executor_v2.py")


class BindingError(ValueError):
    pass


def read_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text())
    if not isinstance(value, dict):
        raise BindingError(f"expected mapping: {path}")
    return value


def sha_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def digest(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def canonical_digest(value: Any) -> str:
    return sha_bytes(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def expect(actual: Any, expected: Any, context: str) -> None:
    if actual != expected:
        raise BindingError(f"{context}: expected {expected!r}, got {actual!r}")


def resolve(candidate_path: Path, requested: str) -> Path:
    path = (candidate_path.parent / requested).resolve()
    if SPIKE.resolve() not in path.parents or not path.is_file():
        raise BindingError(f"reference missing or outside spike root: {requested}")
    return path


def parse_time(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise BindingError("timestamp lacks timezone")
    return parsed.astimezone(dt.timezone.utc)


def validate_candidate(candidate_path: Path = CANDIDATE) -> dict[str, Any]:
    candidate = read_yaml(candidate_path)
    expect(candidate.get("kind"), "GO1RuntimeBindingCandidate", "kind")
    spec = candidate["spec"]
    expect(spec["version"], "ok141-go1-runtime-binding/v2", "version")
    expect(spec["state"], "OFFLINE-PROVEN-BLOCKED-NO-GO", "state")
    for key in ("protocol", "lifecycleObserver", "networkObserver"):
        expect(digest(resolve(candidate_path, spec[key]["path"])), spec[key]["digest"], f"{key} digest")
    expect(digest(resolve(candidate_path, spec["tool"]["path"])), spec["tool"]["digest"], "tool digest")
    expect(spec["management"]["secretRawURI"], "/api/v1/namespaces/disposable-ok141/secrets/disposable-ok141-kubeconfig", "Secret URI")
    expect(spec["workload"]["queries"], {
        "kubeSystem": "/api/v1/namespaces/kube-system",
        "localPath": "/apis/storage.k8s.io/v1/storageclasses/local-path",
    }, "workload query boundary")
    expect(spec["workload"]["tokenAudience"], "https://kubernetes.default.svc.cluster.local", "TokenRequest audience")
    if any(spec["authorization"].get(key) for key in spec["authorization"] if key.endswith("Granted")):
        raise BindingError("candidate grants authority")
    return candidate


def validate_grant(candidate_path: Path, grant_path: Path, now: dt.datetime | None = None) -> dict[str, Any]:
    candidate = validate_candidate(candidate_path)
    grant = read_yaml(grant_path)
    expect(grant.get("kind"), "GO1RuntimeBindingGrant", "grant kind")
    spec = grant["spec"]
    expect(spec["decision"], "GO", "decision")
    expect(spec["candidateDigest"], digest(candidate_path), "candidate digest")
    expect(spec["protocolDigest"], candidate["spec"]["protocol"]["digest"], "protocol digest")
    for key in ("lifecycleEvidenceDigest", "networkEvidenceDigest"):
        value = spec.get(key, "")
        if not isinstance(value, str) or not value.startswith("sha256:") or len(value) != 71:
            raise BindingError(f"invalid {key}")
    required_true = ("clusterContactGranted", "credentialUseGranted", "secretReadGranted", "ephemeralMaterializationGranted", "readOnlyQueriesGranted")
    forbidden = ("persistentMutationGranted", "registrationGranted", "platformSubmissionGranted", "go1Granted", "retryGranted", "cleanupGranted")
    if any(spec.get(key) is not True for key in required_true) or any(spec.get(key) is not False for key in forbidden):
        raise BindingError("grant authority mismatch")
    current = now or dt.datetime.now(dt.timezone.utc)
    issued, expires = parse_time(spec["issuedAt"]), parse_time(spec["expiresAt"])
    if not issued <= current <= expires or expires - issued > dt.timedelta(minutes=15):
        raise BindingError("grant is inactive or exceeds 15 minutes")
    if spec.get("singleRun") is not True or spec.get("consumed") is not False:
        raise BindingError("grant is not an unused single run")
    return grant


def verify_evidence(path: Path, expected: str, kind: str, state: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or digest(path) != expected:
        raise BindingError(f"{kind} evidence identity mismatch")
    value = json.loads(path.read_text())
    expect(value.get("kind"), kind, f"{kind} kind")
    expect(value.get("closureState"), state, f"{kind} state")
    return value


def run_raw(client: Path, kubeconfig: Path, uri: str, runner: Callable[..., Any]) -> dict[str, Any]:
    completed = runner([str(client), "--kubeconfig", str(kubeconfig), "get", "--raw", uri], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if completed.returncode != 0:
        raise BindingError("bounded raw GET failed")
    value = json.loads(completed.stdout)
    if not isinstance(value, dict):
        raise BindingError("bounded raw GET returned non-object")
    return value


def write_exclusive(path: Path, raw: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)


def kubeconfig_values(raw: bytes) -> tuple[str, str, str]:
    value = yaml.safe_load(raw)
    context_name = value["current-context"]
    context = next(item["context"] for item in value["contexts"] if item["name"] == context_name)
    cluster = next(item["cluster"] for item in value["clusters"] if item["name"] == context["cluster"])
    server, ca_data = cluster["server"], cluster["certificate-authority-data"]
    ca_raw = base64.b64decode(ca_data, validate=True)
    if not server.startswith("https://") or not ca_raw:
        raise BindingError("workload kubeconfig has no HTTPS server or CA")
    return server, ca_data, sha_bytes(ca_raw)


def execute(candidate_path: Path, grant_path: Path, lifecycle_path: Path, network_path: Path, management_client: Path, workload_client: Path, runner: Callable[..., Any] = subprocess.run) -> dict[str, Any]:
    candidate = validate_candidate(candidate_path)
    grant = validate_grant(candidate_path, grant_path)
    spec, grant_spec = candidate["spec"], grant["spec"]
    lifecycle = verify_evidence(lifecycle_path, grant_spec["lifecycleEvidenceDigest"], "GO1LLifecycleAPIEvidence", "PASS-CURRENT-LIFECYCLE-API-EVIDENCE")
    network = verify_evidence(network_path, grant_spec["networkEvidenceDigest"], "GO1LNetworkReadyEvidence", "PASS-NETWORK-READY")
    expect(digest(lifecycle_path), network["lifecycleEvidenceDigest"], "lifecycle/network correlation")
    for key in ("protocolDigest", "fixtureDigest"):
        expect(lifecycle[key], spec["protocol"][key], f"lifecycle {key}")
        expect(network[key], spec["protocol"][key], f"network {key}")
    expect(network["R"], spec["protocol"]["R"], "network R")
    expect(network["E"], spec["protocol"]["E"], "network E")
    if network.get("NetworkReady") is not True:
        raise BindingError("NetworkReady is not true")
    if digest(management_client) != spec["management"]["clientDigest"] or digest(workload_client) != spec["workload"]["clientDigest"]:
        raise BindingError("kubectl digest mismatch")
    mgmt_kubeconfig = Path(spec["management"]["credentialPath"])
    if mgmt_kubeconfig.is_symlink() or not mgmt_kubeconfig.is_file() or (mgmt_kubeconfig.stat().st_mode & 0o777) != 0o600:
        raise BindingError("unsafe management kubeconfig")
    expect(EXECUTOR.inspect_identity(mgmt_kubeconfig)["identityDigest"], spec["management"]["credentialIdentityDigest"], "management identity")
    output, ephemeral = Path(spec["outputPath"]), Path(spec["workload"]["ephemeralKubeconfigPath"])
    if output.exists() or ephemeral.exists():
        raise BindingError("exclusive output already exists")
    secret = run_raw(management_client, mgmt_kubeconfig, spec["management"]["secretRawURI"], runner)
    raw = base64.b64decode(secret["data"]["value"], validate=True)
    try:
        write_exclusive(ephemeral, raw)
        identity = EXECUTOR.inspect_identity(ephemeral)
        expect(identity["identityDigest"], network["workloadTargetIdentityDigest"], "workload identity")
        server, ca_data, ca_fingerprint = kubeconfig_values(raw)
        expect(ca_fingerprint, identity["caFingerprint"], "CA fingerprint")
        kube_system = run_raw(workload_client, ephemeral, spec["workload"]["queries"]["kubeSystem"], runner)
        storage = run_raw(workload_client, ephemeral, spec["workload"]["queries"]["localPath"], runner)
    finally:
        raw = b""
        ephemeral.unlink(missing_ok=True)
    if storage.get("provisioner") != spec["workload"]["localPathProvisioner"]:
        raise BindingError("local-path provisioner mismatch")
    cluster = lifecycle["details"]["objects"]["cluster"]
    binding = {
        "apiVersion": "evidence.openkubes.io/v1alpha1", "kind": "GO1RuntimeBinding",
        "spec": {
            "version": "ok141-go1-runtime-binding/v2", "state": "CURRENT-RUNTIME-BOUND-NO-GO",
            "protocolDigest": spec["protocol"]["protocolDigest"], "fixtureDigest": spec["protocol"]["fixtureDigest"],
            "R": spec["protocol"]["R"], "E": spec["protocol"]["E"], "P": spec["protocol"]["P"],
            "target": {"name": "disposable-ok141", "capiClusterUID": cluster["uid"], "capiObservedGeneration": cluster["observedGeneration"], "workloadKubeSystemUID": kube_system["metadata"]["uid"], "workloadAPIServer": server, "workloadAPICAFingerprint": ca_fingerprint, "caData": ca_data, "tokenAudience": spec["workload"]["tokenAudience"]},
            "evidence": {"lifecycleDigest": lifecycle["semanticDigest"], "networkDigest": network["semanticDigest"], "NetworkReady": True, "localPathStorageClassUID": storage["metadata"]["uid"], "localPathProvisioner": storage["provisioner"]},
            "authorization": {"registrationGranted": False, "platformSubmissionGranted": False, "go1Granted": False},
        },
    }
    binding["spec"]["semanticDigest"] = canonical_digest(binding["spec"])
    write_exclusive(output, (json.dumps(binding, sort_keys=True, separators=(",", ":")) + "\n").encode())
    return {"state": binding["spec"]["state"], "semanticDigest": binding["spec"]["semanticDigest"], "outputPath": str(output), "credentialPayloadPrinted": False, "ephemeralKubeconfigRemoved": not ephemeral.exists(), "persistentMutationPerformed": False}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "verify-grant", "bind"))
    parser.add_argument("--candidate", type=Path, default=CANDIDATE)
    parser.add_argument("--grant", type=Path)
    parser.add_argument("--lifecycle-evidence", type=Path)
    parser.add_argument("--network-evidence", type=Path)
    parser.add_argument("--management-kubectl", type=Path)
    parser.add_argument("--workload-kubectl", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "verify":
            validate_candidate(args.candidate.resolve()); print(digest(args.candidate.resolve()))
        elif args.command == "verify-grant":
            if args.grant is None: raise BindingError("grant is required")
            validate_grant(args.candidate.resolve(), args.grant.resolve()); print(digest(args.grant.resolve()))
        else:
            required = (args.grant, args.lifecycle_evidence, args.network_evidence, args.management_kubectl, args.workload_kubectl)
            if not args.execute or any(value is None for value in required): raise BindingError("bind requires --execute and all runtime inputs")
            print(json.dumps(execute(args.candidate.resolve(), args.grant.resolve(), args.lifecycle_evidence.resolve(), args.network_evidence.resolve(), args.management_kubectl.resolve(), args.workload_kubectl.resolve()), sort_keys=True))
        return 0
    except (BindingError, OSError, KeyError, TypeError, ValueError, yaml.YAMLError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr); return 2


if __name__ == "__main__":
    raise SystemExit(main())
