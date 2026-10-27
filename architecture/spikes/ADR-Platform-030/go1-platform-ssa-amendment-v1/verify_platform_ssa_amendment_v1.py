#!/usr/bin/env python3
"""Fail-closed verifier for the additive OK-141 SSA amendment."""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

import yaml


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
HARNESS = SPIKE / "harness"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


V1 = load_module("ok141_harness_for_ssa_verifier", HARNESS / "ok141_harness.py")


def documents(path: Path) -> list[dict]:
    return [item for item in yaml.load_all(path.read_text(), Loader=V1.UniqueKeyLoader) if item]


def expect(actual, expected, claim: str) -> None:
    if actual != expected:
        raise RuntimeError(f"{claim} mismatch")


def validate(path: Path) -> str:
    amendment = json.loads(path.read_text())
    expect(amendment.get("kind"), "PlatformServerSideApplyAmendment", "kind")
    spec = amendment["spec"]
    expect(spec["authorization"], "NO-GO", "offline authorization")
    expect(spec["base"], {
        "fixtureDigest": "sha256:3aa621cd8f3b21e87a5d7059911d02a4b0f10f2d724df351750787eb274b9ae6",
        "R": "sha256:89248df8cd908394d2d75c18fbb39d52d84cf181f66480c743bfe9d732a0aaa4",
        "P": "sha256:02206b92b487a0f12eee8139d82f9ef150ab9688c7a60687d3f7b6b782266472",
    }, "base identities")
    platform = spec["platform"]
    profile = json.loads((SPIKE / platform["profilePath"]).read_text())
    apps = documents(SPIKE / platform["applicationsPath"])
    values = V1.read_yaml_or_json(SPIKE / platform["providerValuesPath"])
    expect(profile["profile"], "minimal-observability-v6", "profile")
    expect(profile["format"], "ok141-platform-profile/v5", "profile format")
    expect(V1.semantic_revision(profile), platform["P"], "P")
    expect(V1.semantic_revision(apps), platform["applicationSetDigest"], "Application set")
    expect(V1.semantic_revision(values), platform["providerValuesDigest"], "Provider Values")
    by_name = {item["metadata"]["name"]: item for item in apps}
    core = by_name["disposable-ok141-observability-core"]
    core_options = core["spec"]["syncPolicy"]["syncOptions"]
    expect(core_options.count("ServerSideApply=true"), 1, "core SSA option")
    for name in (
        "disposable-ok141-observability-alerting",
        "disposable-ok141-observability-dashboards",
    ):
        if "ServerSideApply=true" in by_name[name]["spec"]["syncPolicy"]["syncOptions"]:
            raise RuntimeError("SSA escaped outside the core Application")
    leafs = {item["name"]: item for item in profile["requiredApplications"]}
    for name, app in by_name.items():
        expect(leafs[name]["applicationDigest"], V1.semantic_revision(app), f"{name} digest")
    expect(profile["resourceApplyPolicy"], {
        "application": "disposable-ok141-observability-core",
        "mode": "server-side-apply",
        "syncOption": "ServerSideApply=true",
        "scope": "core Application including Prometheus Operator CRDs",
        "reason": "large CRDs exceed the Kubernetes client-side last-applied annotation limit",
    }, "apply policy")

    contract_claim = spec["contract"]
    contract_path = SPIKE / contract_claim["path"]
    schema_path = SPIKE / contract_claim["schemaPath"]
    schema = json.loads(schema_path.read_text())
    normalized = V1.normalize(V1.read_yaml_or_json(contract_path), schema)
    expect(normalized["spec"]["platform"], {
        "profile": "minimal-observability-v6", "revision": platform["P"]
    }, "contract Platform identity")
    expect(V1.semantic_revision(V1.semantic_projection(normalized, schema)), contract_claim["R"], "R")
    fixture = copy.deepcopy(spec)
    declared = fixture.pop("fixtureDigest")
    fixture.pop("identities")
    expect(V1.semantic_revision(fixture), declared, "FixtureDigest")
    expect(spec["identities"], {
        "P": platform["P"], "R": contract_claim["R"], "FixtureDigest": declared
    }, "identity summary")

    negative_profile = copy.deepcopy(profile)
    negative_profile.pop("resourceApplyPolicy")
    negative_profile["syncContract"].pop("coreSyncOptions")
    if V1.semantic_revision(negative_profile) == platform["P"]:
        raise RuntimeError("negative control did not change P")
    return declared


def main() -> int:
    try:
        print(validate(HERE / "platform-ssa-amendment-v1.json"))
        return 0
    except (KeyError, OSError, ValueError, RuntimeError, yaml.YAMLError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
