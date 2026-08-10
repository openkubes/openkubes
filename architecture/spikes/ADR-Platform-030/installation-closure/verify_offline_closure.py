#!/usr/bin/env python3
"""Fail-closed verifier for the nine OK-141 offline-closable obligations."""

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


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


INSTALLER = _load("ok141_offline_closure_installer", HERE / "bounded_installer.py")
V1 = INSTALLER.V1

EXPECTED_RESULTS = {
    "M0AI-INSTALLER-ARTIFACT": "PROVEN-OFFLINE",
    "M0AI-SUBMISSION-INTEGRITY": "PROVEN-OFFLINE",
    "M0AI-RBAC-ANALYSIS": "PROVEN-OFFLINE",
    "M0AI-COMPATIBILITY-EVIDENCE": "PARTIAL-UNRESOLVED",
    "M0BI-SOURCE-MATERIALIZATION-VERIFY": "PROVEN-REPEATABLE-PREFLIGHT",
    "M0BI-INSTALLER-ARTIFACT": "PROVEN-OFFLINE",
    "M0BI-SUBMISSION-INTEGRITY": "PROVEN-OFFLINE",
    "M0BI-RBAC-ANALYSIS": "PROVEN-OFFLINE",
    "M0BI-IMAGE-COMPATIBILITY-EVIDENCE": "PROVEN-OFFLINE",
}
EXPECTED_ARTIFACTS = {
    "boundedInstaller",
    "rbacAnalyzer",
    "m0aRBAC",
    "m0bRBAC",
    "compatibility",
    "m0bMaterialization",
}
EXPECTED_RBAC = {
    "M0A-I": {
        "roles": 4,
        "bindings": 3,
        "findings": 7,
        "byFinding": {
            "SECRET-READ": 2,
            "SUBJECTACCESSREVIEW": 2,
            "TOKENREVIEW": 2,
            "WILDCARD-RESOURCE-SCOPE": 1,
        },
    },
    "M0B-I": {
        "roles": 7,
        "bindings": 7,
        "findings": 9,
        "byFinding": {"SECRET-READ": 7, "SECRET-WRITE": 2},
    },
}


def _expect(actual: Any, expected: Any, claim: str) -> None:
    if actual != expected:
        raise INSTALLER.InstallerError(f"offline closure {claim} mismatch")


def _resolve(base: Path, requested: str) -> Path:
    candidate = (base.parent / requested).resolve()
    if SPIKE.resolve() not in candidate.parents or not candidate.is_file():
        raise INSTALLER.InstallerError(
            f"offline closure reference missing or outside spike root: {requested}"
        )
    return candidate


def _index(items: list[dict[str, Any]], claim: str) -> dict[str, dict[str, Any]]:
    indexed = {item.get("id"): item for item in items}
    if None in indexed or len(indexed) != len(items):
        raise INSTALLER.InstallerError(
            f"offline closure {claim} contains missing or duplicate IDs"
        )
    return indexed


def _verify_rbac(path: Path, expected_gate: str, analyzer_digest: str) -> None:
    report = json.loads(path.read_text())
    spec = report["spec"]
    _expect(spec["gate"], expected_gate, f"{expected_gate} RBAC gate")
    _expect(spec["decision"], "ANALYZED-NOT-ACCEPTED", f"{expected_gate} RBAC decision")
    _expect(spec["mutationAuthorized"], False, f"{expected_gate} RBAC authorization")
    _expect(spec["toolDigest"], analyzer_digest, f"{expected_gate} RBAC analyzer digest")
    _expect(spec["summary"], EXPECTED_RBAC[expected_gate], f"{expected_gate} RBAC summary")
    if expected_gate == "M0B-I" and any(role["kind"] == "ClusterRole" for role in spec["roles"]):
        raise INSTALLER.InstallerError("offline closure M0B-I unexpectedly contains a ClusterRole")


