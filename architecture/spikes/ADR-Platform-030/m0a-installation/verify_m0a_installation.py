#!/usr/bin/env python3
"""Fail-closed verifier for the non-authorizing OK-141 M0a-I protocol."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import yaml


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
HARNESS = SPIKE / "harness"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


V4 = _load("ok141_phase_r_v4_m0ai", HARNESS / "ok141_phase_r_v4.py")
V1 = V4.V1

GO1_DIGEST = "sha256:2718d719c322190e36036f98730edcb9aaa679c434fb04f151f7f24fc2626705"
PARTITION_DIGEST = "sha256:a12a5e30f5bd5479d502f0dbf80e709e14216702ba804f986afcb408f0c32be9"
HISTORICAL_M0A_DIGEST = "sha256:c06f9c0d670f46f209ee5f540d6497e3dea34fa80b85ecc740db8ded6f68e5d0"
RAW_DIGEST = "sha256:a70f4eb77eac626231daca1e2a046b4b069bb84320efa327cc8c56a9c4ca03e6"
SEMANTIC_DIGEST = "sha256:01fc13d694da3304385a7bae0d1bd662d7c8c3d336b8a4d44da5324439d59095"
IMAGE = "registry.k8s.io/cluster-api-helm/cluster-api-helm-controller:v0.6.4"
IMAGE_PLATFORM_DIGEST = "sha256:66344ab0107c0a3fcbce860697206ac7e6a2316a7af4a07f81a9f8d53e448e6a"
PRE_IDS = {
    "M0AI-AUTHORITY", "M0AI-BASELINE-FRESHNESS", "M0AI-INSTALLER-IDENTITY",
    "M0AI-EXACT-OBJECT-SUBMISSION", "M0AI-CONTROLLER-RBAC-ACCEPTANCE",
    "M0AI-COMPATIBILITY", "M0AI-OBSERVERS-EVIDENCE", "M0AI-RECOVERY",
}
RUNTIME_IDS = {
    "M0AI-INVENTORY-IDENTITY", "M0AI-API-WEBHOOK-READY",
    "M0AI-CONTROLLER-IMAGE-READY", "M0AI-NO-TARGET-RESOURCES",
    "M0AI-EVIDENCE-BUNDLE",
}
PHASE_IDS = {"M0AI-G0", "M0AI-G1", "M0AI-G2", "M0AI-G3"}
KINDS = {
    "Namespace": 1, "CustomResourceDefinition": 2, "ServiceAccount": 1,
    "Role": 1, "RoleBinding": 1, "ClusterRole": 3,
    "ClusterRoleBinding": 2, "ConfigMap": 1, "Service": 2,
    "Deployment": 1, "Certificate": 1, "Issuer": 1,
    "MutatingWebhookConfiguration": 1, "ValidatingWebhookConfiguration": 1,
}


def _expect(actual: Any, expected: Any, claim: str) -> None:
    if actual != expected:
        raise V1.HarnessError(f"M0a-I {claim} mismatch")


def _resolve(protocol_path: Path, requested: str) -> Path:
    candidate = (protocol_path.parent / requested).resolve()
    if SPIKE.resolve() not in candidate.parents or not candidate.is_file():
        raise V1.HarnessError(f"M0a-I reference missing or outside spike root: {requested}")
    return candidate


def _indexed(items: list[dict[str, Any]], claim: str) -> dict[str, dict[str, Any]]:
    result = {item.get("id"): item for item in items}
    if None in result or len(result) != len(items):
        raise V1.HarnessError(f"M0a-I {claim} contains missing or duplicate IDs")
    return result


def _documents(path: Path) -> list[dict[str, Any]]:
    return [item for item in yaml.load_all(path.read_text(), Loader=V1.UniqueKeyLoader) if item]


def validate(document: dict[str, Any], protocol_path: Path) -> str:
    schema = json.loads((HERE / "m0a-installation-v1.schema.json").read_text())
    V1.normalize(document, schema)
    spec = document["spec"]
    _expect(spec["protocolState"], "BLOCKED", "protocol state")

    references = spec["references"]
    expected_references = {
        "go1Protocol": GO1_DIGEST,
        "gatePartition": PARTITION_DIGEST,
        "historicalM0a": HISTORICAL_M0A_DIGEST,
    }
    for name, digest in expected_references.items():
        claim = references[name]
        _expect(claim["digest"], digest, f"{name} declared digest")
        _expect(V1.sha256_bytes(_resolve(protocol_path, claim["path"]).read_bytes()), digest, f"{name} raw digest")

    boundary = spec["authorityBoundary"]
    _expect(boundary["gate"], "M0A-I", "gate identity")
    for field in ("mayAuthorizeTargetConvergence", "mayAuthorizeGO1", "maySubmitHelmChartProxy", "maySubmitHelmReleaseProxy", "mayAccessWorkloadCluster"):
        _expect(boundary[field], False, f"authority boundary {field}")

    authorization = spec["authorization"]
    _expect(authorization["decision"], "NO-GO", "decision")
    for field in ("mutationAuthorized", "m0aInstallationGranted", "m0aTargetConvergenceGranted", "go1Granted"):
        _expect(authorization[field], False, f"authorization {field}")
    for field in ("grantID", "authorizedProtocolDigest", "decidedAt"):
        _expect(authorization[field], None, f"authorization {field}")

    source = spec["source"]
    manifest_path = _resolve(protocol_path, source["manifestPath"])
    _expect(V1.sha256_bytes(manifest_path.read_bytes()), RAW_DIGEST, "release manifest raw digest")
    _expect(source["rawDigest"], RAW_DIGEST, "declared release manifest raw digest")
    _expect(manifest_path.stat().st_size, 55263, "release manifest size")
    _expect(source["sizeBytes"], 55263, "declared release manifest size")
    documents = _documents(manifest_path)
    _expect(len(documents), 19, "release manifest object count")
    _expect(source["objectCount"], 19, "declared release manifest object count")
    _expect(dict(Counter(item["kind"] for item in documents)), KINDS, "release manifest kind inventory")
    _expect(V1.semantic_revision(documents), SEMANTIC_DIGEST, "release manifest semantic digest")
    _expect(source["semanticDigest"], SEMANTIC_DIGEST, "declared semantic digest")
    _expect(source["objectKinds"], KINDS, "declared kind inventory")

    deployments = [item for item in documents if item["kind"] == "Deployment"]
    containers = deployments[0]["spec"]["template"]["spec"]["containers"]
    _expect([container["image"] for container in containers], [IMAGE], "controller image reference")
    _expect(source["controllerImage"]["reference"], IMAGE, "declared controller image reference")
    _expect(source["controllerImage"]["linuxAmd64Digest"], IMAGE_PLATFORM_DIGEST, "controller platform digest")
    forbidden_kinds = {"HelmChartProxy", "HelmReleaseProxy", "Cluster", "Machine"}
    if any(item["kind"] in forbidden_kinds for item in documents):
        raise V1.HarnessError("M0a-I installation manifest contains a target or lifecycle resource")

    submission = spec["submission"]
    _expect(submission["operation"], "ApplyReviewedInstallationSet", "submission operation")
    _expect(submission["enabled"], False, "submission state")
    _expect(submission["freeFormShellEndpoint"], False, "shell boundary")
    _expect(submission["targetPlane"], "ok-mgmt", "submission plane")
    _expect((submission["expectedRawDigest"], submission["expectedSemanticDigest"]), (RAW_DIGEST, SEMANTIC_DIGEST), "submission object-set identity")

    security_path = _resolve(protocol_path, spec["securityReview"]["path"])
    security = V1.read_yaml_or_json(security_path)
    _expect(security["spec"]["result"]["m0a"], "NOT-GRANTED", "historical security decision")
    _expect(spec["securityReview"]["status"], "EXPLICIT-ACCEPTANCE-REQUIRED", "security acceptance")

    pre = _indexed(spec["preInstallationRequirements"], "pre-installation requirements")
    _expect(set(pre), PRE_IDS, "pre-installation requirement membership")
    if any(item["status"] != "BLOCKED" for item in pre.values()):
        raise V1.HarnessError("M0a-I pre-installation requirement was closed without a new protocol")

    runtime = _indexed(spec["runtimeObligations"], "runtime obligations")
    _expect(set(runtime), RUNTIME_IDS, "runtime obligation membership")
    for item in runtime.values():
        if item["status"] != "PENDING-RUNTIME" or item["phase"] not in {"M0AI-G2", "M0AI-G3"}:
            raise V1.HarnessError("M0a-I runtime obligation was closed early or assigned to an invalid phase")
        if item["mayBeClosedBeforeRuntime"] is not False or item["onFailure"] != "STOP-NOT-SUCCESS":
            raise V1.HarnessError("M0a-I runtime obligation does not fail closed")

    phases = _indexed(spec["phases"], "phases")
    _expect(set(phases), PHASE_IDS, "phase membership")
    if any(item["enabled"] is not False for item in phases.values()):
        raise V1.HarnessError("M0a-I phase enabled without authorization")
    if {item_id for item_id, item in phases.items() if item["mutating"]} != {"M0AI-G1"}:
        raise V1.HarnessError("M0a-I G1 is not the sole prospective installation phase")

    rollback = spec["rollback"]
    _expect(rollback["enabled"], False, "rollback state")
    _expect(rollback["authorizationRequired"], True, "rollback authorization")
    if len(rollback["preconditions"]) < 5 or "STOP" not in rollback["preconditions"][0]:
        raise V1.HarnessError("M0a-I rollback does not fail closed on explicit STOP")
    excluded = " ".join(spec["excludedScenarios"]).lower()
    for phrase in ("helmchartproxy", "restart", "go-1", "management outage"):
        if phrase not in excluded:
            raise V1.HarnessError(f"M0a-I exclusion missing: {phrase}")

    return V1.sha256_bytes(protocol_path.read_bytes())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--digest-file", type=Path)
    args = parser.parse_args()
    try:
        digest = validate(V1.read_yaml_or_json(args.protocol), args.protocol.resolve())
        if args.digest_file:
            expected = args.digest_file.read_text().split()[0]
            _expect(digest.removeprefix("sha256:"), expected, "raw protocol digest")
        print(digest)
        return 0
    except (V1.HarnessError, OSError, ValueError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
