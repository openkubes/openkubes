#!/usr/bin/env python3
"""Read-only exact Prometheus scrape-path diagnostic for OK-141."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

MGMT_CLIENT = Path("/private/tmp/ok141-kubectl-v1.34.1-darwin-amd64")
TARGET_CLIENT = Path("/usr/local/bin/kubectl")
MGMT_KUBECONFIG = Path("/Users/arash/.kube/ok-mgmt.yaml")
EPHEMERAL = Path("/private/tmp/ok141-prometheus-scrape-diagnostic-v1-kubeconfig.yaml")
OUTPUT = Path("/private/tmp/ok141-prometheus-scrape-diagnostic-v3-evidence.json")


def sha(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def write_exclusive(path: Path, value: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(value)


def get(client: Path, kubeconfig: Path, uri: str) -> dict[str, Any]:
    completed = subprocess.run([str(client), "--kubeconfig", str(kubeconfig), "get", "--raw", uri], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=30)
    if completed.returncode != 0:
        raise RuntimeError("exact GET failed; output suppressed")
    value = json.loads(completed.stdout)
    if not isinstance(value, dict):
        raise RuntimeError("exact GET returned non-object")
    return value


def main() -> int:
    if OUTPUT.exists() or EPHEMERAL.exists():
        raise RuntimeError("exclusive output exists")
    secret = get(MGMT_CLIENT, MGMT_KUBECONFIG, "/api/v1/namespaces/disposable-ok141/secrets/disposable-ok141-kubeconfig")
    write_exclusive(EPHEMERAL, base64.b64decode(secret["data"]["value"], validate=True))
    try:
        prometheus = get(TARGET_CLIENT, EPHEMERAL, "/apis/monitoring.coreos.com/v1/namespaces/ok-observability/prometheuses/ok-observability-prometheus")
        statefulset = get(TARGET_CLIENT, EPHEMERAL, "/apis/apps/v1/namespaces/ok-observability/statefulsets/prometheus-ok-observability-prometheus")
        role = get(TARGET_CLIENT, EPHEMERAL, "/apis/rbac.authorization.k8s.io/v1/clusterroles/ok-observability-prometheus")
        operator_role = get(TARGET_CLIENT, EPHEMERAL, "/apis/rbac.authorization.k8s.io/v1/clusterroles/ok-observability-operator")
        spec = prometheus.get("spec", {})
        status = prometheus.get("status", {})
        rules = role.get("rules", [])
        operator_rules = operator_role.get("rules", [])
        result = {
            "prometheus": {
                "uidDigest": sha(str(prometheus.get("metadata", {}).get("uid", "")).encode()),
                "serviceMonitorSelector": spec.get("serviceMonitorSelector", "MISSING"),
                "serviceMonitorNamespaceSelector": spec.get("serviceMonitorNamespaceSelector", "MISSING"),
                "podMonitorSelector": spec.get("podMonitorSelector", "MISSING"),
                "ruleSelector": spec.get("ruleSelector", "MISSING"),
                "availableReplicas": status.get("availableReplicas"),
                "updatedReplicas": status.get("updatedReplicas"),
                "conditions": [
                    {"type": item.get("type"), "status": item.get("status"), "reason": item.get("reason")}
                    for item in status.get("conditions", [])
                ],
            },
            "statefulSet": {
                "replicas": statefulset.get("status", {}).get("replicas"),
                "readyReplicas": statefulset.get("status", {}).get("readyReplicas"),
                "currentReplicas": statefulset.get("status", {}).get("currentReplicas"),
            },
            "rbac": {
                "servicesRead": any("services" in item.get("resources", []) and all(verb in item.get("verbs", []) for verb in ("get", "list", "watch")) for item in rules),
                "endpointsRead": any(any(resource in item.get("resources", []) for resource in ("endpoints", "endpointslices")) and "list" in item.get("verbs", []) for item in rules),
                "serviceMonitorsRead": any("servicemonitors" in item.get("resources", []) and "list" in item.get("verbs", []) for item in rules),
                "operatorServiceMonitorsRead": any("servicemonitors" in item.get("resources", []) and ("*" in item.get("verbs", []) or all(verb in item.get("verbs", []) for verb in ("get", "list", "watch"))) for item in operator_rules),
                "operatorPrometheusRulesRead": any("prometheusrules" in item.get("resources", []) and ("*" in item.get("verbs", []) or all(verb in item.get("verbs", []) for verb in ("get", "list", "watch"))) for item in operator_rules),
            },
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
