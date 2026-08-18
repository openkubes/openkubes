#!/usr/bin/env python3
"""Generate the consolidated, still-NO-GO OK-141 Phase-R v6 fixture."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import yaml


HERE = Path(__file__).resolve().parent


def _module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(result)
    return result


V6 = _module("ok141_phase_r_v6_generator", HERE / "ok141_phase_r_v6.py")
V1 = V6.V1
AMENDMENTS = [
    ("platform-ssa-v1", "../go1-platform-ssa-amendment-v1/platform-ssa-amendment-v1.json", "sha256:e83ddec6908ca416d0ddc718a5652ba5db2b4950c26deff1da1ae03b908f028c"),
    ("platform-ssa-migration-v1", "../go1-platform-ssa-migration-amendment-v1/platform-ssa-migration-amendment-v1.json", "sha256:ad13f4e233a25fe4aa252bd0013f3257c8003f78955a133501a117997462feed"),
    ("platform-defaulting-diff-v1", "../go1-platform-defaulting-diff-amendment-v1/platform-defaulting-diff-amendment-v1.json", "sha256:3ad6f2dbe82da2abc15e8dc44bbf2aabf5afcfd8cb54b54b2d2807fd815b7eba"),
    ("capability-name-boundary-v1", "../go1-capability-name-boundary-amendment-v1/capability-name-boundary-amendment-v1.json", V6.CAPABILITY_AMENDMENT_DIGEST),
]


def _documents(path: Path) -> list[dict]:
    return [item for item in yaml.load_all(path.read_text(), Loader=V1.UniqueKeyLoader) if item]


def main() -> None:
    historical = json.loads((HERE / "fixtures/execution/phase-r-v5.json").read_text())
    contract_path = HERE / "fixtures/contracts-v9/base.yaml"
    contract_schema_path = HERE / "schema/contract-v3.schema.json"
    contract, revision = V6.V5.load_contract(contract_path, contract_schema_path)
    if revision != V6.R9:
        raise RuntimeError("contract-v9 no longer reproduces R9")

    platform_dir = HERE / "profiles/platform/minimal-observability-v9"
    profile = json.loads((platform_dir / "profile.json").read_text())
    applications = _documents(platform_dir / "applications.yaml")
    values = V1.read_yaml_or_json(platform_dir / "provider-values.yaml")
    if V1.semantic_revision(profile) != V6.P9:
        raise RuntimeError("Platform v9 no longer reproduces P9")

    projection_manifest_path = HERE / "projections/phase-r-v6/projection-manifest.json"
    projection_manifest = json.loads(projection_manifest_path.read_text())
    if projection_manifest["R"] != V6.R9:
        raise RuntimeError("Phase-R v6 projection does not carry R9")

    document = copy.deepcopy(historical)
    document.update({
        "format": V6.FORMAT,
        "fixtureVersion": V6.VERSION,
        "authorizationState": "NO-GO",
        "supersedes": {
            "fixtureVersion": "phase-r-v5",
            "fixtureDigest": V6.PHASE_R_V5_DIGEST,
            "disposition": "valid-historical-superseded-not-mutated",
            "reason": "The additive live amendments through capability-name-boundary-v1 are consolidated into one complete offline fixture and projection for future runner planning.",
        },
        "consolidates": [
            {"name": name, "path": path, "fixtureDigest": digest, "disposition": "valid-historical-source-evidence"}
            for name, path, digest in AMENDMENTS
        ],
        "contractIdentity": contract["metadata"],
        "contract": {
            "path": "fixtures/contracts-v9/base.yaml",
            "schemaPath": "schema/contract-v3.schema.json",
            "canonicalizationProfile": "openkubes-contract-c14n/v1",
            "rawArtifactDigest": V1.sha256_bytes(contract_path.read_bytes()),
            "schemaDigest": V1.sha256_bytes(contract_schema_path.read_bytes()),
            "R": revision,
        },
        "clusterSemantics": {key: contract["spec"][key] for key in ("kubernetesVersion", "infrastructure", "operatingSystem", "topology", "connectivity")},
        "projection": {
            "format": V6.V5.PROJECTION_VERSION,
            "manifestPath": "projections/phase-r-v6/projection-manifest.json",
            "manifestDigest": V1.sha256_bytes(projection_manifest_path.read_bytes()),
            "authorityMapPath": "projections/phase-r-v6/authority-map.json",
            "managementObjectsPath": "projections/phase-r-v6/ok-mgmt-lifecycle.yaml",
            "infrastructurePrerequisitesPath": "projections/phase-r-v6/ok-infra-prerequisites.yaml",
            "objectSets": projection_manifest["objectSets"],
        },
        "platform": {
            "profilePath": "profiles/platform/minimal-observability-v9/profile.json",
            "applicationsPath": "profiles/platform/minimal-observability-v9/applications.yaml",
            "providerValuesPath": "profiles/platform/minimal-observability-v9/provider-values.yaml",
            "profile": "minimal-observability-v9",
            "P": V6.P9,
            "applicationSetDigest": V1.semantic_revision(applications),
            "providerValuesDigest": V1.semantic_revision(values),
            "sourceCommit": "c09c18759aeb7526d22106ccb001599f5f06bc4e",
            "immutableTargetIdentityScheme": "capi-cluster-uid/v1",
            "convergenceOwnerCandidate": "argo-cd",
            "candidateStatus": "execution-proven-for-historical-run-fresh-run-not-yet-performed",
            "registrationAndRBAC": "outside-P-runtime-materialized-and-separately-gated",
        },
        "positiveAssertions": [
            {"id": "PA-R", "claim": "The consolidated Cluster contract reproduces R9."},
            {"id": "PA-PROJECTION", "claim": "Every projected lifecycle and prerequisite object carries R9."},
            {"id": "PA-PROVIDER-AUTHORITY", "claim": "The KubevirtCluster explicitly references the per-cluster external ok-infra credential identity while credential material remains outside the fixture."},
            {"id": "PA-E", "claim": "The target-bound Enablement profile reproduces E-prime."},
            {"id": "PA-P", "claim": "The capability-name-corrected Platform profile, exact Application membership and authoritative source closure reproduce P9."},
            {"id": "PA-CONSOLIDATION", "claim": "The SSA, migration, API-defaulting and capability-name amendments are bound as historical source evidence without mutation."},
            {"id": "PA-BOUNDARY", "claim": "Provider credentials, target registration credentials and runtime target identity remain separately gated and absent from the public fixture."},
        ],
    })
    document["expectedEvidence"]["platform"] = [
        "exact three-Application membership",
        "P9",
        "authoritative package and capability-script closure",
        "current applied commit",
        "current Synced and Healthy",
        "current capability-check evidence",
    ]
    document["fixtureSchema"] = {
        "path": "schema/execution-fixture-v6.schema.json",
        "digest": V1.sha256_bytes((HERE / "schema/execution-fixture-v6.schema.json").read_bytes()),
    }
    document["tools"] = {
        **{key: value for key, value in historical["tools"].items() if key != "phaseRV5ToolDigest"},
        "phaseRV6ToolDigest": V1.sha256_bytes((HERE / "ok141_phase_r_v6.py").read_bytes()),
    }
    document.pop("fixtureDigest", None)
    document["fixtureDigest"] = V1.semantic_revision(document)
    output = HERE / "fixtures/execution/phase-r-v6.json"
    output.write_text(json.dumps(document, indent=2, sort_keys=False) + "\n")
    print(document["fixtureDigest"])


if __name__ == "__main__":
    main()
