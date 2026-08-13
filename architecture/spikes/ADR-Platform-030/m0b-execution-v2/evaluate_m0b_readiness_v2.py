#!/usr/bin/env python3
"""Fail-closed, read-only runtime evaluator for the OK-141 M0b v2 install."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import yaml


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
TARGET_KUBECONFIG = Path("/Users/arash/.kube/ok-shared.yaml")
TARGET_NAMESPACE = "argocd"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


EXECUTION = _load("ok141_m0b_execution_v2_for_readiness", HERE / "controlled_m0b_execution_v2.py")


class ReadinessError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def expect(actual: Any, expected: Any, claim: str) -> None:
    if actual != expected:
        raise ReadinessError(f"{claim}: expected {expected!r}, got {actual!r}")


def read(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text())
    if not isinstance(value, dict):
        raise ReadinessError(f"expected mapping in {path}")
    return value


def resolve(base: Path, reference: dict[str, Any]) -> Path:
    path = (base.parent / reference["path"]).resolve()
    if SPIKE.resolve() not in path.parents or not path.is_file():
        raise ReadinessError(f"invalid reference: {reference['path']}")
    expect(sha256_file(path), reference["digest"], reference["path"])
    return path


def verify_candidate(path: Path) -> tuple[dict[str, Any], dict[str, Path]]:
    document = read(path)
    spec = document["spec"]
    expect(spec["version"], "ok141-m0b-readiness/v2", "version")
    expect(spec["state"], "READY-READ-ONLY-NO-GO", "state")
    references = {name: resolve(path, reference) for name, reference in spec["references"].items()}
    expect(references["evaluator"], Path(__file__).resolve(), "evaluator")
    execution = read(references["executionCandidate"])["spec"]
    expect(execution["target"]["kubeSystemNamespaceUID"], spec["target"]["kubeSystemNamespaceUID"], "target UID")
    expect(execution["submission"]["expectedObjects"], spec["assertions"]["reviewedObjectsPresent"], "object count")
    expect(execution["submission"]["expectedDesiredPods"], spec["assertions"]["readyPods"], "Pod count")
    if any(value is not False for value in spec["authorization"].values()):
        raise ReadinessError("readiness candidate grants authority")
    return document, references


def run(command: list[str], input_bytes: bytes | None = None, runner: Callable[..., Any] = subprocess.run) -> subprocess.CompletedProcess:
    return runner(command, input=input_bytes, check=True, capture_output=True, timeout=120)


def get_json(kube: list[str], arguments: list[str], runner: Callable[..., Any]) -> dict[str, Any]:
    return json.loads(run([*kube, *arguments, "-o", "json"], runner=runner).stdout)


def condition_true(resource: dict[str, Any], condition_type: str) -> bool:
    return any(
        item.get("type") == condition_type and item.get("status") == "True"
        for item in resource.get("status", {}).get("conditions", [])
    )


def object_identity(resource: dict[str, Any]) -> dict[str, Any]:
    metadata = resource["metadata"]
    result = {
        "apiVersion": resource["apiVersion"],
        "kind": resource["kind"],
        "name": metadata["name"],
        "uid": metadata["uid"],
        "generation": metadata.get("generation"),
    }
    if metadata.get("namespace"):
        result["namespace"] = metadata["namespace"]
    return result


def validate_workload(resource: dict[str, Any]) -> dict[str, Any]:
    kind = resource["kind"]
    metadata = resource["metadata"]
    spec = resource.get("spec", {})
    status = resource.get("status", {})
    desired = spec.get("replicas", 1)
    expect(status.get("observedGeneration"), metadata.get("generation"), f"{kind}/{metadata['name']} observedGeneration")
    if kind == "Deployment":
        expect(status.get("updatedReplicas", 0), desired, f"{kind}/{metadata['name']} updated")
        expect(status.get("readyReplicas", 0), desired, f"{kind}/{metadata['name']} ready")
        expect(status.get("availableReplicas", 0), desired, f"{kind}/{metadata['name']} available")
    elif kind == "StatefulSet":
        expect(status.get("updatedReplicas", 0), desired, f"{kind}/{metadata['name']} updated")
        expect(status.get("readyReplicas", 0), desired, f"{kind}/{metadata['name']} ready")
        expect(status.get("currentReplicas", 0), desired, f"{kind}/{metadata['name']} current")
        expect(status.get("currentRevision"), status.get("updateRevision"), f"{kind}/{metadata['name']} revision")
    else:
        raise ReadinessError(f"unsupported workload kind {kind}")
    return {"kind": kind, "name": metadata["name"], "uid": metadata["uid"], "desired": desired, "ready": desired}


def write_evidence(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        stream.write(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")


def evaluate(
    readiness_candidate_path: Path,
    materialized_dir: Path,
    evidence_path: Path,
    runner: Callable[..., Any] = subprocess.run,
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    candidate, references = verify_candidate(readiness_candidate_path)
    spec = candidate["spec"]
    expected_output = Path(spec["evidence"]["localOutputPath"])
    expect(evidence_path.resolve(), expected_output.resolve(), "evidence path")
    if evidence_path.exists():
        raise ReadinessError("readiness evidence already exists")
    plan, reviewed = EXECUTION.plan(references["executionCandidate"], materialized_dir)
    kube = ["kubectl", "--kubeconfig", str(TARGET_KUBECONFIG)]
    evidence: dict[str, Any] = {
        "apiVersion": "evidence.openkubes.io/v1alpha1",
        "kind": "M0bReadinessEvidence",
        "spec": {
            "version": "ok141-m0b-readiness-evidence/v2",
            "observedAt": (observed_at or datetime.now(timezone.utc)).isoformat().replace("+00:00", "Z"),
            "candidateDigest": sha256_file(readiness_candidate_path),
            "executionCandidateDigest": plan["candidateDigest"],
            "mutationPerformed": False,
            "result": "STARTED",
            "rawSecretDataRetained": False,
        },
    }
    try:
        identity = get_json(kube, ["get", "namespace", "kube-system"], runner)
        expect(identity["metadata"]["uid"], spec["target"]["kubeSystemNamespaceUID"], "target UID")

        live_set = json.loads(
            run(
                [*kube, "get", "--filename", "-", "-o", "json"],
                EXECUTION.payload(reviewed.projected_documents),
                runner,
            ).stdout
        )
        live_items = live_set.get("items", [live_set]) if live_set.get("kind") == "List" else [live_set]
        expect(len(live_items), spec["assertions"]["reviewedObjectsPresent"], "reviewed live objects")
        identities = sorted((object_identity(item) for item in live_items), key=lambda item: (item["kind"], item.get("namespace", ""), item["name"]))

        crds = [item for item in live_items if item["kind"] == "CustomResourceDefinition"]
        expect(len(crds), spec["assertions"]["establishedCRDs"], "CRD count")
        expect(sum(condition_true(item, "Established") for item in crds), len(crds), "Established CRDs")

        workload_identities = {(item["kind"], item["metadata"]["name"]) for item in reviewed.projected_documents if item["kind"] in {"Deployment", "StatefulSet"}}
        workloads = [item for item in live_items if (item["kind"], item["metadata"]["name"]) in workload_identities]
        expect(len(workloads), spec["assertions"]["readyWorkloads"], "workload count")
        workload_evidence = sorted((validate_workload(item) for item in workloads), key=lambda item: (item["kind"], item["name"]))

        pods = get_json(kube, ["--namespace", TARGET_NAMESPACE, "get", "pods"], runner)["items"]
        expect(len(pods), spec["assertions"]["readyPods"], "Pod count")
        locked_images = {item["reference"]: item["linuxAmd64Digest"] for item in read(references["executionCandidate"])["spec"]["controllerImages"]}
        pod_evidence = []
        for pod in pods:
            conditions = pod.get("status", {}).get("conditions", [])
            if not any(item.get("type") == "Ready" and item.get("status") == "True" for item in conditions):
                raise ReadinessError(f"Pod/{pod['metadata']['name']} is not Ready")
            statuses = {item["name"]: item for item in pod.get("status", {}).get("containerStatuses", [])}
            containers = []
            for container in pod["spec"]["containers"]:
                if container["image"] not in locked_images:
                    raise ReadinessError(f"Pod/{pod['metadata']['name']} uses unbound image {container['image']}")
                status = statuses.get(container["name"], {})
                expect(status.get("ready"), True, f"Pod/{pod['metadata']['name']} container readiness")
                expected_suffix = "@" + locked_images[container["image"]]
                if not status.get("imageID", "").endswith(expected_suffix):
                    raise ReadinessError(f"Pod/{pod['metadata']['name']} runtime image identity differs")
                containers.append({"name": container["name"], "image": container["image"], "imageID": status["imageID"], "ready": True})
            pod_evidence.append({"name": pod["metadata"]["name"], "uid": pod["metadata"]["uid"], "nodeName": pod["spec"].get("nodeName"), "containers": containers})

        target_state = {}
        for resource in ("applications.argoproj.io", "applicationsets.argoproj.io", "appprojects.argoproj.io"):
            target_state[resource] = len(get_json(kube, ["get", resource, "--all-namespaces"], runner).get("items", []))
        expect(sum(target_state.values()), 0, "Argo target-state custom resources")

        evidence["spec"].update({
            "result": "PASS-READINESS-NO-TARGET-STATE",
            "target": {"kubeSystemNamespaceUID": identity["metadata"]["uid"], "namespace": TARGET_NAMESPACE},
            "inventory": {"reviewedObjectsPresent": len(identities), "objects": identities},
            "readiness": {"establishedCRDs": len(crds), "workloads": workload_evidence, "pods": sorted(pod_evidence, key=lambda item: item["name"])},
            "targetState": target_state,
        })
        return evidence
    except Exception as error:
        evidence["spec"].update({"result": "FAIL-CLOSED", "failureType": type(error).__name__, "failure": str(error)})
        raise
    finally:
        write_evidence(evidence_path, evidence)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "evaluate"))
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--materialized-dir", type=Path)
    parser.add_argument("--evidence-out", type=Path)
    args = parser.parse_args()
    try:
        candidate, _ = verify_candidate(args.candidate.resolve())
        result: dict[str, Any] = {"candidateDigest": sha256_file(args.candidate.resolve()), "state": candidate["spec"]["state"], "mutationAuthorized": False}
        if args.command == "evaluate":
            if args.materialized_dir is None or args.evidence_out is None:
                raise ReadinessError("evaluate requires materialized sources and an evidence output")
            result = evaluate(args.candidate.resolve(), args.materialized_dir.resolve(), args.evidence_out.resolve())
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (ReadinessError, OSError, KeyError, TypeError, ValueError, yaml.YAMLError, json.JSONDecodeError, subprocess.SubprocessError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
