#!/usr/bin/env python3
"""Bounded read-only observer for OK-141 M0a-I and M0b-I live obligations."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

import yaml


PLANES = {
    "ok-mgmt": Path("/Users/arash/.kube/ok-mgmt.yaml"),
    "ok-shared": Path("/Users/arash/.kube/ok-shared.yaml"),
}
READS = {
    "version": ("get", "--raw=/version"),
    "identity": ("get", "namespace", "kube-system", "-o", "json"),
    "namespaces": ("get", "namespaces", "-o", "json"),
    "nodes": ("get", "nodes", "-o", "json"),
    "deployments": ("get", "deployments", "--all-namespaces", "-o", "json"),
    "daemonsets": ("get", "daemonsets", "--all-namespaces", "-o", "json"),
    "statefulsets": ("get", "statefulsets", "--all-namespaces", "-o", "json"),
    "crds": ("get", "customresourcedefinitions", "-o", "json"),
    "storageclasses": ("get", "storageclasses", "-o", "json"),
    "csidrivers": ("get", "csidrivers", "-o", "json"),
    "pods": ("get", "pods", "--all-namespaces", "-o", "json"),
}


class ObservationError(ValueError):
    pass


def _sha256(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _run_json(
    kubeconfig: Path,
    args: tuple[str, ...],
    runner: Callable[..., Any] = subprocess.run,
) -> Any:
    if not args or args[0] != "get" or any(item in args for item in ("apply", "create", "delete", "patch", "replace", "edit")):
        raise ObservationError("observer command is not an allowed read")
    command = ["kubectl", "--kubeconfig", str(kubeconfig), *args]
    completed = runner(command, check=True, capture_output=True, text=True)
    return json.loads(completed.stdout)


def _kubeconfig_identity(path: Path) -> dict[str, str]:
    config = yaml.safe_load(path.read_text())
    current = config.get("current-context")
    contexts = {item["name"]: item["context"] for item in config.get("contexts", [])}
    clusters = {item["name"]: item["cluster"] for item in config.get("clusters", [])}
    if current not in contexts:
        raise ObservationError("kubeconfig current context is missing")
    cluster_name = contexts[current]["cluster"]
    if cluster_name not in clusters or not clusters[cluster_name].get("server"):
        raise ObservationError("kubeconfig cluster server is missing")
    return {"context": current, "cluster": cluster_name, "server": clusters[cluster_name]["server"]}


def _workload(item: dict[str, Any]) -> dict[str, Any]:
    metadata = item["metadata"]
    spec = item["spec"]
    status = item.get("status", {})
    template = spec["template"]["spec"]
    if item["kind"] == "DaemonSet":
        desired = status.get("desiredNumberScheduled")
        ready = status.get("numberReady", 0)
        available = status.get("numberAvailable", 0)
    else:
        desired = spec.get("replicas")
        ready = status.get("readyReplicas", 0)
        available = status.get("availableReplicas", 0)
    return {
        "kind": item["kind"],
        "namespace": metadata.get("namespace", "default"),
        "name": metadata["name"],
        "uid": metadata["uid"],
        "generation": metadata.get("generation"),
        "observedGeneration": status.get("observedGeneration"),
        "desiredReplicas": desired,
        "readyReplicas": ready,
        "availableReplicas": available,
        "images": sorted(
            {container["image"] for container in template.get("containers", [])}
        ),
        "serviceAccountName": template.get("serviceAccountName", "default"),
    }


def _node(item: dict[str, Any]) -> dict[str, Any]:
    metadata = item["metadata"]
    labels = metadata.get("labels", {})
    info = item.get("status", {}).get("nodeInfo", {})
    ready = next(
        (condition for condition in item.get("status", {}).get("conditions", []) if condition["type"] == "Ready"),
        {},
    )
    return {
        "name": metadata["name"],
        "uid": metadata["uid"],
        "architecture": labels.get("kubernetes.io/arch"),
        "controlPlane": "node-role.kubernetes.io/control-plane" in labels,
        "kubeletVersion": info.get("kubeletVersion"),
        "osImage": info.get("osImage"),
        "containerRuntimeVersion": info.get("containerRuntimeVersion"),
        "ready": ready.get("status"),
        "capacity": item.get("status", {}).get("capacity", {}),
        "allocatable": item.get("status", {}).get("allocatable", {}),
    }


CPU_FACTORS = {"n": Decimal("0.000001"), "u": Decimal("0.001"), "m": Decimal(1)}
MEMORY_FACTORS = {
    "Ki": 1024,
    "Mi": 1024**2,
    "Gi": 1024**3,
    "Ti": 1024**4,
    "K": 1000,
    "M": 1000**2,
    "G": 1000**3,
    "T": 1000**4,
}


def _cpu_milli(value: str | None) -> int:
    if not value:
        return 0
    for suffix, factor in CPU_FACTORS.items():
        if value.endswith(suffix):
            return int(Decimal(value[: -len(suffix)]) * factor)
    return int(Decimal(value) * 1000)


def _memory_bytes(value: str | None) -> int:
    if not value:
        return 0
    for suffix, factor in MEMORY_FACTORS.items():
        if value.endswith(suffix):
            return int(Decimal(value[: -len(suffix)]) * factor)
    return int(Decimal(value))


def _pod_resources(pods: list[dict[str, Any]]) -> dict[str, Any]:
    by_node: dict[str, Counter] = {}
    unscheduled = 0
    included = 0
    for pod in pods:
        if pod.get("status", {}).get("phase") in {"Succeeded", "Failed"}:
            continue
        node = pod.get("spec", {}).get("nodeName")
        if not node:
            unscheduled += 1
            continue
        included += 1
        totals = by_node.setdefault(node, Counter())
        app = Counter()
        for container in pod.get("spec", {}).get("containers", []):
            resources = container.get("resources", {})
            app["cpuRequestMilli"] += _cpu_milli(resources.get("requests", {}).get("cpu"))
            app["cpuLimitMilli"] += _cpu_milli(resources.get("limits", {}).get("cpu"))
            app["memoryRequestBytes"] += _memory_bytes(resources.get("requests", {}).get("memory"))
            app["memoryLimitBytes"] += _memory_bytes(resources.get("limits", {}).get("memory"))
        init_peak = Counter()
        for container in pod.get("spec", {}).get("initContainers", []):
            resources = container.get("resources", {})
            init_peak["cpuRequestMilli"] = max(init_peak["cpuRequestMilli"], _cpu_milli(resources.get("requests", {}).get("cpu")))
            init_peak["cpuLimitMilli"] = max(init_peak["cpuLimitMilli"], _cpu_milli(resources.get("limits", {}).get("cpu")))
            init_peak["memoryRequestBytes"] = max(init_peak["memoryRequestBytes"], _memory_bytes(resources.get("requests", {}).get("memory")))
            init_peak["memoryLimitBytes"] = max(init_peak["memoryLimitBytes"], _memory_bytes(resources.get("limits", {}).get("memory")))
        overhead = pod.get("spec", {}).get("overhead", {})
        for key in app:
            value = max(app[key], init_peak[key])
            if key == "cpuRequestMilli":
                value += _cpu_milli(overhead.get("cpu"))
            elif key == "memoryRequestBytes":
                value += _memory_bytes(overhead.get("memory"))
            totals[key] += value
    return {
        "method": "non-terminal scheduled Pods; max(sum app containers, max init container) plus Pod overhead for requests",
        "includedPods": included,
        "unscheduledPods": unscheduled,
        "byNode": {name: dict(sorted(values.items())) for name, values in sorted(by_node.items())},
    }


def observe(
    plane: str,
    runner: Callable[..., Any] = subprocess.run,
    observed_at: str | None = None,
) -> dict[str, Any]:
    if plane not in PLANES:
        raise ObservationError("unknown observation plane")
    kubeconfig = PLANES[plane]
    raw = {name: _run_json(kubeconfig, args, runner) for name, args in READS.items()}
    workloads = [
        _workload(item)
        for source in ("deployments", "daemonsets", "statefulsets")
        for item in raw[source].get("items", [])
    ]
    crds = sorted(
        [
          {
            "name": item["metadata"]["name"],
            "uid": item["metadata"]["uid"],
            "group": item["spec"]["group"],
          }
          for item in raw["crds"].get("items", [])
        ],
        key=lambda item: item["name"],
    )
    relevant_crds = [
        item
        for item in crds
        if item["group"] in {
            "addons.cluster.x-k8s.io",
            "argoproj.io",
            "cluster.x-k8s.io",
            "infrastructure.cluster.x-k8s.io",
            "cert-manager.io",
        }
    ]
    pods = raw["pods"].get("items", [])
    control_plane_pods = []
    for pod in pods:
        name = pod["metadata"]["name"]
        if pod["metadata"].get("namespace") == "kube-system" and name.startswith(("etcd-", "kube-apiserver-", "kube-controller-manager-", "kube-scheduler-")):
            control_plane_pods.append(
                {
                    "name": name,
                    "uid": pod["metadata"]["uid"],
                    "nodeName": pod.get("spec", {}).get("nodeName"),
                    "phase": pod.get("status", {}).get("phase"),
                    "images": sorted({item["image"] for item in pod.get("spec", {}).get("containers", [])}),
                }
            )
    projection = {
        "apiVersion": "evidence.openkubes.io/v1alpha1",
        "kind": "LivePlaneObservation",
        "metadata": {"name": f"ok141-{plane}-live-observation"},
        "spec": {
            "plane": plane,
            "observedAt": observed_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "operation": "READ-ONLY",
            "clusterContacted": True,
            "mutationAuthorized": False,
            "kubeconfigIdentity": _kubeconfig_identity(kubeconfig),
            "apiVersion": raw["version"],
            "clusterIdentity": {
                "kubeSystemNamespaceUID": raw["identity"]["metadata"]["uid"],
                "kubeSystemCreatedAt": raw["identity"]["metadata"]["creationTimestamp"],
            },
            "namespaces": sorted(
                [
                  {
                    "name": item["metadata"]["name"],
                    "uid": item["metadata"]["uid"],
                  }
                  for item in raw["namespaces"].get("items", [])
                ],
                key=lambda item: item["name"],
            ),
            "nodes": sorted((_node(item) for item in raw["nodes"].get("items", [])), key=lambda item: item["name"]),
            "workloads": sorted(workloads, key=lambda item: (item["namespace"], item["kind"], item["name"])),
            "relevantCRDs": relevant_crds,
            "storageClasses": sorted(
                [
                  {
                    "name": item["metadata"]["name"],
                    "provisioner": item["provisioner"],
                    "reclaimPolicy": item.get("reclaimPolicy"),
                    "volumeBindingMode": item.get("volumeBindingMode"),
                  }
                  for item in raw["storageclasses"].get("items", [])
                ],
                key=lambda item: item["name"],
            ),
            "csiDrivers": sorted(item["metadata"]["name"] for item in raw["csidrivers"].get("items", [])),
            "controlPlanePods": sorted(control_plane_pods, key=lambda item: item["name"]),
            "allocatedPodResources": _pod_resources(pods),
        },
    }
    projection["spec"]["semanticDigest"] = _sha256(projection["spec"])
    return projection


def summarize(observation: dict[str, Any]) -> dict[str, Any]:
    spec = observation["spec"]
    resources = spec["allocatedPodResources"]["byNode"]
    nodes = [
        {
            "name": item["name"],
            "uid": item["uid"],
            "controlPlane": item["controlPlane"],
            "ready": item["ready"],
            "architecture": item["architecture"],
            "kubeletVersion": item["kubeletVersion"],
            "osImage": item["osImage"],
            "allocatable": item["allocatable"],
            "allocatedPodResources": resources.get(item["name"], {}),
        }
        for item in spec["nodes"]
    ]
    workloads = [
        {
            field: item[field]
            for field in (
                "kind",
                "namespace",
                "name",
                "generation",
                "observedGeneration",
                "desiredReplicas",
                "readyReplicas",
                "availableReplicas",
                "images",
            )
        }
        for item in spec["workloads"]
    ]
    summary = {
        "apiVersion": observation["apiVersion"],
        "kind": "LivePlaneObservationSummary",
        "metadata": observation["metadata"],
        "spec": {
            "plane": spec["plane"],
            "observedAt": spec["observedAt"],
            "operation": spec["operation"],
            "clusterContacted": spec["clusterContacted"],
            "mutationAuthorized": spec["mutationAuthorized"],
            "kubeconfigIdentity": spec["kubeconfigIdentity"],
            "kubernetes": {
                field: spec["apiVersion"][field]
                for field in ("gitVersion", "gitCommit", "buildDate", "platform")
            },
            "clusterIdentity": spec["clusterIdentity"],
            "nodes": nodes,
            "podResourceMethod": spec["allocatedPodResources"]["method"],
            "includedPods": spec["allocatedPodResources"]["includedPods"],
            "unscheduledPods": spec["allocatedPodResources"]["unscheduledPods"],
            "controlPlanePods": spec["controlPlanePods"],
            "namespaces": [item["name"] for item in spec["namespaces"]],
            "relevantCRDs": [item["name"] for item in spec["relevantCRDs"]],
            "workloads": workloads,
            "storageClasses": spec["storageClasses"],
            "csiDrivers": spec["csiDrivers"],
            "sourceProjectionDigest": spec["semanticDigest"],
        },
    }
    summary["spec"]["semanticDigest"] = _sha256(summary["spec"])
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plane", choices=sorted(PLANES), required=True)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()
    try:
        observation = observe(args.plane)
        print(json.dumps(summarize(observation) if args.summary else observation, indent=2, sort_keys=True))
        return 0
    except (ObservationError, OSError, ValueError, yaml.YAMLError, subprocess.SubprocessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
