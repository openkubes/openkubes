#!/usr/bin/env python3
"""Offline verifier for the consolidated OK-141 Phase-R v6 fixture."""

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


def _module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(result)
    return result


V5 = _module("ok141_phase_r_v5_for_v6", HARNESS_DIR / "ok141_phase_r_v5.py")
V1 = V5.V1
FORMAT = "ok141-execution-fixture/v6"
VERSION = "phase-r-v6"
P9 = "sha256:2956184005f4860607e91672fce82164095dee6ebcbe57e5af883951a199c427"
R9 = "sha256:47bb651f6bc0bdb3a7a567efcd4ca4c776f872a63496fa55c2a6aed77d6fa995"
PHASE_R_V5_DIGEST = "sha256:7536456a762880a78a37dcba76a5f3f0628140bd37b55d5fd62273c64e4cc3eb"
CAPABILITY_AMENDMENT_DIGEST = "sha256:11133538388c3562f135e814ba4560b76d9ffcb0dac6dab5019f7d75c5a71178"


def _expect(actual: Any, expected: Any, claim: str) -> None:
    if actual != expected:
        raise V1.HarnessError(f"Phase-R v6 {claim} mismatch")


def _path(root: Path, requested: str) -> Path:
    candidate = (root / requested).resolve()
    if root not in candidate.parents or not candidate.is_file():
        raise V1.HarnessError(f"fixture input is missing or outside root: {requested}")
    return candidate


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
    _expect(supersedes["fixtureVersion"], "phase-r-v5", "superseded version")
    _expect(supersedes["fixtureDigest"], PHASE_R_V5_DIGEST, "superseded digest")
    _expect(supersedes["disposition"], "valid-historical-superseded-not-mutated", "superseded disposition")
    consolidated = {item["fixtureDigest"] for item in document["consolidates"]}
    if CAPABILITY_AMENDMENT_DIGEST not in consolidated:
        raise V1.HarnessError("Phase-R v6 does not bind the capability-name amendment")
    spike_root = root.parent.resolve()
    for item in document["consolidates"]:
        amendment_path = (root / item["path"]).resolve()
        if spike_root not in amendment_path.parents or not amendment_path.is_file():
            raise V1.HarnessError("consolidated amendment is missing or outside the spike root")
        amendment = json.loads(amendment_path.read_text())
        declared_amendment_digest = amendment.get("spec", amendment).get("fixtureDigest")
        _expect(declared_amendment_digest, item["fixtureDigest"], f"{item['name']} amendment digest")

    contract_claim = document["contract"]
    contract_path = _path(root, contract_claim["path"])
    contract_schema_path = _path(root, contract_claim["schemaPath"])
    contract, revision = V5.load_contract(contract_path, contract_schema_path)
    _expect(V1.sha256_bytes(contract_path.read_bytes()), contract_claim["rawArtifactDigest"], "raw contract digest")
    _expect(V1.sha256_bytes(contract_schema_path.read_bytes()), contract_claim["schemaDigest"], "contract schema digest")
    _expect(revision, R9, "R9")
    _expect(revision, contract_claim["R"], "R")
    _expect(contract["metadata"], document["contractIdentity"], "contract identity")
    spec = contract["spec"]
    _expect(document["clusterSemantics"], {key: spec[key] for key in ("kubernetesVersion", "infrastructure", "operatingSystem", "topology", "connectivity")}, "cluster semantics")

    platform = document["platform"]
    profile = json.loads(_path(root, platform["profilePath"]).read_text())
    applications = _documents(_path(root, platform["applicationsPath"]))
    values = V1.read_yaml_or_json(_path(root, platform["providerValuesPath"]))
    _expect(profile["format"], "ok141-platform-profile/v8", "Platform format")
    _expect(profile["profile"], "minimal-observability-v9", "Platform profile")
    _expect(V1.semantic_revision(profile), P9, "P9")
    _expect(platform["P"], P9, "P")
    _expect(spec["platform"], {"profile": platform["profile"], "revision": P9}, "contract Platform identity")
    _expect(V1.semantic_revision(applications), platform["applicationSetDigest"], "Application set digest")
    _expect(V1.semantic_revision(values), platform["providerValuesDigest"], "Provider Values digest")
    by_name = {item["metadata"]["name"]: item for item in applications}
    leaves = {item["name"]: item for item in profile["requiredApplications"]}
    _expect(set(by_name), set(leaves), "Application membership")
    for name, leaf in leaves.items():
        _expect(V1.semantic_revision(by_name[name]), leaf["applicationDigest"], f"{name} Application digest")
    _expect({leaf["source"]["commit"] for leaf in leaves.values()}, {platform["sourceCommit"]}, "Platform source commit")
    _expect({app["spec"]["source"]["targetRevision"] for app in applications}, {platform["sourceCommit"]}, "Application target revisions")
    _expect(profile["target"]["immutableIdentityReference"]["scheme"], platform["immutableTargetIdentityScheme"], "target identity scheme")

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
    _expect(manifest["format"], V5.PROJECTION_VERSION, "projection format")
    _expect(manifest["R"], revision, "projection R")
    _expect(manifest["source"]["okClusterCommit"], V5.OK_CLUSTER_COMMIT, "projection source commit")
    _expect(manifest["source"]["okLinuxCommit"], V5.OK_LINUX_COMMIT, "ok-linux source commit")
    _expect(manifest["objectSets"], projection["objectSets"], "object sets")
    projection_dir = manifest_path.parent
    for artifact, digest in manifest["artifacts"].items():
        _expect(V1.sha256_bytes((projection_dir / artifact).read_bytes()), digest, f"projection artifact {artifact}")
    authority = json.loads(_path(root, projection["authorityMapPath"]).read_text())
    _expect(authority["intentRevision"], revision, "authority R")
    _expect(authority["managementPlane"]["identity"], "ok-mgmt", "management authority")
    _expect(authority["infrastructurePlane"]["identity"], "ok-infra", "infrastructure authority")
    management = _documents(_path(root, projection["managementObjectsPath"]))
    infrastructure = _documents(_path(root, projection["infrastructurePrerequisitesPath"]))
    _expect(len(management), 8, "management object count")
    _expect(len(infrastructure), 3, "infrastructure prerequisite count")
    for item in management + infrastructure:
        _expect(item.get("metadata", {}).get("annotations", {}).get("openkubes.io/intent-revision"), revision, "object R carrier")
    if any(item.get("kind") == "Secret" for item in management + infrastructure):
        raise V1.HarnessError("credential materialization escaped into projection")

    condition = document["conditions"]
    condition_profile = V1.read_yaml_or_json(_path(root, condition["profilePath"]))
    _expect(V1.semantic_revision(condition_profile), condition["profileDigest"], "condition profile")
    _expect(condition_profile["requiredConditions"], spec["conditions"]["required"], "condition membership")
    evidence = document["evidence"]
    evidence_bytes = _path(root, evidence["schemaPath"]).read_bytes()
    _expect(V1.sha256_bytes(evidence_bytes), evidence["schemaDigest"], "evidence schema digest")
    _expect(V1.sha256_bytes(HARNESS_DIR.joinpath("ok141_phase_r_v6.py").read_bytes()), document["tools"]["phaseRV6ToolDigest"], "Phase-R v6 tool digest")
    _expect({item.get("id") for item in document["negativeControls"]}, V1.NEGATIVE_CONTROL_IDS, "negative controls")
    if any(item.get("expectedReady") == "True" for item in document["negativeControls"]):
        raise V1.HarnessError("negative control expects Ready=True")

    digest_input = copy.deepcopy(document)
    declared = digest_input.pop("fixtureDigest", None)
    digest = V1.semantic_revision(digest_input)
    if declared is not None:
        _expect(digest, declared, "FixtureDigest")
    if digest in {revision, P9, PHASE_R_V5_DIGEST, CAPABILITY_AMENDMENT_DIGEST}:
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
    except (V1.HarnessError, OSError, ValueError, yaml.YAMLError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
