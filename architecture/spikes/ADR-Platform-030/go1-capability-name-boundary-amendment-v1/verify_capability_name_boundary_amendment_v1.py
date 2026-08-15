#!/usr/bin/env python3
"""Fail-closed verifier for the OK-141 capability-name amendment."""

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
from pathlib import Path

import yaml


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
HARNESS = SPIKE / "harness"
SOURCE = SPIKE.parents[3] / "ok-observability"
AMENDMENT = HERE / "capability-name-boundary-amendment-v1.json"
OLD_COMMIT = "b5f7be6a7ddab798f31f32197fcbb9e86a9798b6"
NEW_COMMIT = "c09c18759aeb7526d22106ccb001599f5f06bc4e"
NEW_SCRIPT_DIGEST = "sha256:98f41106b7ddc2f7ecffaca9bd9e3c3584d97ab41b169054d8be91ae9cdfb949"
NEW_LOCK_DIGEST = "sha256:f916900bccb3731636969145d4677dc0e1578cd16ab7cf053fb1afbbf047ce31"
RENDER_INPUT_PATHS = [
    "profiles/ok-observability-standard/Chart.yaml",
    "profiles/ok-observability-standard/values.yaml",
    "profiles/ok-observability-standard/charts",
    "alerting/prometheus-rules.yaml",
    "dashboards/platform-overview-configmap.yaml",
]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


V1 = load_module("ok141_harness_for_capability_boundary_verifier", HARNESS / "ok141_harness.py")


def documents(path: Path) -> list[dict]:
    return [item for item in yaml.load_all(path.read_text(), Loader=V1.UniqueKeyLoader) if item]


def expect(actual, expected, claim: str) -> None:
    if actual != expected:
        raise RuntimeError(f"{claim} mismatch: expected {expected!r}, got {actual!r}")


def strip_target_revision(apps: list[dict]) -> list[dict]:
    result = copy.deepcopy(apps)
    for app in result:
        app["spec"]["source"].pop("targetRevision", None)
    return result


