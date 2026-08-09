#!/usr/bin/env python3
"""Fail-closed verifier for the non-authorizing OK-141 GO-1 v3 protocol."""

from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import yaml


HERE = Path(__file__).resolve().parent
HARNESS = HERE.parent / "harness"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


V4 = _load("ok141_phase_r_v4_go1", HARNESS / "ok141_phase_r_v4.py")
V1 = V4.V1
FIXTURE = "sha256:a2ae3437645db5a83426b89d36d00693d2600e4ef20dc1aba2650dcda7f936f6"
R = "sha256:636fe23404ac53109f44d6346534dcf1367ae91c572d5e18bd32cd0a3128a16e"
E = "sha256:2a849d69e9c64344e907c1bce3bb1abf3d8f77217377081a5be055d62c213300"
P = "sha256:b0f25c639a45d895b889997f5ecc2325db45dd5d51b0684998c94d5e17bd47bf"
SOURCE_COMMIT = "b5f7be6a7ddab798f31f32197fcbb9e86a9798b6"
SOURCE_LOCK = "sha256:cdcc6f63b6202a89e90510ddb371cfd3130ff2ebc450336b3ee66e0f1fa85bf5"
FORBIDDEN_HISTORICAL = {
    "sha256:a97e1e31e1f09cc44210679b48130e36edd90709d84ba3ee7b729ba5df82c9ba",
    "sha256:b27bb7c8e959e2c1028fcc0822755caa795ce21432344a64a62474abeb7f9f2b",
    "sha256:a880b119148dbd6e2532932a91b1367d04b042f7a638f891da02b9a1bf9199c7",
    "sha256:d49e844113bdd96868eb9dec2d6672dfcc98ccb7a0bd43f2c6b53aabc2adda62",
    "sha256:17ef42f4187a743fa09f6d955e70811af47763c4f98a4e73735da70055bc8969",
    "sha256:b46911c06ac31ed4755ffa83b0c960fafa0a23cab8442dc9eb1945df927b0665",
    "sha256:67fa2e63bba98d8cc70f680e8df56dea5803c0a0d8c5db81ab78578daacebd9f",
    "sha256:62e4d20fdd352474f4a5d2ea6639d7d63fa494af58b9b4532169bd96437d9f78",
    "sha256:0dcfbe10f271aeb7e82d94fbad0ff2691dec67f69c7452578662df09a650439b",
}
BLOCKERS = {
    "EXECUTOR-IDENTITY", "SUBMISSION-CREDENTIALS", "M0A-INSTALLATION",
    "M0A-CHART-SOURCE", "M0A-PROJECTION", "M0B-PLACEMENT",
    "M0B-REGISTRATION", "M0B-RBAC", "M0B-TARGET-CAPABILITIES",
    "M0B-RUNTIME-CAPABILITY", "OBSERVERS", "HUMAN-AUTHORITIES",
    "EVIDENCE-DESTINATION", "RECOVERY-EVIDENCE",
}


def _expect(actual: Any, expected: Any, claim: str) -> None:
    if actual != expected:
        raise V1.HarnessError(f"GO-1 v3 {claim} mismatch")


def _resolve(protocol_path: Path, requested: str) -> Path:
    root = HERE.parent.resolve()
    candidate = (protocol_path.parent / requested).resolve()
    if root not in candidate.parents or not candidate.is_file():
        raise V1.HarnessError(f"protocol reference missing or outside spike root: {requested}")
    return candidate


def _documents(path: Path) -> list[dict[str, Any]]:
    return [item for item in yaml.load_all(path.read_text(), Loader=V1.UniqueKeyLoader) if item]


