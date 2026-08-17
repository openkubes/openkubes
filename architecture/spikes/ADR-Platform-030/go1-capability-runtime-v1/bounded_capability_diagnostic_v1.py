#!/usr/bin/env python3
"""Read-only post-run capability diagnostic for the fixed OK-141 run identity."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import signal
import ssl
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

CLIENT = Path("/usr/local/bin/kubectl")
MGMT_CLIENT = Path("/private/tmp/ok141-kubectl-v1.34.1-darwin-amd64")
MGMT_KUBECONFIG = Path("/Users/arash/.kube/ok-mgmt.yaml")
EPHEMERAL = Path("/private/tmp/ok141-capability-diagnostic-v1-kubeconfig.yaml")
OUTPUT = Path("/private/tmp/ok141-capability-diagnostic-v2-evidence.json")
RUN_ID = "ok141-happy-capability-20260815-v1"
NAMESPACE = "ok-observability"
SERVICES = {
    "prometheus": ("ok-observability-prometheus", 9090, 29801),
    "grafana": ("ok-observability-grafana", 80, 29802),
    "opensearch": ("opensearch-cluster-master", 9200, 29803),
    "alertmanager": ("ok-observability-alertmanager", 9093, 29804),
}


def sha_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def write_exclusive(path: Path, value: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(value)


def raw_get(client: Path, kubeconfig: Path, uri: str) -> dict[str, Any]:
    completed = subprocess.run([str(client), "--kubeconfig", str(kubeconfig), "get", "--raw", uri], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=30)
    if completed.returncode != 0:
        raise RuntimeError("exact GET failed; output suppressed")
    value = json.loads(completed.stdout)
    if not isinstance(value, dict):
        raise RuntimeError("exact GET returned non-object")
    return value


def http_json(url: str, *, user: str = "", password: str = "", data: bytes | None = None, insecure: bool = False) -> tuple[str, Any | None]:
    request = urllib.request.Request(url, data=data)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    if user:
        token = base64.b64encode(f"{user}:{password}".encode()).decode()
        request.add_header("Authorization", "Basic " + token)
    context = ssl._create_unverified_context() if insecure else None
    try:
        with urllib.request.urlopen(request, timeout=10, context=context) as response:
            body = response.read()
            return "SUCCESS", json.loads(body) if body else None
    except urllib.error.HTTPError as error:
        return f"HTTP-{error.code}", None
    except urllib.error.URLError:
        return "TRANSPORT", None
    except (TimeoutError, json.JSONDecodeError):
        return "INVALID-OR-TIMEOUT", None


def wait_forward(port: int, process: subprocess.Popen[bytes]) -> bool:
    for _ in range(30):
        if process.poll() is not None:
            return False
        try:
            import socket
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return True
        except OSError:
            time.sleep(0.5)
    return False


def main() -> int:
    if OUTPUT.exists() or EPHEMERAL.exists():
        raise RuntimeError("exclusive output exists")
    secret = raw_get(MGMT_CLIENT, MGMT_KUBECONFIG, "/api/v1/namespaces/disposable-ok141/secrets/disposable-ok141-kubeconfig")
    write_exclusive(EPHEMERAL, base64.b64decode(secret["data"]["value"], validate=True))
    credentials: dict[str, str] = {}
    processes: list[subprocess.Popen[bytes]] = []
    result: dict[str, Any] = {"runID": RUN_ID, "serviceObjects": {}, "forwardReady": {}, "checks": {}}
    try:
        credential_secret = raw_get(CLIENT, EPHEMERAL, "/api/v1/namespaces/ok-observability/secrets/ok-observability-credentials")
        for key in ("grafana-admin-user", "grafana-admin-password", "opensearch-admin-password"):
            credentials[key] = base64.b64decode(credential_secret["data"][key], validate=True).decode()
        for key, (name, remote, local) in SERVICES.items():
            service = raw_get(CLIENT, EPHEMERAL, f"/api/v1/namespaces/{NAMESPACE}/services/{name}")
            result["serviceObjects"][key] = {"present": True, "uidDigest": sha_bytes(str(service["metadata"].get("uid", "")).encode())}
            process = subprocess.Popen([str(CLIENT), "--kubeconfig", str(EPHEMERAL), "-n", NAMESPACE, "port-forward", f"service/{name}", f"{local}:{remote}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            processes.append(process)
            result["forwardReady"][key] = wait_forward(local, process)

        metric = "ok_observability_contract_test_metric_ok141_happy_capability_20260815_v1"
        state, prometheus = http_json("http://127.0.0.1:29801/api/v1/query?" + urllib.parse.urlencode({"query": metric}))
        result["checks"]["prometheus"] = {"transport": state, "historicalMetricPresent": bool(prometheus and prometheus.get("data", {}).get("result"))}
        end = int(time.time())
        range_base = "http://127.0.0.1:29801/api/v1/query_range?"
        range_args = {"start": end - 3600, "end": end, "step": 30}
        metric_state, metric_range = http_json(range_base + urllib.parse.urlencode({**range_args, "query": metric}))
        alert_state, alert_range = http_json(range_base + urllib.parse.urlencode({**range_args, "query": 'ALERTS{alertname="OKObservabilitySyntheticAlert",alertstate="firing"}'}))
        result["checks"]["prometheus"]["rangeTransport"] = metric_state
        result["checks"]["prometheus"]["metricObservedInLastHour"] = bool(metric_range and metric_range.get("data", {}).get("result"))
        result["checks"]["prometheus"]["alertQueryTransport"] = alert_state
        result["checks"]["prometheus"]["syntheticAlertFiredInLastHour"] = bool(alert_range and alert_range.get("data", {}).get("result"))

        state, datasources = http_json("http://127.0.0.1:29802/api/datasources", user=credentials["grafana-admin-user"], password=credentials["grafana-admin-password"])
        prometheus_sources = [item for item in (datasources or []) if isinstance(item, dict) and item.get("type") == "prometheus"] if isinstance(datasources, list) else []
        result["checks"]["grafana"] = {"transport": state, "prometheusDatasourceCount": len(prometheus_sources)}

        marker = "OK_OBSERVABILITY_CONTRACT_TEST_LOG_MARKER_ok141_happy_capability_20260815_v1"
        query = json.dumps({"query": {"match_phrase": {"log": marker}}}, separators=(",", ":")).encode()
        state, search = http_json("https://127.0.0.1:29803/ok-observability-logs*/_search", user="admin", password=credentials["opensearch-admin-password"], data=query, insecure=True)
        total = ((search or {}).get("hits", {}).get("total", {}) or {}).get("value", 0) if isinstance(search, dict) else 0
        result["checks"]["opensearch"] = {"transport": state, "historicalMarkerPresent": total > 0}

        state, alerts = http_json("http://127.0.0.1:29804/api/v2/alerts")
        firing = sum(1 for item in (alerts or []) if isinstance(item, dict) and item.get("labels", {}).get("alertname") == "OKObservabilitySyntheticAlert") if isinstance(alerts, list) else 0
        result["checks"]["alertmanager"] = {"transport": state, "historicalSyntheticAlertCount": firing}
    finally:
        for process in processes:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
        credentials = {key: "" for key in credentials}
        EPHEMERAL.unlink(missing_ok=True)
    result["secretBytesRetained"] = False
    result["ephemeralKubeconfigRemoved"] = not EPHEMERAL.exists()
    result["semanticDigest"] = sha_bytes(json.dumps(result, sort_keys=True, separators=(",", ":")).encode())
    write_exclusive(OUTPUT, (json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n").encode())
    print(json.dumps({"evidencePath": str(OUTPUT), "evidenceDigest": sha_bytes(OUTPUT.read_bytes()), "semanticDigest": result["semanticDigest"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