def main() -> None:
    amendment = json.loads(AMENDMENT.read_text())
    expect(amendment["kind"], "CapabilityNameBoundaryAmendment", "kind")
    spec = amendment["spec"]
    expect(spec["authorization"], "NO-GO", "authorization")
    expect(spec["basePlatform"], {
        "profile": "minimal-observability-v8",
        "sourceCommit": OLD_COMMIT,
        "artifactLockDigest": "sha256:cdcc6f63b6202a89e90510ddb371cfd3130ff2ebc450336b3ee66e0f1fa85bf5",
        "capabilityScriptDigest": "sha256:bd68328f35de960bfc291880dd7f85274021c0cce8d7b69ccecde0a459ead648",
    }, "base Platform")
    platform = spec["platform"]
    profile = json.loads((SPIKE / platform["profilePath"]).read_text())
    apps = documents(SPIKE / platform["applicationsPath"])
    values = V1.read_yaml_or_json(SPIKE / platform["providerValuesPath"])
    expect(profile["format"], "ok141-platform-profile/v8", "profile format")
    expect(profile["profile"], "minimal-observability-v9", "profile name")
    expect(profile["capabilityCheck"]["executable"]["digest"], NEW_SCRIPT_DIGEST, "script digest")
    expect(V1.semantic_revision(profile), platform["P"], "P")
    expect(V1.semantic_revision(apps), platform["applicationSetDigest"], "Application set")
    expect(V1.semantic_revision(values), platform["providerValuesDigest"], "Provider Values")

    by_name = {app["metadata"]["name"]: app for app in apps}
    leaves = {leaf["name"]: leaf for leaf in profile["requiredApplications"]}
    expect(set(by_name), set(leaves), "Application membership")
    expect({leaf["source"]["commit"] for leaf in leaves.values()}, {NEW_COMMIT}, "profile source revisions")
    expect({app["spec"]["source"]["targetRevision"] for app in apps}, {NEW_COMMIT}, "Application target revisions")
    for name, leaf in leaves.items():
        expect(leaf["applicationDigest"], V1.semantic_revision(by_name[name]), f"{name} digest")
    lock = leaves["disposable-ok141-observability-core"]["sourceArtifacts"]["sourceClosure"]["artifactLock"]
    expect(lock["digest"], NEW_LOCK_DIGEST, "artifact lock digest")

    contract = V1.read_yaml_or_json(SPIKE / spec["contract"]["path"])
    schema = json.loads((SPIKE / spec["contract"]["schemaPath"]).read_text())
    normalized = V1.normalize(contract, schema)
    V1.validate_contract_semantics(normalized)
    expect(normalized["spec"]["platform"], {"profile": profile["profile"], "revision": platform["P"]}, "contract Platform identity")
    expect(V1.semantic_revision(V1.semantic_projection(normalized, schema)), spec["contract"]["R"], "R")

    fixture = copy.deepcopy(spec)
    declared = fixture.pop("fixtureDigest")
    fixture.pop("identities")
    expect(V1.semantic_revision(fixture), declared, "FixtureDigest")
    expect(spec["identities"], {"P": platform["P"], "R": spec["contract"]["R"], "FixtureDigest": declared}, "identity summary")

    old_profile = json.loads((HARNESS / "profiles/platform/minimal-observability-v8/profile.json").read_text())
    old_apps = documents(HARNESS / "profiles/platform/minimal-observability-v8/applications.yaml")
    expect(V1.semantic_revision(old_profile), spec["base"]["P"], "historical v8 P")
    expect(strip_target_revision(old_apps), strip_target_revision(apps), "Application spec delta")
    expect(
        V1.read_yaml_or_json(HARNESS / "profiles/platform/minimal-observability-v8/provider-values.yaml"),
        values,
        "Provider Values preservation",
    )
    if platform["P"] == spec["base"]["P"]:
        raise RuntimeError("corrected capability identity did not change P")

    old_script = copy.deepcopy(profile)
    old_script["capabilityCheck"]["executable"]["digest"] = "sha256:bd68328f35de960bfc291880dd7f85274021c0cce8d7b69ccecde0a459ead648"
    if V1.semantic_revision(old_script) == platform["P"]:
        raise RuntimeError("old-script negative control did not change P")
    mutated = copy.deepcopy(profile)
    mutated["capabilityCheck"]["parameters"]["alertAcceptance"] = "pending-or-firing"
    if V1.semantic_revision(mutated) == platform["P"]:
        raise RuntimeError("profile mutation negative control did not change P")
    for bad_revision, claim in ((OLD_COMMIT, "stale"), ("main", "mutable")):
        bad_apps = copy.deepcopy(apps)
        bad_apps[0]["spec"]["source"]["targetRevision"] = bad_revision
        if all(app["spec"]["source"]["targetRevision"] == NEW_COMMIT for app in bad_apps):
            raise RuntimeError(f"{claim} revision negative control was accepted")
        bad_by_name = {app["metadata"]["name"]: app for app in bad_apps}
        if all(
            leaves[name]["applicationDigest"] == V1.semantic_revision(bad_by_name[name])
            for name in leaves
        ):
            raise RuntimeError(f"{claim} Application digest negative control was accepted")

    if (SOURCE / ".git").exists():
        expect(
            V1.sha256_bytes(subprocess.run(
                ["git", "-C", str(SOURCE), "show", f"{NEW_COMMIT}:tests/contract-test.sh"],
                check=True, capture_output=True,
            ).stdout),
            NEW_SCRIPT_DIGEST,
            "authoritative capability script",
        )
        expect(
            V1.sha256_bytes(subprocess.run(
                ["git", "-C", str(SOURCE), "show", f"{NEW_COMMIT}:profiles/ok-observability-standard/artifact-lock.json"],
                check=True, capture_output=True,
            ).stdout),
            NEW_LOCK_DIGEST,
            "authoritative artifact lock",
        )
        unchanged = subprocess.run(
            ["git", "-C", str(SOURCE), "diff", "--quiet", OLD_COMMIT, NEW_COMMIT, "--", *RENDER_INPUT_PATHS],
            check=False,
        )
        expect(unchanged.returncode, 0, "render input equivalence")

    print(json.dumps({"state": "PASS", **spec["identities"]}, sort_keys=True))


if __name__ == "__main__":
    main()
