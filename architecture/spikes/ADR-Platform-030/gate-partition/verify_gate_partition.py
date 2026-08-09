#!/usr/bin/env python3
"""Fail-closed verifier for the read-only OK-141 gate partition."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
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


V4 = _load("ok141_phase_r_v4_gate_partition", HARNESS / "ok141_phase_r_v4.py")
V1 = V4.V1

SOURCE_PROTOCOL_DIGEST = "sha256:9a8c62d09bc8cdd86b2488aed0e1cf43846321f37329cefe25fb9e260e1185fc"
FIXTURE_DIGEST = "sha256:a2ae3437645db5a83426b89d36d00693d2600e4ef20dc1aba2650dcda7f936f6"
SOURCE_BLOCKERS = {
    "EXECUTOR-IDENTITY", "SUBMISSION-CREDENTIALS", "M0A-INSTALLATION",
    "M0A-CHART-SOURCE", "M0A-PROJECTION", "M0B-PLACEMENT",
    "M0B-REGISTRATION", "M0B-RBAC", "M0B-TARGET-CAPABILITIES",
    "M0B-RUNTIME-CAPABILITY", "OBSERVERS", "HUMAN-AUTHORITIES",
    "EVIDENCE-DESTINATION", "RECOVERY-EVIDENCE",
}
PRE_GO_IDS = {
    "EXECUTOR-IDENTITY", "SUBMISSION-CREDENTIAL-MODEL", "M0A-I-INSTALLATION",
    "M0A-CHART-SOURCE", "M0A-HCP-PROJECTION", "M0B-I-PLACEMENT",
    "M0B-REGISTRATION-MODEL", "M0B-RBAC-SPEC", "M0B-TARGET-COMPATIBILITY",
    "OBSERVERS", "HUMAN-AUTHORITIES", "EVIDENCE-AND-RECOVERY",
}
RUNTIME_IDS = {
    "G2-LIFECYCLE-IDENTITY", "G3-M0A-TARGET-CORRELATION",
    "G3-ENABLEMENT-CONVERGENCE", "G4-M0B-REGISTRATION-INSTANCE",
    "G4-M0B-RBAC-BINDINGS", "G4-TARGET-CAPABILITIES",
    "G4-PLATFORM-CONVERGENCE", "G5-AGGREGATE-EVIDENCE",
}
DEFERRED_IDS = {
    "CAAPH-RESTART-RETRY-INJECTION", "ARGO-RESTART-RETRY-INJECTION",
    "EXECUTOR-CRASH-INJECTION", "MANUAL-DRIFT-INJECTION",
    "WORKER-FAILURE-INJECTION", "DELETE-AND-FINALIZER",
    "MANAGEMENT-OUTAGE", "BREAK-GLASS-AND-DR",
}


def _expect(actual: Any, expected: Any, claim: str) -> None:
    if actual != expected:
        raise V1.HarnessError(f"gate partition {claim} mismatch")


def _unique_ids(items: list[dict[str, Any]], expected: set[str], claim: str) -> None:
    ids = [item.get("id") for item in items]
    if len(ids) != len(set(ids)):
        raise V1.HarnessError(f"gate partition {claim} contains duplicate IDs")
    _expect(set(ids), expected, f"{claim} membership")


def _resolve(partition_path: Path, requested: str) -> Path:
    candidate = (partition_path.parent / requested).resolve()
    if SPIKE.resolve() not in candidate.parents or not candidate.is_file():
        raise V1.HarnessError(f"partition reference missing or outside spike root: {requested}")
    return candidate


def validate(document: dict[str, Any], partition_path: Path) -> str:
    schema = json.loads((HERE / "gate-partition-v1.schema.json").read_text())
    V1.normalize(document, schema)
    spec = document["spec"]

    authorization = spec["authorization"]
    _expect(spec["state"], "PROPOSED-READ-ONLY", "state")
    _expect(authorization["decision"], "NO-GO", "authorization decision")
    for field in ("mutationAuthorized", "m0aInstallationGranted", "m0bInstallationGranted", "go1Granted"):
        _expect(authorization[field], False, f"authorization {field}")

    source = spec["sourceProtocol"]
    source_path = _resolve(partition_path, source["path"])
    _expect(V1.sha256_bytes(source_path.read_bytes()), SOURCE_PROTOCOL_DIGEST, "source protocol raw digest")
    _expect(source["draftDigest"], SOURCE_PROTOCOL_DIGEST, "source protocol declared digest")
    _expect(source["fixtureDigest"], FIXTURE_DIGEST, "source fixture digest")
    source_document = V1.read_yaml_or_json(source_path)
    _expect(source_document["spec"]["fixture"]["fixtureDigest"], FIXTURE_DIGEST, "source protocol fixture")
    source_blockers = {item["id"] for item in source_document["spec"]["blockers"]}
    _expect(source_blockers, SOURCE_BLOCKERS, "historical source blocker set")

    gates = spec["installationGates"]
    _unique_ids(gates, {"M0A-I", "M0B-I"}, "installation gates")
    for gate in gates:
        _expect(gate["status"], "NOT-GRANTED", f"{gate['id']} status")
        _expect(gate["mayAuthorizeTargetConvergence"], False, f"{gate['id']} target-convergence authority")
        _expect(gate["mayAuthorizeGO1"], False, f"{gate['id']} GO-1 authority")
        if "only" not in gate["scope"]:
            raise V1.HarnessError(f"gate partition {gate['id']} scope is not installation-only")

    pre_go = spec["preGoRequirements"]
    _unique_ids(pre_go, PRE_GO_IDS, "pre-GO requirements")
    if any(item["status"] != "BLOCKED" or item["requiredBefore"] != "GO1-DECISION" for item in pre_go):
        raise V1.HarnessError("every pre-GO requirement must remain BLOCKED before GO1-DECISION")

    runtime = spec["runtimeObligations"]
    _unique_ids(runtime, RUNTIME_IDS, "runtime obligations")
    allowed_phases = {"G2", "G3", "G4", "G5"}
    for item in runtime:
        if item["status"] != "PENDING-RUNTIME":
            raise V1.HarnessError(f"{item['id']}: runtime obligation was prematurely closed")
        if item["phase"] not in allowed_phases:
            raise V1.HarnessError(f"{item['id']}: runtime obligation assigned outside G2-G5")
        _expect(item["mayBeClosedBeforeRuntime"], False, f"{item['id']} pre-runtime closure")
        _expect(item["onFailure"], "STOP-NOT-SUCCESS", f"{item['id']} failure behavior")

    deferred = spec["deferredScenarios"]
    _unique_ids(deferred, DEFERRED_IDS, "deferred scenarios")
    for item in deferred:
        if item["status"] != "DEFERRED-SEPARATE-GATE" or item["includedInGO1"] is not False:
            raise V1.HarnessError(f"{item['id']}: deferred scenario leaked into GO-1")

    covered = {
        blocker
        for item in [*pre_go, *runtime]
        for blocker in item.get("sourceBlockers", [])
    }
    _expect(covered, SOURCE_BLOCKERS, "source blocker coverage")

    required_splits = {
        "M0A-PROJECTION": ({"M0A-HCP-PROJECTION"}, {"G3-M0A-TARGET-CORRELATION"}),
        "M0B-REGISTRATION": ({"M0B-REGISTRATION-MODEL"}, {"G4-M0B-REGISTRATION-INSTANCE"}),
        "M0B-RBAC": ({"M0B-RBAC-SPEC"}, {"G4-M0B-RBAC-BINDINGS"}),
        "M0B-TARGET-CAPABILITIES": ({"M0B-TARGET-COMPATIBILITY"}, {"G4-TARGET-CAPABILITIES"}),
    }
    for blocker, (expected_pre, expected_runtime) in required_splits.items():
        actual_pre = {item["id"] for item in pre_go if blocker in item["sourceBlockers"]}
        actual_runtime = {item["id"] for item in runtime if blocker in item["sourceBlockers"]}
        if not expected_pre <= actual_pre or not expected_runtime <= actual_runtime:
            raise V1.HarnessError(f"source blocker {blocker} is not split across pre-GO and runtime evidence")

    return V1.sha256_bytes(partition_path.read_bytes())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--partition", type=Path, required=True)
    parser.add_argument("--digest-file", type=Path)
    args = parser.parse_args()
    try:
        digest = validate(V1.read_yaml_or_json(args.partition), args.partition.resolve())
        if args.digest_file:
            expected = args.digest_file.read_text().split()[0]
            _expect(digest.removeprefix("sha256:"), expected, "raw partition digest")
        print(digest)
        return 0
    except (V1.HarnessError, OSError, ValueError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
