#!/usr/bin/env python3
"""Bounded two-phase create-only installer for the OK-141 M0b v2 candidate."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import urllib.request
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import yaml


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
HARNESS = SPIKE / "harness" / "ok141_phase_r_v4.py"
CLUSTER_SCOPED_KINDS = {"Namespace", "CustomResourceDefinition"}
TARGET_NAMESPACE = "argocd"
TARGET_KUBECONFIG = "/Users/arash/.kube/ok-shared.yaml"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


V4 = _load("ok141_m0b_v2_phase_r", HARNESS)
V1 = V4.V1


class ExecutionError(ValueError):
    pass


@dataclass(frozen=True)
class ReviewedSet:
    source_documents: list[dict[str, Any]]
    projected_documents: list[dict[str, Any]]
    phase1: list[dict[str, Any]]
    phase2: list[dict[str, Any]]
    source_claims: list[dict[str, Any]]


def sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def expect(actual: Any, expected: Any, claim: str) -> None:
    if actual != expected:
        raise ExecutionError(f"{claim} mismatch")


def read(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text())
    if not isinstance(value, dict):
        raise ExecutionError(f"invalid YAML object: {path}")
    return value


def resolve(base: Path, requested: str) -> Path:
    candidate = (base.parent / requested).resolve()
    if SPIKE.resolve() not in candidate.parents or not candidate.is_file():
        raise ExecutionError(f"reference missing or outside spike: {requested}")
    return candidate


def documents(raw: bytes, source: str) -> list[dict[str, Any]]:
    try:
        return [item for item in yaml.load_all(raw.decode(), Loader=V1.UniqueKeyLoader) if item]
    except (UnicodeError, yaml.YAMLError) as exc:
        raise ExecutionError(f"cannot parse {source}: {exc}") from exc


def materialize(
    lock_path: Path,
    output_dir: Path,
    fetch: Callable[[str], bytes] | None = None,
) -> dict[str, Any]:
    lock = read(lock_path)["spec"]
    output_dir.mkdir(parents=True, exist_ok=True)
    fetch_bytes = fetch or (lambda url: urllib.request.urlopen(url, timeout=30).read())
    result = []
    for item in lock["files"]:
        raw = fetch_bytes(item["url"])
        parsed = documents(raw, item["id"])
        actual = {
            "id": item["id"],
            "rawDigest": sha256_bytes(raw),
            "semanticDigest": V1.semantic_revision(parsed),
            "sizeBytes": len(raw),
            "objectCount": len(parsed),
        }
        for field in ("rawDigest", "semanticDigest", "sizeBytes", "objectCount"):
            expect(actual[field], item[field], f"{item['id']} {field}")
        (output_dir / f"{item['id']}.yaml").write_bytes(raw)
        result.append(actual)
    return {
        "operation": "materialize",
        "files": result,
        "clusterContacted": False,
        "mutationAuthorized": False,
    }


def payload(items: list[dict[str, Any]]) -> bytes:
    return yaml.safe_dump_all(items, explicit_start=True, sort_keys=False).encode()


def reviewed_set(lock_path: Path, materialized_dir: Path) -> ReviewedSet:
    lock = read(lock_path)["spec"]
    namespace_path = resolve(lock_path, lock["localNamespace"]["path"])
    namespace_raw = namespace_path.read_bytes()
    expect(sha256_bytes(namespace_raw), lock["localNamespace"]["rawDigest"], "Namespace raw digest")
    source_documents = documents(namespace_raw, "Namespace")
    source_claims = [{"id": "namespace", "rawDigest": sha256_bytes(namespace_raw)}]
    raw_chunks = [namespace_raw]
    for item in lock["files"]:
        path = materialized_dir / f"{item['id']}.yaml"
        if not path.is_file():
            raise ExecutionError(f"materialized source missing: {item['id']}")
        raw = path.read_bytes()
        parsed = documents(raw, item["id"])
        expect(sha256_bytes(raw), item["rawDigest"], f"{item['id']} raw digest")
        expect(V1.semantic_revision(parsed), item["semanticDigest"], f"{item['id']} semantic digest")
        expect(len(raw), item["sizeBytes"], f"{item['id']} size")
        expect(len(parsed), item["objectCount"], f"{item['id']} object count")
        source_documents.extend(parsed)
        raw_chunks.append(raw)
        source_claims.append({"id": item["id"], "rawDigest": item["rawDigest"], "semanticDigest": item["semanticDigest"]})

    source = lock["sourceSet"]
    expect(len(source_documents), source["objectCount"], "source object count")
    expect(V1.semantic_revision(source_documents), source["semanticDigest"], "source semantics")
    raw_payload = b"\n---\n".join(chunk.rstrip() for chunk in raw_chunks) + b"\n"
    expect(sha256_bytes(raw_payload), source["rawPayloadDigest"], "raw source payload")
    expect(dict(sorted(Counter(item["kind"] for item in source_documents).items())), dict(sorted(lock["inventory"].items())), "source inventory")

    projected = copy.deepcopy(source_documents)
    for item in projected:
        kind = item["kind"]
        metadata = item.setdefault("metadata", {})
        if kind in CLUSTER_SCOPED_KINDS:
            if metadata.get("namespace"):
                raise ExecutionError(f"cluster-scoped {kind} unexpectedly has a Namespace")
            continue
        current = metadata.get("namespace")
        if current not in (None, TARGET_NAMESPACE):
            raise ExecutionError(f"{kind}/{metadata.get('name')} targets unexpected Namespace {current}")
        metadata["namespace"] = TARGET_NAMESPACE

    projection = lock["targetProjection"]
    expect(V1.semantic_revision(projected), projection["projectedSemanticDigest"], "target projection")
    phase1 = [item for item in projected if item["kind"] in CLUSTER_SCOPED_KINDS]
    phase2 = [item for item in projected if item["kind"] not in CLUSTER_SCOPED_KINDS]
    expect(len(phase2), projection["namespacedObjectCount"], "namespaced object count")
    if any(item["kind"] in {"AppProject", "Application", "ApplicationSet"} for item in projected):
        raise ExecutionError("installation payload contains target desired state")
    return ReviewedSet(source_documents, projected, phase1, phase2, source_claims)


def validate_candidate(candidate_path: Path) -> dict[str, Any]:
    candidate = read(candidate_path)["spec"]
    expect(candidate["state"], "READY-FOR-FINAL-PREFLIGHT-NO-GO", "candidate state")
    for reference in candidate["references"].values():
        path = resolve(candidate_path, reference["path"])
        expect(sha256_file(path), reference["digest"], f"reference {reference['path']}")
    authorization = candidate["authorization"]
    expect(authorization["decision"], "NO-GO", "candidate authorization")
    if any(value is not False for key, value in authorization.items() if key != "decision"):
        raise ExecutionError("candidate grants authority")
    return candidate


def plan(candidate_path: Path, materialized_dir: Path) -> tuple[dict[str, Any], ReviewedSet]:
    candidate = validate_candidate(candidate_path)
    lock_reference = candidate["references"]["sourceLock"]
    lock_path = resolve(candidate_path, lock_reference["path"])
    reviewed = reviewed_set(lock_path, materialized_dir)
    submission = candidate["submission"]
    expect(len(reviewed.phase1), submission["phase1"]["objectCount"], "phase-1 count")
    expect(V1.semantic_revision(reviewed.phase1), submission["phase1"]["semanticDigest"], "phase-1 semantics")
    expect(len(reviewed.phase2), submission["phase2"]["objectCount"], "phase-2 count")
    expect(V1.semantic_revision(reviewed.phase2), submission["phase2"]["semanticDigest"], "phase-2 semantics")
    expect(V1.semantic_revision(reviewed.projected_documents), submission["combinedTargetSemanticDigest"], "combined target semantics")
    phase1_payload = payload(reviewed.phase1)
    phase2_payload = payload(reviewed.phase2)
    result = {
        "operation": "plan",
        "candidateDigest": sha256_file(candidate_path),
        "targetPlane": "ok-shared",
        "targetNamespace": TARGET_NAMESPACE,
        "phase1": {"objectCount": len(reviewed.phase1), "semanticDigest": V1.semantic_revision(reviewed.phase1), "transportDigest": sha256_bytes(phase1_payload)},
        "phase2": {"objectCount": len(reviewed.phase2), "semanticDigest": V1.semantic_revision(reviewed.phase2), "transportDigest": sha256_bytes(phase2_payload)},
        "combinedTargetSemanticDigest": V1.semantic_revision(reviewed.projected_documents),
        "clusterContacted": False,
        "mutationAuthorized": False,
        "commands": [
            ["kubectl", "--kubeconfig", TARGET_KUBECONFIG, "create", "--filename", "-"],
            ["kubectl", "--kubeconfig", TARGET_KUBECONFIG, "--namespace", TARGET_NAMESPACE, "create", "--filename", "-"],
        ],
    }
    return result, reviewed


def parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def validate_grant(grant_path: Path, candidate_path: Path, now: datetime) -> dict[str, Any]:
    grant = read(grant_path)["spec"]
    expect(grant["state"], "GRANTED", "grant state")
    expect(grant["candidateDigest"], sha256_file(candidate_path), "authorized candidate")
    expect(grant["decision"], "GO", "grant decision")
    expect(grant["m0bInstallationGranted"], True, "M0b-I grant")
    expect(grant["maximumRuns"], 1, "run budget")
    if not grant.get("grantID") or grant.get("authority") != "github:arashkaffamanesh":
        raise ExecutionError("grant identity is unresolved")
    if not (parse_utc(grant["validFrom"]) <= now <= parse_utc(grant["validUntil"])):
        raise ExecutionError("grant window is not active")
    exclusions = grant["exclusions"]
    for required in ("rollback", "target-registration", "target-convergence", "go-1", "failure-injection"):
        if required not in exclusions:
            raise ExecutionError(f"grant exclusion missing: {required}")
    return grant


def run(command: list[str], input_bytes: bytes | None = None, runner: Callable[..., Any] = subprocess.run) -> subprocess.CompletedProcess:
    return runner(command, input=input_bytes, check=True, capture_output=True)


def write_evidence(path: Path, value: dict[str, Any], create: bool = False) -> None:
    flags = os.O_WRONLY | os.O_CREAT | (os.O_EXCL if create else os.O_TRUNC)
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True) + "\n")


def live_preflight(
    candidate_path: Path,
    materialized_dir: Path,
    runner: Callable[..., Any] = subprocess.run,
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    planned, reviewed = plan(candidate_path, materialized_dir)
    kube = ["kubectl", "--kubeconfig", TARGET_KUBECONFIG]
    identity = json.loads(run([*kube, "get", "namespace", "kube-system", "-o", "json"], runner=runner).stdout)
    expect(identity["metadata"]["uid"], "46b9ecf7-2e7a-48b1-a6eb-7d11df396efb", "target incarnation")
    version = json.loads(run([*kube, "get", "--raw=/version"], runner=runner).stdout)
    expect(version["gitVersion"], "v1.34.1", "target Kubernetes version")
    nodes = json.loads(run([*kube, "get", "nodes", "-o", "json"], runner=runner).stdout)["items"]
    node_evidence = []
    for item in nodes:
        ready = next((condition for condition in item.get("status", {}).get("conditions", []) if condition["type"] == "Ready"), {})
        node_evidence.append({
            "name": item["metadata"]["name"],
            "uid": item["metadata"]["uid"],
            "ready": ready.get("status"),
            "architecture": item["metadata"].get("labels", {}).get("kubernetes.io/arch"),
        })
    if len(node_evidence) != 4 or any(item["ready"] != "True" or item["architecture"] != "amd64" for item in node_evidence):
        raise ExecutionError("target Nodes are not the expected 4/4 Ready amd64 shape")
    combined_payload = payload(reviewed.projected_documents)
    existing = run([*kube, "get", "--filename", "-", "--ignore-not-found", "-o", "name"], combined_payload, runner).stdout.decode().splitlines()
    if existing:
        raise ExecutionError("one or more reviewed target identities already exist")
    current = observed_at or datetime.now(timezone.utc)
    return {
        "apiVersion": "evidence.openkubes.io/v1alpha1",
        "kind": "M0bFinalLivePreflight",
        "metadata": {"name": "ok141-m0b-v2-final-live-preflight"},
        "spec": {
            "observedAt": current.isoformat().replace("+00:00", "Z"),
            "operation": "READ-ONLY",
            "candidateDigest": planned["candidateDigest"],
            "targetKubeSystemUID": identity["metadata"]["uid"],
            "kubernetesVersion": version["gitVersion"],
            "nodes": sorted(node_evidence, key=lambda item: item["name"]),
            "reviewedTargetIdentities": len(reviewed.projected_documents),
            "existingReviewedTargetIdentities": 0,
            "result": "PASS-POINT-IN-TIME-NO-GO",
            "clusterContacted": True,
            "mutationAuthorized": False,
        },
    }


def execute(
    candidate_path: Path,
    grant_path: Path,
    materialized_dir: Path,
    evidence_path: Path,
    runner: Callable[..., Any] = subprocess.run,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    grant = validate_grant(grant_path, candidate_path, current)
    planned, reviewed = plan(candidate_path, materialized_dir)
    expected_evidence = Path(grant["rawEvidencePath"])
    if evidence_path.resolve() != expected_evidence.resolve() or evidence_path.parent.resolve() != Path("/private/tmp").resolve():
        raise ExecutionError("raw evidence path is not the exact authorized /private/tmp path")
    if evidence_path.exists():
        raise ExecutionError("raw evidence path already exists")

    kube = ["kubectl", "--kubeconfig", TARGET_KUBECONFIG]
    identity = json.loads(run([*kube, "get", "namespace", "kube-system", "-o", "json"], runner=runner).stdout)
    expect(identity["metadata"]["uid"], "46b9ecf7-2e7a-48b1-a6eb-7d11df396efb", "target incarnation")
    combined_payload = payload(reviewed.projected_documents)
    existing = run([*kube, "get", "--filename", "-", "--ignore-not-found", "-o", "name"], combined_payload, runner).stdout.decode().strip()
    if existing:
        raise ExecutionError("one or more reviewed target identities already exist")

    evidence: dict[str, Any] = {
        "apiVersion": "evidence.openkubes.io/v1alpha1",
        "kind": "M0bExecutionEvidence",
        "spec": {
            "observedAt": current.isoformat().replace("+00:00", "Z"),
            "grantID": grant["grantID"],
            "candidateDigest": planned["candidateDigest"],
            "targetKubeSystemUID": identity["metadata"]["uid"],
            "sourceClaims": reviewed.source_claims,
            "phases": [],
            "rawSecretDataRetained": False,
            "result": "STARTED-NO-CREATE-ACCEPTED",
        },
    }
    write_evidence(evidence_path, evidence, create=True)
    try:
        for phase_name, items, command in (
            ("cluster-prerequisites", reviewed.phase1, planned["commands"][0]),
            ("namespaced-control-plane", reviewed.phase2, planned["commands"][1]),
        ):
            completed = run(command, payload(items), runner)
            evidence["spec"]["phases"].append({
                "name": phase_name,
                "objectCount": len(items),
                "semanticDigest": V1.semantic_revision(items),
                "transportDigest": sha256_bytes(payload(items)),
                "result": "CREATE-ACCEPTED",
                "stdoutDigest": sha256_bytes(completed.stdout),
            })
            evidence["spec"]["result"] = f"PARTIAL-{len(evidence['spec']['phases'])}-OF-2-CREATE-PHASES-ACCEPTED"
            write_evidence(evidence_path, evidence)
        evidence["spec"]["result"] = "CREATE-PHASES-ACCEPTED-RUNTIME-READINESS-PENDING"
    except Exception as exc:
        evidence["spec"]["result"] = "PARTIAL-OR-FAILED-STOP-NO-AUTOMATIC-ROLLBACK"
        evidence["spec"]["failureType"] = type(exc).__name__
        write_evidence(evidence_path, evidence)
        raise
    write_evidence(evidence_path, evidence)
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    materialize_parser = sub.add_parser("materialize")
    materialize_parser.add_argument("--lock", type=Path, required=True)
    materialize_parser.add_argument("--output-dir", type=Path, required=True)
    plan_parser = sub.add_parser("plan")
    plan_parser.add_argument("--candidate", type=Path, required=True)
    plan_parser.add_argument("--materialized-dir", type=Path, required=True)
    preflight_parser = sub.add_parser("preflight")
    preflight_parser.add_argument("--candidate", type=Path, required=True)
    preflight_parser.add_argument("--materialized-dir", type=Path, required=True)
    execute_parser = sub.add_parser("execute")
    execute_parser.add_argument("--candidate", type=Path, required=True)
    execute_parser.add_argument("--grant", type=Path, required=True)
    execute_parser.add_argument("--materialized-dir", type=Path, required=True)
    execute_parser.add_argument("--evidence-out", type=Path, required=True)
    execute_parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "materialize":
            result = materialize(args.lock.resolve(), args.output_dir.resolve())
        elif args.command == "plan":
            result, _ = plan(args.candidate.resolve(), args.materialized_dir.resolve())
        elif args.command == "preflight":
            result = live_preflight(args.candidate.resolve(), args.materialized_dir.resolve())
        else:
            if not args.execute:
                raise ExecutionError("execute requires the explicit --execute flag")
            result = execute(args.candidate.resolve(), args.grant.resolve(), args.materialized_dir.resolve(), args.evidence_out.resolve())
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (ExecutionError, OSError, ValueError, yaml.YAMLError, subprocess.SubprocessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
