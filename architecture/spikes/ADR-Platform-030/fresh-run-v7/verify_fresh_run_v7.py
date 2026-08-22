#!/usr/bin/env python3
"""Fail-closed offline verification for the OK-141 fresh-run v7 package."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

import generate_fresh_run_v7 as generator


SEQUENCE = [
    "provider-prerequisites", "cluster-lifecycle", "lifecycle-observation",
    "enablement", "network-observation", "runtime-binding", "target-access",
    "target-credential", "target-registration", "platform-applications",
    "platform-observation", "aggregate-evidence",
]


class VerificationError(ValueError):
    pass


def expect(actual: object, expected: object, claim: str) -> None:
    if actual != expected:
        raise VerificationError(f"{claim} mismatch")


def verify(root: Path) -> str:
    root = root.resolve()
    manifest = json.loads((root / "package-manifest.json").read_text())
    plan = json.loads((root / "staged-plan.json").read_text())
    expect(manifest["format"], "ok141-fresh-run-package/v7", "package format")
    expect(manifest["authorizationState"], "NO-GO", "package authorization")
    expect(plan["authorizationState"], "NO-GO", "plan authorization")
    expect(manifest["phaseRFixture"], generator.FIXTURE, "fixture")
    expect((manifest["intentRevision"], manifest["enablementRevision"], manifest["platformRevision"]), (generator.R, generator.E, generator.P), "R/E/P")
    if not generator.RUNNER_IMAGE.fullmatch(manifest["runnerImage"]):
        raise VerificationError("runner image is not pinned by digest")
    receipt_path = root / manifest["runnerProvenance"]["receiptPath"]
    receipt_bytes = receipt_path.read_bytes()
    receipt = json.loads(receipt_bytes)
    expect(generator.digest_bytes(receipt_bytes), manifest["runnerProvenance"]["receiptDigest"], "runner receipt digest")
    expect(receipt["format"], generator.RUNNER_RECEIPT_FORMAT, "runner receipt format")
    expect(receipt["sourceSha"], generator.RUNNER_SOURCE_SHA, "runner source SHA")
    expect(f"{receipt['image']}@{receipt['digest']}", manifest["runnerImage"], "runner image provenance")
    expect(receipt["pullbackByDigestVerified"], True, "runner digest pullback")
    expect(receipt["deploymentPerformed"], False, "runner publish deployment boundary")
    expect(receipt["clusterContactPerformed"], False, "runner publish cluster boundary")
    for key in (
        "sourceSha", "workflowRunUrl", "publicationContractDigest",
        "githubAttestationVerificationDigest", "pullbackByDigestVerified",
    ):
        expect(manifest["runnerProvenance"][key], receipt[key], f"runner provenance {key}")
    expect(manifest["planDigest"], generator.semantic_digest(plan), "plan digest")
    expect([item["id"] for item in plan["stages"]], SEQUENCE, "stage sequence")
    for index, stage in enumerate(plan["stages"]):
        expect(stage["order"], index + 1, f"stage {stage['id']} order")
        expect(stage["requires"], [] if index == 0 else [SEQUENCE[index - 1]], f"stage {stage['id']} predecessor")
        expected_inputs = 2 if stage["id"] == "cluster-lifecycle" else 1
        if len(stage["inputs"]) != expected_inputs:
            raise VerificationError(f"stage {stage['id']} immutable input count mismatch")
    expect(
        [item["name"] for item in plan["stages"][1]["inputs"]],
        ["projection.cluster-lifecycle", "stage.provider-access"],
        "cluster-lifecycle input order",
    )

    projection_claim = manifest["activationProjection"]
    projection_manifest_path = root / projection_claim["manifestPath"]
    projection_manifest_bytes = projection_manifest_path.read_bytes()
    projection = json.loads(projection_manifest_bytes)
    expect(generator.digest_bytes(projection_manifest_bytes), projection_claim["manifestDigest"], "activation projection manifest digest")
    expect(projection["format"], projection_claim["format"], "activation projection format")
    expect(projection["authorizationState"], "NO-GO", "activation projection authorization")
    expect(projection["R"], generator.R, "activation projection R")
    expect(projection["objectSets"], projection_claim["objectSets"], "activation projection object sets")
    projection_root = projection_manifest_path.parent
    for name, claimed in projection["artifacts"].items():
        expect(generator.digest_bytes((projection_root / name).read_bytes()), claimed, f"activation projection artifact {name}")
    projection_management = generator.load_documents(root / projection_claim["managementObjectsPath"])
    projection_infrastructure = generator.load_documents(root / projection_claim["infrastructurePrerequisitesPath"])
    expect(len(projection_management), 8, "activation management membership")
    expect(len(projection_infrastructure), 3, "activation infrastructure membership")
    expect(generator.semantic_digest(projection_management), projection["objectSets"]["okMgmtLifecycle"]["digest"], "activation management semantic digest")
    expect(generator.semantic_digest(projection_infrastructure), projection["objectSets"]["okInfraPrerequisites"]["digest"], "activation infrastructure semantic digest")
    expect(
        generator.digest_bytes((root / projection_claim["managementObjectsPath"]).read_bytes()),
        manifest["artifacts"]["cluster-lifecycle.yaml"],
        "activation lifecycle equals staged lifecycle",
    )
    if any(
        item.get("metadata", {}).get("annotations", {}).get("openkubes.io/intent-revision") != generator.R
        for item in projection_management + projection_infrastructure
    ):
        raise VerificationError("activation projection object lacks the exact R carrier")

    spike = root.parent
    locations = {
        **{name: root / "artifacts" / name for name in (
            "lifecycle-observation.json", "network-profile.json", "runtime-binding.json",
            "target-credential.json", "platform-profile.json", "aggregate-evidence-profile.json",
            "enablement.yaml", "target-access.yaml", "target-registration.yaml", "platform-applications.yaml",
            "cluster-lifecycle.yaml", "provider-access-policy.json",
        )},
        "provider-prerequisites.yaml": spike / "harness/projections/phase-r-v6/ok-infra-prerequisites.yaml",
    }
    for name, claimed in manifest["artifacts"].items():
        path = locations.get(name)
        if path is None or not path.is_file():
            raise VerificationError(f"unknown or missing artifact {name}")
        expect(generator.digest_bytes(path.read_bytes()), claimed, f"artifact {name}")

    lifecycle = generator.load_documents(locations["cluster-lifecycle.yaml"])
    kubevirt_cluster = next(item for item in lifecycle if item.get("kind") == "KubevirtCluster")
    expect(
        kubevirt_cluster["spec"]["controlPlaneServiceTemplate"]["metadata"]["annotations"],
        {"metallb.io/loadBalancerIPs": generator.WORKLOAD_API_ADDRESS},
        "workload API allocation carrier",
    )
    provider_policy = json.loads(locations["provider-access-policy.json"].read_text())
    expect(provider_policy, generator.build_provider_access_policy(), "provider-access policy")
    expect(
        plan["stages"][1]["inputs"][1]["digest"],
        generator.digest_bytes(locations["provider-access-policy.json"].read_bytes()),
        "provider-access staged digest",
    )

    hcp = generator.load_documents(locations["enablement.yaml"])
    expect(len(hcp), 1, "HCP count")
    annotations = hcp[0]["metadata"]["annotations"]
    for key, value in {
        "openkubes.io/contract-name": "disposable-ok141",
        "openkubes.io/contract-namespace": "disposable-ok141",
        "openkubes.io/intent-revision": generator.R,
        "openkubes.io/enablement-revision": generator.E,
        "openkubes.io/execution-fixture": generator.FIXTURE,
    }.items():
        expect(annotations.get(key), value, f"HCP carrier {key}")
    if hcp[0]["spec"].get("reconcileStrategy") != "Continuous":
        raise VerificationError("HCP is not continuously reconciled")

    target_access = generator.load_documents(locations["target-access.yaml"])
    expect(len(target_access), 8, "target-access membership")
    cluster_role = next(item for item in target_access if item["kind"] == "ClusterRole")
    serialized_rules = json.dumps(cluster_role["rules"], sort_keys=True)
    if '"*"' in serialized_rules:
        raise VerificationError("target-access contains wildcard RBAC")
    if "selfsubjectaccessreviews" not in serialized_rules or "escalate" not in serialized_rules or "bind" not in serialized_rules:
        raise VerificationError("target-access lacks proven Argo strict-cache RBAC")

    policy = json.loads(locations["target-credential.json"].read_text())
    expect(policy["targetIdentityDigest"], generator.TARGET_PLACEHOLDER, "credential target placeholder")
    registration = generator.load_documents(locations["target-registration.yaml"])
    expect(len(registration), 2, "registration membership")
    applications = generator.load_documents(locations["platform-applications.yaml"])
    expect(len(applications), 3, "Application membership")
    for item in registration + applications:
        annotations = item["metadata"].get("annotations", {})
        expect(annotations.get("openkubes.io/target-identity-digest"), generator.TARGET_PLACEHOLDER, f"{item['kind']} target placeholder")

    network = json.loads(locations["network-profile.json"].read_text())
    platform = json.loads(locations["platform-profile.json"].read_text())
    aggregate = json.loads(locations["aggregate-evidence-profile.json"].read_text())
    expect(generator.semantic_digest(network), manifest["semanticDigests"]["networkProfile"], "network profile")
    expect(generator.semantic_digest(platform), manifest["semanticDigests"]["platformProfile"], "platform profile")
    expect(generator.ordered_json_digest(aggregate), manifest["semanticDigests"]["aggregateEvidenceProfile"], "aggregate profile")
    expectations = {item["name"]: item["specDigest"] for item in platform["requiredApplications"]}
    for application in applications:
        expect(generator.platform_spec_digest(application["spec"]), expectations[application["metadata"]["name"]], "Application spec identity")

    expect(manifest["boundaries"], {
        "clusterContact": False,
        "mutationAuthorized": False,
        "credentialsIncluded": False,
        "runtimeTargetIdentityMaterialized": False,
    }, "package boundary")
    expect(manifest["runtimeNetwork"], {
        "allocationMode": "dev-static-preflight-required",
        "workloadAPI": {"address": generator.WORKLOAD_API_ADDRESS, "cidr": generator.WORKLOAD_API_CIDR, "port": 6443},
        "evidenceCollector": {"address": generator.EVIDENCE_COLLECTOR_ADDRESS, "cidr": generator.EVIDENCE_COLLECTOR_CIDR, "port": 8443},
        "allocationAuthority": "ok-infra/MetalLB",
    }, "runtime network binding")
    return manifest["planDigest"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=generator.HERE)
    args = parser.parse_args()
    try:
        print(verify(args.root))
        return 0
    except (OSError, KeyError, TypeError, VerificationError, json.JSONDecodeError, yaml.YAMLError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
