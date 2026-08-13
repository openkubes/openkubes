#!/usr/bin/env python3
"""Read-only M0b v2.2 evaluator for CRI identity and native default project."""

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


V2 = _load("ok141_m0b_readiness_v2_for_v21", HERE / "evaluate_m0b_readiness_v2.py")
EXECUTION = V2.EXECUTION


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
    expect(spec["version"], "ok141-m0b-readiness/v2.2", "version")
    expect(spec["state"], "READY-READ-ONLY-CORRECTION-NO-GO", "state")
    references = {name: resolve(path, reference) for name, reference in spec["references"].items()}
    expect(references["evaluator"], Path(__file__).resolve(), "evaluator")
    execution = read(references["executionCandidate"])["spec"]
    expect(execution["target"]["kubeSystemNamespaceUID"], spec["target"]["kubeSystemNamespaceUID"], "target UID")
    source_images = {item["reference"]: item["linuxAmd64Digest"] for item in execution["controllerImages"]}
    runtime_images = {item["reference"]: item for item in spec["runtimeImageIdentity"]}
    expect(set(runtime_images), set(source_images), "runtime image membership")
    for reference, child_digest in source_images.items():
        expect(runtime_images[reference]["linuxAmd64ChildManifestDigest"], child_digest, f"{reference} platform child")
        if runtime_images[reference]["indexDigest"] == child_digest:
            raise ReadinessError(f"{reference} index and platform child must remain distinct")
    if any(value is not False for value in spec["authorization"].values()):
        raise ReadinessError("readiness candidate grants authority")
    return document, references


def run(command: list[str], input_bytes: bytes | None = None, runner: Callable[..., Any] = subprocess.run) -> subprocess.CompletedProcess:
    return runner(command, input=input_bytes, check=True, capture_output=True, timeout=120)


def get_json(kube: list[str], arguments: list[str], runner: Callable[..., Any]) -> dict[str, Any]:
    return json.loads(run([*kube, *arguments, "-o", "json"], runner=runner).stdout)


