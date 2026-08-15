#!/usr/bin/env python3
"""One-shot, read-only and redacted Cilium functional connectivity diagnostic."""

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
from urllib.parse import quote

import yaml


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
CANDIDATE = HERE / "network-functional-diagnostic-candidate-v1.yaml"
NETWORK_CANDIDATE = SPIKE / "go1-l-network-observer-v1" / "go1-l-network-observer-candidate-v1.yaml"
NETWORK_CANDIDATE_DIGEST = "sha256:15b24bd0d7247e0a05d4b1f291221cc52e4f1cefa498b8fe4c5d00b6347f3e04"
FAILED_PATH = Path("/private/tmp/ok141-go1-l-network-ready-observer-defaulting-v1-evidence.json")
OUTPUT_PATH = Path("/private/tmp/ok141-network-functional-diagnostic-v1-evidence.json")
EPHEMERAL_PATH = Path("/private/tmp/ok141-network-functional-diagnostic-v1-kubeconfig.yaml")
MGMT_CLIENT = Path("/private/tmp/ok141-kubectl-v1.34.1-darwin-amd64")
WORKLOAD_CLIENT = Path("/private/tmp/ok141-kubectl-v1.36.2-darwin-amd64")
MGMT_KUBECONFIG = Path("/Users/arash/.kube/ok-mgmt.yaml")
PROBE = ("cilium-health", "status", "--probe", "--output", "json")


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(value)
    return value


NETWORK = load_module("ok141_network_v1_for_functional_diagnostic", SPIKE / "go1-l-network-observer-v1" / "bounded_go1_l_network_observer_v1.py")


class DiagnosticError(ValueError):
    pass


