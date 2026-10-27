#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import yaml


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
DEFAULT = HERE / "go1-protocol-v6.yaml"
DIGEST = HERE / "go1-protocol-v6.sha256"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    assert spec.loader is not None
    spec.loader.exec_module(result)
    return result


SUBMITTER = load_module("ok141_submitter_v3_for_go1_v6", SPIKE / "go1-l-submitter-v3/bounded_go1_l_submitter_v3.py")
MATERIALIZER = load_module("ok141_provider_access_for_go1_v6", SPIKE / "go1-l-provider-access-v1/bounded_provider_access_materializer_v1.py")
V2 = SUBMITTER.V2
V1 = SUBMITTER.V1


class ProtocolError(ValueError):
    pass


def sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def expect(actual: Any, expected: Any, context: str) -> None:
    if actual != expected:
        raise ProtocolError(f"{context}: expected {expected!r}, got {actual!r}")


def resolve(protocol_path: Path, requested: str) -> Path:
    path = (protocol_path.parent / requested).resolve()
    if SPIKE.resolve() not in path.parents or not path.is_file():
        raise ProtocolError(f"reference missing or outside spike root: {requested}")
    return path


def semantic_digest(value: Any) -> str:
    return V1.sha256_bytes(V1.jcs(value).encode())


def validate(value: dict[str, Any], protocol_path: Path = DEFAULT) -> dict[str, Any]:
    expect(value.get("apiVersion"), "test.openkubes.io/v1alpha5", "apiVersion")
    expect(value.get("kind"), "GO1Protocol", "kind")
    spec = value["spec"]
    expect(spec["protocolVersion"], "ok141-go1/v6", "version")
    expect(spec["protocolState"], "BLOCKED", "state")

    auth = spec["authorization"]
    expect(auth["decision"], "NO-GO", "authorization decision")
    boolean_keys = [key for key, item in auth.items() if isinstance(item, bool)]
    if any(auth[key] for key in boolean_keys) or auth["grantIDs"] or auth["authorizedProtocolDigest"] is not None:
        raise ProtocolError("protocol grants authority")

    base_ref = spec["supersedesForFutureExecution"]
    base_path = resolve(protocol_path, base_ref["protocol"])
    expect(sha(base_path), base_ref["digest"], "v5 protocol digest")
    base = V1.read_yaml_or_json(base_path)
    expect(base["spec"]["protocolState"], "BLOCKED", "v5 protocol state")
    expect(base_ref["historicalEvidencePreserved"], True, "v5 evidence preservation")
    expect(base_ref["allowedForFutureExecution"], False, "v5 execution rejection")

    closure_ref = spec["cleanBaseline"]
    closure_path = resolve(protocol_path, closure_ref["path"])
    expect(sha(closure_path), closure_ref["digest"], "clean baseline digest")
    closure = V1.read_yaml_or_json(closure_path)["spec"]
    expect(closure["conclusion"]["cleanBaselineProven"], True, "clean baseline proof")
    expect(closure["conclusion"]["recreationPerformed"], False, "clean baseline history")

    fixture_ref = spec["fixture"]
    fixture_path = resolve(protocol_path, fixture_ref["path"])
    expect(sha(fixture_path), fixture_ref["fileDigest"], "fixture file digest")
    fixture = V1.read_yaml_or_json(fixture_path)
    expect(fixture["fixtureVersion"], fixture_ref["version"], "fixture version")
    expect(fixture["fixtureDigest"], fixture_ref["fixtureDigest"], "FixtureDigest")
    expect(fixture["contract"]["R"], fixture_ref["R"], "R")
    expect(fixture["enablement"]["E"], fixture_ref["E"], "E")
    expect(fixture["platform"]["P"], fixture_ref["P"], "P")
    expect(fixture["authorizationState"], "NO-GO", "fixture authorization")

    mechanisms = spec["mechanisms"]
    submitter_ref = mechanisms["staticSubmitter"]
    submitter_path = resolve(protocol_path, submitter_ref["path"])
    expect(sha(submitter_path), submitter_ref["digest"], "submitter digest")
    submitter = SUBMITTER.load_candidate(submitter_path)
    reviewed = SUBMITTER.validate_candidate(submitter, submitter_path)
    expect(submitter["spec"]["state"], submitter_ref["state"], "submitter state")
    expect(len(reviewed), submitter_ref["operationCount"], "submitter operation count")
    expect(sum(len(item.documents) for item in reviewed.values()), submitter_ref["objectCount"], "submitter object count")

    materializer_ref = mechanisms["providerAccessMaterializer"]
    materializer_path = resolve(protocol_path, materializer_ref["path"])
    expect(sha(materializer_path), materializer_ref["digest"], "materializer digest")
    materializer = MATERIALIZER.load_candidate(materializer_path)
    materializer_spec = MATERIALIZER.validate_candidate(materializer, materializer_path)
    expect(materializer_spec["state"], materializer_ref["state"], "materializer state")
    expect(materializer_spec["submitter"]["digest"], submitter_ref["digest"], "materializer submitter binding")

    for name in ("caaphReadiness", "argoInstallation"):
        ref = mechanisms[name]
        path = resolve(protocol_path, ref["path"])
        expect(sha(path), ref["digest"], f"{name} digest")
        expect(V1.read_yaml_or_json(path)["spec"]["state"], ref["requiredState"], f"{name} state")

    lifecycle = spec["lifecycleSubmission"]
    expect(lifecycle["enabled"], False, "lifecycle enabled")
    expect(lifecycle["staticSubmitterDigest"], submitter_ref["digest"], "lifecycle submitter")
    expect(lifecycle["providerAccessMaterializerDigest"], materializer_ref["digest"], "lifecycle materializer")
    groups = lifecycle["groups"]
    ids = ["provider-prerequisites", "management-namespace", "provider-access-secret", "capi-lifecycle", "helmchartproxy"]
    expect([item["id"] for item in groups], ids, "group order")
    expect([item["order"] for item in groups], [1, 2, 3, 4, 5], "group sequence")
    expect([item["objectCount"] for item in groups], [3, 1, 1, 7, 1], "group counts")
    if any(item["enabled"] for item in groups):
        raise ProtocolError("lifecycle group is enabled")
    submitter_operations = {item["id"]: item for item in submitter["spec"]["operations"]}
    for group in groups:
        if group["executor"] == "staticSubmitter":
            operation = submitter_operations[group["id"]]
            expect(group["targetPlane"], operation["targetPlane"], f"{group['id']} plane")
            expect(group["objectCount"], operation["objectCount"], f"{group['id']} object count")
            expect(group["semanticDigest"], operation["semanticDigest"], f"{group['id']} semantic digest")
            expect(group["payloadDigest"], operation["payloadRawDigest"], f"{group['id']} payload digest")
            expect(group["predecessorEvidenceCount"], operation["predecessorEvidenceCount"], f"{group['id']} predecessor count")
    secret_group = groups[2]
    plan = MATERIALIZER.build_plan(materializer, materializer_path)
    expect(secret_group["executor"], "providerAccessMaterializer", "Secret executor")
    expect(secret_group["objectIdentity"], plan["secretIdentity"], "Secret identity")
    expect(secret_group["predecessorEvidenceCount"], materializer_spec["runtimeGrant"]["predecessorEvidenceCount"], "Secret predecessor count")
    expect(secret_group["secretBytesInProtocolOrEvidenceAllowed"], False, "Secret bytes boundary")
    expect(spec["scope"]["maximumBoundary"]["lifecycleSubmissionObjects"], sum(item["objectCount"] for item in groups[:4]), "lifecycle object total")
    expect(spec["scope"]["maximumBoundary"]["hcpObjects"], groups[4]["objectCount"], "HCP total")

    correlation = lifecycle["correlation"]
    for path_key, digest_key in (("projectionManifestPath", "projectionManifestDigest"), ("authorityMapPath", "authorityMapDigest")):
        path = resolve(protocol_path, correlation[path_key])
        expect(sha(path), correlation[digest_key], f"correlation {path_key}")
    expect(correlation["requireRCarrierOnEveryStaticObject"], True, "static R carriers")
    expect(correlation["dynamicSecretCarrierBoundByMaterializer"], True, "dynamic Secret carrier")

    inherited = spec["inheritedLaterStages"]
    inherited_path = resolve(protocol_path, inherited["sourceProtocol"])
    expect(inherited_path, base_path, "inherited source")
    expect(inherited["sourceDigest"], base_ref["digest"], "inherited source digest")
    selected: dict[str, Any] = {}
    for name, digest in inherited["sections"].items():
        selected[name] = base["spec"][name]
        expect(semantic_digest(selected[name]), digest, f"inherited {name}")
    expect(semantic_digest(selected), inherited["aggregateDigest"], "inherited aggregate")

    expected_phases = [f"G{index}" for index in range(12)]
    expect([item["id"] for item in spec["phases"]], expected_phases, "phase ordering")
    if any(item["enabled"] for item in spec["phases"]):
        raise ProtocolError("protocol phase is enabled")
    expect([item["id"] for item in spec["stageGates"]], ["GO1-L", "GO1-RUNTIME-PAUSE", "M0B-R-TA", "M0B-R-TR", "M0B-R-RM", "GO1-P"], "stage gates")
    if any(item["state"] not in ("NOT-GRANTED", "NOT-ENTERED") for item in spec["stageGates"]):
        raise ProtocolError("stage gate is not closed")
    expect(spec["acceptance"]["processExitIsLifecycleSuccess"], False, "process-exit claim")
    expect(spec["acceptance"]["automaticPauseReleaseAllowed"], False, "pause release")
    return spec


def main() -> int:
    try:
        value = V1.read_yaml_or_json(DEFAULT)
        spec = validate(value, DEFAULT)
        actual = sha(DEFAULT)
        expect(DIGEST.read_text().strip(), actual, "protocol digest file")
        print(json.dumps({
            "protocolDigest": actual,
            "state": spec["protocolState"],
            "fixtureDigest": spec["fixture"]["fixtureDigest"],
            "lifecycleGroups": len(spec["lifecycleSubmission"]["groups"]),
            "lifecycleObjectsBeforeHCP": spec["scope"]["maximumBoundary"]["lifecycleSubmissionObjects"],
            "hcpObjects": spec["scope"]["maximumBoundary"]["hcpObjects"],
            "phasesEnabled": 0,
            "mutationAuthorized": False,
            "clusterContacted": False,
        }, sort_keys=True))
        return 0
    except (KeyError, OSError, ProtocolError, SUBMITTER.SubmitterError, MATERIALIZER.MaterializerError, V2.SubmitterError, TypeError, ValueError, yaml.YAMLError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