def validate(document: dict[str, Any], protocol_path: Path) -> str:
    schema = json.loads((HERE / "go1-protocol-v3.schema.json").read_text())
    V1.normalize(document, schema)
    spec = document["spec"]
    _expect(spec["protocolState"], "BLOCKED", "protocol readiness")
    authorization = spec["authorization"]
    _expect(authorization["decision"], "NO-GO", "decision")
    _expect(authorization["goGranted"], False, "GO grant")
    for field in ("grantID", "authorizedProtocolDigest", "decidedAt"):
        _expect(authorization[field], None, f"authorization {field}")

    fixture_claim = spec["fixture"]
    _expect(fixture_claim["fixtureDigest"], FIXTURE, "FixtureDigest-triple-prime")
    _expect(fixture_claim["R"], R, "R-triple-prime")
    _expect(fixture_claim["E"], E, "E-prime")
    _expect(fixture_claim["P"], P, "P-triple-prime")
    fixture_path = _resolve(protocol_path, fixture_claim["path"])
    fixture = V1.read_yaml_or_json(fixture_path)
    _expect(V4.validate(fixture, HARNESS), FIXTURE, "verified execution fixture")

    encoded = V1.jcs(document)
    leaked = sorted(value for value in FORBIDDEN_HISTORICAL if value in encoded)
    if leaked:
        raise V1.HarnessError("historical R/P/Fixture identity reused by GO-1 v3")

    scope = spec["scope"]
    _expect(scope["cluster"]["workerReplicas"], 1, "worker count")
    _expect(scope["cluster"]["contractNamespace"], "disposable-ok141", "contract namespace")
    _expect(scope["maximumBoundary"]["reviewedSubmissionGroups"], 2, "submission group count")
    _expect(scope["maximumBoundary"]["reviewedObjects"], 11, "reviewed object count")

    submission = spec["submission"]
    _expect(submission["operation"], "ApplyReviewedObjectSet", "semantic operation")
    _expect(submission["freeFormShellEndpoint"], False, "shell boundary")
    _expect(submission["enabled"], False, "submission state")
    groups = submission["groups"]
    expected_groups = {
        "provider-prerequisites": ("ok-infra", 3, "sha256:7482633570ad5a6cfe4a738d8f116367d013af4523398c79997fb00d404d1a37", False),
        "capi-lifecycle": ("ok-mgmt", 8, "sha256:78bc25624dd52c172590c2d7fdef0df16c20459fe4464090a4190113e3a7cabe", True),
    }
    _expect({group["id"] for group in groups}, set(expected_groups), "submission membership")
    for group in groups:
        plane, count, digest, capi_allowed = expected_groups[group["id"]]
        _expect((group["targetPlane"], group["objectCount"], group["objectSetDigest"], group["capiLifecycleObjectsAllowed"]), (plane, count, digest, capi_allowed), f"{group['id']} boundary")
        _expect(group["enabled"], False, f"{group['id']} state")
        documents = _documents(_resolve(protocol_path, group["path"]))
        _expect(len(documents), count, f"{group['id']} object count")
        _expect(V1.semantic_revision(documents), digest, f"{group['id']} object digest")
        if not capi_allowed and any(item.get("apiVersion", "").split("/", 1)[0] in V4.V2.CAPI_GROUPS for item in documents):
            raise V1.HarnessError("CAPI lifecycle object targeted at ok-infra")
        if any(item.get("metadata", {}).get("annotations", {}).get("openkubes.io/intent-revision") != R for item in documents):
            raise V1.HarnessError(f"{group['id']}: missing exact R carrier")

    correlation = submission["correlation"]
    projection_manifest_path = _resolve(protocol_path, correlation["projectionManifestPath"])
    _expect(V1.sha256_bytes(projection_manifest_path.read_bytes()), correlation["projectionManifestDigest"], "projection manifest digest")
    _expect(json.loads(projection_manifest_path.read_text())["R"], R, "projection R")

    mechanisms = spec["mechanisms"]
    _expect(mechanisms["enablement"]["desiredRevision"], E, "Enablement revision")
    _expect(mechanisms["platform"]["desiredRevision"], P, "Platform revision")
    _expect(mechanisms["platform"]["sourceCommit"], SOURCE_COMMIT, "Platform source commit")
    _expect(mechanisms["platform"]["sourceClosureLockDigest"], SOURCE_LOCK, "Platform source closure")
    if "BLOCKED-M0A" not in mechanisms["enablement"]["status"] or "BLOCKED-M0B" not in mechanisms["platform"]["status"]:
        raise V1.HarnessError("M0a/M0b must remain blocked and not granted")
    blockers = spec["blockers"]
    _expect({item.get("id") for item in blockers}, BLOCKERS, "blocker set")
    if len(blockers) != len(BLOCKERS) or any(item.get("status") != "BLOCKED" for item in blockers):
        raise V1.HarnessError("every unique blocker must remain BLOCKED")
    phases = spec["phases"]
    _expect({item.get("id") for item in phases}, {"G0", "G1", "G2", "G3", "G4", "G5"}, "phase membership")
    if any(item.get("enabled") is not False for item in phases):
        raise V1.HarnessError("all T3 phases must remain disabled")
    if [item["id"] for item in phases if item.get("mutating")] != ["G1"]:
        raise V1.HarnessError("G1 must be the only prospective mutating phase")
    if spec["acceptance"].get("allBlockersMustBeClosedBeforeGoDecision") is not True:
        raise V1.HarnessError("GO decision does not fail closed on blockers")
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
