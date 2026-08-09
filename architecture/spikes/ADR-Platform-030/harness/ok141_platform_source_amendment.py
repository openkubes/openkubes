#!/usr/bin/env python3
"""Fail-closed verifier for the additive OK-141 Platform source amendment."""

from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import yaml


HARNESS_DIR = Path(__file__).resolve().parent


def _module(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, HARNESS_DIR / file)
    result = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(result)
    return result


V3 = _module("ok141_platform_v3_for_source_amendment", "ok141_platform_amendment.py")
V1 = V3.V1
FORMAT = "ok141-platform-profile/v3"
PROFILE = "minimal-observability-v4"
OLD_COMMIT = V3.COMMIT
COMMIT = "b5f7be6a7ddab798f31f32197fcbb9e86a9798b6"
CORE = "disposable-ok141-observability-core"
LOCK_SCHEMA = "openkubes.io/ok-observability-vendored-artifacts/v1"
LOCK_PATH = "profiles/ok-observability-standard/artifact-lock.json"
PACKAGES = {
    "profiles/ok-observability-standard/charts/ok-observability-grafana-0.1.0.tgz":
        "sha256:1d80132e47136ef2d0d67eca1f77d63d8a8397bff7fdc31b632cc420a277e5d8",
    "profiles/ok-observability-standard/charts/ok-observability-opensearch-0.1.0.tgz":
        "sha256:c9c8eaf2f32891cafc04eb273804fb11ed7a26c2f94b9367e4c5b879f1b609d7",
    "profiles/ok-observability-standard/charts/ok-observability-prometheus-0.1.0.tgz":
        "sha256:241acee7834df7d2de6697f505b64a0ae5105fe2771bf3d34cfca66361fe94f0",
}


def _documents(path: Path) -> list[dict[str, Any]]:
    return [item for item in yaml.load_all(path.read_text(), Loader=V1.UniqueKeyLoader) if item]


def _fail_if(condition: bool, message: str) -> None:
    if condition:
        raise V1.HarnessError(message)


def validate_platform_source_amendment(
    profile: dict[str, Any], applications: list[dict[str, Any]], provider_values: Any
) -> str:
    _fail_if(profile.get("format") != FORMAT, "unsupported Platform source-amendment format")
    _fail_if(profile.get("profile") != PROFILE, "unexpected Platform source-amendment identity")

    leaves = profile.get("requiredApplications", [])
    apps = {app.get("metadata", {}).get("name"): app for app in applications}
    _fail_if(len(leaves) != 3 or len(apps) != 3, "required Application membership is not exact")
    _fail_if(
        {leaf.get("source", {}).get("commit") for leaf in leaves} != {COMMIT},
        "Platform profile does not bind the authoritative source commit",
    )
    _fail_if(
        {app.get("spec", {}).get("source", {}).get("targetRevision") for app in applications}
        != {COMMIT},
        "Application set does not bind the authoritative source commit",
    )

    by_name = {leaf.get("name"): leaf for leaf in leaves}
    core = by_name.get(CORE, {})
    closure = core.get("sourceArtifacts", {}).get("sourceClosure", {})
    lock = closure.get("artifactLock", {})
    _fail_if(
        lock
        != {
            "path": LOCK_PATH,
            "schema": LOCK_SCHEMA,
            "digest": "sha256:cdcc6f63b6202a89e90510ddb371cfd3130ff2ebc450336b3ee66e0f1fa85bf5",
        },
        "authoritative artifact-lock identity mismatch",
    )
    package_map = {
        item.get("path"): item.get("digest") for item in closure.get("packages", [])
    }
    _fail_if(package_map != PACKAGES or len(closure.get("packages", [])) != 3, "package closure mismatch")

    # Reuse the complete P-double-prime semantics proof after projecting only
    # the intentionally changed source identity back to its historical form.
    historical_profile = copy.deepcopy(profile)
    historical_profile["format"] = V3.FORMAT
    historical_profile["profile"] = V3.PROFILE
    historical_apps = copy.deepcopy(applications)
    historical_by_name = {
        app.get("metadata", {}).get("name"): app for app in historical_apps
    }
    for leaf in historical_profile["requiredApplications"]:
        leaf["source"]["commit"] = OLD_COMMIT
        if leaf["name"] == CORE:
            leaf["sourceArtifacts"].pop("sourceClosure")
        historical_app = historical_by_name[leaf["name"]]
        historical_app["spec"]["source"]["targetRevision"] = OLD_COMMIT
        leaf["applicationDigest"] = V1.semantic_revision(historical_app)
    V3.validate_platform_amendment(historical_profile, historical_apps, provider_values)

    for leaf in leaves:
        _fail_if(
            leaf.get("applicationDigest") != V1.semantic_revision(apps[leaf["name"]]),
            f"{leaf['name']}: exact Application digest mismatch",
        )
    return V1.semantic_revision(profile)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--applications", type=Path, required=True)
    parser.add_argument("--provider-values", type=Path, required=True)
    args = parser.parse_args()
    try:
        profile = json.loads(args.profile.read_text())
        print(
            validate_platform_source_amendment(
                profile,
                _documents(args.applications),
                V1.read_yaml_or_json(args.provider_values),
            )
        )
        return 0
    except (V1.HarnessError, OSError, ValueError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
