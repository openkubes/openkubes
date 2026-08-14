#!/usr/bin/env python3
"""Verify the offline-only OK-141 clean-baseline recreation preflight."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import sys
from pathlib import Path
from typing import Any

import yaml


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
DEFAULT = HERE / "recreation-preflight-v1.yaml"
MODULE_SPEC = importlib.util.spec_from_file_location("ok141_phase_r_v5_recreation", SPIKE / "harness/ok141_phase_r_v5.py")
V5 = importlib.util.module_from_spec(MODULE_SPEC)
assert MODULE_SPEC.loader is not None
MODULE_SPEC.loader.exec_module(V5)
V1 = V5.V1


class PreflightError(ValueError):
    pass


def sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def expect(actual: Any, expected: Any, context: str) -> None:
    if actual != expected:
        raise PreflightError(f"{context}: expected {expected!r}, got {actual!r}")


def resolve(base: Path, requested: str) -> Path:
    path = (base.parent / requested).resolve()
    if SPIKE.resolve() not in path.parents or not path.is_file():
        raise PreflightError(f"reference missing or outside spike root: {requested}")
    return path


def documents(path: Path) -> list[dict[str, Any]]:
    return [item for item in yaml.load_all(path.read_text(), Loader=V1.UniqueKeyLoader) if item]


def identity(item: dict[str, Any]) -> str:
    metadata = item.get("metadata", {})
    return f"{item.get('apiVersion')}|{item.get('kind')}|{metadata.get('namespace', '_')}|{metadata.get('name')}"


def verify(path: Path = DEFAULT) -> dict[str, Any]:
    value = V1.read_yaml_or_json(path)
    expect(value.get("apiVersion"), "recovery.openkubes.io/v1alpha1", "apiVersion")
    expect(value.get("kind"), "GO1LRecreationPreflight", "kind")
    spec = value["spec"]
    expect(spec["version"], "ok141-go1-l-recreation-preflight/v1", "version")
    expect(spec["state"], "OFFLINE-PREPARED-BLOCKED-NO-GO", "state")

    closure_path = resolve(path, spec["cleanBaseline"]["path"])
    expect(sha(closure_path), spec["cleanBaseline"]["digest"], "clean baseline digest")
    closure = V1.read_yaml_or_json(closure_path)["spec"]
    expect(closure["conclusion"]["cleanBaselineProven"], True, "clean baseline proof")
    expect(closure["conclusion"]["recreationPerformed"], False, "recreation history")

    fixture_path = resolve(path, spec["correctedFixture"]["path"])
    expect(sha(fixture_path), spec["correctedFixture"]["fileDigest"], "fixture file digest")
    fixture = V1.read_yaml_or_json(fixture_path)
    expect(fixture["fixtureVersion"], "phase-r-v5", "fixture version")
    expect(fixture["fixtureDigest"], spec["correctedFixture"]["fixtureDigest"], "fixture digest")
    expect(fixture["contract"]["R"], spec["correctedFixture"]["R"], "R")

    for rejected in spec["rejectedHistoricalExecutionArtifacts"]:
        rejected_path = resolve(path, rejected["path"])
        expect(sha(rejected_path), rejected["digest"], "historical artifact digest")
        expect(rejected["allowedForRecreation"], False, "historical artifact rejection")

    lifecycle = spec["projection"]["managementLifecycle"]
    lifecycle_path = resolve(path, lifecycle["path"])
    expect(sha(lifecycle_path), lifecycle["rawDigest"], "lifecycle raw digest")
    docs = documents(lifecycle_path)
    expect(len(docs), 8, "lifecycle document count")
    expect(V1.semantic_revision(docs), lifecycle["semanticDigest"], "lifecycle semantic digest")
    expect(V1.semantic_revision(docs[:1]), lifecycle["namespaceSemanticDigest"], "namespace semantic digest")
    expect(V1.semantic_revision(docs[1:]), lifecycle["remainingSemanticDigest"], "remaining lifecycle semantic digest")
    expect(identity(docs[0]), "v1|Namespace|_|disposable-ok141", "first lifecycle document")
    expect([item["id"] for item in spec["requiredSequence"]], [
        "provider-prerequisites", "management-namespace", "provider-access-secret", "capi-lifecycle", "helmchartproxy"
    ], "recreation sequence")
    expect(spec["requiredSequence"][1]["documentIndices"], [0], "namespace slice")
    expect(spec["requiredSequence"][3]["documentIndices"], list(range(1, 8)), "lifecycle slice")

    kubevirt_cluster = next(item for item in docs if item.get("kind") == "KubevirtCluster")
    expect(kubevirt_cluster["spec"]["infraClusterSecretRef"], spec["providerAccess"]["secretRef"], "provider secret reference")
    if any(item.get("kind") == "Secret" for item in docs):
        raise PreflightError("credential Secret entered static lifecycle projection")
    expect(spec["providerAccess"]["sourceCredentialPath"], "/Users/arash/.kube/ok-infra.yaml", "credential source")
    expect(spec["providerAccess"]["secretDataKey"], "kubeconfig", "CAPK secret key")
    expect(spec["providerAccess"]["credentialBytesInRepositoryAllowed"], False, "credential repository boundary")

    authorization = spec["authorization"]
    if any(authorization.values()):
        raise PreflightError("preflight grants authority")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight", type=Path, default=DEFAULT)
    args = parser.parse_args()
    try:
        verify(args.preflight.resolve())
        print(sha(args.preflight.resolve()))
        return 0
    except (PreflightError, KeyError, OSError, TypeError, ValueError, yaml.YAMLError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
