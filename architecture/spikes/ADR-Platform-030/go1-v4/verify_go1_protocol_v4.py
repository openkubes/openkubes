#!/usr/bin/env python3
"""Fail-closed verifier for the non-authorizing OK-141 GO-1 v4 protocol."""

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


V4 = _load("ok141_phase_r_v4_go1_v4", HARNESS / "ok141_phase_r_v4.py")
V1 = V4.V1

HISTORICAL_DIGEST = "sha256:9a8c62d09bc8cdd86b2488aed0e1cf43846321f37329cefe25fb9e260e1185fc"
PARTITION_DIGEST = "sha256:a12a5e30f5bd5479d502f0dbf80e709e14216702ba804f986afcb408f0c32be9"
FIXTURE = "sha256:a2ae3437645db5a83426b89d36d00693d2600e4ef20dc1aba2650dcda7f936f6"
R = "sha256:636fe23404ac53109f44d6346534dcf1367ae91c572d5e18bd32cd0a3128a16e"
E = "sha256:2a849d69e9c64344e907c1bce3bb1abf3d8f77217377081a5be055d62c213300"
P = "sha256:b0f25c639a45d895b889997f5ecc2325db45dd5d51b0684998c94d5e17bd47bf"
PHASES = {"G0", "G1", "G2", "G3", "G4", "G5"}


def _expect(actual: Any, expected: Any, claim: str) -> None:
    if actual != expected:
        raise V1.HarnessError(f"GO-1 v4 {claim} mismatch")


def _resolve(protocol_path: Path, requested: str) -> Path:
    candidate = (protocol_path.parent / requested).resolve()
    if SPIKE.resolve() not in candidate.parents or not candidate.is_file():
        raise V1.HarnessError(f"protocol reference missing or outside spike root: {requested}")
    return candidate


def _indexed(items: list[dict[str, Any]], claim: str) -> dict[str, dict[str, Any]]:
    result = {item.get("id"): item for item in items}
    if None in result or len(result) != len(items):
        raise V1.HarnessError(f"GO-1 v4 {claim} contains missing or duplicate IDs")
    return result


