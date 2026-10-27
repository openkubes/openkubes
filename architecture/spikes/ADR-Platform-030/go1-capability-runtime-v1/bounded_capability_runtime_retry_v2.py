#!/usr/bin/env python3
"""Single diagnosis-bound retry for the OK-141 capability test."""

from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import json
import os
import signal
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent


def load_v1():
    spec = importlib.util.spec_from_file_location("ok141_capability_v1", HERE / "bounded_capability_runtime_v1.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


V1 = load_v1()


class RetryError(ValueError):
    pass


def sha_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def digest(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise RetryError("expected mapping")
    return value


def expect(actual: Any, expected: Any, context: str) -> None:
    if actual != expected:
        raise RetryError(f"{context} mismatch")


def validate(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    candidate = read_json(path)
    expect(candidate.get("kind"), "OK141CapabilityRuntimeRetryCandidate", "kind")
    spec = candidate["spec"]
    expect(spec.get("version"), "ok141-capability-runtime-retry/v2", "version")
    expect(spec.get("state"), "AUTHORIZED-SINGLE-DIAGNOSIS-BASED-RETRY", "state")
    predecessor_path = (path.parent / spec["predecessor"]["candidatePath"]).resolve()
    expect(digest(predecessor_path), spec["predecessor"]["candidateDigest"], "predecessor candidate")
    predecessor = V1.validate_candidate(predecessor_path)
    for key in ("failedEvidence", "componentDiagnostic", "prometheusDiagnostic", "logDiagnostic"):
        evidence_path = Path(spec["predecessor"][key]["path"])
        expect(digest(evidence_path), spec["predecessor"][key]["digest"], key)
    if spec["retry"].get("singleRun") is not True or spec["retry"].get("furtherRetryAllowed") is not False:
        raise RetryError("retry boundary mismatch")
    tool_path = (path.parent / spec["tool"]["path"]).resolve()
    expect(digest(tool_path), spec["tool"]["digest"], "retry tool")
    return candidate, predecessor


def target_snapshot(port: int, target_name: str) -> tuple[bool, bool, str]:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/v1/targets?state=active", timeout=3) as response:
            body = json.loads(response.read())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return False, False, "UNAVAILABLE"
    targets = body.get("data", {}).get("activeTargets", []) if isinstance(body, dict) else []
    matches = [item for item in targets if target_name in str(item.get("scrapePool", ""))]
    if not matches:
        return False, False, "ABSENT"
    healthy = any(item.get("health") == "up" for item in matches)
    return True, healthy, "UP" if healthy else "DOWN"


def classify(stdout: bytes, stderr: bytes) -> dict[str, Any]:
    combined = (stdout + b"\n" + stderr).decode(errors="replace")
    success_markers = {
        "syntheticWorkloadReady": "synthetic workload (Pushgateway) ready",
        "serviceMonitorRegistered": "ServiceMonitor registered",
        "metricsPushed": "synthetic metric + alert-trigger metric pushed",
        "prometheusIngested": "metric ingested by Prometheus",
        "grafanaVisible": "metric visible via Grafana datasource",
        "logSearchable": "log marker found in OpenSearch",
        "alertFiring": "synthetic alert reached Alertmanager",
        "contractPass": "CONTRACT TEST: PASS",
        "cleanupInvoked": "[CLEANUP]",
    }
    failure_markers = {
        "prometheusTimeout": "metric never appeared in Prometheus",
        "grafanaFailure": "Grafana datasource proxy query failed",
        "logFailure": "OpenSearch log search failed",
        "alertTimeout": "synthetic alert never appeared in Alertmanager",
        "applyFailure": "kubectl apply reported errors",
        "workloadReadinessFailure": "synthetic workload did not become ready",
    }
    return {
        "success": {key: marker in combined for key, marker in success_markers.items()},
        "failure": {key: marker in combined for key, marker in failure_markers.items()},
        "stdoutDigest": sha_bytes(stdout),
        "stderrDigest": sha_bytes(stderr),
        "rawOutputRetained": False,
    }


def execute(path: Path) -> dict[str, Any]:
    candidate, predecessor = validate(path)
    spec = candidate["spec"]
    base = predecessor["spec"]
    output = Path(spec["outputPath"])
    ephemeral = Path(spec["runtime"]["ephemeralKubeconfigPath"])
    tool_dir = Path(spec["runtime"]["ephemeralToolDirectory"])
    if any(item.exists() or item.is_symlink() for item in (output, ephemeral, tool_dir)):
        raise RetryError("exclusive runtime path exists")
    shared_client = Path(base["tools"]["sharedAndManagementKubectl"]["path"])
    workload_client = Path(base["tools"]["workloadKubectl"]["path"])
    shared_kubeconfig = Path(base["credentials"]["sharedKubeconfig"])
    management_kubeconfig = Path(base["credentials"]["managementKubeconfig"])

    applications = []
    for name in base["applications"]:
        uri = f"/apis/argoproj.io/v1alpha1/namespaces/argocd/applications/{name}"
        applications.append(V1.application_status(V1.raw_get(shared_client, shared_kubeconfig, uri), base))
    secret = V1.raw_get(shared_client, management_kubeconfig, base["workload"]["kubeconfigSecretURI"])
    V1.write_exclusive(ephemeral, base64.b64decode(secret["data"]["value"], validate=True))

    credentials: dict[str, str] = {}
    process: subprocess.Popen[bytes] | None = None
    monitor: subprocess.Popen[bytes] | None = None
    observations: list[dict[str, Any]] = []
    completed_stdout = b""
    completed_stderr = b""
    exit_code = -1
    run_id = spec["retry"]["runID"]
    target_name = "ok-observability-contract-test-" + run_id.replace("_", "-")
    try:
        credential_secret = V1.raw_get(workload_client, ephemeral, base["workload"]["credentialSecretURI"])
        for key in base["workload"]["credentialKeys"]:
            credentials[key] = base64.b64decode(credential_secret["data"][key], validate=True).decode()
            if len(credentials[key]) < 16:
                raise RetryError("credential shape mismatch")
        tool_dir.mkdir(mode=0o700)
        os.symlink(workload_client, tool_dir / "kubectl")
        env = os.environ.copy()
        env.update({
            "PATH": f"{tool_dir}:/usr/local/bin:/usr/bin:/bin",
            "KUBECONFIG": str(ephemeral),
            "CONTRACT_TEST_NAMESPACE": base["capability"]["namespace"],
            "CONTRACT_TEST_RUN_ID": run_id,
            "CONTRACT_TEST_TIMEOUT": str(base["capability"]["asyncTimeoutSeconds"]),
            "GRAFANA_USER": credentials["grafana-admin-user"],
            "GRAFANA_PASSWORD": credentials["grafana-admin-password"],
            "OPENSEARCH_USER": "admin",
            "OPENSEARCH_PASSWORD": credentials["opensearch-admin-password"],
            "CONTRACT_TEST_RECEIVER_CAPTURE_URL": "",
        })
        monitor_port = spec["retry"]["prometheusMonitorPort"]
        monitor = subprocess.Popen([str(workload_client), "--kubeconfig", str(ephemeral), "-n", base["capability"]["namespace"], "port-forward", "service/ok-observability-prometheus", f"{monitor_port}:9090"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        process = subprocess.Popen([base["tools"]["bash"]["path"], base["capability"]["scriptPath"]], stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, start_new_session=True)
        deadline = time.monotonic() + base["capability"]["overallTimeoutSeconds"]
        while True:
            try:
                completed_stdout, completed_stderr = process.communicate(timeout=5)
                exit_code = process.returncode
                break
            except subprocess.TimeoutExpired:
                seen, healthy, state = target_snapshot(monitor_port, target_name)
                observations.append({"iteration": len(observations) + 1, "targetSeen": seen, "targetHealthy": healthy, "state": state})
                if time.monotonic() >= deadline:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        completed_stdout, completed_stderr = process.communicate(timeout=10)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        completed_stdout, completed_stderr = process.communicate()
                    exit_code = process.returncode
                    raise RetryError("capability retry exceeded bounded timeout")
    finally:
        if monitor is not None and monitor.poll() is None:
            os.killpg(monitor.pid, signal.SIGTERM)
            try:
                monitor.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(monitor.pid, signal.SIGKILL)
        credentials = {key: "" for key in credentials}
        ephemeral.unlink(missing_ok=True)
        (tool_dir / "kubectl").unlink(missing_ok=True)
        try:
            tool_dir.rmdir()
        except FileNotFoundError:
            pass
        for log_path in Path("/tmp").glob(f"pf-*-{run_id}.log"):
            if log_path.is_file() and not log_path.is_symlink():
                log_path.unlink()

    classification = classify(completed_stdout, completed_stderr)
    passed = exit_code == 0 and classification["success"]["contractPass"]
    evidence = {
        "apiVersion": "evidence.openkubes.io/v1alpha1",
        "kind": "OK141CapabilityRuntimeRetryEvidence",
        "state": "PASS-CAPABILITY" if passed else "FAIL-CAPABILITY",
        "candidateDigest": digest(path),
        "predecessorEvidenceDigest": spec["predecessor"]["failedEvidence"]["digest"],
        "identities": base["identities"],
        "applications": applications,
        "classification": classification,
        "targetObservation": {
            "iterations": len(observations),
            "everSeen": any(item["targetSeen"] for item in observations),
            "everHealthy": any(item["targetHealthy"] for item in observations),
            "states": sorted(set(item["state"] for item in observations)),
        },
        "exitCode": exit_code,
        "cleanup": {
            "scriptCleanupInvoked": classification["success"]["cleanupInvoked"],
            "ephemeralKubeconfigRemoved": not ephemeral.exists(),
            "toolDirectoryRemoved": not tool_dir.exists(),
            "portForwardLogsRemoved": not any(Path("/tmp").glob(f"pf-*-{run_id}.log")),
        },
        "secretBytesRetained": False,
        "rawOutputRetained": False,
        "furtherRetryAllowed": False,
    }
    evidence["semanticDigest"] = sha_bytes(json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode())
    V1.write_exclusive(output, (json.dumps(evidence, sort_keys=True, separators=(",", ":")) + "\n").encode())
    if not passed:
        raise RetryError("capability retry failed; normalized evidence retained")
    return {"state": evidence["state"], "evidencePath": str(output), "evidenceDigest": digest(output), "semanticDigest": evidence["semanticDigest"]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "execute"))
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "verify":
            validate(args.candidate.resolve())
            print(digest(args.candidate.resolve()))
        else:
            if not args.execute:
                raise RetryError("execution flag required")
            print(json.dumps(execute(args.candidate.resolve()), sort_keys=True))
        return 0
    except (RetryError, KeyError, OSError, TypeError, ValueError, json.JSONDecodeError, subprocess.SubprocessError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
