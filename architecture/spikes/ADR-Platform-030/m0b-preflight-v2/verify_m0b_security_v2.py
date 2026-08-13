#!/usr/bin/env python3
"""Fail-closed verifier for the OK-141 M0b v2 security candidate."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
from typing import Any

import yaml


HERE = Path(__file__).resolve().parent
CANDIDATE = HERE / "m0b-v2-security-candidate.yaml"


class VerificationError(ValueError):
    pass


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def expect(actual: Any, expected: Any, claim: str) -> None:
    if actual != expected:
        raise VerificationError(f"{claim} mismatch")


def verify(path: Path = CANDIDATE) -> str:
    document = yaml.safe_load(path.read_text())
    spec = document["spec"]
    expect(spec["state"], "READY-FOR-RISK-DECISION-NO-GO", "state")
    refs = spec["references"]
    expected = {
        "livePreflight": "sha256:abd0a8599c3ad159a8d8cd84ab6e8e982e45bdb6f5ab64480d8118aa03acb4b4",
        "sourceLock": "sha256:f715fed2f1e5a7c80aa5838b1f9ac243e2a2de8cec711e324f223dde8298f6e9",
    }
    for name, value in expected.items():
        reference = refs[name]
        expect(reference["digest"], value, f"{name} declared digest")
        target = (HERE / reference["path"]).resolve()
        expect(digest(target), value, f"{name} content digest")

    admin = spec["administratorIdentity"]
    expect(admin["certificateSubject"], "O=system:masters,CN=kubernetes-admin", "admin subject")
    expect(admin["credentialClass"], "LONG-LIVED-CLUSTER-ADMIN", "credential class")
    expect(admin["shortLivedCredentialClaimAllowed"], False, "credential claim")

    submission = spec["submissionModel"]
    expect(submission["operation"], "DIRECT-ADMIN-TWO-PHASE-CREATE-ONLY", "operation")
    for field in ("serverSideApplyAllowed", "updatePatchReplaceAllowed", "automaticRetryAllowed", "automaticRollbackAllowed"):
        expect(submission[field], False, field)
    expect(submission["phase1"]["objectCount"], 4, "phase-1 object count")
    expect(submission["phase2"]["objectCount"], 50, "phase-2 object count")
    expect(submission["phase2"]["targetNamespace"], "argocd", "target Namespace")
    expect(submission["phase2"]["namespaceMustBeExplicitInPayload"], True, "explicit Namespace")
    expect(submission["combinedTargetSemanticDigest"], "sha256:9664b22ac554c3e470484ce3319f302e53e332f9d2b46e7d78b4fc47eb865b0b", "combined target semantics")
    expect(submission["transport"], {"verb": "create", "namespaceArgument": "argocd", "stdinOnly": True}, "transport")

    controller = spec["controllerBoundary"]
    expect((controller["clusterRolesInstalled"], controller["clusterRoleBindingsInstalled"]), (0, 0), "cluster RBAC")
    expect(controller["findings"], {"SECRET-READ": 7, "SECRET-WRITE": 2}, "controller findings")
    expect(controller["wildcardFindingObserved"], False, "wildcard finding")

    risk_ids = {item["id"] for item in spec["risksRequiringAcceptance"]}
    expect(risk_ids, {"DIRECT-ADMIN-CONTENT", "NON-ATOMIC-TWO-PHASE-CREATE", "NAMESPACE-SECRET-ACCESS", "UNDECLARED-RESOURCE-REQUESTS", "REMOTE-SOURCE-MATERIALIZATION"}, "risk membership")
    authorization = spec["authorization"]
    if any(authorization.values()):
        raise VerificationError("security candidate grants authority")
    if not spec["nextDecision"]["mustCiteThisCandidateDigest"]:
        raise VerificationError("risk decision is not bound to candidate digest")
    return digest(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, default=CANDIDATE)
    parser.add_argument("--digest-file", type=Path)
    args = parser.parse_args()
    try:
        value = verify(args.candidate.resolve())
        if args.digest_file:
            expect(value.removeprefix("sha256:"), args.digest_file.read_text().split()[0], "candidate digest")
        print(value)
        return 0
    except (OSError, KeyError, TypeError, VerificationError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