def write_evidence(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        stream.write(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")


def evaluate(
    candidate_path: Path,
    materialized_dir: Path,
    evidence_path: Path,
    runner: Callable[..., Any] = subprocess.run,
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    candidate, references = verify_candidate(candidate_path)
    spec = candidate["spec"]
    expect(evidence_path.resolve(), Path(spec["evidence"]["localOutputPath"]).resolve(), "evidence path")
    if evidence_path.exists():
        raise ReadinessError("readiness evidence already exists")
    plan, reviewed = EXECUTION.plan(references["executionCandidate"], materialized_dir)
    kube = ["kubectl", "--kubeconfig", str(TARGET_KUBECONFIG)]
    evidence: dict[str, Any] = {
        "apiVersion": "evidence.openkubes.io/v1alpha1",
        "kind": "M0bReadinessEvidence",
        "spec": {
            "version": "ok141-m0b-readiness-evidence/v2.2",
            "observedAt": (observed_at or datetime.now(timezone.utc)).isoformat().replace("+00:00", "Z"),
            "candidateDigest": sha256_file(candidate_path),
            "executionCandidateDigest": plan["candidateDigest"],
            "supersedesFailedEvaluatorEvidenceDigest": spec["failedV2EvidenceDigest"],
            "mutationPerformed": False,
            "rawSecretDataRetained": False,
            "result": "STARTED",
        },
    }
    try:
        identity = get_json(kube, ["get", "namespace", "kube-system"], runner)
        expect(identity["metadata"]["uid"], spec["target"]["kubeSystemNamespaceUID"], "target UID")
        live_set = json.loads(run([*kube, "get", "--filename", "-", "-o", "json"], EXECUTION.payload(reviewed.projected_documents), runner).stdout)
        live_items = live_set.get("items", [live_set]) if live_set.get("kind") == "List" else [live_set]
        expect(len(live_items), spec["assertions"]["reviewedObjectsPresent"], "reviewed live objects")
        identities = sorted((V2.object_identity(item) for item in live_items), key=lambda item: (item["kind"], item.get("namespace", ""), item["name"]))

        crds = [item for item in live_items if item["kind"] == "CustomResourceDefinition"]
        expect(len(crds), spec["assertions"]["establishedCRDs"], "CRD count")
        expect(sum(V2.condition_true(item, "Established") for item in crds), len(crds), "Established CRDs")

        workload_ids = {(item["kind"], item["metadata"]["name"]) for item in reviewed.projected_documents if item["kind"] in {"Deployment", "StatefulSet"}}
        workloads = [item for item in live_items if (item["kind"], item["metadata"]["name"]) in workload_ids]
        expect(len(workloads), spec["assertions"]["readyWorkloads"], "workload count")
        workload_evidence = sorted((V2.validate_workload(item) for item in workloads), key=lambda item: (item["kind"], item["name"]))

        pods = get_json(kube, ["--namespace", TARGET_NAMESPACE, "get", "pods"], runner)["items"]
        expect(len(pods), spec["assertions"]["readyPods"], "Pod count")
        runtime_images = {item["reference"]: item for item in spec["runtimeImageIdentity"]}
        pod_evidence = []
        for pod in pods:
            if not any(item.get("type") == "Ready" and item.get("status") == "True" for item in pod.get("status", {}).get("conditions", [])):
                raise ReadinessError(f"Pod/{pod['metadata']['name']} is not Ready")
            evidence_containers = []
            groups = (
                (pod["spec"].get("initContainers", []), pod.get("status", {}).get("initContainerStatuses", []), True),
                (pod["spec"].get("containers", []), pod.get("status", {}).get("containerStatuses", []), False),
            )
            for containers, statuses, is_init in groups:
                indexed_statuses = {item["name"]: item for item in statuses}
                for container in containers:
                    claim = runtime_images.get(container["image"])
                    if claim is None:
                        raise ReadinessError(f"Pod/{pod['metadata']['name']} uses unbound image {container['image']}")
                    status = indexed_statuses.get(container["name"], {})
                    expected_suffix = "@" + claim["indexDigest"]
                    if not status.get("imageID", "").endswith(expected_suffix):
                        raise ReadinessError(f"Pod/{pod['metadata']['name']} runtime index identity differs")
                    if is_init:
                        expect(status.get("state", {}).get("terminated", {}).get("exitCode"), 0, f"Pod/{pod['metadata']['name']} init completion")
                    else:
                        expect(status.get("ready"), True, f"Pod/{pod['metadata']['name']} container readiness")
                    evidence_containers.append({"name": container["name"], "class": "init" if is_init else "main", "image": container["image"], "runtimeImageID": status["imageID"], "indexDigestMatched": True})
            pod_evidence.append({"name": pod["metadata"]["name"], "uid": pod["metadata"]["uid"], "nodeName": pod["spec"].get("nodeName"), "containers": evidence_containers})

        target_state = {}
        for resource in ("applications.argoproj.io", "applicationsets.argoproj.io", "appprojects.argoproj.io"):
            target_state[resource] = len(get_json(kube, ["get", resource, "--all-namespaces"], runner).get("items", []))
        expect(target_state, {
            "applications.argoproj.io": 0,
            "applicationsets.argoproj.io": 0,
            "appprojects.argoproj.io": 1,
        }, "Argo target-state custom resources")
        default_project = get_json(kube, ["--namespace", TARGET_NAMESPACE, "get", "appproject", "default"], runner)
        expect(default_project["metadata"]["uid"], spec["nativeDefaultProject"]["uid"], "default AppProject UID")
        expect(default_project["metadata"].get("generation"), 1, "default AppProject generation")
        expect(default_project.get("spec"), spec["nativeDefaultProject"]["spec"], "default AppProject semantics")

        evidence["spec"].update({
            "result": "PASS-RUNTIME-NATIVE-DEFAULT-PROJECT-RISK-PENDING",
            "target": {"kubeSystemNamespaceUID": identity["metadata"]["uid"], "namespace": TARGET_NAMESPACE},
            "inventory": {"reviewedObjectsPresent": len(identities), "objects": identities},
            "readiness": {"establishedCRDs": len(crds), "workloads": workload_evidence, "pods": sorted(pod_evidence, key=lambda item: item["name"])},
            "targetState": {"counts": target_state, "nativeDefaultProject": V2.object_identity(default_project), "openKubesSubmittedObjects": 0},
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