def _partition_projection(item: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    return {field: item[field] for field in fields}


def validate(document: dict[str, Any], protocol_path: Path) -> str:
    schema = json.loads((HERE / "go1-protocol-v4.schema.json").read_text())
    V1.normalize(document, schema)
    spec = document["spec"]
    _expect(spec["protocolState"], "BLOCKED", "protocol state")

    historical = spec["historicalProtocol"]
    historical_path = _resolve(protocol_path, historical["path"])
    _expect(V1.sha256_bytes(historical_path.read_bytes()), HISTORICAL_DIGEST, "historical protocol raw digest")
    _expect(historical["draftDigest"], HISTORICAL_DIGEST, "historical protocol declared digest")

    partition_claim = spec["gatePartition"]
    partition_path = _resolve(protocol_path, partition_claim["path"])
    _expect(V1.sha256_bytes(partition_path.read_bytes()), PARTITION_DIGEST, "gate partition raw digest")
    _expect(partition_claim["digest"], PARTITION_DIGEST, "gate partition declared digest")
    partition = V1.read_yaml_or_json(partition_path)["spec"]
    _expect(partition_claim["version"], partition["version"], "gate partition version")
    _expect(partition["authorization"]["decision"], "NO-GO", "partition authorization")

    fixture_claim = spec["fixture"]
    _expect(
        (fixture_claim["fixtureDigest"], fixture_claim["R"], fixture_claim["E"], fixture_claim["P"]),
        (FIXTURE, R, E, P),
        "fixture identity",
    )
    fixture_path = _resolve(protocol_path, fixture_claim["path"])
    _expect(V4.validate(V1.read_yaml_or_json(fixture_path), HARNESS), FIXTURE, "verified fixture")

    authorization = spec["authorization"]
    _expect(authorization["decision"], "NO-GO", "decision")
    _expect(authorization["mutationAuthorized"], False, "mutation authority")
    _expect(authorization["goGranted"], False, "GO grant")
    for field in ("grantID", "authorizedProtocolDigest", "decidedAt"):
        _expect(authorization[field], None, f"authorization {field}")

    gates = _indexed(spec["installationGates"], "installation gates")
    partition_gates = _indexed(partition["installationGates"], "partition installation gates")
    _expect(gates, partition_gates, "installation gate projection")
    if any(
        gate["status"] != "NOT-GRANTED"
        or gate["mayAuthorizeTargetConvergence"] is not False
        or gate["mayAuthorizeGO1"] is not False
        for gate in gates.values()
    ):
        raise V1.HarnessError("GO-1 v4 installation gate exceeds installation-only authority")

    pre_go = _indexed(spec["preGoRequirements"], "pre-GO requirements")
    partition_pre_go = _indexed(partition["preGoRequirements"], "partition pre-GO requirements")
    expected_pre_go = {
        item_id: _partition_projection(item, ("id", "sourceBlockers", "status", "requiredBefore"))
        for item_id, item in partition_pre_go.items()
    }
    _expect(pre_go, expected_pre_go, "pre-GO projection")
    if any(item["status"] != "BLOCKED" or item["requiredBefore"] != "GO1-DECISION" for item in pre_go.values()):
        raise V1.HarnessError("GO-1 v4 pre-GO requirements are not fail-closed")

    runtime = _indexed(spec["runtimeObligations"], "runtime obligations")
    partition_runtime = _indexed(partition["runtimeObligations"], "partition runtime obligations")
    expected_runtime = {
        item_id: _partition_projection(
            item,
            ("id", "sourceBlockers", "phase", "status", "mayBeClosedBeforeRuntime", "onFailure"),
        )
        for item_id, item in partition_runtime.items()
    }
    _expect(runtime, expected_runtime, "runtime projection")
    for item in runtime.values():
        if item["status"] != "PENDING-RUNTIME" or item["phase"] not in {"G2", "G3", "G4", "G5"}:
            raise V1.HarnessError("GO-1 v4 runtime obligation was closed early or assigned outside G2-G5")
        if item["mayBeClosedBeforeRuntime"] is not False or item["onFailure"] != "STOP-NOT-SUCCESS":
            raise V1.HarnessError("GO-1 v4 runtime obligation does not fail closed")

    deferred = _indexed(spec["deferredScenarios"], "deferred scenarios")
    partition_deferred = _indexed(partition["deferredScenarios"], "partition deferred scenarios")
    _expect(deferred, partition_deferred, "deferred-scenario projection")
    if any(item["includedInGO1"] is not False for item in deferred.values()):
        raise V1.HarnessError("GO-1 v4 includes a deferred scenario")

    submission = spec["submission"]
    _expect(submission["operation"], "ApplyReviewedObjectSet", "semantic submission operation")
    _expect(submission["enabled"], False, "submission state")
    _expect(submission["freeFormShellEndpoint"], False, "shell boundary")
    groups = _indexed(submission["groups"], "submission groups")
    expected_groups = {
        "provider-prerequisites": ("ok-infra", 3, "sha256:7482633570ad5a6cfe4a738d8f116367d013af4523398c79997fb00d404d1a37", False),
        "capi-lifecycle": ("ok-mgmt", 8, "sha256:78bc25624dd52c172590c2d7fdef0df16c20459fe4464090a4190113e3a7cabe", True),
    }
    _expect(set(groups), set(expected_groups), "submission group membership")
    for item_id, group in groups.items():
        expected = expected_groups[item_id]
        actual = (group["targetPlane"], group["objectCount"], group["objectSetDigest"], group["capiLifecycleObjectsAllowed"])
        _expect(actual, expected, f"{item_id} authority boundary")
        _expect(group["enabled"], False, f"{item_id} state")

    phases = _indexed(spec["phases"], "phases")
    _expect(set(phases), PHASES, "phase membership")
    if any(phase["enabled"] is not False for phase in phases.values()):
        raise V1.HarnessError("GO-1 v4 phase enabled without authorization")
    if {item_id for item_id, phase in phases.items() if phase["mutating"]} != {"G1"}:
        raise V1.HarnessError("GO-1 v4 G1 is not the sole prospective mutating phase")

    acceptance = spec["acceptance"]
    _expect(acceptance["allHistoricalBlockersMustBeClosedBeforeGoDecision"], False, "historical blocker rule")
    _expect(acceptance["successRequiresAllRuntimeObligations"], True, "runtime acceptance rule")
    _expect(acceptance["executorExitIsLifecycleSuccess"], False, "executor success boundary")
    _expect(acceptance["historicalSuccessIsCurrentProof"], False, "historical evidence boundary")
    if any("all blockers" in item.lower() for item in spec["preconditions"]):
        raise V1.HarnessError("GO-1 v4 retained the historical all-blockers-before-GO contradiction")

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
            _expect(digest.removeprefix("sha256:"), expected, "raw draft digest")
        print(digest)
        return 0
    except (V1.HarnessError, OSError, ValueError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
