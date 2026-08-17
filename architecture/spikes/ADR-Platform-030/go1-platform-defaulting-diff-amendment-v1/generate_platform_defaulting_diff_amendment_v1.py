#!/usr/bin/env python3
"""Generate a narrow OpenSearch API-defaulting comparison amendment."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import yaml


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
HARNESS = SPIKE / "harness"
V7_PROFILE = HARNESS / "profiles/platform/minimal-observability-v7"
V8_PROFILE = HARNESS / "profiles/platform/minimal-observability-v8"
BASE_IDENTITIES = {
    "fixtureDigest": "sha256:ad13f4e233a25fe4aa252bd0013f3257c8003f78955a133501a117997462feed",
    "R": "sha256:32c2abeb6f08a6853006f31b764900b65faa9f36db2482b062aa5b3709764d13",
    "P": "sha256:86db1e51e2d4ecbe2cf32d27e7e0f76a6a29a17f6bab201289fff6eee5299925",
}
JSON_POINTERS = [
    "/spec/persistentVolumeClaimRetentionPolicy",
    "/spec/revisionHistoryLimit",
    "/spec/template/spec/dnsPolicy",
    "/spec/template/spec/restartPolicy",
    "/spec/template/spec/schedulerName",
]
JQ_PATH_EXPRESSIONS = [
    ".spec.template.spec.containers[]?.env[]?.valueFrom.fieldRef.apiVersion",
    ".spec.template.spec.containers[]?.ports[]?.protocol",
    ".spec.template.spec.containers[]?.readinessProbe.successThreshold",
    ".spec.template.spec.containers[]?.startupProbe.successThreshold",
    ".spec.template.spec.containers[]?.terminationMessagePath",
    ".spec.template.spec.containers[]?.terminationMessagePolicy",
    ".spec.template.spec.initContainers[]?.terminationMessagePath",
    ".spec.template.spec.initContainers[]?.terminationMessagePolicy",
    ".spec.template.spec.volumes[]?.configMap.defaultMode",
    ".spec.volumeClaimTemplates[]?.apiVersion",
    ".spec.volumeClaimTemplates[]?.kind",
    ".spec.volumeClaimTemplates[]?.spec.volumeMode",
    ".spec.volumeClaimTemplates[]?.status",
]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


V1 = load_module("ok141_harness_for_defaulting_diff", HARNESS / "ok141_harness.py")


def documents(path: Path) -> list[dict]:
    return [item for item in yaml.load_all(path.read_text(), Loader=V1.UniqueKeyLoader) if item]


def app_map(apps: list[dict]) -> dict[str, dict]:
    return {item["metadata"]["name"]: item for item in apps}


def update_leaf_digests(profile: dict, apps: list[dict]) -> None:
    by_name = app_map(apps)
    for leaf in profile["requiredApplications"]:
        leaf["applicationDigest"] = V1.semantic_revision(by_name[leaf["name"]])


def main() -> None:
    profile = json.loads((V7_PROFILE / "profile.json").read_text())
    apps = documents(V7_PROFILE / "applications.yaml")
    values = V1.read_yaml_or_json(V7_PROFILE / "provider-values.yaml")
    if V1.semantic_revision(profile) != BASE_IDENTITIES["P"]:
        raise RuntimeError("v7 Platform identity mismatch")

    v8_profile = copy.deepcopy(profile)
    v8_apps = copy.deepcopy(apps)
    v8_values = copy.deepcopy(values)
    core = app_map(v8_apps)["disposable-ok141-observability-core"]
    if core["spec"].get("ignoreDifferences"):
        raise RuntimeError("v7 Core Application already defines ignoreDifferences")
    ignore_rule = {
        "group": "apps",
        "kind": "StatefulSet",
        "name": "ok-observability-opensearch",
        "namespace": "ok-observability",
        "jsonPointers": JSON_POINTERS,
        "jqPathExpressions": JQ_PATH_EXPRESSIONS,
    }
    core["spec"]["ignoreDifferences"] = [ignore_rule]

    v8_profile["format"] = "ok141-platform-profile/v7"
    v8_profile["profile"] = "minimal-observability-v8"
    v8_profile["resourceComparisonPolicy"] = {
        "application": "disposable-ok141-observability-core",
        "resource": "apps/StatefulSet/ok-observability/ok-observability-opensearch",
        "mode": "ignore-exact-api-defaulted-live-fields",
        "jsonPointers": JSON_POINTERS,
        "jqPathExpressions": JQ_PATH_EXPRESSIONS,
        "respectIgnoreDifferencesDuringSync": False,
        "semanticDesiredFieldsIgnored": False,
        "reason": "bounded live/render comparison found only Kubernetes API-defaulted live-only fields",
    }
    v8_profile["syncContract"]["coreIgnoreDifferences"] = ignore_rule
    update_leaf_digests(v8_profile, v8_apps)

    V8_PROFILE.mkdir(parents=True, exist_ok=True)
    (V8_PROFILE / "profile.json").write_text(json.dumps(v8_profile, indent=2, sort_keys=True) + "\n")
    (V8_PROFILE / "applications.yaml").write_text(yaml.safe_dump_all(v8_apps, sort_keys=False))
    (V8_PROFILE / "provider-values.yaml").write_text(yaml.safe_dump(v8_values, sort_keys=False))

    p8 = V1.semantic_revision(v8_profile)
    contract = V1.read_yaml_or_json(HARNESS / "fixtures/contracts-v7/base.yaml")
    contract["spec"]["platform"] = {"profile": "minimal-observability-v8", "revision": p8}
    contract_path = HARNESS / "fixtures/contracts-v8/base.yaml"
    contract_path.parent.mkdir(parents=True, exist_ok=True)
    contract_path.write_text(yaml.safe_dump(contract, sort_keys=False))
    schema = json.loads((HARNESS / "schema/contract-v3.schema.json").read_text())
    normalized = V1.normalize(contract, schema)
    V1.validate_contract_semantics(normalized)
    r8 = V1.semantic_revision(V1.semantic_projection(normalized, schema))

    fixture = {
        "format": "ok141-execution-fixture-amendment/defaulting-diff-v1",
        "base": BASE_IDENTITIES,
        "platform": {
            "profile": "minimal-observability-v8",
            "profilePath": "harness/profiles/platform/minimal-observability-v8/profile.json",
            "applicationsPath": "harness/profiles/platform/minimal-observability-v8/applications.yaml",
            "providerValuesPath": "harness/profiles/platform/minimal-observability-v8/provider-values.yaml",
            "P": p8,
            "applicationSetDigest": V1.semantic_revision(v8_apps),
            "providerValuesDigest": V1.semantic_revision(v8_values),
            "sourceCommit": "b5f7be6a7ddab798f31f32197fcbb9e86a9798b6",
        },
        "contract": {
            "path": "harness/fixtures/contracts-v8/base.yaml",
            "schemaPath": "harness/schema/contract-v3.schema.json",
            "R": r8,
        },
        "semanticDelta": {
            "application": "disposable-ok141-observability-core",
            "resource": "apps/StatefulSet/ok-observability/ok-observability-opensearch",
            "comparisonOnly": True,
            "exactDefaultFieldCount": len(JSON_POINTERS) + len(JQ_PATH_EXPRESSIONS),
            "desiredResourceSetChanged": False,
            "sourceRevisionChanged": False,
            "syncOptionsChanged": False,
        },
        "authorization": "NO-GO",
    }
    fixture_digest = V1.semantic_revision(fixture)
    amendment = {
        "apiVersion": "test.openkubes.io/v1alpha1",
        "kind": "PlatformDefaultingDiffAmendment",
        "metadata": {"name": "ok141-platform-defaulting-diff-amendment-v1"},
        "spec": {
            **fixture,
            "fixtureDigest": fixture_digest,
            "identities": {"P": p8, "R": r8, "FixtureDigest": fixture_digest},
        },
    }
    output = HERE / "platform-defaulting-diff-amendment-v1.json"
    output.write_text(json.dumps(amendment, indent=2, sort_keys=True) + "\n")
    print(json.dumps(amendment["spec"]["identities"], sort_keys=True))


if __name__ == "__main__":
    main()
