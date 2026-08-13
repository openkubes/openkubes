#!/usr/bin/env python3
"""Fail-closed verifier for the read-only OK-141 M0b v2 preflight."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
from typing import Any

import yaml


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
PREFLIGHT = HERE / "m0b-v2-live-preflight-v1.yaml"
LOCK = HERE / "argocd-installation-source-lock-v2.yaml"


class VerificationError(ValueError):
    pass


def sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def expect(actual: Any, expected: Any, claim: str) -> None:
    if actual != expected:
        raise VerificationError(f"{claim} mismatch")


def load(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text())
    if not isinstance(value, dict):
        raise VerificationError(f"invalid YAML object: {path}")
    return value


def resolve(reference: str) -> Path:
    candidate = (HERE / reference).resolve()
    if SPIKE.resolve() not in candidate.parents or not candidate.is_file():
        raise VerificationError(f"reference missing or outside spike: {reference}")
    return candidate


def verify(preflight_path: Path = PREFLIGHT) -> str:
    document = load(preflight_path)
    spec = document["spec"]
    expect(spec["state"], "READ-ONLY-COMPLETE-MUTATION-NO-GO", "state")
    expect(spec["baseCommit"], "ee229500a5f9622ff48fd330572f30ee7de035d8", "base commit")

    expected_references = {
        "authorityInputs": "sha256:4b618081517eb96ef1896b40a7f9f5556054ab2d029fbbf706e8630bb6b42c5c",
        "talosBaseline": "sha256:b71b0aada174cc4dc338dfab927bd9e4e7510c38324c8a735e9084f7e72cd345",
        "evidenceObserver": "sha256:b14b83e9358a98f0991610acfa7a75228d82b68b30bb7337a7e32f7d74f66888",
        "historicalInstallationProtocol": "sha256:79feba3dc3b58d5065c47de894ca3d926fd0cdee134c7252f7df3c0f644d40a7",
        "sourceLock": "sha256:f715fed2f1e5a7c80aa5838b1f9ac243e2a2de8cec711e324f223dde8298f6e9",
    }
    for name, digest in expected_references.items():
        reference = spec["references"][name]
        expect(reference["digest"], digest, f"{name} declared digest")
        expect(sha256(resolve(reference["path"])), digest, f"{name} content digest")

    accepted = spec["acceptedBoundaries"]
    expect(accepted["placement"], "ok-shared", "placement")
    expect(accepted["externalWorkloadClustersOnly"], True, "external-only boundary")
    expect(accepted["manageLocalOkSharedResources"], False, "local ownership boundary")
    expect(accepted["selfManagementAllowed"], False, "self-management boundary")
    expect(accepted["productionHAClaimAllowed"], False, "HA boundary")

    target = spec["liveTarget"]
    expect(target["kubeSystemNamespaceUID"], "46b9ecf7-2e7a-48b1-a6eb-7d11df396efb", "cluster incarnation")
    expect(target["kubernetesVersion"], "v1.34.1", "Kubernetes version")
    expect(target["platform"], "linux/amd64", "platform")
    expect(target["nodeShape"], {"controlPlane": 1, "workers": 3, "ready": 4, "expected": 4}, "node shape")
    expect(target["existingArgo"], {"namespacePresent": False, "argoprojCRDs": 0, "controllerWorkloads": 0, "conflictingWritersObserved": False}, "Argo absence")

    candidate = spec["candidate"]
    expect(candidate["installationProfile"], "namespace-install-non-ha", "installation profile")
    expect(candidate["sourceObjectCount"], 54, "source object count")
    expect(candidate["sourceSemanticDigest"], "sha256:60da7edffcc0ccf46f6952ceab2c9ec615b00415689888cd88363388682914ed", "source semantics")
    expect(candidate["targetProjectedSemanticDigest"], "sha256:9664b22ac554c3e470484ce3319f302e53e332f9d2b46e7d78b4fc47eb865b0b", "target projection")
    expect(candidate["desiredPods"], 7, "desired Pod count")
    expect(candidate["namespaceTransportRequired"], True, "namespace transport")
    transport = candidate["futureTransportPrefix"]
    if "--namespace" not in transport or transport[transport.index("--namespace") + 1] != "argocd":
        raise VerificationError("future transport does not bind argocd Namespace")

    invalidation = spec["historicalCandidateInvalidation"]
    expect(invalidation["status"], "INVALIDATED-FOR-FUTURE-M0B-I", "historical invalidation")
    codes = {item["code"] for item in invalidation["reasons"]}
    expect(codes, {"HA-PROFILE-CONFLICTS-WITH-ACCEPTED-DEV-SOLO", "TARGET-NAMESPACE-MISSING-FROM-TRANSPORT"}, "invalidation reasons")

    rbac = spec["rbacObservation"]
    expect(rbac["decision"], "ANALYZED-NOT-ACCEPTED", "RBAC decision")
    expect(rbac["findings"], {"SECRET-READ": 7, "SECRET-WRITE": 2}, "RBAC findings")

    authorization = spec["authorization"]
    expect(authorization["decision"], "NO-GO", "authorization")
    if any(value is not False for key, value in authorization.items() if key != "decision"):
        raise VerificationError("preflight grants authority")

    if not spec["obligations"]["openBeforeInstallationDecision"]:
        raise VerificationError("preflight unexpectedly has no open obligations")
    expect(spec["nextStep"]["mutating"], False, "next-step mutation boundary")
    return sha256(preflight_path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight", type=Path, default=PREFLIGHT)
    parser.add_argument("--digest-file", type=Path)
    args = parser.parse_args()
    try:
        digest = verify(args.preflight.resolve())
        if args.digest_file:
            expected = args.digest_file.read_text().split()[0]
            expect(digest.removeprefix("sha256:"), expected, "preflight digest")
        print(digest)
        return 0
    except (OSError, KeyError, TypeError, VerificationError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
