#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import yaml


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
HARNESS = SPIKE / "harness"
PROTOCOL = HERE / "go1-protocol-v5.yaml"
DIGEST = HERE / "go1-protocol-v5.sha256"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


V4 = load_module("ok141_phase_r_v4_go1_v5", HARNESS / "ok141_phase_r_v4.py")
V1 = V4.V1
FIXTURE = "sha256:a2ae3437645db5a83426b89d36d00693d2600e4ef20dc1aba2650dcda7f936f6"
R = "sha256:636fe23404ac53109f44d6346534dcf1367ae91c572d5e18bd32cd0a3128a16e"
E = "sha256:2a849d69e9c64344e907c1bce3bb1abf3d8f77217377081a5be055d62c213300"
P = "sha256:b0f25c639a45d895b889997f5ecc2325db45dd5d51b0684998c94d5e17bd47bf"
PRIOR_V4 = "sha256:2718d719c322190e36036f98730edcb9aaa679c434fb04f151f7f24fc2626705"
M0A_CLOSURE = "sha256:5b445b91f16f1b791c28d637e84d65c5b5c0bb5d05214aa0968341b373c441b0"
M0A_READINESS = "sha256:ec5457aba5729a45973dbf276f6fef324da782cef718469e2e81d59143b91bc5"
HCP = "sha256:7fd0a0831ddccac1b2ca4beb3f5ca968e48ba446de104876897180a768e257fb"
M0B_CLOSURE = "sha256:48d9d43c1c51338982a6143d7e6f04e77256682424172531ce0cdb224355f8ba"
BRIDGE = "sha256:f219c5d1e0524db317fb8c807b2083198f19e39cf684ba9eead0bbefe605d924"
RUNTIME_TEMPLATE = "sha256:a03353ace0cfed9c800dcf0972614a91f20160b19631102659ffe4f7c46b8da2"
TARGET_ACCESS = "sha256:aeb7d1f65a1553bf8b004f0789f705d3c70b330d878bf6032b410491571fe29a"
APPLICATION_RAW = "sha256:7738d9501c0b19d26b51111d818251d6308994b51678aa6a9322ef54f7567392"
APPLICATION_SEMANTIC = "sha256:2502e8ec4310004d26bb7ec89cf5484d4cd301ff4385b888a22c724d3b7c2921"
PROJECTION_MANIFEST = "sha256:73d36ce5f89508f7cbea4c78de452291b7e8708d7cb50041fb464f38a7e3fafe"
HCP_MANIFEST = "sha256:b8d600c542c97dc8652429e12487ecce922d73de9785505457a8f653833e75f9"
HCP_CHART = "sha256:21c43cf53841f9ab0375047d95aa4c64051ea52bbd2c679416e6408f5f1c9179"
PLATFORM_SOURCE = "b5f7be6a7ddab798f31f32197fcbb9e86a9798b6"


class VerificationError(ValueError):
    pass


def expect(actual: Any, expected: Any, context: str) -> None:
    if actual != expected:
        raise VerificationError(f"{context}: expected {expected!r}, got {actual!r}")


def sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def resolve(protocol_path: Path, requested: str) -> Path:
    path = (protocol_path.parent / requested).resolve()
    if SPIKE.resolve() not in path.parents or not path.is_file():
        raise VerificationError(f"reference missing or outside spike root: {requested}")
    return path


def documents(path: Path) -> list[dict[str, Any]]:
    return [item for item in yaml.load_all(path.read_text(), Loader=V1.UniqueKeyLoader) if item]


def contains_placeholder(value: Any) -> bool:
    if isinstance(value, str):
        return value.startswith("RUNTIME-")
    if isinstance(value, list):
        return any(contains_placeholder(item) for item in value)
    if isinstance(value, dict):
        return any(contains_placeholder(item) for item in value.values())
    return False


