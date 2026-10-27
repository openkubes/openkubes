#!/usr/bin/env python3
"""Fail-closed verifier for the OK-141 SSA migration-disable amendment."""

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


V1 = load_module("ok141_harness_for_ssa_migration_verifier", HARNESS / "ok141_harness.py")


def documents(path: Path) -> list[dict]:
    return [item for item in yaml.load_all(path.read_text(), Loader=V1.UniqueKeyLoader) if item]


def expect(actual, expected, claim: str) -> None:
    if actual != expected:
        raise RuntimeError(f"{claim} mismatch")


def validate(path: Path) -> str:
    amendment = json.loads(path.read_text())
    expect(amendment.get("kind"), "PlatformServerSideApplyMigrationAmendment", "kind")
    spec = amendment["spec"]
    expect(spec["authorization"], "NO-GO", "offline authorization")
    expect(spec["base"], {
        "fixtureDigest": "sha256:e83ddec6908ca416d0ddc718a5652ba5db2b4950c26deff1da1ae03b908f028c",
        "R": "sha256:7503b0cd54d5d68243f05e231fe76cb56173a96ba9f2e4f76c83106b30731305",
        "P": "sha256:30946024c91c64d29840bbdd1184d5f1f1e20dde3869505e07e262caef22df7b",
    }, "base identities")

    platform = spec["platform"]
    profile = json.loads((SPIKE / platform["profilePath"]).read_text())
    apps = documents(SPIKE / platform["applicationsPath"])
    values = V1.read_yaml_or_json(SPIKE / platform["providerValuesPath"])
    expect(profile["profile"], "minimal-observability-v7", "profile")
    expect(profile["format"], "ok141-platform-profile/v6", "profile format")
    expect(V1.semantic_revision(profile), platform["P"], "P")
    expect(V1.semantic_revision(apps), platform["applicationSetDigest"], "Application set")
    expect(V1.semantic_revision(values), platform["providerValuesDigest"], "Provider Values")

    by_name = {item["metadata"]["name"]: item for item in apps}
    core_options = by_name["disposable-ok141-observability-core"]["spec"]["syncPolicy"]["syncOptions"]
    expect(core_options.count("ServerSideApply=true"), 1, "core SSA option")
    expect(core_options.count("ClientSideApplyMigration=false"), 1, "migration-disable option")
    for name in ("disposable-ok141-observability-alerting", "disposable-ok141-observability-dashboards"):
        if "ClientSideApplyMigration=false" in by_name[name]["spec"]["syncPolicy"]["syncOptions"]:
            raise RuntimeError("migration-disable option escaped outside Core")
    leafs = {item["name"]: item for item in profile["requiredApplications"]}
    for name, app in by_name.items():
        expect(leafs[name]["applicationDigest"], V1.semantic_revision(app), f"{name} digest")
    expect(profile["syncContract"]["coreSyncOptions"], [
        "ServerSideApply=true", "ClientSideApplyMigration=false"
    ], "core sync contract")
    expect(profile["resourceApplyPolicy"]["clientSideApplyMigration"], False, "migration policy")

    contract = V1.read_yaml_or_json(SPIKE / spec["contract"]["path"])
    schema = json.loads((SPIKE / spec["contract"]["schemaPath"]).read_text())
    normalized = V1.normalize(contract, schema)
    expect(normalized["spec"]["platform"], {
        "profile": "minimal-observability-v7", "revision": platform["P"]
    }, "contract Platform identity")
    expect(V1.semantic_revision(V1.semantic_projection(normalized, schema)), spec["contract"]["R"], "R")

    fixture = copy.deepcopy(spec)
    declared = fixture.pop("fixtureDigest")
    fixture.pop("identities")
    expect(V1.semantic_revision(fixture), declared, "FixtureDigest")
    expect(spec["identities"], {
        "P": platform["P"], "R": spec["contract"]["R"], "FixtureDigest": declared
    }, "identity summary")

    negative = copy.deepcopy(profile)
    negative["syncContract"]["coreSyncOptions"].remove("ClientSideApplyMigration=false")
    negative["resourceApplyPolicy"]["clientSideApplyMigration"] = True
    if V1.semantic_revision(negative) == platform["P"]:
        raise RuntimeError("negative control did not change P")
    return declared


def main() -> int:
    try:
        print(validate(HERE / "platform-ssa-migration-amendment-v1.json"))
        return 0
    except (KeyError, OSError, ValueError, RuntimeError, yaml.YAMLError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
