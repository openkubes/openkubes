#!/usr/bin/env python3
"""Generate the immutable, non-authorizing OK-141 fresh-run v4 package."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

import yaml


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
HARNESS = SPIKE / "harness"
ARTIFACTS = HERE / "artifacts"

R = "sha256:47bb651f6bc0bdb3a7a567efcd4ca4c776f872a63496fa55c2a6aed77d6fa995"
E = "sha256:2a849d69e9c64344e907c1bce3bb1abf3d8f77217377081a5be055d62c213300"
P = "sha256:2956184005f4860607e91672fce82164095dee6ebcbe57e5af883951a199c427"
FIXTURE = "sha256:438a6882d8e22b644c826cb0a6f2856850afd7c7ef71badb44cd66e8db0393ec"
TARGET_PLACEHOLDER = "RUNTIME-TARGET-IDENTITY-DIGEST-REQUIRED"
SOURCE_REPOSITORY = "https://github.com/openkubes/ok-observability.git"
RUNNER_IMAGE = re.compile(r"^ghcr\.io/openkubes/ok-cluster-runner@sha256:[0-9a-f]{64}$")
RUNNER_SOURCE_SHA = "a963f6bf887871e3653b33e5d17b0c53f5d10248"
RUNNER_RECEIPT_FORMAT = "ok147-runner-publication-receipt/v1"


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def digest_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def semantic_digest(value: object) -> str:
    return digest_bytes(canonical(value))


def ordered_json_digest(value: object) -> str:
    """Match Go json.Marshal for structs whose field order is normative."""
    return digest_bytes(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode())


def load_documents(path: Path) -> list[dict]:
    return [item for item in yaml.safe_load_all(path.read_text()) if item]


def dump_documents(path: Path, documents: list[dict]) -> None:
    path.write_text(yaml.safe_dump_all(documents, sort_keys=False, explicit_start=False))


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=False) + "\n")


def exact_annotations() -> dict[str, str]:
    return {
        "openkubes.io/intent-revision": R,
        "openkubes.io/platform-revision": P,
        "openkubes.io/execution-fixture": FIXTURE,
        "openkubes.io/target-identity-digest": TARGET_PLACEHOLDER,
    }


def selected_digest(spec: dict, keys: list[str]) -> str:
    return semantic_digest({key: spec.get(key) for key in keys})


def platform_spec_digest(spec: dict) -> str:
    source = spec["source"]
    destination = spec["destination"]
    normalized = {
        "project": spec["project"],
        "source": source,
        "destination": {"name": destination["name"], "namespace": destination["namespace"]},
    }
    for key in ("syncPolicy", "ignoreDifferences"):
        if key in spec:
            normalized[key] = spec[key]
    return semantic_digest(normalized)


def build_enablement() -> tuple[dict, str, str]:
    source = SPIKE / "go1-l-hcp-v1/helmchartproxy-phase-r-v5-candidate.yaml"
    hcp = load_documents(source)[0]
    annotations = hcp["metadata"]["annotations"]
    annotations.update({
        "openkubes.io/candidate-status": "fresh-run-v6-no-go",
        "openkubes.io/contract-name": "disposable-ok141",
        "openkubes.io/contract-namespace": "disposable-ok141",
        "openkubes.io/intent-revision": R,
        "openkubes.io/enablement-revision": E,
        "openkubes.io/execution-fixture": FIXTURE,
    })
    spec = hcp["spec"]
    hcp_digest = selected_digest(spec, [
        "chartName", "repoURL", "version", "releaseName", "namespace",
        "reconcileStrategy", "valuesTemplate", "options",
    ])
    hrp_spec = {
        "chartName": spec["chartName"],
        "repoURL": spec["repoURL"],
        "version": spec["version"],
        "releaseName": spec["releaseName"],
        "namespace": spec["namespace"],
        "reconcileStrategy": spec["reconcileStrategy"],
        "values": spec["valuesTemplate"],
        "clusterRef": {
            "apiVersion": "cluster.x-k8s.io/v1beta2",
            "kind": "Cluster",
            "namespace": "disposable-ok141",
            "name": "disposable-ok141",
        },
    }
    hrp_digest = selected_digest(hrp_spec, [
        "chartName", "repoURL", "version", "releaseName", "namespace",
        "reconcileStrategy", "values", "clusterRef",
    ])
    return hcp, hcp_digest, hrp_digest


def build_target_access() -> list[dict]:
    documents = load_documents(SPIKE / "m0b-target-registration-v1/target-access-v1.template.yaml")
    for document in documents:
        annotations = document.setdefault("metadata", {}).setdefault("annotations", {})
        annotations.update({
            "openkubes.io/candidate-status": "fresh-run-v6-no-go",
            "openkubes.io/intent-revision": R,
            "openkubes.io/platform-revision": P,
            "openkubes.io/execution-fixture": FIXTURE,
        })
    cluster_role = next(item for item in documents if item["kind"] == "ClusterRole")
    cluster_role["rules"].extend([
        {
            "apiGroups": ["authorization.k8s.io"],
            "resources": ["selfsubjectaccessreviews"],
            "verbs": ["create"],
        },
        {
            "apiGroups": ["rbac.authorization.k8s.io"],
            "resources": ["clusterroles"],
            "resourceNames": [
                "disposable-ok141-observability-core-kube-state-metrics",
                "ok-observability-grafana-clusterrole",
                "ok-observability-log-collector",
                "ok-observability-operator",
                "ok-observability-prometheus",
            ],
            "verbs": ["bind", "escalate"],
        },
    ])
    return documents


def build_registration() -> list[dict]:
    project = load_documents(SPIKE / "m0b-target-registration-v1/appproject-v5-candidate.yaml")[0]
    secret = load_documents(SPIKE / "m0b-target-registration-v1/cluster-registration-v5.template.yaml")[0]
    project["metadata"]["annotations"] = exact_annotations()
    project["spec"]["description"] = "Fresh-run-v6 OK-141 P9 AppProject"
    secret["metadata"]["annotations"] = {
        **exact_annotations(),
        "openkubes.io/capi-cluster-uid": "RUNTIME-CAPI-UID-REQUIRED",
        "openkubes.io/workload-kube-system-uid": "RUNTIME-WORKLOAD-KUBE-SYSTEM-UID-REQUIRED",
        "openkubes.io/workload-api-ca-sha256": "RUNTIME-WORKLOAD-CA-DIGEST-REQUIRED",
        "openkubes.io/token-expiration": "RUNTIME-TOKEN-EXPIRATION-REQUIRED",
    }
    secret["stringData"]["config"] = "RUNTIME-IN-MEMORY-MATERIALIZATION-ONLY"
    return [project, secret]


def build_applications() -> tuple[list[dict], list[dict]]:
    applications = load_documents(HARNESS / "profiles/platform/minimal-observability-v9/applications.yaml")
    expectations = []
    for application in applications:
        application["metadata"] = {
            "name": application["metadata"]["name"],
            "namespace": "argocd",
            "annotations": exact_annotations(),
        }
        expectations.append({
            "name": application["metadata"]["name"],
            "specDigest": platform_spec_digest(application["spec"]),
        })
    return applications, sorted(expectations, key=lambda item: item["name"])


def build_plan(inputs: dict[str, str]) -> dict:
    rules = [
        ("provider-prerequisites", "Submission", "infrastructure", "CreateProviderPrerequisites"),
        ("cluster-lifecycle", "Submission", "management", "CreateCluster"),
        ("lifecycle-observation", "Observation", "management", ""),
        ("enablement", "Submission", "management", "CreateEnablement"),
        ("network-observation", "Observation", "workload", ""),
        ("runtime-binding", "Binding", "runner", ""),
        ("target-access", "Submission", "workload", "CreateTargetAccess"),
        ("target-credential", "Credential", "workload", "IssueTargetCredential"),
        ("target-registration", "Submission", "gitops", "RegisterTarget"),
        ("platform-applications", "Submission", "gitops", "CreatePlatformApplications"),
        ("platform-observation", "Observation", "gitops", ""),
        ("aggregate-evidence", "Evaluation", "runner", ""),
    ]
    stages = []
    for index, (stage_id, kind, authority, operation) in enumerate(rules):
        stage = {
            "id": stage_id,
            "order": index + 1,
            "kind": kind,
            "authority": authority,
            "requires": [] if index == 0 else [rules[index - 1][0]],
            "inputs": [{"name": inputs[stage_id][0], "digest": inputs[stage_id][1]}],
        }
        if operation:
            stage["grantOperation"] = operation
        stages.append(stage)
    return {
        "format": "ok147-staged-execution-plan/v1",
        "contractIdentity": {"namespace": "disposable-ok141", "name": "disposable-ok141"},
        "intentRevision": R,
        "enablementRevision": E,
        "platformRevision": P,
        "executionFixture": FIXTURE,
        "authorizationState": "NO-GO",
        "authorities": {
            "infrastructure": "ok-infra",
            "management": "ok-mgmt",
            "gitOps": "ok-shared",
            "workloadIdentityMode": "capi-cluster-uid/v1",
            "runnerIdentityMode": "bounded-job/v1",
        },
        "stages": stages,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runner-image", required=True)
    parser.add_argument("--runner-publication-receipt", required=True, type=Path)
    args = parser.parse_args()
    if not RUNNER_IMAGE.fullmatch(args.runner_image):
        raise SystemExit("runner image must be pinned by sha256 digest")
    receipt_bytes = args.runner_publication_receipt.read_bytes()
    receipt = json.loads(receipt_bytes)
    receipt_image = f"{receipt.get('image')}@{receipt.get('digest')}"
    if receipt.get("format") != RUNNER_RECEIPT_FORMAT:
        raise SystemExit("runner publication receipt format mismatch")
    if receipt.get("sourceSha") != RUNNER_SOURCE_SHA:
        raise SystemExit("runner publication receipt source SHA mismatch")
    if receipt_image != args.runner_image:
        raise SystemExit("runner publication receipt image mismatch")
    if receipt.get("pullbackByDigestVerified") is not True:
        raise SystemExit("runner publication receipt lacks digest pullback proof")
    if receipt.get("deploymentPerformed") is not False or receipt.get("clusterContactPerformed") is not False:
        raise SystemExit("runner publication receipt crosses the offline boundary")
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    (HERE / "runner-publication-receipt.json").write_bytes(receipt_bytes)

    fixture = json.loads((HARNESS / "fixtures/execution/phase-r-v6.json").read_text())
    if fixture["fixtureDigest"] != FIXTURE or fixture["contract"]["R"] != R or fixture["enablement"]["E"] != E or fixture["platform"]["P"] != P:
        raise SystemExit("Phase-R v6 identity mismatch")

    projection_dir = HARNESS / "projections/phase-r-v6"
    provider = (projection_dir / "ok-infra-prerequisites.yaml").read_bytes()
    lifecycle = (projection_dir / "ok-mgmt-lifecycle.yaml").read_bytes()

    hcp, hcp_spec_digest, hrp_spec_digest = build_enablement()
    dump_documents(ARTIFACTS / "enablement.yaml", [hcp])
    target_access = build_target_access()
    dump_documents(ARTIFACTS / "target-access.yaml", target_access)
    registration = build_registration()
    dump_documents(ARTIFACTS / "target-registration.yaml", registration)
    applications, expectations = build_applications()
    dump_documents(ARTIFACTS / "platform-applications.yaml", applications)

    lifecycle_policy = {
        "format": "ok141-lifecycle-observation-policy/v1",
        "intentRevision": R,
        "expectedControlPlaneReplicas": 1,
        "expectedWorkerReplicas": 1,
        "pollIntervalSeconds": 15,
        "pollTimeoutSeconds": 1800,
        "failClosedOnStaleGeneration": True,
    }
    runtime_policy = {
        "format": "ok141-runtime-binding-policy/v1",
        "intentRevision": R,
        "targetIdentityScheme": "capi-cluster-uid/v1",
        "requiredNamespace": "kube-system",
        "requiredStorageClass": "local-path",
        "persistence": "private-kubernetes-secret",
        "publicCredentialMaterial": False,
    }
    credential_policy = {
        "format": "ok147-target-credential-policy/v1",
        "targetIdentityDigest": TARGET_PLACEHOLDER,
        "serviceAccount": {"namespace": "kube-system", "name": "ok141-argocd-manager"},
        "requestedAudiences": [],
        "expirationSeconds": 10800,
        "credentialUse": "argocd-target-registration",
        "retention": "memory-only",
        "nativeRotation": False,
        "productionSuitable": False,
    }
    network_profile = {
        "format": "ok147-network-profile/v1",
        "intentRevision": R,
        "enablementRevision": E,
        "expectedNodeCount": 2,
        "expectedHcpSpecDigest": hcp_spec_digest,
        "expectedHrpSpecDigest": hrp_spec_digest,
        "expectedImages": {
            "ciliumAgent": "quay.io/cilium/cilium:v1.19.6@sha256:0df5b2750b64c49843aba1d649e9eaf61467cb0645ad3171db6f6962c095ac92",
            "ciliumEnvoy": "quay.io/cilium/cilium-envoy:v1.36.9-1782267392-edeb3f2af56c37c407efa1f63f0b32f595399bbc@sha256:767101fb8a5e38f055778cb43b7aa8eed80450b37f8121effac3d9de9e06dc99",
            "ciliumOperator": "quay.io/cilium/operator-generic:v1.19.6@sha256:0db4ca4e06969d8904ee036617795d0e9c3228cf7b8d902ba74fc2bb98d2d665",
        },
        "minimumProbeFreshnessSeconds": 30,
        "maximumProbeIntervalSeconds": 60,
        "cacheExposureSeconds": 30,
    }
    platform_profile = {
        "format": "ok147-platform-profile/v1",
        "intentRevision": R,
        "platformRevision": P,
        "executionFixture": FIXTURE,
        "targetIdentityScheme": "capi-cluster-uid/v1",
        "argoNamespace": "argocd",
        "registrationName": "disposable-ok141",
        "requiredApplications": expectations,
        "capabilityContractDigest": "sha256:b6ef10a8ecf6daf42e6d44018d51e2263f380ed649445e5a70ff5c550c73415e",
        "capabilityExecutableDigest": "sha256:98f41106b7ddc2f7ecffaca9bd9e3c3584d97ab41b169054d8be91ae9cdfb949",
        "maximumCapabilityAgeSeconds": 3600,
    }
    aggregate_profile = {
        "format": "ok147-aggregate-evidence-profile/v1",
        "intentRevision": R,
        "enablementRevision": E,
        "platformRevision": P,
        "executionFixture": FIXTURE,
        "required": ["InfrastructureReady", "ControlPlaneAvailable", "NetworkReady", "PlatformReady"],
    }
    json_artifacts = {
        "lifecycle-observation.json": lifecycle_policy,
        "network-profile.json": network_profile,
        "runtime-binding.json": runtime_policy,
        "target-credential.json": credential_policy,
        "platform-profile.json": platform_profile,
        "aggregate-evidence-profile.json": aggregate_profile,
    }
    for name, value in json_artifacts.items():
        write_json(ARTIFACTS / name, value)

    raw_digest = lambda name: digest_bytes((ARTIFACTS / name).read_bytes())
    inputs = {
        "provider-prerequisites": ("projection.provider-prerequisites", digest_bytes(provider)),
        "cluster-lifecycle": ("projection.cluster-lifecycle", digest_bytes(lifecycle)),
        "lifecycle-observation": ("stage.lifecycle-observation", raw_digest("lifecycle-observation.json")),
        "enablement": ("stage.enablement", raw_digest("enablement.yaml")),
        "network-observation": ("stage.network-observation", semantic_digest(network_profile)),
        "runtime-binding": ("stage.runtime-binding", raw_digest("runtime-binding.json")),
        "target-access": ("stage.target-access", raw_digest("target-access.yaml")),
        "target-credential": ("stage.target-credential", raw_digest("target-credential.json")),
        "target-registration": ("stage.target-registration", raw_digest("target-registration.yaml")),
        "platform-applications": ("stage.platform-applications", raw_digest("platform-applications.yaml")),
        "platform-observation": ("stage.platform-observation", semantic_digest(platform_profile)),
        "aggregate-evidence": ("stage.aggregate-evidence", ordered_json_digest(aggregate_profile)),
    }
    plan = build_plan(inputs)
    write_json(HERE / "staged-plan.json", plan)

    manifest = {
        "format": "ok141-fresh-run-package/v6",
        "authorizationState": "NO-GO",
        "phaseRFixture": FIXTURE,
        "intentRevision": R,
        "enablementRevision": E,
        "platformRevision": P,
        "runnerImage": args.runner_image,
        "runnerProvenance": {
            "receiptPath": "runner-publication-receipt.json",
            "receiptDigest": digest_bytes(receipt_bytes),
            "sourceSha": receipt["sourceSha"],
            "workflowRunUrl": receipt["workflowRunUrl"],
            "publicationContractDigest": receipt["publicationContractDigest"],
            "githubAttestationVerificationDigest": receipt["githubAttestationVerificationDigest"],
            "pullbackByDigestVerified": receipt["pullbackByDigestVerified"],
        },
        "planPath": "staged-plan.json",
        "planDigest": semantic_digest(plan),
        "artifacts": {name: digest_bytes(path.read_bytes()) for name, path in sorted({
            **{name: ARTIFACTS / name for name in json_artifacts},
            "enablement.yaml": ARTIFACTS / "enablement.yaml",
            "target-access.yaml": ARTIFACTS / "target-access.yaml",
            "target-registration.yaml": ARTIFACTS / "target-registration.yaml",
            "platform-applications.yaml": ARTIFACTS / "platform-applications.yaml",
            "provider-prerequisites.yaml": projection_dir / "ok-infra-prerequisites.yaml",
            "cluster-lifecycle.yaml": projection_dir / "ok-mgmt-lifecycle.yaml",
        }.items())},
        "semanticDigests": {
            "hcpSpec": hcp_spec_digest,
            "hrpSpec": hrp_spec_digest,
            "networkProfile": semantic_digest(network_profile),
            "platformProfile": semantic_digest(platform_profile),
            "aggregateEvidenceProfile": ordered_json_digest(aggregate_profile),
        },
        "boundaries": {
            "clusterContact": False,
            "mutationAuthorized": False,
            "credentialsIncluded": False,
            "runtimeTargetIdentityMaterialized": False,
        },
    }
    write_json(HERE / "package-manifest.json", manifest)
    print(manifest["planDigest"])


if __name__ == "__main__":
    main()