def _verify_compatibility(path: Path, m0a: dict[str, Any], m0b: dict[str, Any]) -> None:
    document = V1.read_yaml_or_json(path)
    spec = document["spec"]
    _expect(spec["authorization"], {"decision": "NO-GO", "mutationAuthorized": False}, "compatibility authorization")
    caaph = spec["caaph"]
    argocd = spec["argocd"]
    _expect((caaph["obligation"], caaph["result"]), ("M0AI-COMPATIBILITY-EVIDENCE", "PARTIAL-UNRESOLVED"), "CAAPH compatibility result")
    _expect((argocd["obligation"], argocd["result"]), ("M0BI-IMAGE-COMPATIBILITY-EVIDENCE", "PROVEN-OFFLINE"), "Argo compatibility result")
    for source in caaph["sources"] + argocd["sources"]:
        source_path = _resolve(path, source["path"])
        _expect(V1.sha256_bytes(source_path.read_bytes()), source["rawDigest"], f"compatibility source {source['path']}")
        if not source.get("claim"):
            raise INSTALLER.InstallerError("offline closure compatibility source has no claim")
    _expect(caaph["imageObservation"]["observedLinuxAmd64Digest"], m0a["spec"]["source"]["controllerImage"]["linuxAmd64Digest"], "CAAPH image lock")
    _expect(caaph["imageObservation"]["equalsInstallationLock"], True, "CAAPH image equality")
    locked_images = {
        item["reference"]: item["linuxAmd64Digest"]
        for item in m0b["spec"]["source"]["controllerImages"]
    }
    observed_images = {item["reference"]: item for item in argocd["images"]}
    _expect(set(observed_images), set(locked_images), "Argo image membership")
    for reference, digest in locked_images.items():
        _expect(observed_images[reference]["observedLinuxAmd64Digest"], digest, f"Argo image lock {reference}")
        _expect(observed_images[reference]["equalsInstallationLock"], True, f"Argo image equality {reference}")
    if not caaph.get("notProven") or not argocd.get("limitations"):
        raise INSTALLER.InstallerError("offline closure compatibility boundaries are absent")


def _verify_materialization(path: Path, protocol: dict[str, Any], protocol_path: Path) -> None:
    evidence = V1.read_yaml_or_json(path)["spec"]
    source = protocol["spec"]["source"]
    _expect(evidence["protocolDigest"], V1.sha256_bytes(protocol_path.read_bytes()), "M0B materialization protocol digest")
    _expect(evidence["sourceLockDigest"], source["lockDigest"], "M0B materialization source lock")
    lock_path = _resolve(protocol_path, source["lockPath"])
    lock = V1.read_yaml_or_json(lock_path)["spec"]
    expected_files = {
        item["id"]: {
            field: item[field]
            for field in ("rawDigest", "semanticDigest", "sizeBytes", "objectCount")
        }
        for item in lock["files"]
    }
    actual_files = {
        item["id"]: {
            field: item[field]
            for field in ("rawDigest", "semanticDigest", "sizeBytes", "objectCount")
        }
        for item in evidence["files"]
    }
    _expect(actual_files, expected_files, "M0B materialized file claims")
    _expect(evidence["combined"]["objectCount"], source["combinedObjectCount"], "M0B combined count")
    _expect(evidence["combined"]["semanticDigest"], source["combinedSemanticDigest"], "M0B combined semantic digest")
    _expect((evidence["result"], evidence["obligation"]), ("PROVEN-REPEATABLE-PREFLIGHT", "M0BI-SOURCE-MATERIALIZATION-VERIFY"), "M0B materialization result")
    _expect((evidence["clusterContacted"], evidence["mutationAuthorized"]), (False, False), "M0B materialization safety")
    freshness = evidence.get("freshnessRule", "").lower()
    for phrase in ("repeated", "before", "cannot be reused as authorization"):
        if phrase not in freshness:
            raise INSTALLER.InstallerError(f"offline closure materialization freshness rule missing: {phrase}")


