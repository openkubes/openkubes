#!/usr/bin/env python3
"""Bounded, redacted Prometheus/operator log classification for OK-141."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import urllib.parse
from pathlib import Path
from typing import Any

MGMT_CLIENT = Path("/private/tmp/ok141-kubectl-v1.34.1-darwin-amd64")
TARGET_CLIENT = Path("/usr/local/bin/kubectl")
MGMT_KUBECONFIG = Path("/Users/arash/.kube/ok-mgmt.yaml")
EPHEMERAL = Path("/private/tmp/ok141-prometheus-log-diagnostic-v1-kubeconfig.yaml")
OUTPUT = Path("/private/tmp/ok141-prometheus-log-diagnostic-v2-evidence.json")
NS = "ok-observability"


def sha(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def write_exclusive(path: Path, value: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(value)


def run(args: list[str]) -> bytes:
    completed = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=30)
    if completed.returncode != 0:
        raise RuntimeError("bounded read failed; output suppressed")
    return completed.stdout


def get(client: Path, kubeconfig: Path, uri: str) -> dict[str, Any]:
    value = json.loads(run([str(client), "--kubeconfig", str(kubeconfig), "get", "--raw", uri]))
    if not isinstance(value, dict):
        raise RuntimeError("exact GET returned non-object")
    return value


def classify(raw: bytes) -> dict[str, Any]:
    text = raw.decode(errors="replace").lower()
    categories = {
        "forbidden": "forbidden",
        "serviceMonitor": "servicemonitor",
        "prometheusRule": "prometheusrule",
        "endpoints": "endpoint",
        "configReload": "reload",
        "error": "error",
        "failed": "fail",
        "noEndpoints": "no endpoints",
        "connectionRefused": "connection refused",
        "deadline": "context deadline exceeded",
        "scrapePool": "scrape pool",
        "duplicate": "duplicate",
        "outOfOrder": "out of order",
        "sample": "sample",
        "pushgateway": "pushgateway",
        "exactRunIdentity": "ok141-happy-capability-20260815-v1",
    }
    return {
        "lineCount": len(text.splitlines()),
        "rawDigest": sha(raw),
        "indicators": {name: sum(1 for line in text.splitlines() if needle in line) for name, needle in categories.items()},
        "rawRetained": False,
    }


def logs(kubeconfig: Path, pod: str, container: str) -> bytes:
    return run([str(TARGET_CLIENT), "--kubeconfig", str(kubeconfig), "-n", NS, "logs", pod, "-c", container, "--since=2h", "--tail=2000"])


def main() -> int:
    if OUTPUT.exists() or EPHEMERAL.exists():
        raise RuntimeError("exclusive output exists")
    secret = get(MGMT_CLIENT, MGMT_KUBECONFIG, "/api/v1/namespaces/disposable-ok141/secrets/disposable-ok141-kubeconfig")
    write_exclusive(EPHEMERAL, base64.b64decode(secret["data"]["value"], validate=True))
    try:
        deployment = get(TARGET_CLIENT, EPHEMERAL, "/apis/apps/v1/namespaces/ok-observability/deployments/ok-observability-operator")
        selector = deployment["spec"]["selector"]["matchLabels"]
        encoded = urllib.parse.quote(",".join(f"{key}={value}" for key, value in sorted(selector.items())), safe="=,")
        pod_list = get(TARGET_CLIENT, EPHEMERAL, f"/api/v1/namespaces/{NS}/pods?labelSelector={encoded}")
        items = pod_list.get("items", [])
        if len(items) != 1:
            raise RuntimeError("operator selector did not resolve exactly one pod")
        operator_pod = items[0]
        operator_container = operator_pod["spec"]["containers"][0]["name"]
        prometheus_pod = get(TARGET_CLIENT, EPHEMERAL, "/api/v1/namespaces/ok-observability/pods/prometheus-ok-observability-prometheus-0")
        prometheus_container = next(item["name"] for item in prometheus_pod["spec"]["containers"] if item["name"] == "prometheus")
        result = {
            "operator": {
                "uidDigest": sha(str(operator_pod["metadata"].get("uid", "")).encode()),
                "logs": classify(logs(EPHEMERAL, operator_pod["metadata"]["name"], operator_container)),
            },
            "prometheus": {
                "uidDigest": sha(str(prometheus_pod["metadata"].get("uid", "")).encode()),
                "logs": classify(logs(EPHEMERAL, prometheus_pod["metadata"]["name"], prometheus_container)),
            },
            "rawLogsRetained": False,
            "secretBytesRetained": False,
        }
    finally:
        EPHEMERAL.unlink(missing_ok=True)
    result["ephemeralKubeconfigRemoved"] = not EPHEMERAL.exists()
    result["semanticDigest"] = sha(json.dumps(result, sort_keys=True, separators=(",", ":")).encode())
    write_exclusive(OUTPUT, (json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n").encode())
    print(json.dumps({"evidencePath": str(OUTPUT), "evidenceDigest": sha(OUTPUT.read_bytes()), "semanticDigest": result["semanticDigest"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