def validate(document: dict[str, Any], protocol_path: Path) -> str:
    schema = json.loads((HERE / "go1-protocol-v5.schema.json").read_text())
    V1.normalize(document, schema)
    spec = document["spec"]
    expect(spec["protocolState"], "BLOCKED", "protocol state")
    auth = spec["authorization"]
    expect(auth["decision"], "NO-GO", "authorization decision")
    expect(auth["grantIDs"], [], "grant IDs")
    expect(auth["authorizedProtocolDigest"], None, "authorized digest")
    if any(value for key, value in auth.items() if key.endswith("Granted")):
        raise VerificationError("every grant must remain false")

    fixture_claim = spec["fixture"]
    expect(
        (fixture_claim["fixtureDigest"], fixture_claim["R"], fixture_claim["E"], fixture_claim["P"]),
        (FIXTURE, R, E, P),
        "fixture identity",
    )
    fixture_path = resolve(protocol_path, fixture_claim["path"])
    expect(V4.validate(V1.read_yaml_or_json(fixture_path), HARNESS), FIXTURE, "fixture verification")
    supersedes = spec["supersedesForFutureExecution"]
    prior = resolve(protocol_path, supersedes["protocol"])
    expect(sha(prior), PRIOR_V4, "prior v4 digest")
    expect(supersedes["digest"], PRIOR_V4, "prior v4 binding")
    expect(supersedes["historicalEvidencePreserved"], True, "historical preservation")

    scope = spec["scope"]
    expect(scope["cluster"]["workerReplicas"], 1, "worker count")
    boundary = scope["maximumBoundary"]
    expect(boundary["wallClockMinutes"], 120, "wall clock")
    expect(
        boundary["lifecycleEnablementMinutes"] + boundary["runtimePauseDecisionMinutes"] + boundary["platformAndClosureMinutes"],
        120,
        "stage budget sum",
    )
    expect((boundary["lifecycleSubmissionObjects"], boundary["hcpObjects"], boundary["targetAccessObjects"], boundary["registrationObjects"], boundary["platformApplications"]), (11, 1, 8, 2, 3), "object bounds")

    lifecycle = spec["lifecycleSubmission"]
    expect(lifecycle["enabled"], False, "lifecycle submission")
    expect(lifecycle["freeFormShellEndpoint"], False, "shell boundary")
    expected_groups = {
        "provider-prerequisites": ("ok-infra", 3, "sha256:7482633570ad5a6cfe4a738d8f116367d013af4523398c79997fb00d404d1a37", False),
        "capi-lifecycle": ("ok-mgmt", 8, "sha256:78bc25624dd52c172590c2d7fdef0df16c20459fe4464090a4190113e3a7cabe", True),
    }
    expect({item["id"] for item in lifecycle["groups"]}, set(expected_groups), "lifecycle groups")
    for group in lifecycle["groups"]:
        plane, count, digest, capi_allowed = expected_groups[group["id"]]
        expect((group["targetPlane"], group["objectCount"], group["objectSetDigest"], group["capiLifecycleObjectsAllowed"], group["enabled"]), (plane, count, digest, capi_allowed, False), f"{group['id']} boundary")
        items = documents(resolve(protocol_path, group["path"]))
        expect(len(items), count, f"{group['id']} count")
        expect(V1.semantic_revision(items), digest, f"{group['id']} semantic digest")
        if any(item.get("metadata", {}).get("annotations", {}).get("openkubes.io/intent-revision") != R for item in items):
            raise VerificationError(f"{group['id']} does not carry current R")
    projection = resolve(protocol_path, lifecycle["correlation"]["projectionManifestPath"])
    expect(sha(projection), PROJECTION_MANIFEST, "projection manifest digest")
    expect(lifecycle["correlation"]["projectionManifestDigest"], PROJECTION_MANIFEST, "projection manifest binding")

    enablement = spec["enablement"]
    closure = resolve(protocol_path, enablement["readinessEvidence"]["path"])
    expect(sha(closure), M0A_CLOSURE, "M0a closure digest")
    expect(enablement["readinessEvidence"]["digest"], M0A_CLOSURE, "M0a closure binding")
    expect(yaml.safe_load(closure.read_text())["spec"]["state"], "CAAPH-CONTROL-PLANE-READY", "M0a closure state")
    readiness = resolve(protocol_path, enablement["currentReadinessCandidate"]["path"])
    expect(sha(readiness), M0A_READINESS, "M0a readiness digest")
    expect(enablement["currentReadinessCandidate"]["digest"], M0A_READINESS, "M0a readiness binding")
    hcp_path = resolve(protocol_path, enablement["hcpCandidate"]["path"])
    expect(sha(hcp_path), HCP, "HCP digest")
    expect(enablement["hcpCandidate"]["digest"], HCP, "HCP binding")
    expect(enablement["hcpCandidate"]["objectCount"], 1, "HCP object count")
    expect(enablement["hcpCandidate"]["ociManifestDigest"], HCP_MANIFEST, "HCP OCI manifest")
    expect(enablement["hcpCandidate"]["chartContentDigest"], HCP_CHART, "HCP chart content")
    expect(enablement["hcpCandidate"]["submitEnabled"], False, "HCP submit")
    hcp = yaml.safe_load(hcp_path.read_text())
    annotations = hcp["metadata"]["annotations"]
    expect((annotations["openkubes.io/intent-revision"], annotations["openkubes.io/enablement-revision"], annotations["openkubes.io/execution-fixture"]), (R, E, FIXTURE), "HCP carriers")
    expect(hcp["spec"]["repoURL"], "oci://quay.io/cilium/charts", "HCP repository")
    if "registry.invalid" in hcp_path.read_text() or hcp["spec"]["clusterSelector"]["matchLabels"] != {"openkubes.io/type": "talos", "openkubes.io/provider": "kubevirt"}:
        raise VerificationError("HCP source or selector is not executable candidate v4")

    pause = spec["runtimePause"]
    expect(pause["state"], "BLOCKED-NOT-ENTERED", "runtime pause state")
    expect(pause["automaticAdvanceAllowed"], False, "automatic pause advance")
    expect(pause["maximumDecisionMinutes"], 15, "runtime decision budget")
    runtime_template = resolve(protocol_path, pause["runtimeBinding"]["templatePath"])
    expect(sha(runtime_template), RUNTIME_TEMPLATE, "runtime template digest")
    expect(pause["runtimeBinding"]["templateDigest"], RUNTIME_TEMPLATE, "runtime template binding")
    expect(pause["runtimeBinding"]["completedArtifactDigest"], None, "runtime artifact digest")
    template = yaml.safe_load(runtime_template.read_text())
    if not contains_placeholder(template) or any(template["spec"]["authorization"].values()):
        raise VerificationError("runtime template must remain placeholder-bound and unauthorized")

    platform = spec["platform"]
    m0b_closure = resolve(protocol_path, platform["installationClosure"]["path"])
    expect(sha(m0b_closure), M0B_CLOSURE, "M0b closure digest")
    expect(platform["installationClosure"]["digest"], M0B_CLOSURE, "M0b closure binding")
    m0b_spec = yaml.safe_load(m0b_closure.read_text())["spec"]
    expect(m0b_spec["conclusions"]["m0bInstallationComplete"], True, "M0b installation")
    expect(m0b_spec["conclusions"]["m0bTargetRegistrationComplete"], False, "M0b target registration")
    bridge = resolve(protocol_path, platform["registrationBridge"]["path"])
    expect(sha(bridge), BRIDGE, "bridge digest")
    expect(platform["registrationBridge"]["digest"], BRIDGE, "bridge binding")
    expect(platform["registrationBridge"]["executeEnabled"], False, "bridge execution")
    target_access = resolve(protocol_path, platform["targetAccess"]["path"])
    expect(sha(target_access), TARGET_ACCESS, "target access digest")
    expect(platform["targetAccess"]["digest"], TARGET_ACCESS, "target access binding")
    expect(len(documents(target_access)), 8, "target access count")
    expect(platform["targetAccess"]["applyEnabled"], False, "target access apply")
    apps_path = resolve(protocol_path, platform["applications"]["path"])
    expect(sha(apps_path), APPLICATION_RAW, "Application raw digest")
    expect(platform["applications"]["rawDigest"], APPLICATION_RAW, "Application raw binding")
    apps = documents(apps_path)
    expect(len(apps), 3, "Application count")
    expect(V1.semantic_revision(apps), APPLICATION_SEMANTIC, "Application semantic digest")
    expect(platform["applications"]["semanticDigest"], APPLICATION_SEMANTIC, "Application semantic binding")
    expect(platform["applications"]["sourceCommit"], PLATFORM_SOURCE, "Application source binding")
    expect(platform["applications"]["submitEnabled"], False, "Application submit")
    if any(item["spec"]["project"] != "openkubes-disposable" or item["spec"]["source"]["targetRevision"] != PLATFORM_SOURCE for item in apps):
        raise VerificationError("Application project or immutable revision mismatch")

    gates = spec["stageGates"]
    expect([item["id"] for item in gates], ["GO1-L", "M0B-R-TA", "M0B-R-TR", "M0B-R-RM", "GO1-P"], "gate ordering")
    if any(item["state"] != "NOT-GRANTED" or item["grantsLaterStages"] for item in gates):
        raise VerificationError("a stage gate grants authority")
    phases = spec["phases"]
    expect([item["id"] for item in phases], [f"G{index}" for index in range(12)], "phase ordering")
    if any(item["enabled"] for item in phases):
        raise VerificationError("a GO-1 v5 phase is enabled")
    expect([item["id"] for item in phases if item["mutating"]], ["G1", "G3", "G6", "G7", "G9"], "mutating phases")
    blockers = spec["blockers"]
    expected_blockers = {
        "GO1-L-EXECUTOR", "GO1-L-GRANT", "RUNTIME-BINDING", "TARGET-ACCESS-GRANT",
        "TOKEN-MATERIALIZER-GRANTS", "PLATFORM-GRANT", "TARGET-CAPABILITIES",
        "RUNTIME-CAPABILITY", "OBSERVERS-AUTHORITIES", "EVIDENCE-DESTINATION", "RECOVERY-ACCESS",
    }
    expect({item["id"] for item in blockers}, expected_blockers, "blocker inventory")
    allowed_status = {"BLOCKED", "BLOCKED-BY-DESIGN", "BLOCKED-BY-RUNTIME"}
    if len({item["id"] for item in blockers}) != len(blockers) or any(item["status"] not in allowed_status for item in blockers):
        raise VerificationError("blocker set is duplicated or not fail-closed")
    acceptance = spec["acceptance"]
    for key in ("automaticPauseReleaseAllowed",):
        expect(acceptance[key], False, key)
    for key in ("allPreRuntimeBlockersMustCloseBeforeGO1L", "allRuntimeBlockersMustCloseBeforePauseRelease"):
        expect(acceptance[key], True, key)
    return sha(protocol_path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", type=Path, default=PROTOCOL)
    parser.add_argument("--digest-file", type=Path, default=DIGEST)
    args = parser.parse_args()
    try:
        result = validate(V1.read_yaml_or_json(args.protocol), args.protocol.resolve())
        if args.digest_file.exists():
            expect(args.digest_file.read_text().strip(), result, "protocol digest file")
        print(result)
        return 0
    except (VerificationError, V1.HarnessError, KeyError, OSError, TypeError, ValueError, yaml.YAMLError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
