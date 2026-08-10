#!/usr/bin/env python3
"""Fail-closed verifier for the OK-141 installation closure matrix."""

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


V4 = _load("ok141_phase_r_v4_installation_closure", HARNESS / "ok141_phase_r_v4.py")
V1 = V4.V1

SOURCE_DIGESTS = {
    "m0aInstallation": "sha256:873d3aa3b15df53d3a4055675288c6d9acdf6c18d4f850e181a4eb7b93fc4a27",
    "m0bInstallation": "sha256:79feba3dc3b58d5065c47de894ca3d926fd0cdee134c7252f7df3c0f644d40a7",
}
CLASS_STATUS = {
    "OFFLINE-CLOSABLE": "OPEN-READ-ONLY",
    "LIVE-OBSERVATION": "BLOCKED-LIVE",
    "EXPLICIT-AUTHORITY": "BLOCKED-AUTHORITY",
    "SEPARATE-MUTATION-GATE": "BLOCKED-GATE",
}
EXPECTED = {
    "M0AI-AUTHORITY": ("M0A-I", {"M0AI-AUTHORITY-GRANT"}),
    "M0AI-BASELINE-FRESHNESS": ("M0A-I", {"M0AI-BASELINE-LIVE"}),
    "M0AI-INSTALLER-IDENTITY": ("M0A-I", {"M0AI-INSTALLER-ARTIFACT", "M0AI-INSTALLER-CREDENTIAL"}),
    "M0AI-EXACT-OBJECT-SUBMISSION": ("M0A-I", {"M0AI-SUBMISSION-INTEGRITY"}),
    "M0AI-CONTROLLER-RBAC-ACCEPTANCE": ("M0A-I", {"M0AI-RBAC-ANALYSIS", "M0AI-RBAC-SECURITY-DECISION"}),
    "M0AI-COMPATIBILITY": ("M0A-I", {"M0AI-COMPATIBILITY-EVIDENCE", "M0AI-COMPATIBILITY-CURRENT-TUPLE"}),
    "M0AI-OBSERVERS-EVIDENCE": ("M0A-I", {"M0AI-OBSERVER-ASSIGNMENT", "M0AI-EVIDENCE-DESTINATION-LIVE"}),
    "M0AI-RECOVERY": ("M0A-I", {"M0AI-RECOVERY-EVIDENCE-LIVE", "M0AI-RECOVERY-AUTHORITY"}),
    "M0BI-AUTHORITY-PLACEMENT": ("M0B-I", {"M0BI-INSTALLATION-AUTHORITY", "M0BI-PLACEMENT-AUTHORITY"}),
    "M0BI-BASELINE-CAPACITY": ("M0B-I", {"M0BI-BASELINE-LIVE", "M0BI-CAPACITY-TOPOLOGY-LIVE"}),
    "M0BI-SOURCE-MATERIALIZATION": ("M0B-I", {"M0BI-SOURCE-MATERIALIZATION-VERIFY"}),
    "M0BI-INSTALLER-IDENTITY": ("M0B-I", {"M0BI-INSTALLER-ARTIFACT", "M0BI-INSTALLER-CREDENTIAL"}),
    "M0BI-EXACT-OBJECT-SUBMISSION": ("M0B-I", {"M0BI-SUBMISSION-INTEGRITY"}),
    "M0BI-CONTROLLER-RBAC-SECURITY": ("M0B-I", {"M0BI-RBAC-ANALYSIS", "M0BI-RBAC-SECURITY-DECISION"}),
    "M0BI-IMAGE-COMPATIBILITY": ("M0B-I", {"M0BI-IMAGE-COMPATIBILITY-EVIDENCE", "M0BI-COMPATIBILITY-CURRENT-TUPLE"}),
    "M0BI-OBSERVERS-EVIDENCE": ("M0B-I", {"M0BI-OBSERVER-ASSIGNMENT", "M0BI-EVIDENCE-DESTINATION-LIVE"}),
    "M0BI-RECOVERY": ("M0B-I", {"M0BI-RECOVERY-EVIDENCE-LIVE", "M0BI-RECOVERY-AUTHORITY"}),
}


def _expect(actual: Any, expected: Any, claim: str) -> None:
    if actual != expected:
        raise V1.HarnessError(f"installation closure {claim} mismatch")


def _resolve(matrix_path: Path, requested: str) -> Path:
    candidate = (matrix_path.parent / requested).resolve()
    if SPIKE.resolve() not in candidate.parents or not candidate.is_file():
        raise V1.HarnessError(f"installation closure reference missing or outside spike root: {requested}")
    return candidate


def _indexed(items: list[dict[str, Any]], claim: str) -> dict[str, dict[str, Any]]:
    result = {item.get("id"): item for item in items}
    if None in result or len(result) != len(items):
        raise V1.HarnessError(f"installation closure {claim} contains missing or duplicate IDs")
    return result


