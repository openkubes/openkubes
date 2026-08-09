#!/usr/bin/env python3
"""Fail-closed offline verifier for the OK-141 Platform P-double-prime amendment."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import yaml


HARNESS_DIR = Path(__file__).resolve().parent
V1_PATH = HARNESS_DIR / "ok141_harness.py"
SPEC = importlib.util.spec_from_file_location("ok141_harness_v1_platform", V1_PATH)
V1 = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(V1)

FORMAT = "ok141-platform-profile/v2"
PROFILE = "minimal-observability-v3"
COMMIT = "fe394da8875adecc3b497137e546cecabd710d1d"
REPO = "https://github.com/openkubes/ok-observability.git"
NAMESPACE = "ok-observability"
REQUIRED_NAMES = {
    "disposable-ok141-observability-core",
    "disposable-ok141-observability-alerting",
    "disposable-ok141-observability-dashboards",
}


def _documents(path: Path) -> list[dict[str, Any]]:
    return [item for item in yaml.load_all(path.read_text(), Loader=V1.UniqueKeyLoader) if item]


def _fail_if(condition: bool, message: str) -> None:
    if condition:
        raise V1.HarnessError(message)


def validate_platform_amendment(
    profile: dict[str, Any], applications: list[dict[str, Any]], provider_values: Any
) -> str:
    _fail_if(profile.get("format") != FORMAT, "unsupported Platform amendment format")
    _fail_if(profile.get("profile") != PROFILE, "unexpected Platform profile identity")
    target = profile.get("target", {})
    _fail_if("intentRevision" in target, "P must not embed R")
    identity = target.get("immutableIdentityReference", {})
    _fail_if(
        identity.get("scheme") != "capi-cluster-uid/v1"
        or identity.get("resolution") != "runtime-required"
        or identity.get("contractRef") != target.get("contractIdentity"),
        "immutable target identity reference is incomplete",
    )
    _fail_if("credentials" in profile or "appProject" in profile, "mechanism security state leaked into P")

    provider = profile.get("providerValues", {})
    _fail_if(
        provider.get("digest") != V1.semantic_revision(provider_values),
        "Provider Values digest mismatch",
    )
    namespace = profile.get("namespace", {})
    labels = namespace.get("podSecurityLabels", {})
    _fail_if(namespace.get("name") != NAMESPACE, "Platform namespace mismatch")
    _fail_if(
        set(labels) != {
            "pod-security.kubernetes.io/enforce",
            "pod-security.kubernetes.io/audit",
            "pod-security.kubernetes.io/warn",
        }
        or set(labels.values()) != {"privileged"},
        "Pod Security semantics are incomplete",
    )

    leaves = profile.get("requiredApplications", [])
    by_name = {leaf.get("name"): leaf for leaf in leaves}
    apps = {app.get("metadata", {}).get("name"): app for app in applications}
    _fail_if(set(by_name) != REQUIRED_NAMES or len(leaves) != 3, "required membership is not exact")
    _fail_if(set(apps) != REQUIRED_NAMES or len(applications) != 3, "Application membership is not exact")
    sync_contract = profile.get("syncContract")
    for name in sorted(REQUIRED_NAMES):
        leaf, app = by_name[name], apps[name]
        _fail_if(app.get("apiVersion") != "argoproj.io/v1alpha1" or app.get("kind") != "Application", f"{name}: not an Application")
        _fail_if(leaf.get("applicationDigest") != V1.semantic_revision(app), f"{name}: exact Application digest mismatch")
        spec = app.get("spec", {})
        source, destination = spec.get("source", {}), spec.get("destination", {})
        wanted = leaf.get("source", {})
        _fail_if(source.get("repoURL") != REPO or source.get("repoURL") != wanted.get("repoURL"), f"{name}: repository mismatch")
        _fail_if(source.get("targetRevision") != COMMIT or wanted.get("commit") != COMMIT, f"{name}: mutable or wrong source revision")
        _fail_if(source.get("path") != wanted.get("path"), f"{name}: source path mismatch")
        _fail_if(destination != {"name": "disposable-ok141", "namespace": NAMESPACE}, f"{name}: destination mismatch")
        policy = spec.get("syncPolicy", {})
        _fail_if(policy.get("automated") != sync_contract.get("automated"), f"{name}: automated sync mismatch")
        _fail_if(policy.get("retry") != sync_contract.get("retry"), f"{name}: retry mismatch")
        options = policy.get("syncOptions", [])
        _fail_if(not set(sync_contract.get("syncOptions", [])).issubset(options), f"{name}: sync options mismatch")
        if name.endswith("-core"):
            _fail_if(source.get("helm", {}).get("valuesObject") != provider_values, "core: Provider Values projection mismatch")
            _fail_if("CreateNamespace=true" not in options, "core: namespace creation is not explicit")
            _fail_if(policy.get("managedNamespaceMetadata", {}).get("labels") != labels, "core: Pod Security projection mismatch")
        else:
            _fail_if(source.get("directory", {}).get("include") != wanted.get("include"), f"{name}: exact artifact include mismatch")

    capability = profile.get("capabilityCheck", {})
    _fail_if(capability.get("parameters") != {"namespace": NAMESPACE, "alertAcceptance": "firing-only"}, "capability parameters mismatch")
    _fail_if(capability.get("requiresCurrentPassingEvidence") is not True, "current capability evidence is required")
    _fail_if(capability.get("argoHealthAloneIsCapabilityProof") is not False, "Argo health cannot be capability proof")
    prereqs = profile.get("mechanismPrerequisites", {})
    _fail_if(prereqs.get("includedInPlatformRevision") is not False, "mechanism security prerequisites must remain outside P")
    return V1.semantic_revision(profile)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--applications", type=Path, required=True)
    parser.add_argument("--provider-values", type=Path, required=True)
    args = parser.parse_args()
    try:
        profile = json.loads(args.profile.read_text())
        print(validate_platform_amendment(profile, _documents(args.applications), V1.read_yaml_or_json(args.provider_values)))
        return 0
    except (V1.HarnessError, OSError, ValueError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
