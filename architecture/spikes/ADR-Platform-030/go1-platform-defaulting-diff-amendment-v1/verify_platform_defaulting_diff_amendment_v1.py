#!/usr/bin/env python3
"""Fail-closed verifier for the narrow OpenSearch defaulting-diff amendment."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import yaml


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
HARNESS = SPIKE / "harness"
AMENDMENT = HERE / "platform-defaulting-diff-amendment-v1.json"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


V1 = load_module("ok141_harness_for_defaulting_diff_verifier", HARNESS / "ok141_harness.py")


def documents(path: Path) -> list[dict]:
    return [item for item in yaml.load_all(path.read_text(), Loader=V1.UniqueKeyLoader) if item]


def expect(actual, expected, claim: str) -> None:
    if actual != expected:
        raise RuntimeError(f"{claim} mismatch")


def main() -> None:
    amendment = json.loads(AMENDMENT.read_text())
    expect(amendment["kind"], "PlatformDefaultingDiffAmendment", "kind")
    spec = amendment["spec"]
    expect(spec["authorization"], "NO-GO", "authorization")
    expect(spec["base"], {
        "fixtureDigest": "sha256:ad13f4e233a25fe4aa252bd0013f3257c8003f78955a133501a117997462feed",
        "R": "sha256:32c2abeb6f08a6853006f31b764900b65faa9f36db2482b062aa5b3709764d13",
        "P": "sha256:86db1e51e2d4ecbe2cf32d27e7e0f76a6a29a17f6bab201289fff6eee5299925",
    }, "base identities")

    platform = spec["platform"]
    profile = json.loads((SPIKE / platform["profilePath"]).read_text())
    apps = documents(SPIKE / platform["applicationsPath"])
    values = V1.read_yaml_or_json(SPIKE / platform["providerValuesPath"])
    expect(profile["profile"], "minimal-observability-v8", "profile")
    expect(profile["format"], "ok141-platform-profile/v7", "profile format")
    expect(V1.semantic_revision(profile), platform["P"], "P")
    expect(V1.semantic_revision(apps), platform["applicationSetDigest"], "Application set")
    expect(V1.semantic_revision(values), platform["providerValuesDigest"], "Provider Values")

    by_name = {item["metadata"]["name"]: item for item in apps}
    core = by_name["disposable-ok141-observability-core"]
    expect(len(core["spec"]["ignoreDifferences"]), 1, "ignore rule count")
    rule = core["spec"]["ignoreDifferences"][0]
    expect({key: rule[key] for key in ("group", "kind", "name", "namespace")}, {
        "group": "apps",
        "kind": "StatefulSet",
        "name": "ok-observability-opensearch",
        "namespace": "ok-observability",
    }, "exact resource boundary")
    expect("managedFieldsManagers" in rule, False, "no broad manager ignore")
    expect(len(rule["jsonPointers"]), 5, "JSON pointer count")
    expect(len(rule["jqPathExpressions"]), 13, "JQ path count")
    expect("/spec" in rule["jsonPointers"], False, "no broad spec ignore")
    expect(
        "RespectIgnoreDifferences=true" in core["spec"]["syncPolicy"]["syncOptions"],
        False,
        "comparison-only boundary",
    )
    expect(core["spec"]["syncPolicy"]["syncOptions"][-2:], [
        "ServerSideApply=true", "ClientSideApplyMigration=false"
    ], "existing apply options")
    for name in ("disposable-ok141-observability-alerting", "disposable-ok141-observability-dashboards"):
        expect(by_name[name]["spec"].get("ignoreDifferences"), None, f"{name} unaffected")

    contract = V1.read_yaml_or_json(SPIKE / spec["contract"]["path"])
    schema = json.loads((SPIKE / spec["contract"]["schemaPath"]).read_text())
    normalized = V1.normalize(contract, schema)
    expect(normalized["spec"]["platform"], {
        "profile": "minimal-observability-v8", "revision": platform["P"]
    }, "contract Platform identity")
    expect(V1.semantic_revision(V1.semantic_projection(normalized, schema)), spec["contract"]["R"], "R")

    fixture = copy.deepcopy(spec)
    declared = fixture.pop("fixtureDigest")
    fixture.pop("identities")
    expect(V1.semantic_revision(fixture), declared, "FixtureDigest")
    expect(spec["identities"], {"P": platform["P"], "R": spec["contract"]["R"], "FixtureDigest": declared}, "identity summary")

    negative = copy.deepcopy(profile)
    negative["resourceComparisonPolicy"]["jsonPointers"].pop()
    if V1.semantic_revision(negative) == platform["P"]:
        raise RuntimeError("negative pointer control did not change P")
    print(json.dumps({"state": "PASS", **spec["identities"]}, sort_keys=True))


if __name__ == "__main__":
    main()
