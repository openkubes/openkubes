#!/usr/bin/env python3
"""Generate the additive OK-141 SSA migration-disable amendment."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import yaml


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
HARNESS = SPIKE / "harness"
V6_PROFILE = HARNESS / "profiles/platform/minimal-observability-v6"
V7_PROFILE = HARNESS / "profiles/platform/minimal-observability-v7"
BASE_IDENTITIES = {
    "fixtureDigest": "sha256:e83ddec6908ca416d0ddc718a5652ba5db2b4950c26deff1da1ae03b908f028c",
    "R": "sha256:7503b0cd54d5d68243f05e231fe76cb56173a96ba9f2e4f76c83106b30731305",
    "P": "sha256:30946024c91c64d29840bbdd1184d5f1f1e20dde3869505e07e262caef22df7b",
}


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


V1 = load_module("ok141_harness_for_ssa_migration", HARNESS / "ok141_harness.py")


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


def main() -> int:
    profile = json.loads((V6_PROFILE / "profile.json").read_text())
    apps = documents(V6_PROFILE / "applications.yaml")
    values = V1.read_yaml_or_json(V6_PROFILE / "provider-values.yaml")
    if V1.semantic_revision(profile) != BASE_IDENTITIES["P"]:
        raise RuntimeError("v6 Platform identity mismatch")

    v7_profile = copy.deepcopy(profile)
    v7_apps = copy.deepcopy(apps)
    v7_values = copy.deepcopy(values)
    core = app_map(v7_apps)["disposable-ok141-observability-core"]
    options = core["spec"]["syncPolicy"]["syncOptions"]
    if "ServerSideApply=true" not in options:
        raise RuntimeError("v6 core Application lacks SSA")
    if "ClientSideApplyMigration=false" in options:
        raise RuntimeError("v6 already disables client-side migration")
    options.append("ClientSideApplyMigration=false")

    v7_profile["format"] = "ok141-platform-profile/v6"
    v7_profile["profile"] = "minimal-observability-v7"
    v7_profile["resourceApplyPolicy"] = {
        "application": "disposable-ok141-observability-core",
        "mode": "server-side-apply",
        "syncOption": "ServerSideApply=true",
        "clientSideApplyMigration": False,
        "migrationSyncOption": "ClientSideApplyMigration=false",
        "scope": "core Application including Prometheus Operator CRDs",
        "reason": "the default Argo client-side migration still exceeds the annotation limit for large CRDs",
    }
    v7_profile["syncContract"]["coreSyncOptions"] = [
        "ServerSideApply=true",
        "ClientSideApplyMigration=false",
    ]
    update_leaf_digests(v7_profile, v7_apps)
    write_profile(V7_PROFILE, v7_profile, v7_apps, v7_values)

    p7 = V1.semantic_revision(v7_profile)
    contract = V1.read_yaml_or_json(HARNESS / "fixtures/contracts-v6/base.yaml")
    contract["spec"]["platform"] = {"profile": "minimal-observability-v7", "revision": p7}
    contract_path = HARNESS / "fixtures/contracts-v7/base.yaml"
    contract_path.parent.mkdir(parents=True, exist_ok=True)
    contract_path.write_text(yaml.safe_dump(contract, sort_keys=False))
    schema = json.loads((HARNESS / "schema/contract-v3.schema.json").read_text())
    normalized = V1.normalize(contract, schema)
    V1.validate_contract_semantics(normalized)
    r7 = V1.semantic_revision(V1.semantic_projection(normalized, schema))

    fixture = {
        "format": "ok141-execution-fixture-amendment/ssa-migration-v1",
        "base": BASE_IDENTITIES,
        "platform": {
            "profile": "minimal-observability-v7",
            "profilePath": "harness/profiles/platform/minimal-observability-v7/profile.json",
            "applicationsPath": "harness/profiles/platform/minimal-observability-v7/applications.yaml",
            "providerValuesPath": "harness/profiles/platform/minimal-observability-v7/provider-values.yaml",
            "P": p7,
            "applicationSetDigest": V1.semantic_revision(v7_apps),
            "providerValuesDigest": V1.semantic_revision(v7_values),
            "sourceCommit": "b5f7be6a7ddab798f31f32197fcbb9e86a9798b6",
        },
        "contract": {
            "path": "harness/fixtures/contracts-v7/base.yaml",
            "schemaPath": "harness/schema/contract-v3.schema.json",
            "R": r7,
        },
        "semanticDelta": {
            "application": "disposable-ok141-observability-core",
            "addedSyncOption": "ClientSideApplyMigration=false",
            "serverSideApplyRetained": True,
            "desiredResourceSetChanged": False,
            "sourceRevisionChanged": False,
        },
        "authorization": "NO-GO",
    }
    fixture_digest = V1.semantic_revision(fixture)
    amendment = {
        "apiVersion": "test.openkubes.io/v1alpha1",
        "kind": "PlatformServerSideApplyMigrationAmendment",
        "metadata": {"name": "ok141-platform-ssa-migration-amendment-v1"},
        "spec": {
            **fixture,
            "fixtureDigest": fixture_digest,
            "identities": {"P": p7, "R": r7, "FixtureDigest": fixture_digest},
        },
    }
    output = HERE / "platform-ssa-migration-amendment-v1.json"
    output.write_text(json.dumps(amendment, indent=2, sort_keys=True) + "\n")
    print(json.dumps(amendment["spec"]["identities"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
