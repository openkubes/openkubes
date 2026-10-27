#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import yaml


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
DEFAULT = HERE / "hcp-phase-r-v5-amendment-v1.yaml"
DIGEST = HERE / "hcp-phase-r-v5-amendment-v1.sha256"


def module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(result)
    return result


V5 = module("ok141_phase_r_v5_hcp_amendment", SPIKE / "harness/ok141_phase_r_v5.py")
V1 = V5.V1


class AmendmentError(ValueError):
    pass


def sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def expect(actual: Any, expected: Any, context: str) -> None:
    if actual != expected:
        raise AmendmentError(f"{context}: expected {expected!r}, got {actual!r}")


def resolve(protocol_path: Path, requested: str) -> Path:
    path = (protocol_path.parent / requested).resolve()
    if SPIKE.resolve() not in path.parents or not path.is_file():
        raise AmendmentError(f"reference missing or outside spike root: {requested}")
    return path


def one_document(path: Path) -> dict[str, Any]:
    docs = [item for item in yaml.load_all(path.read_text(), Loader=V1.UniqueKeyLoader) if item]
    if len(docs) != 1:
        raise AmendmentError(f"expected exactly one document: {path}")
    return docs[0]


def identity(item: dict[str, Any]) -> str:
    metadata = item["metadata"]
    return f"{item['apiVersion']}|{item['kind']}|{metadata.get('namespace', '_')}|{metadata['name']}"


def validate(value: dict[str, Any], protocol_path: Path = DEFAULT) -> dict[str, Any]:
    expect(value.get("apiVersion"), "execution.openkubes.io/v1alpha1", "apiVersion")
    expect(value.get("kind"), "GO1LHCPAmendment", "kind")
    spec = value["spec"]
    expect(spec["version"], "ok141-go1-l-hcp-amendment/v1", "version")
    expect(spec["state"], "OFFLINE-PROVEN-BLOCKED-NO-GO", "state")
    if any(spec["authorization"].values()):
        raise AmendmentError("amendment grants authority")

    fixture_ref = spec["fixture"]
    fixture_path = resolve(protocol_path, fixture_ref["path"])
    expect(sha(fixture_path), fixture_ref["fileDigest"], "fixture file digest")
    fixture = V1.read_yaml_or_json(fixture_path)
    expect(fixture["fixtureVersion"], "phase-r-v5", "fixture version")
    expect(fixture["fixtureDigest"], fixture_ref["fixtureDigest"], "FixtureDigest")
    expect(fixture["contract"]["R"], fixture_ref["R"], "R")
    expect(fixture["enablement"]["E"], fixture_ref["E"], "E")
    expect(fixture["authorizationState"], "NO-GO", "fixture authorization")

    historical_ref, current_ref = spec["historicalHCP"], spec["currentHCP"]
    historical_path = resolve(protocol_path, historical_ref["path"])
    current_path = resolve(protocol_path, current_ref["path"])
    expect(sha(historical_path), historical_ref["rawDigest"], "historical HCP raw digest")
    expect(sha(current_path), current_ref["rawDigest"], "current HCP raw digest")
    historical, current = one_document(historical_path), one_document(current_path)
    expect(V1.semantic_revision([historical]), historical_ref["semanticDigest"], "historical HCP semantic digest")
    expect(V1.semantic_revision([current]), current_ref["semanticDigest"], "current HCP semantic digest")
    expect(identity(current), current_ref["objectIdentity"], "current HCP identity")
    expect(current["spec"], historical["spec"], "desired Helm semantics")

    historical_annotations = historical["metadata"]["annotations"]
    current_annotations = current["metadata"]["annotations"]
    changed = {key for key in set(historical_annotations) | set(current_annotations) if historical_annotations.get(key) != current_annotations.get(key)}
    expect(changed, {"openkubes.io/intent-revision", "openkubes.io/execution-fixture"}, "carrier-only changes")
    expect(historical_annotations["openkubes.io/intent-revision"], historical_ref["R"], "historical R")
    expect(historical_annotations["openkubes.io/execution-fixture"], historical_ref["fixtureDigest"], "historical fixture")
    expect(current_annotations["openkubes.io/intent-revision"], fixture_ref["R"], "current R")
    expect(current_annotations["openkubes.io/enablement-revision"], fixture_ref["E"], "current E")
    expect(current_annotations["openkubes.io/execution-fixture"], fixture_ref["fixtureDigest"], "current fixture")
    expect(current_ref["desiredHelmSemanticsEqualHistorical"], True, "Helm equivalence claim")
    expect(current_ref["submissionEnabled"], False, "HCP submission boundary")
    expect(historical_ref["allowedForFutureSubmission"], False, "historical HCP rejection")

    submitter_ref = spec["submitterCheckpoint"]
    submitter_path = resolve(protocol_path, submitter_ref["path"])
    expect(sha(submitter_path), submitter_ref["digest"], "submitter checkpoint digest")
    submitter = V1.read_yaml_or_json(submitter_path)["spec"]
    expect(submitter["state"], submitter_ref["state"], "submitter state")
    hcp_operation = next(item for item in submitter["operations"] if item["id"] == "helmchartproxy")
    expect(hcp_operation["runtimeEligible"], False, "historical HCP runtime boundary")
    expect(submitter_ref["historicalHCPOperationRuntimeEligible"], False, "recorded historical HCP boundary")
    expect(submitter_ref["additiveSubmitterBindingRequired"], True, "submitter follow-up")
    return current


def main() -> int:
    try:
        value = V1.read_yaml_or_json(DEFAULT)
        current = validate(value, DEFAULT)
        actual = sha(DEFAULT)
        expect(DIGEST.read_text().strip(), actual, "amendment digest file")
        print(json.dumps({
            "amendmentDigest": actual,
            "state": value["spec"]["state"],
            "currentHCPRawDigest": value["spec"]["currentHCP"]["rawDigest"],
            "objectIdentity": identity(current),
            "desiredHelmSemanticsEqualHistorical": True,
            "submissionEnabled": False,
            "clusterContacted": False,
            "mutationAuthorized": False,
        }, sort_keys=True))
        return 0
    except (AmendmentError, KeyError, OSError, TypeError, ValueError, yaml.YAMLError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
