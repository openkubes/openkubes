#!/usr/bin/env python3
"""Fail-closed verifier for the read-only OK-141 GHCR preflight."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import yaml


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


PROTOCOL = _load(
    "ok141_ghcr_source_protocol",
    SPIKE / "evidence-observer-protocol" / "verify_evidence_observer_protocol.py",
)
V1 = PROTOCOL.V1
SOURCE_DIGEST = "sha256:401fa5c5e13a867d5fb747efb5b51870942547b584cd82959a6d6d54f4964dad"
OFFICIAL_REFERENCES = {
    "https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry",
    "https://docs.github.com/en/packages/learn-github-packages/about-permissions-for-github-packages",
    "https://docs.github.com/en/packages/learn-github-packages/configuring-a-packages-access-control-and-visibility",
    "https://docs.github.com/en/packages/learn-github-packages/deleting-and-restoring-a-package",
    "https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/use-artifact-attestations",
}


def _expect(actual: Any, expected: Any, claim: str) -> None:
    if actual != expected:
        raise V1.HarnessError(f"GHCR observer preflight {claim} mismatch")


def validate(document: dict[str, Any], preflight_path: Path) -> str:
    schema = json.loads((HERE / "ghcr-observer-preflight-v1.schema.json").read_text())
    V1.normalize(document, schema)
    spec = document["spec"]
    _expect((spec["state"], spec["operation"]), ("OBSERVED-BLOCKED-NO-GO", "READ-ONLY"), "state/operation")

    source = spec["sourceProtocol"]
    source_path = (preflight_path.parent / source["path"]).resolve()
    if SPIKE.resolve() not in source_path.parents or not source_path.is_file():
        raise V1.HarnessError("GHCR observer source is missing or outside spike")
    _expect(source["digest"], SOURCE_DIGEST, "source declared digest")
    _expect(V1.sha256_bytes(source_path.read_bytes()), SOURCE_DIGEST, "source raw digest")
    PROTOCOL.validate(V1.read_yaml_or_json(source_path), source_path)

    live = spec["liveObservations"]
    package = live["package"]
    _expect((package["repository"], package["result"], package["httpStatus"], package["packageCreated"]), ("ghcr.io/openkubes/ok141-evidence", "NOT-FOUND", 404, False), "package observation")
    listing = live["packageListing"]
    _expect((listing["result"], listing["httpStatus"], listing["requiredScope"], listing["currentTokenProvesPackageRead"]), ("FORBIDDEN-MISSING-SCOPE", 403, "read:packages", False), "listing observation")
    actions = live["repositoryActions"]
    _expect(
        (actions["repository"], actions["enabled"], actions["allowedActions"], actions["organizationRequiresActionSHAPinning"], actions["defaultWorkflowPermissions"], actions["canApprovePullRequestReviews"], actions["evidencePublishEnvironmentPresent"], actions["observedEnvironments"]),
        ("openkubes/openkubes", True, "all", False, "read", False, False, ["github-pages"]),
        "Actions observation",
    )

    official = spec["officialCapabilityEvidence"]
    registry = official["containerRegistry"]
    _expect(registry, {"supportsOCI": True, "pullByDigestSupported": True, "firstPublishDefaultVisibility": "private", "granularPackagePermissionsSupported": True, "githubTokenMayPublishFromLinkedWorkflow": True, "classicPATOtherwiseRequired": True}, "registry capabilities")
    access = official["accessBoundary"]
    _expect(access["proposedWorkflowPermissions"], {"contents": "read", "packages": "write", "attestations": "write", "id-token": "write"}, "workflow permissions")
    _expect((access["workflowRepositoryLinkRequired"], access["actionReferencesMustUseFullCommitSHA"], access["packageDeletePermissionGranted"]), (True, True, False), "access boundary")
    deletion = official["deletionBoundary"]
    _expect((deletion["administratorDeletionPossible"], deletion["conditionalRestoreWindowDays"], deletion["restoreGuaranteed"], deletion["namespaceReuseCanPreventRestore"], deletion["workflowDeleteRestoreFeatureMaturity"]), (True, 30, False, True, "PUBLIC-PREVIEW"), "deletion boundary")
    attestation = official["attestationBoundary"]
    _expect(attestation, {"githubArtifactAttestationSupported": True, "subjectMustBeOCIDigest": True, "signatureTimestampAndSignerIdentityMustBeVerified": True, "attestationDeletionPossible": True, "attestationIsNotRetentionProof": True}, "attestation boundary")
    _expect(set(official["references"]), OFFICIAL_REFERENCES, "official reference membership")

    clock = spec["clockObservation"]
    _expect((clock["cacheControl"], clock["maximumObservedSkewSeconds"], clock["requiredMaximumSkewSeconds"], clock["result"]), ("no-cache", 1, 5, "OBSERVED-PASS-POINT-IN-TIME"), "clock result")
    if clock["maximumObservedSkewSeconds"] > clock["requiredMaximumSkewSeconds"]:
        raise V1.HarnessError("GHCR observer clock skew exceeds limit")
    _expect(clock["rejectedObservation"]["retainedAsClockEvidence"], False, "cached clock rejection")
    if "repeated" not in clock["boundary"].lower():
        raise V1.HarnessError("GHCR observer clock refresh boundary missing")

    runtime = spec["proposedObserverRuntime"]
    _expect((runtime["platform"], runtime["repository"], runtime["environment"], runtime["environmentStatus"], runtime["workflowStatus"], runtime["trigger"], runtime["executionIdentity"]), ("GitHub-Actions", "openkubes/openkubes", "ok-141-evidence-publish", "NOT-CREATED", "NOT-IMPLEMENTED", "workflow_dispatch", "repository-scoped-GITHUB_TOKEN"), "runtime proposal")
    _expect(len(runtime["publishSequence"]), 8, "publish sequence")
    restrictions = " ".join(runtime["restrictions"]).lower()
    for phrase in ("full commit sha", "no pat", "no delete", "tag is never", "separate exact publish gate"):
        if phrase not in restrictions:
            raise V1.HarnessError(f"GHCR observer runtime restriction missing: {phrase}")

    retention = spec["retentionProposal"]
    _expect((retention["status"], retention["model"], retention["minimumRetentionDaysAfterOK141Closure"], retention["primaryCopy"], retention["deletionMonitoring"]), ("PROPOSED-NOT-ACCEPTED", "DEV-BEST-EFFORT-NON-WORM", 90, "GHCR OCI artifact by digest", "REQUIRED-NOT-IMPLEMENTED"), "retention proposal")
    _expect(len(spec["remainingBlockers"]), 8, "remaining blocker count")

    authorization = spec["authorization"]
    _expect(authorization["decision"], "NO-GO", "authorization decision")
    for field in ("externalWriteAuthorized", "packageCreationAuthorized", "environmentCreationAuthorized", "workflowDeploymentAuthorized", "credentialMutationAuthorized", "infrastructureMutationAuthorized", "m0aInstallationGranted", "m0bInstallationGranted", "go1Granted"):
        _expect(authorization[field], False, f"authorization {field}")
    _expect(spec["summary"], {"destinationSelected": True, "packageExists": False, "currentPackageReadProven": False, "pointInTimeClockSkewPass": True, "retentionAccepted": False, "observerRuntimeDeployed": False, "installationGatesGranted": 0}, "summary")

    rules = " ".join(spec["rules"]).lower()
    for phrase in ("are blockers", "expires outside", "separate write gate", "do not make ghcr immutable", "retention remains undecided", "creates no package"):
        if phrase not in rules:
            raise V1.HarnessError(f"GHCR observer safety rule missing: {phrase}")
    return V1.sha256_bytes(preflight_path.read_bytes())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight", type=Path, required=True)
    parser.add_argument("--digest-file", type=Path)
    args = parser.parse_args()
    try:
        path = args.preflight.resolve()
        digest = validate(V1.read_yaml_or_json(path), path)
        if args.digest_file:
            _expect(digest.removeprefix("sha256:"), args.digest_file.read_text().split()[0], "raw digest")
        print(digest)
        return 0
    except (V1.HarnessError, OSError, ValueError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
