#!/usr/bin/env python3
"""Fail-closed verifier for the additive OK-141 Platform network amendment."""

from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import sys
from pathlib import Path

import yaml


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
HARNESS = SPIKE / "harness"
COMPONENTS = ["coreDns", "kubeControllerManager", "kubeEtcd", "kubeProxy", "kubeScheduler"]


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


V5 = load("ok141_phase_r_v5_for_platform_network", HARNESS / "ok141_phase_r_v5.py")
SOURCE = V5.PLATFORM
V1 = V5.V1


def expect(actual, expected, claim: str) -> None:
    if actual != expected:
        raise V1.HarnessError(f"{claim} mismatch")


def documents(path: Path) -> list[dict]:
    return [item for item in yaml.load_all(path.read_text(), Loader=V1.UniqueKeyLoader) if item]


def validate(candidate: dict) -> str:
    spec = candidate["spec"]
    expect(spec["authorizationState"], "NO-GO", "authorization")
    base_path = SPIKE / spec["base"]["fixturePath"]
    base = json.loads(base_path.read_text(encoding="utf-8"))
    expect(V5.validate(base, HARNESS), spec["base"]["fixtureDigest"], "base fixture")
    expect(base["contract"]["R"], spec["base"]["R"], "base R")
    expect(base["platform"]["P"], spec["base"]["P"], "base P")

    claim = spec["fixture"]
    profile_path = SPIKE / claim["profilePath"]
    apps_path = SPIKE / claim["applicationsPath"]
    values_path = SPIKE / claim["providerValuesPath"]
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    apps = documents(apps_path)
    values = V1.read_yaml_or_json(values_path)
    expect(profile["format"], "ok141-platform-profile/v4", "profile format")
    expect(profile["profile"], claim["profile"], "profile identity")
    network = profile["targetNetworkIntegration"]
    expect(network["cni"], "cilium", "CNI")
    expect(network["kubeProxyReplacement"], True, "kube-proxy replacement")
    expect(network["disabledKubePrometheusComponents"], COMPONENTS, "disabled components")
    expect(network["requiredRenderedNamespaces"], ["ok-observability"], "rendered namespace boundary")
    stack = values["ok-observability-prometheus"]["kube-prometheus-stack"]
    for component in COMPONENTS:
        expect(stack[component], {"enabled": False}, f"{component} value")
    app_by_name = {item["metadata"]["name"]: item for item in apps}
    core = app_by_name["disposable-ok141-observability-core"]
    expect(core["spec"]["source"]["helm"]["valuesObject"], values, "Provider Values projection")
    expect(V1.semantic_revision(values), claim["providerValuesDigest"], "Provider Values digest")
    expect(V1.semantic_revision(apps), claim["applicationSetDigest"], "Application set digest")
    expect(V1.semantic_revision(profile), claim["P"], "P")
    expect(profile["providerValues"]["digest"], claim["providerValuesDigest"], "profile Provider Values digest")
    for leaf in profile["requiredApplications"]:
        expect(leaf["applicationDigest"], V1.semantic_revision(app_by_name[leaf["name"]]), f"{leaf['name']} digest")

    historical_profile = copy.deepcopy(profile)
    historical_profile.pop("targetNetworkIntegration")
    historical_profile["format"] = "ok141-platform-profile/v3"
    historical_profile["profile"] = "minimal-observability-v4"
    historical_values = copy.deepcopy(values)
    historical_stack = historical_values["ok-observability-prometheus"]["kube-prometheus-stack"]
    for component in COMPONENTS:
        historical_stack.pop(component)
    historical_apps = copy.deepcopy(apps)
    historical_core = next(x for x in historical_apps if x["metadata"]["name"].endswith("-core"))
    historical_core["spec"]["source"]["helm"]["valuesObject"] = historical_values
    historical_profile["providerValues"]["digest"] = V1.semantic_revision(historical_values)
    for leaf in historical_profile["requiredApplications"]:
        app = next(x for x in historical_apps if x["metadata"]["name"] == leaf["name"])
        leaf["applicationDigest"] = V1.semantic_revision(app)
    expect(SOURCE.validate_platform_source_amendment(historical_profile, historical_apps, historical_values), spec["base"]["P"], "historical projection")

    contract_path = HARNESS / base["contract"]["path"]
    schema_path = HARNESS / base["contract"]["schemaPath"]
    contract, _ = V5.load_contract(contract_path, schema_path)
    contract = copy.deepcopy(contract)
    contract["spec"]["platform"] = {"profile": claim["profile"], "revision": claim["P"]}
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    expect(V1.semantic_revision(V1.semantic_projection(contract, schema)), claim["R"], "R")

    inventory_path = SPIKE / claim["renderInventoryPath"]
    inventory_bytes = inventory_path.read_bytes()
    inventory = json.loads(inventory_bytes)
    expect(V1.sha256_bytes(inventory_bytes), claim["renderInventoryArtifactDigest"], "inventory artifact")
    expect(inventory["inventoryDigest"], claim["renderInventoryDigest"], "inventory semantic digest")
    expect(inventory["coreRenderedRawDigest"], claim["coreRenderedRawDigest"], "raw render digest")
    expect(len(inventory["removedObjects"]), spec["semanticDelta"]["removedObjectCount"], "removed object count")
    if any(item.get("namespace") == "kube-system" for item in inventory["objects"]):
        raise V1.HarnessError("render escaped into kube-system")

    fixture_identity = copy.deepcopy(claim)
    declared = fixture_identity.pop("fixtureDigest")
    derived = V1.semantic_revision({
        "format": "ok141-execution-fixture-amendment/v1",
        "baseFixtureDigest": spec["base"]["fixtureDigest"],
        "fixture": fixture_identity,
        "semanticDelta": spec["semanticDelta"],
    })
    expect(derived, declared, "amended FixtureDigest")
    return derived


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(validate(V1.read_yaml_or_json(args.candidate)))
        return 0
    except (KeyError, OSError, ValueError, yaml.YAMLError, V1.HarnessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
