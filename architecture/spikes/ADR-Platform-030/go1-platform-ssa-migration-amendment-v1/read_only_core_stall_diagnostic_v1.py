#!/usr/bin/env python3
"""Bounded, redacted read-only diagnostic for the OK-141 Core sync stall."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import subprocess
from urllib.parse import quote


KUBECTL = Path("/private/tmp/ok141-kubectl-v1.34.1-darwin-amd64")
MGMT_KUBECONFIG = Path("/Users/arash/.kube/ok-mgmt.yaml")
EPHEMERAL = Path("/private/tmp/ok141-core-stall-diagnostic-workload-kubeconfig.yaml")
SECRET_URI = "/api/v1/namespaces/disposable-ok141/secrets/disposable-ok141-kubeconfig"
CRDS = (
    "prometheusagents.monitoring.coreos.com",
    "alertmanagerconfigs.monitoring.coreos.com",
    "thanosrulers.monitoring.coreos.com",
    "prometheuses.monitoring.coreos.com",
)
POD_COLLECTION_URI = "/api/v1/namespaces/ok-observability/pods?labelSelector=app.kubernetes.io%2Fname%3Dkube-prometheus-stack-prometheus-operator%2Capp.kubernetes.io%2Finstance%3Ddisposable-ok141-observability-core"
DEPLOYMENT_URI = "/apis/apps/v1/namespaces/ok-observability/deployments/ok-observability-operator"
PROMETHEUS_URI = "/apis/monitoring.coreos.com/v1/namespaces/ok-observability/prometheuses/ok-observability-prometheus"
OPERATOR_CLUSTERROLE_URI = "/apis/rbac.authorization.k8s.io/v1/clusterroles/ok-observability-operator"
PROMETHEUS_STATEFULSET_URI = "/apis/apps/v1/namespaces/ok-observability/statefulsets/prometheus-ok-observability-prometheus"


def exact_get(kubeconfig: Path, uri: str) -> dict:
    completed = subprocess.run(
        [str(KUBECTL), "--kubeconfig", str(kubeconfig), "get", "--raw", uri],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"exact GET failed for bounded resource: exit={completed.returncode}")
    return json.loads(completed.stdout)


def exact_text_get(kubeconfig: Path, uri: str) -> str:
    completed = subprocess.run(
        [str(KUBECTL), "--kubeconfig", str(kubeconfig), "get", "--raw", uri],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"exact text GET failed for bounded resource: exit={completed.returncode}")
    return completed.stdout.decode("utf-8", errors="replace")


def main() -> None:
    secret = exact_get(MGMT_KUBECONFIG, SECRET_URI)
    raw = base64.b64decode(secret["data"]["value"], validate=True)
    EPHEMERAL.write_bytes(raw)
    os.chmod(EPHEMERAL, 0o600)
    try:
        crds = []
        for name in CRDS:
            obj = exact_get(
                EPHEMERAL,
                f"/apis/apiextensions.k8s.io/v1/customresourcedefinitions/{name}",
            )
            crds.append(
                {
                    "name": name,
                    "createdAt": obj["metadata"].get("creationTimestamp"),
                    "generation": obj["metadata"].get("generation"),
                    "conditions": [
                        {
                            "type": item.get("type"),
                            "status": item.get("status"),
                            "reason": item.get("reason"),
                        }
                        for item in obj.get("status", {}).get("conditions", [])
                    ],
                }
            )
        pods = exact_get(EPHEMERAL, POD_COLLECTION_URI).get("items", [])
        ready_pods = [
            item
            for item in pods
            if item.get("status", {}).get("phase") == "Running"
            and any(
                condition.get("type") == "Ready" and condition.get("status") == "True"
                for condition in item.get("status", {}).get("conditions", [])
            )
        ]
        if len(ready_pods) != 1:
            raise RuntimeError("expected exactly one ready bound operator pod")
        pod = ready_pods[0]
        pod_uri = f"/api/v1/namespaces/ok-observability/pods/{pod['metadata']['name']}"
        deployment = exact_get(EPHEMERAL, DEPLOYMENT_URI)
        prometheus = exact_get(EPHEMERAL, PROMETHEUS_URI)
        operator_clusterrole = exact_get(EPHEMERAL, OPERATOR_CLUSTERROLE_URI)
        prometheus_statefulset = exact_get(EPHEMERAL, PROMETHEUS_STATEFULSET_URI)
        container_name = pod["spec"]["containers"][0]["name"]
        log_uri = (
            f"{pod_uri}/log?container={quote(container_name)}&tailLines=500&sinceSeconds=1800"
        )
        logs = exact_text_get(EPHEMERAL, log_uri).lower()
        indicators = (
            "forbidden",
            "failed to list",
            "failed to watch",
            "no matches for kind",
            "prometheuses",
            "statefulsets",
            "secrets",
            "configmaps",
            "services",
            "serviceaccounts",
            "pods",
            "nodes",
            "persistentvolumes",
            "storageclasses",
            "error",
        )
        print(
            json.dumps(
                {
                    "crds": crds,
                    "operatorPod": {
                        "createdAt": pod["metadata"].get("creationTimestamp"),
                        "labels": pod["metadata"].get("labels", {}),
                        "phase": pod.get("status", {}).get("phase"),
                        "containers": [x["name"] for x in pod["spec"].get("containers", [])],
                        "containerReady": {
                            x["name"]: x.get("ready")
                            for x in pod.get("status", {}).get("containerStatuses", [])
                        },
                    },
                    "operatorDeployment": {
                        "generation": deployment["metadata"].get("generation"),
                        "observedGeneration": deployment.get("status", {}).get("observedGeneration"),
                        "args": deployment["spec"]["template"]["spec"]["containers"][0].get("args", []),
                    },
                    "prometheus": {
                        "createdAt": prometheus["metadata"].get("creationTimestamp"),
                        "generation": prometheus["metadata"].get("generation"),
                        "statusPresent": bool(prometheus.get("status")),
                        "conditionTypes": [
                            item.get("type")
                            for item in prometheus.get("status", {}).get("conditions", [])
                        ],
                        "availableReplicas": prometheus.get("status", {}).get("availableReplicas"),
                        "replicas": prometheus.get("status", {}).get("replicas"),
                        "updatedReplicas": prometheus.get("status", {}).get("updatedReplicas"),
                    },
                    "prometheusStatefulSet": {
                        "generation": prometheus_statefulset["metadata"].get("generation"),
                        "observedGeneration": prometheus_statefulset.get("status", {}).get("observedGeneration"),
                        "replicas": prometheus_statefulset.get("status", {}).get("replicas"),
                        "readyReplicas": prometheus_statefulset.get("status", {}).get("readyReplicas", 0),
                        "availableReplicas": prometheus_statefulset.get("status", {}).get("availableReplicas", 0),
                        "updatedReplicas": prometheus_statefulset.get("status", {}).get("updatedReplicas", 0),
                    },
                    "operatorClusterRole": {
                        "generation": operator_clusterrole["metadata"].get("generation"),
                        "nodeVerbs": sorted(
                            {
                                verb
                                for rule in operator_clusterrole.get("rules", [])
                                if rule.get("apiGroups") == [""] and "nodes" in rule.get("resources", [])
                                for verb in rule.get("verbs", [])
                            }
                        ),
                        "ruleCount": len(operator_clusterrole.get("rules", [])),
                    },
                    "operatorLogIndicators": {
                        indicator: logs.count(indicator) for indicator in indicators
                    },
                },
                sort_keys=True,
            )
        )
    finally:
        EPHEMERAL.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
