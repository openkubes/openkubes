#!/usr/bin/env python3
"""Offline verifier for the additive OK-141 Phase-R v4 execution fixture."""

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


V3 = _module("ok141_phase_r_v3_for_v4", "ok141_phase_r_v3.py")
V2 = V3.V2
PLATFORM = _module("ok141_platform_for_v4", "ok141_platform_source_amendment.py")
V1 = V2.V1
FORMAT = "ok141-execution-fixture/v4"
VERSION = "phase-r-v4"


def _path(root: Path, requested: str) -> Path:
    candidate = (root / requested).resolve()
    if root not in candidate.parents or not candidate.is_file():
        raise V1.HarnessError(f"fixture input is missing or outside root: {requested}")
    return candidate


def _expect(actual: Any, expected: Any, claim: str) -> None:
    if actual != expected:
        raise V1.HarnessError(f"Phase-R v4 {claim} mismatch")


def _documents(path: Path) -> list[dict[str, Any]]:
    return [item for item in yaml.load_all(path.read_text(), Loader=V1.UniqueKeyLoader) if item]


def validate(document: dict[str, Any], root: Path) -> str:
    root = root.resolve()
    _expect(document.get("format"), FORMAT, "format")
    _expect(document.get("fixtureVersion"), VERSION, "version")
    _expect(document.get("authorizationState"), "NO-GO", "authorization")

    schema_claim = document["fixtureSchema"]
    schema_path = _path(root, schema_claim["path"])
    schema_bytes = schema_path.read_bytes()
    schema = json.loads(schema_bytes)
    _expect(schema.get("$id"), FORMAT, "schema identity")
    _expect(V1.sha256_bytes(schema_bytes), schema_claim["digest"], "schema digest")
    V1.normalize(document, schema)

    supersedes = document["supersedes"]
    _expect(supersedes.get("fixtureVersion"), "phase-r-v3", "superseded version")
    _expect(supersedes.get("fixtureDigest"), "sha256:67fa2e63bba98d8cc70f680e8df56dea5803c0a0d8c5db81ab78578daacebd9f", "superseded digest")
    _expect(supersedes.get("disposition"), "valid-historical-superseded-not-mutated", "superseded disposition")

    contract_claim = document["contract"]
    contract_path = _path(root, contract_claim["path"])
    contract_schema_path = _path(root, contract_claim["schemaPath"])
    contract, revision = V2.load_contract(contract_path, contract_schema_path)
    _expect(V1.sha256_bytes(contract_path.read_bytes()), contract_claim["rawArtifactDigest"], "raw contract digest")
    _expect(V1.sha256_bytes(contract_schema_path.read_bytes()), contract_claim["schemaDigest"], "contract schema digest")
    _expect(revision, contract_claim["R"], "R")
    _expect(contract["metadata"], document["contractIdentity"], "contract identity")
    spec = contract["spec"]
    _expect(document["clusterSemantics"], {key: spec[key] for key in ("kubernetesVersion", "infrastructure", "operatingSystem", "topology", "connectivity")}, "cluster semantics")

    platform = document["platform"]
    profile_path = _path(root, platform["profilePath"])
    apps_path = _path(root, platform["applicationsPath"])
    values_path = _path(root, platform["providerValuesPath"])
    profile = json.loads(profile_path.read_text())
    apps = _documents(apps_path)
    provider_values = V1.read_yaml_or_json(values_path)
    p_revision = PLATFORM.validate_platform_source_amendment(profile, apps, provider_values)
    _expect(p_revision, platform["P"], "P")
    _expect(p_revision, spec["platform"]["revision"], "contract P")
    _expect(profile["profile"], spec["platform"]["profile"], "Platform profile")
    _expect(V1.semantic_revision(apps), platform["applicationSetDigest"], "Application set digest")
    _expect(V1.semantic_revision(provider_values), platform["providerValuesDigest"], "Provider Values digest")
    _expect(profile["target"]["immutableIdentityReference"]["scheme"], platform["immutableTargetIdentityScheme"], "target identity scheme")
    _expect({leaf["source"]["commit"] for leaf in profile["requiredApplications"]}, {platform["sourceCommit"]}, "Platform source commit")

    enablement = document["enablement"]
    enable_profile = json.loads(_path(root, enablement["profilePath"]).read_text())
    enable_values = V1.read_yaml_or_json(_path(root, enablement["valuesPath"]))
    e_revision = V1.validate_enablement_profile(enable_profile, enable_values)
    _expect(e_revision, enablement["E"], "E")
    _expect(e_revision, spec["enablement"]["revision"], "contract E")

    projection = document["projection"]
    manifest_path = _path(root, projection["manifestPath"])
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    _expect(V1.sha256_bytes(manifest_bytes), projection["manifestDigest"], "projection manifest digest")
    _expect(manifest["R"], revision, "projection R")
    _expect(manifest["objectSets"], projection["objectSets"], "object sets")
    projection_dir = manifest_path.parent
    for artifact, digest in manifest["artifacts"].items():
        _expect(V1.sha256_bytes((projection_dir / artifact).read_bytes()), digest, f"projection artifact {artifact}")
    authority = json.loads(_path(root, projection["authorityMapPath"]).read_text())
    _expect(authority["intentRevision"], revision, "authority R")
    _expect(authority["managementPlane"]["identity"], "ok-mgmt", "management authority")
    _expect(authority["infrastructurePlane"]["identity"], "ok-infra", "infrastructure authority")
    projected_sets = []
    for requested in (projection["managementObjectsPath"], projection["infrastructurePrerequisitesPath"]):
        documents = _documents(_path(root, requested))
        projected_sets.append(documents)
        for item in documents:
            _expect(item.get("metadata", {}).get("annotations", {}).get("openkubes.io/intent-revision"), revision, "object R carrier")
    _expect(len(projected_sets[0]), 8, "management object count")
    _expect(len(projected_sets[1]), 3, "infrastructure prerequisite count")
    if any(item.get("apiVersion", "").split("/", 1)[0] in V2.CAPI_GROUPS for item in projected_sets[1]):
        raise V1.HarnessError("CAPI lifecycle resource escaped to ok-infra")

    condition = document["conditions"]
    condition_profile = V1.read_yaml_or_json(_path(root, condition["profilePath"]))
    _expect(V1.semantic_revision(condition_profile), condition["profileDigest"], "condition profile")
    _expect(condition_profile["requiredConditions"], spec["conditions"]["required"], "condition membership")
    evidence = document["evidence"]
    evidence_bytes = _path(root, evidence["schemaPath"]).read_bytes()
    _expect(V1.sha256_bytes(evidence_bytes), evidence["schemaDigest"], "evidence schema digest")

    tools = document["tools"]
    _expect(V1.sha256_bytes(HARNESS_DIR.joinpath("ok141_platform_source_amendment.py").read_bytes()), tools["platformSourceAmendmentToolDigest"], "Platform source tool digest")
    _expect(V1.sha256_bytes(Path(__file__).read_bytes()), tools["phaseRV4ToolDigest"], "Phase-R v4 tool digest")
    ids = {item.get("id") for item in document["negativeControls"]}
    _expect(ids, V1.NEGATIVE_CONTROL_IDS, "negative controls")
    if any(item.get("expectedReady") == "True" for item in document["negativeControls"]):
        raise V1.HarnessError("negative control expects Ready=True")

    digest_input = copy.deepcopy(document)
    declared = digest_input.pop("fixtureDigest", None)
    digest = V1.semantic_revision(digest_input)
    if declared is not None:
        _expect(digest, declared, "FixtureDigest")
    if digest in {revision, p_revision, supersedes["fixtureDigest"]}:
        raise V1.HarnessError("FixtureDigest is not distinct")
    return digest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(validate(V1.read_yaml_or_json(args.input), args.root))
        return 0
    except (V1.HarnessError, OSError, ValueError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
