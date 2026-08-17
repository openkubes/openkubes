#!/usr/bin/env python3
"""Generate the additive OK-141 server-side-apply Platform amendment."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import yaml


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
HARNESS = SPIKE / "harness"
BASE_PROFILE = HARNESS / "profiles/platform/minimal-observability-v4"
V5_PROFILE = HARNESS / "profiles/platform/minimal-observability-v5"
V6_PROFILE = HARNESS / "profiles/platform/minimal-observability-v6"
EXPECTED_NETWORK_P = "sha256:02206b92b487a0f12eee8139d82f9ef150ab9688c7a60687d3f7b6b782266472"
BASE_IDENTITIES = {
    "fixtureDigest": "sha256:3aa621cd8f3b21e87a5d7059911d02a4b0f10f2d724df351750787eb274b9ae6",
    "R": "sha256:89248df8cd908394d2d75c18fbb39d52d84cf181f66480c743bfe9d732a0aaa4",
    "P": EXPECTED_NETWORK_P,
}


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


V1 = load_module("ok141_harness_for_ssa_amendment", HARNESS / "ok141_harness.py")


def documents(path: Path) -> list[dict]:
    return [item for item in yaml.load_all(path.read_text(), Loader=V1.UniqueKeyLoader) if item]


def app_map(apps: list[dict]) -> dict[str, dict]:
    return {item["metadata"]["name"]: item for item in apps}


def update_leaf_digests(profile: dict, apps: list[dict]) -> None:
    by_name = app_map(apps)
    for leaf in profile["requiredApplications"]:
        leaf["applicationDigest"] = V1.semantic_revision(by_name[leaf["name"]])


def write_profile(path: Path, profile: dict, apps: list[dict], values: dict) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "profile.json").write_text(json.dumps(profile, indent=2, sort_keys=True) + "\n")
    (path / "applications.yaml").write_text(
        yaml.safe_dump_all(apps, sort_keys=False, explicit_start=False)
    )
    (path / "provider-values.yaml").write_text(yaml.safe_dump(values, sort_keys=False))


def network_profile() -> tuple[dict, list[dict], dict]:
    profile = json.loads((BASE_PROFILE / "profile.json").read_text())
    apps = documents(BASE_PROFILE / "applications.yaml")
    values = V1.read_yaml_or_json(BASE_PROFILE / "provider-values.yaml")
    stack = values["ok-observability-prometheus"]["kube-prometheus-stack"]
    components = ["coreDns", "kubeControllerManager", "kubeEtcd", "kubeProxy", "kubeScheduler"]
    for component in components:
        stack[component] = {"enabled": False}
    core = app_map(apps)["disposable-ok141-observability-core"]
    core["spec"]["source"]["helm"]["valuesObject"] = copy.deepcopy(values)
    profile["format"] = "ok141-platform-profile/v4"
    profile["profile"] = "minimal-observability-v5"
    profile["targetNetworkIntegration"] = {
        "cni": "cilium",
        "kubeProxyReplacement": True,
        "disabledKubePrometheusComponents": components,
        "requiredRenderedNamespaces": ["ok-observability"],
        "reason": "Talos/Cilium target does not authorize GitOps management of kube-system monitoring Services",
    }
    profile["providerValues"]["digest"] = V1.semantic_revision(values)
    update_leaf_digests(profile, apps)
    if V1.semantic_revision(profile) != EXPECTED_NETWORK_P:
        raise RuntimeError("reconstructed v5 Platform identity differs from the live amendment")
    return profile, apps, values


def ssa_profile(profile: dict, apps: list[dict], values: dict) -> tuple[dict, list[dict], dict]:
    result_profile = copy.deepcopy(profile)
    result_apps = copy.deepcopy(apps)
    core = app_map(result_apps)["disposable-ok141-observability-core"]
    options = core["spec"]["syncPolicy"]["syncOptions"]
    if "ServerSideApply=true" not in options:
        options.append("ServerSideApply=true")
    result_profile["format"] = "ok141-platform-profile/v5"
    result_profile["profile"] = "minimal-observability-v6"
    result_profile["resourceApplyPolicy"] = {
        "application": "disposable-ok141-observability-core",
        "mode": "server-side-apply",
        "syncOption": "ServerSideApply=true",
        "scope": "core Application including Prometheus Operator CRDs",
        "reason": "large CRDs exceed the Kubernetes client-side last-applied annotation limit",
    }
    result_profile["syncContract"]["coreSyncOptions"] = ["ServerSideApply=true"]
    update_leaf_digests(result_profile, result_apps)
    return result_profile, result_apps, copy.deepcopy(values)


def main() -> int:
    v5_profile, v5_apps, v5_values = network_profile()
    write_profile(V5_PROFILE, v5_profile, v5_apps, v5_values)
    v6_profile, v6_apps, v6_values = ssa_profile(v5_profile, v5_apps, v5_values)
    write_profile(V6_PROFILE, v6_profile, v6_apps, v6_values)

    p6 = V1.semantic_revision(v6_profile)
    contract = V1.read_yaml_or_json(HARNESS / "fixtures/contracts-v5/base.yaml")
    contract["spec"]["platform"] = {"profile": "minimal-observability-v6", "revision": p6}
    contract_path = HARNESS / "fixtures/contracts-v6/base.yaml"
    contract_path.parent.mkdir(parents=True, exist_ok=True)
    contract_path.write_text(yaml.safe_dump(contract, sort_keys=False))
    schema = json.loads((HARNESS / "schema/contract-v3.schema.json").read_text())
    normalized = V1.normalize(contract, schema)
    V1.validate_contract_semantics(normalized)
    r6 = V1.semantic_revision(V1.semantic_projection(normalized, schema))
    fixture = {
        "format": "ok141-execution-fixture-amendment/ssa-v1",
        "base": BASE_IDENTITIES,
        "platform": {
            "profile": "minimal-observability-v6",
            "profilePath": "harness/profiles/platform/minimal-observability-v6/profile.json",
            "applicationsPath": "harness/profiles/platform/minimal-observability-v6/applications.yaml",
            "providerValuesPath": "harness/profiles/platform/minimal-observability-v6/provider-values.yaml",
            "P": p6,
            "applicationSetDigest": V1.semantic_revision(v6_apps),
            "providerValuesDigest": V1.semantic_revision(v6_values),
            "sourceCommit": "b5f7be6a7ddab798f31f32197fcbb9e86a9798b6",
        },
        "contract": {
            "path": "harness/fixtures/contracts-v6/base.yaml",
            "schemaPath": "harness/schema/contract-v3.schema.json",
            "R": r6,
        },
        "semanticDelta": {
            "application": "disposable-ok141-observability-core",
            "addedSyncOption": "ServerSideApply=true",
            "desiredResourceSetChanged": False,
            "sourceRevisionChanged": False,
        },
        "authorization": "NO-GO",
    }
    fixture_digest = V1.semantic_revision(fixture)
    amendment = {
        "apiVersion": "test.openkubes.io/v1alpha1",
        "kind": "PlatformServerSideApplyAmendment",
        "metadata": {"name": "ok141-platform-ssa-amendment-v1"},
        "spec": {
            **fixture,
            "fixtureDigest": fixture_digest,
            "identities": {"P": p6, "R": r6, "FixtureDigest": fixture_digest},
        },
    }
    output = HERE / "platform-ssa-amendment-v1.json"
    output.write_text(json.dumps(amendment, indent=2, sort_keys=True) + "\n")
    print(json.dumps(amendment["spec"]["identities"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