def sha_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def sha(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def read(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text())
    if not isinstance(value, dict):
        raise DiagnosticError(f"expected mapping: {path}")
    return value


def expect(actual: Any, expected: Any, context: str) -> None:
    if actual != expected:
        raise DiagnosticError(f"{context}: expected {expected!r}, got {actual!r}")


def parse_time(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise DiagnosticError("timestamp lacks timezone")
    return parsed.astimezone(dt.timezone.utc)


def write_exclusive(path: Path, raw: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)


def validate_candidate(path: Path = CANDIDATE) -> dict[str, Any]:
    value = read(path)
    expect(value.get("kind"), "GO1NetworkFunctionalDiagnosticCandidate", "kind")
    spec = value["spec"]
    expect(spec["version"], "ok141-network-functional-diagnostic/v1", "version")
    expect(spec["state"], "OFFLINE-PROVEN-BLOCKED-NO-GO", "state")
    expect(sha(NETWORK_CANDIDATE), NETWORK_CANDIDATE_DIGEST, "network candidate")
    NETWORK.validate_candidate(NETWORK_CANDIDATE)
    expect(spec["predecessor"]["candidateDigest"], NETWORK_CANDIDATE_DIGEST, "network candidate binding")
    expect(spec["predecessor"]["privateEvidencePath"], str(FAILED_PATH), "failed evidence path")
    expect(spec["probe"]["command"], list(PROBE), "probe command")
    expect(spec["output"]["path"], str(OUTPUT_PATH), "output path")
    expect(sha(HERE / spec["tool"]["path"]), spec["tool"]["digest"], "tool digest")
    auth = spec["authorization"]
    expect(auth["decision"], "NO-GO", "authorization")
    if any(item for key, item in auth.items() if key.endswith("Granted")):
        raise DiagnosticError("candidate grants authority")
    return value


def safe_failed(path: Path, expected_digest: str) -> dict[str, Any]:
    expect(path, FAILED_PATH, "failed evidence path")
    if path.is_symlink() or not path.is_file() or (path.stat().st_mode & 0o777) != 0o600:
        raise DiagnosticError("unsafe failed evidence")
    expect(sha(path), expected_digest, "failed evidence digest")
    value = read(path)
    expect((value.get("kind"), value.get("closureState"), value.get("NetworkReady")), ("GO1LNetworkReadyEvidence", "FAIL-FUNCTIONAL-CONNECTIVITY", False), "failed result")
    expect((value.get("persistentMutationPerformed"), value.get("fixedPodExecProbePerformed")), (False, True), "failed probe boundary")
    pod = value.get("details", {}).get("probePod", {})
    if not pod.get("name") or not pod.get("uid") or not value.get("workloadTargetIdentityDigest"):
        raise DiagnosticError("failed evidence lacks bound probe identity")
    return value


TRUE = ("clusterContactGranted", "managementCredentialUseGranted", "exactSecretReadGranted", "ephemeralCredentialMaterializationGranted", "workloadCredentialUseGranted", "exactPodReadGranted", "fixedPodExecDiagnosticGranted")
FALSE = ("persistentMutationGranted", "networkObserverRetryGranted", "happyRunResumeGranted", "rollbackOrCleanupGranted", "evidencePublicationGranted", "failureInjectionGranted")


def validate_grant(candidate_path: Path, grant_path: Path, now: dt.datetime | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    validate_candidate(candidate_path)
    grant = read(grant_path)
    expect(grant.get("kind"), "GO1NetworkFunctionalDiagnosticGrant", "grant kind")
    spec = grant["spec"]
    expect((spec.get("decision"), spec.get("authority"), spec.get("singleRun"), spec.get("consumed")), ("GO", "github:arashkaffamanesh", True, False), "grant identity")
    expect(spec.get("candidateDigest"), sha(candidate_path), "candidate digest")
    if any(spec.get(key) is not True for key in TRUE) or any(spec.get(key) is not False for key in FALSE):
        raise DiagnosticError("diagnostic authority is incomplete or overbroad")
    current = now or dt.datetime.now(dt.timezone.utc)
    issued, expires = parse_time(spec["issuedAt"]), parse_time(spec["expiresAt"])
    if not issued <= current <= expires or expires - issued > dt.timedelta(minutes=20):
        raise DiagnosticError("grant inactive or exceeds 20 minutes")
    failed = safe_failed(Path(spec["failedNetworkEvidencePath"]), spec["failedNetworkEvidenceDigest"])
    pod = failed["details"]["probePod"]
    expect((spec["podName"], spec["podUID"]), (pod["name"], pod["uid"]), "probe pod binding")
    expect(spec["workloadTargetIdentityDigest"], failed["workloadTargetIdentityDigest"], "workload identity binding")
    return grant, failed


def classify(status: Any) -> tuple[str, str]:
    if status == "":
        return "PASS", sha_bytes(b"")
    if not isinstance(status, str):
        return "INVALID", sha_bytes(json.dumps(status, sort_keys=True).encode())
    lowered = status.lower()
    if "timeout" in lowered or "deadline exceeded" in lowered or "timed out" in lowered:
        category = "TIMEOUT"
    elif "refused" in lowered:
        category = "REFUSED"
    elif "no route" in lowered or "unreachable" in lowered:
        category = "UNREACHABLE"
    elif "permission" in lowered or "unauthorized" in lowered or "forbidden" in lowered:
        category = "AUTHORIZATION"
    else:
        category = "OTHER"
    return category, sha_bytes(status.encode())


def summarize_probe(value: dict[str, Any], expected_nodes: list[str]) -> tuple[str, dict[str, Any]]:
    nodes = value.get("nodes")
    if not isinstance(nodes, list) or sorted(item.get("name") for item in nodes if isinstance(item, dict)) != sorted(expected_nodes):
        return "FAIL-PROBE-NODE-COVERAGE", {"expectedNodeCount": len(expected_nodes)}
    results = []
    all_pass = True
    for node in sorted(nodes, key=lambda item: item.get("name", "")):
        for section in ("host", "health-endpoint"):
            primary = node.get(section, {}).get("primary-address", {})
            for protocol in ("http", "icmp"):
                path = primary.get(protocol, {})
                category, status_digest = classify(path.get("status"))
                all_pass = all_pass and category == "PASS"
                results.append({"node": node.get("name"), "section": section, "protocol": protocol, "category": category, "statusDigest": status_digest, "lastProbed": path.get("lastProbed")})
    return ("PASS-CURRENT-FUNCTIONAL-CONNECTIVITY" if all_pass else "OBSERVED-FUNCTIONAL-CONNECTIVITY-FAILURE"), {"paths": results, "pathCount": len(results)}


def raw_get(client: Path, kubeconfig: Path, uri: str, runner: Callable[..., Any]) -> dict[str, Any]:
    completed = runner([str(client), "--kubeconfig", str(kubeconfig), "get", "--raw", uri], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if completed.returncode != 0:
        raise DiagnosticError("bounded raw GET failed")
    value = json.loads(completed.stdout)
    if not isinstance(value, dict):
        raise DiagnosticError("bounded raw GET returned non-object")
    return value


def execute(candidate_path: Path, grant_path: Path, runner: Callable[..., Any] = subprocess.run) -> dict[str, Any]:
    candidate = validate_candidate(candidate_path)
    grant, failed = validate_grant(candidate_path, grant_path)
    spec, grant_spec = candidate["spec"], grant["spec"]
    for path, expected, label in ((MGMT_CLIENT, spec["clients"]["managementDigest"], "management client"), (WORKLOAD_CLIENT, spec["clients"]["workloadDigest"], "workload client")):
        expect(sha(path), expected, label)
    if MGMT_KUBECONFIG.is_symlink() or not MGMT_KUBECONFIG.is_file() or (MGMT_KUBECONFIG.stat().st_mode & 0o777) != 0o600:
        raise DiagnosticError("unsafe management kubeconfig")
    expect(NETWORK.EXECUTOR.inspect_identity(MGMT_KUBECONFIG)["identityDigest"], spec["managementCredentialIdentityDigest"], "management identity")
    if OUTPUT_PATH.exists() or EPHEMERAL_PATH.exists():
        raise DiagnosticError("exclusive output already exists")
    secret = raw_get(MGMT_CLIENT, MGMT_KUBECONFIG, spec["secretRawURI"], runner)
    write_exclusive(EPHEMERAL_PATH, base64.b64decode(secret["data"]["value"], validate=True))
    probe_completed = None
    pod_identity_verified = False
    try:
        expect(NETWORK.EXECUTOR.inspect_identity(EPHEMERAL_PATH)["identityDigest"], grant_spec["workloadTargetIdentityDigest"], "workload identity")
        pod_name = grant_spec["podName"]
        pod = raw_get(WORKLOAD_CLIENT, EPHEMERAL_PATH, f"/api/v1/namespaces/kube-system/pods/{quote(pod_name, safe='')}", runner)
        expect(pod.get("metadata", {}).get("uid"), grant_spec["podUID"], "probe pod UID")
        containers = {item.get("name") for item in pod.get("spec", {}).get("containers", [])}
        if "cilium-agent" not in containers:
            raise DiagnosticError("bound pod lacks cilium-agent")
        pod_identity_verified = True
        command = [str(WORKLOAD_CLIENT), "--kubeconfig", str(EPHEMERAL_PATH), "exec", "--namespace", "kube-system", pod_name, "--container", "cilium-agent", "--", *PROBE]
        probe_completed = runner(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        if probe_completed.returncode == 0:
            state, details = summarize_probe(json.loads(probe_completed.stdout), failed["details"]["nodeNames"])
        else:
            state, details = "PROBE-EXEC-FAILED", {"stdoutDigest": sha_bytes(probe_completed.stdout), "stderrDigest": sha_bytes(probe_completed.stderr)}
    finally:
        EPHEMERAL_PATH.unlink(missing_ok=True)
    evidence = {
        "apiVersion": "evidence.openkubes.io/v1alpha1",
        "kind": "GO1NetworkFunctionalDiagnosticEvidence",
        "candidateDigest": sha(candidate_path),
        "grantID": grant_spec["grantID"],
        "failedNetworkEvidenceDigest": grant_spec["failedNetworkEvidenceDigest"],
        "probePod": {"name": grant_spec["podName"], "uid": grant_spec["podUID"]},
        "podIdentityVerified": pod_identity_verified,
        "probeExitCode": probe_completed.returncode if probe_completed is not None else None,
        "result": state,
        "details": details,
        "workloadKubeconfigRemoved": not EPHEMERAL_PATH.exists(),
        "rawProbeOutputRetained": False,
        "secretPayloadRetained": False,
        "persistentMutationPerformed": False,
        "happyRunResumed": False,
    }
    evidence["semanticDigest"] = sha_bytes(json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode())
    write_exclusive(OUTPUT_PATH, (json.dumps(evidence, sort_keys=True, separators=(",", ":")) + "\n").encode())
    return evidence


def plan(path: Path = CANDIDATE) -> dict[str, Any]:
    value = validate_candidate(path)
    return {"candidateDigest": sha(path), "probe": value["spec"]["probe"], "authorization": "NO-GO", "clusterContacted": False, "mutationPerformed": False}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "verify-grant", "run"))
    parser.add_argument("--candidate", type=Path, default=CANDIDATE)
    parser.add_argument("--grant", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "verify":
            print(json.dumps(plan(args.candidate.resolve()), indent=2, sort_keys=True))
        elif args.command == "verify-grant":
            if args.grant is None:
                raise DiagnosticError("grant required")
            validate_grant(args.candidate.resolve(), args.grant.resolve())
            print(sha(args.grant.resolve()))
        else:
            if not args.execute or args.grant is None:
                raise DiagnosticError("run requires --execute and grant")
            result = execute(args.candidate.resolve(), args.grant.resolve())
            print(json.dumps({"result": result["result"], "semanticDigest": result["semanticDigest"]}, sort_keys=True))
        return 0
    except Exception as error:
        print(f"ERROR: {type(error).__name__}: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