def validate(document: dict[str, Any], results_path: Path) -> str:
    schema = json.loads((HERE / "offline-closure-results-v1.schema.json").read_text())
    V1.normalize(document, schema)
    spec = document["spec"]
    _expect(spec["state"], "EVALUATED-NO-GO", "state")

    authorization = spec["authorization"]
    _expect(authorization["decision"], "NO-GO", "decision")
    for field in ("mutationAuthorized", "m0aInstallationGranted", "m0bInstallationGranted", "go1Granted"):
        _expect(authorization[field], False, f"authorization {field}")

    matrix_path = _resolve(results_path, spec["sourceMatrix"]["path"])
    _expect(V1.sha256_bytes(matrix_path.read_bytes()), spec["sourceMatrix"]["digest"], "source matrix digest")

    artifacts = spec["artifacts"]
    _expect(set(artifacts), EXPECTED_ARTIFACTS, "artifact membership")
    artifact_paths: dict[str, Path] = {}
    for name, claim in artifacts.items():
        artifact_path = _resolve(results_path, claim["path"])
        _expect(V1.sha256_bytes(artifact_path.read_bytes()), claim["digest"], f"artifact {name} digest")
        artifact_paths[name] = artifact_path

    results = _index(spec["results"], "results")
    _expect({item: value["result"] for item, value in results.items()}, EXPECTED_RESULTS, "result classifications")
    for result_id, result in results.items():
        if not result.get("claim") or not result.get("boundary"):
            raise INSTALLER.InstallerError(f"offline closure {result_id} lacks claim or boundary")
        if not result.get("evidence") or any(name not in artifacts for name in result["evidence"]):
            raise INSTALLER.InstallerError(f"offline closure {result_id} has invalid evidence references")

    expected_counts = dict(Counter(EXPECTED_RESULTS.values()))
    summary = spec["summary"]
    _expect(summary["evaluated"], 9, "evaluated count")
    _expect(summary["byResult"], expected_counts, "result counts")
    _expect(summary["sourceBlockersClosed"], 0, "source blockers closed")
    _expect(summary["installationGatesGranted"], 0, "installation gates granted")

    _expect(INSTALLER.COMMANDS, {"materialize", "verify", "apply", "evidence"}, "bounded command surface")
    m0a_path = SPIKE / "m0a-installation" / "m0a-installation-v1.yaml"
    m0b_path = SPIKE / "m0b-installation" / "m0b-installation-v1.yaml"
    m0a = V1.read_yaml_or_json(m0a_path)
    m0b = V1.read_yaml_or_json(m0b_path)
    reviewed = INSTALLER.verify_reviewed_object_set(m0a, m0a_path)
    try:
        INSTALLER._authorization_plan(m0a, m0a_path, reviewed)
    except INSTALLER.InstallerError:
        pass
    else:
        raise INSTALLER.InstallerError("offline closure current M0A-I protocol unexpectedly permits apply")

    analyzer_digest = artifacts["rbacAnalyzer"]["digest"]
    _verify_rbac(artifact_paths["m0aRBAC"], "M0A-I", analyzer_digest)
    _verify_rbac(artifact_paths["m0bRBAC"], "M0B-I", analyzer_digest)
    _verify_compatibility(artifact_paths["compatibility"], m0a, m0b)
    _verify_materialization(artifact_paths["m0bMaterialization"], m0b, m0b_path)

    rules = " ".join(spec["rules"]).lower()
    for phrase in (
        "only its atomic analysis obligation",
        "never its composite source blocker",
        "not closure",
        "fail closed",
        "fresh rerun",
        "does not authorize credential issuance",
    ):
        if phrase not in rules:
            raise INSTALLER.InstallerError(f"offline closure safety rule missing: {phrase}")
    return V1.sha256_bytes(results_path.read_bytes())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--digest-file", type=Path)
    args = parser.parse_args()
    try:
        results_path = args.results.resolve()
        digest = validate(V1.read_yaml_or_json(results_path), results_path)
        if args.digest_file:
            expected = args.digest_file.read_text().split()[0]
            _expect(digest.removeprefix("sha256:"), expected, "raw results digest")
        print(digest)
        return 0
    except (INSTALLER.InstallerError, OSError, ValueError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
