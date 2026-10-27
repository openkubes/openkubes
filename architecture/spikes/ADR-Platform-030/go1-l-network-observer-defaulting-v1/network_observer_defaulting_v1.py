#!/usr/bin/env python3
"""Validate and apply the bounded CAAPH HCP defaulting normalization."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import yaml


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
CANDIDATE = HERE / "network-observer-defaulting-candidate-v1.yaml"
V1_CANDIDATE = SPIKE / "go1-l-network-observer-v1" / "go1-l-network-observer-candidate-v1.yaml"
V1_TOOL = SPIKE / "go1-l-network-observer-v1" / "bounded_go1_l_network_observer_v1.py"
CAAPH_MANIFEST = SPIKE / "m0a-installation" / "caaph-v0.6.4-addon-components.yaml"

V1_CANDIDATE_DIGEST = "sha256:15b24bd0d7247e0a05d4b1f291221cc52e4f1cefa498b8fe4c5d00b6347f3e04"
V1_TOOL_DIGEST = "sha256:801780456e5f4ec4381ad4fa58b28568bdf6ad655d642b114eb537f27feb28a5"
CAAPH_MANIFEST_DIGEST = "sha256:a70f4eb77eac626231daca1e2a046b4b069bb84320efa327cc8c56a9c4ca03e6"
SEMANTIC_KEYS = (
    "clusterSelector",
    "chartName",
    "repoURL",
    "releaseName",
    "namespace",
    "version",
    "reconcileStrategy",
    "valuesTemplate",
    "options",
)


class DefaultingError(ValueError):
    pass


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def read_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text())
    if not isinstance(value, dict):
        raise DefaultingError(f"expected mapping: {path}")
    return value


def expect(actual: Any, expected: Any, context: str) -> None:
    if actual != expected:
        raise DefaultingError(f"{context}: expected {expected!r}, got {actual!r}")


def hcp_enable_client_cache_default() -> bool:
    documents = list(yaml.safe_load_all(CAAPH_MANIFEST.read_text()))
    matches = [
        item
        for item in documents
        if isinstance(item, dict)
        and item.get("kind") == "CustomResourceDefinition"
        and item.get("metadata", {}).get("name") == "helmchartproxies.addons.cluster.x-k8s.io"
    ]
    if len(matches) != 1:
        raise DefaultingError("expected exactly one HelmChartProxy CRD")
    versions = matches[0]["spec"]["versions"]
    schemas = [item["schema"]["openAPIV3Schema"] for item in versions if item.get("name") == "v1alpha1"]
    if len(schemas) != 1:
        raise DefaultingError("expected exactly one HelmChartProxy v1alpha1 schema")
    field = schemas[0]["properties"]["spec"]["properties"]["options"]["properties"]["enableClientCache"]
    expect(field.get("type"), "boolean", "enableClientCache type")
    default = field.get("default")
    if not isinstance(default, bool):
        raise DefaultingError("enableClientCache default is not boolean")
    return default


def semantic_hcp_spec(value: dict[str, Any]) -> dict[str, Any]:
    """Return the reviewed HCP projection after only the bound API default is applied.

    This does not drop unknown fields. Therefore any unbound additional field or
    any non-default value still fails equality.
    """

    spec = value.get("spec", {})
    projected = {key: copy.deepcopy(spec.get(key)) for key in SEMANTIC_KEYS}
    options = projected.get("options")
    if not isinstance(options, dict):
        return projected
    options.setdefault("enableClientCache", hcp_enable_client_cache_default())
    return projected


def equivalent(expected: dict[str, Any], observed: dict[str, Any]) -> bool:
    return semantic_hcp_spec(expected) == semantic_hcp_spec(observed)


def validate_candidate(path: Path = CANDIDATE) -> dict[str, Any]:
    value = read_yaml(path)
    expect(value.get("kind"), "GO1LNetworkObserverDefaultingAmendmentCandidate", "kind")
    spec = value["spec"]
    expect(spec["version"], "ok141-go1-l-network-observer-defaulting/v1", "version")
    expect(spec["state"], "OFFLINE-PROVEN-BLOCKED-NO-GO", "state")
    expect(digest(V1_CANDIDATE), V1_CANDIDATE_DIGEST, "v1 candidate digest")
    expect(digest(V1_TOOL), V1_TOOL_DIGEST, "v1 tool digest")
    expect(digest(CAAPH_MANIFEST), CAAPH_MANIFEST_DIGEST, "CAAPH manifest digest")
    expect(spec["supersedes"]["candidateDigest"], V1_CANDIDATE_DIGEST, "v1 candidate binding")
    expect(spec["supersedes"]["toolDigest"], V1_TOOL_DIGEST, "v1 tool binding")
    expect(spec["defaultingSource"]["manifestDigest"], CAAPH_MANIFEST_DIGEST, "CRD binding")
    expect(spec["normalization"]["field"], "spec.options.enableClientCache", "normalized field")
    expect(spec["normalization"]["default"], hcp_enable_client_cache_default(), "bound default")
    expect(spec["normalization"]["unknownFieldsIgnored"], False, "unknown-field behavior")
    expect(digest(HERE / spec["tool"]["path"]), spec["tool"]["digest"], "tool digest")
    expect(spec["authorization"]["decision"], "NO-GO", "authorization")
    if any(item for key, item in spec["authorization"].items() if key.endswith("Granted")):
        raise DefaultingError("candidate grants authority")
    return value


def plan(path: Path = CANDIDATE) -> dict[str, Any]:
    value = validate_candidate(path)
    return {
        "candidateDigest": digest(path),
        "defaultingRule": value["spec"]["normalization"],
        "authorization": "NO-GO",
        "clusterContacted": False,
        "mutationPerformed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify",))
    parser.add_argument("--candidate", type=Path, default=CANDIDATE)
    args = parser.parse_args()
    try:
        print(json.dumps(plan(args.candidate.resolve()), indent=2, sort_keys=True))
        return 0
    except Exception as error:
        print(f"ERROR: {type(error).__name__}: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