def validate(document: dict[str, Any], matrix_path: Path) -> str:
    schema = json.loads((HERE / "installation-closure-v1.schema.json").read_text())
    V1.normalize(document, schema)
    spec = document["spec"]
    _expect(spec["state"], "READ-ONLY-CLASSIFIED", "state")

    authorization = spec["authorization"]
    _expect(authorization["decision"], "NO-GO", "decision")
    for field in ("mutationAuthorized", "m0aInstallationGranted", "m0bInstallationGranted", "go1Granted"):
        _expect(authorization[field], False, f"authorization {field}")

    source_blockers: dict[str, set[str]] = {}
    for source_name, expected_digest in SOURCE_DIGESTS.items():
        claim = spec["sources"][source_name]
        source_path = _resolve(matrix_path, claim["path"])
        _expect(claim["digest"], expected_digest, f"{source_name} declared digest")
        _expect(V1.sha256_bytes(source_path.read_bytes()), expected_digest, f"{source_name} raw digest")
        source = V1.read_yaml_or_json(source_path)["spec"]
        gate = source["authorityBoundary"]["gate"]
        source_blockers[gate] = {item["id"] for item in source["preInstallationRequirements"]}
        if any(item["status"] != "BLOCKED" for item in source["preInstallationRequirements"]):
            raise V1.HarnessError(f"installation closure {source_name} source is not fully blocked")

    _expect(source_blockers["M0A-I"], {item for item, (gate, _) in EXPECTED.items() if gate == "M0A-I"}, "M0a-I source blocker coverage")
    _expect(source_blockers["M0B-I"], {item for item, (gate, _) in EXPECTED.items() if gate == "M0B-I"}, "M0b-I source blocker coverage")

    classes = spec["classes"]
    _expect(set(classes), set(CLASS_STATUS), "class membership")
    for class_name, status in CLASS_STATUS.items():
        _expect(classes[class_name]["requiredStatus"], status, f"{class_name} status mapping")

    blockers = _indexed(spec["blockers"], "blockers")
    _expect(set(blockers), set(EXPECTED), "blocker membership")
    all_obligations: dict[str, dict[str, Any]] = {}
    for blocker_id, blocker in blockers.items():
        expected_gate, expected_obligations = EXPECTED[blocker_id]
        _expect(blocker["gate"], expected_gate, f"{blocker_id} gate")
        _expect(blocker["sourceStatus"], "BLOCKED", f"{blocker_id} source status")
        obligations = _indexed(blocker["obligations"], f"{blocker_id} obligations")
        _expect(set(obligations), expected_obligations, f"{blocker_id} obligation membership")
        duplicate = set(all_obligations) & set(obligations)
        if duplicate:
            raise V1.HarnessError(f"installation closure obligation appears under multiple blockers: {sorted(duplicate)}")
        all_obligations.update(obligations)

    if len(all_obligations) != 29:
        raise V1.HarnessError("installation closure atomic obligation count differs from 29")
    for obligation_id, obligation in all_obligations.items():
        class_name = obligation["class"]
        if class_name not in CLASS_STATUS:
            raise V1.HarnessError(f"installation closure {obligation_id} has unknown class")
        _expect(obligation["status"], CLASS_STATUS[class_name], f"{obligation_id} class/status")
        if not obligation.get("claim"):
            raise V1.HarnessError(f"installation closure {obligation_id} has no closure claim")

    counts = Counter(item["class"] for item in all_obligations.values())
    _expect(dict(counts), {"EXPLICIT-AUTHORITY": 9, "LIVE-OBSERVATION": 9, "OFFLINE-CLOSABLE": 9, "SEPARATE-MUTATION-GATE": 2}, "class counts")
    summary = spec["summary"]
    _expect((summary["sourceBlockers"], summary["atomicObligations"]), (17, 29), "summary totals")
    _expect(summary["byClass"], dict(counts), "summary class counts")
    offline_ids = {item_id for item_id, item in all_obligations.items() if item["class"] == "OFFLINE-CLOSABLE"}
    if len(spec["nextReadOnlyCandidates"]) != len(set(spec["nextReadOnlyCandidates"])):
        raise V1.HarnessError("installation closure next read-only candidates contain duplicates")
    _expect(set(spec["nextReadOnlyCandidates"]), offline_ids, "next read-only candidate membership")

    rules = " ".join(spec["rules"]).lower()
    for phrase in ("does not close", "all of its atomic obligations", "may not create", "separate mutation gate", "cannot inherit", "no-go"):
        if phrase not in rules:
            raise V1.HarnessError(f"installation closure safety rule missing: {phrase}")

    return V1.sha256_bytes(matrix_path.read_bytes())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--matrix", type=Path, required=True)
    parser.add_argument("--digest-file", type=Path)
    args = parser.parse_args()
    try:
        digest = validate(V1.read_yaml_or_json(args.matrix), args.matrix.resolve())
        if args.digest_file:
            expected = args.digest_file.read_text().split()[0]
            _expect(digest.removeprefix("sha256:"), expected, "raw matrix digest")
        print(digest)
        return 0
    except (V1.HarnessError, OSError, ValueError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
