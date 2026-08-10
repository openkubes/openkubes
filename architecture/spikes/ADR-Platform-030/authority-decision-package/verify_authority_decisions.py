#!/usr/bin/env python3
"""Fail-closed verifier for the undecided OK-141 authority package."""

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


INSTALLER = _load(
    "ok141_authority_installer",
    SPIKE / "installation-closure" / "bounded_installer.py",
)
V1 = INSTALLER.V1

SOURCE_DIGESTS = {
    "m0aProtocol": "sha256:873d3aa3b15df53d3a4055675288c6d9acdf6c18d4f850e181a4eb7b93fc4a27",
    "m0bProtocol": "sha256:79feba3dc3b58d5065c47de894ca3d926fd0cdee134c7252f7df3c0f644d40a7",
    "closureMatrix": "sha256:0cd56a0fa6d4e483ea02cce795980100166ac47006b37defbf0ce8a4b1ff8d3c",
    "offlineResults": "sha256:1e34953595fa98de3e2207f8ac90c2e1a52e2652491012f6323021f8570cc6e3",
    "liveResults": "sha256:2ab2a20d2143a798954527efcf43aa031cb6e224bd18dbb273e0293918d46f7d",
    "m0aRbacAnalysis": "sha256:d88d5f7cd060b479554046e624e420b433b04dc7165190610e98d2aaa62520c8",
    "m0bRbacAnalysis": "sha256:196af85614c1d4f3cfc4b273134e07b819499e408bf400e3d9a0fb4b8bc0d07c",
}
EXPECTED_DECISIONS = {
    "M0AI-AUTHORITY-GRANT": ("M0A-I", "INSTALLATION-AUTHORITY", "m0aProtocol"),
    "M0AI-RBAC-SECURITY-DECISION": ("M0A-I", "SECURITY-ACCEPTANCE", "m0aProtocol"),
    "M0AI-OBSERVER-ASSIGNMENT": ("M0A-I", "OBSERVER-ASSIGNMENT", "m0aProtocol"),
    "M0AI-RECOVERY-AUTHORITY": ("M0A-I", "RECOVERY-AUTHORITY", "m0aProtocol"),
    "M0BI-INSTALLATION-AUTHORITY": ("M0B-I", "INSTALLATION-AUTHORITY", "m0bProtocol"),
    "M0BI-PLACEMENT-AUTHORITY": ("M0B-I", "PLACEMENT-AUTHORITY", "m0bProtocol"),
    "M0BI-RBAC-SECURITY-DECISION": ("M0B-I", "SECURITY-ACCEPTANCE", "m0bProtocol"),
    "M0BI-OBSERVER-ASSIGNMENT": ("M0B-I", "OBSERVER-ASSIGNMENT", "m0bProtocol"),
    "M0BI-RECOVERY-AUTHORITY": ("M0B-I", "RECOVERY-AUTHORITY", "m0bProtocol"),
}
EXCLUDED = {
    "M0AI-INSTALLER-CREDENTIAL": "M0A-I",
    "M0BI-INSTALLER-CREDENTIAL": "M0B-I",
}


def _expect(actual: Any, expected: Any, claim: str) -> None:
    if actual != expected:
        raise V1.HarnessError(f"authority package {claim} mismatch")


def _resolve(package_path: Path, requested: str) -> Path:
    candidate = (package_path.parent / requested).resolve()
    if SPIKE.resolve() not in candidate.parents or not candidate.is_file():
        raise V1.HarnessError(
            f"authority package reference missing or outside spike root: {requested}"
        )
    return candidate


def _index(items: list[dict[str, Any]], claim: str) -> dict[str, dict[str, Any]]:
    result = {item.get("id"): item for item in items}
    if None in result or len(result) != len(items):
        raise V1.HarnessError(f"authority package {claim} has missing or duplicate IDs")
    return result


def validate(document: dict[str, Any], package_path: Path) -> str:
    schema = json.loads((HERE / "authority-decisions-v1.schema.json").read_text())
    V1.normalize(document, schema)
    spec = document["spec"]
    _expect(spec["state"], "PREPARED-UNDECIDED-NO-GO", "state")

    authorization = spec["authorization"]
    _expect(authorization["decision"], "NO-GO", "authorization decision")
    for field in (
        "mutationAuthorized",
        "m0aInstallationGranted",
        "m0bInstallationGranted",
        "go1Granted",
    ):
        _expect(authorization[field], False, f"authorization {field}")

    paths: dict[str, Path] = {}
    _expect(set(spec["sources"]), set(SOURCE_DIGESTS), "source membership")
    for name, expected_digest in SOURCE_DIGESTS.items():
        claim = spec["sources"][name]
        _expect(claim["digest"], expected_digest, f"source {name} declared digest")
        path = _resolve(package_path, claim["path"])
        _expect(V1.sha256_bytes(path.read_bytes()), expected_digest, f"source {name} raw digest")
        paths[name] = path

    matrix = V1.read_yaml_or_json(paths["closureMatrix"])
    authority_from_matrix = {
        obligation["id"]: blocker["gate"]
        for blocker in matrix["spec"]["blockers"]
        for obligation in blocker["obligations"]
        if obligation["class"] == "EXPLICIT-AUTHORITY"
    }
    mutation_from_matrix = {
        obligation["id"]: blocker["gate"]
        for blocker in matrix["spec"]["blockers"]
        for obligation in blocker["obligations"]
        if obligation["class"] == "SEPARATE-MUTATION-GATE"
    }
    _expect(authority_from_matrix, {key: value[0] for key, value in EXPECTED_DECISIONS.items()}, "matrix authority coverage")
    _expect(mutation_from_matrix, EXCLUDED, "matrix mutation-gate coverage")

    decisions = _index(spec["decisions"], "decisions")
    _expect(set(decisions), set(EXPECTED_DECISIONS), "decision membership")
    allowed_evidence = set(SOURCE_DIGESTS)
    for decision_id, (gate, category, protocol) in EXPECTED_DECISIONS.items():
        decision = decisions[decision_id]
        _expect(decision["gate"], gate, f"{decision_id} gate")
        _expect(decision["category"], category, f"{decision_id} category")
        _expect(decision["outcome"], "UNDECIDED", f"{decision_id} outcome")
        _expect(decision["authority"], "UNASSIGNED", f"{decision_id} authority")
        for field in ("decidedAt", "validFrom", "validUntil"):
            _expect(decision[field], None, f"{decision_id} {field}")
        _expect(decision["boundProtocol"], protocol, f"{decision_id} protocol")
        if not decision.get("boundEvidence") or any(
            item not in allowed_evidence for item in decision["boundEvidence"]
        ):
            raise V1.HarnessError(f"authority package {decision_id} has invalid evidence binding")
        for field in ("question", "acceptanceRequired", "rejectEffect"):
            if not decision.get(field):
                raise V1.HarnessError(f"authority package {decision_id} lacks {field}")

    _expect(
        decisions["M0AI-RBAC-SECURITY-DECISION"]["residualRisks"],
        {"SECRET-READ": 2, "SUBJECTACCESSREVIEW": 2, "TOKENREVIEW": 2, "WILDCARD-RESOURCE-SCOPE": 1},
        "M0a RBAC risks",
    )
    _expect(
        decisions["M0BI-RBAC-SECURITY-DECISION"]["residualRisks"],
        {"SECRET-READ": 7, "SECRET-WRITE": 2, "CLUSTERROLE": 0},
        "M0b RBAC risks",
    )
    for decision_id in ("M0AI-OBSERVER-ASSIGNMENT", "M0BI-OBSERVER-ASSIGNMENT"):
        if set(decisions[decision_id]["assignments"].values()) != {"UNASSIGNED"}:
            raise V1.HarnessError(f"authority package {decision_id} contains an assignment")

    m0a_findings = V1.read_yaml_or_json(paths["m0aRbacAnalysis"])["spec"]
    m0b_findings = V1.read_yaml_or_json(paths["m0bRbacAnalysis"])["spec"]
    _expect(m0a_findings["decision"], "ANALYZED-NOT-ACCEPTED", "M0a RBAC acceptance")
    _expect(m0b_findings["decision"], "ANALYZED-NOT-ACCEPTED", "M0b RBAC acceptance")

    risk = spec["developmentRiskProfile"]
    _expect(
        risk,
        {
            "environment": "DEV",
            "highAvailabilityRequired": False,
            "providerSnapshotsRequired": False,
            "totalStateLossAccepted": True,
            "intendedRecoveryMode": "rebuild-not-restore",
            "rebuildPathProven": False,
            "automaticAdoptionAllowed": False,
            "productionDRClaimAllowed": False,
            "lifecycleContinuityClaimAllowed": False,
        },
        "development risk profile",
    )
    shared = spec["targetIncarnations"]["ok-shared"]
    _expect(shared["kubeSystemNamespaceUID"], "46b9ecf7-2e7a-48b1-a6eb-7d11df396efb", "ok-shared UID")
    _expect(shared["apiServer"], "https://192.168.100.206:6443", "ok-shared endpoint")
    _expect((shared["kubernetesVersion"], shared["platform"]), ("v1.34.1", "linux/amd64"), "ok-shared tuple")

    excluded = _index(spec["excludedMutationGates"], "excluded mutation gates")
    _expect({key: item["gate"] for key, item in excluded.items()}, EXCLUDED, "excluded mutation membership")
    for item_id, item in excluded.items():
        _expect(item["status"], "NOT-AUTHORIZED", f"{item_id} status")
        rule = item["rule"].lower()
        for phrase in ("own protocol", "explicit authority", "cannot inherit"):
            if phrase not in rule:
                raise V1.HarnessError(f"authority package {item_id} exclusion rule missing {phrase}")

    _expect(
        spec["summary"],
        {"decisionsPrepared": 9, "decided": 0, "accepted": 0, "rejected": 0, "deferred": 0, "undecided": 9, "excludedMutationGates": 2},
        "summary",
    )
    rules = " ".join(spec["rules"]).lower()
    for phrase in (
        "does not mean any decision",
        "fail closed",
        "grants no authority",
        "separate mutation gate",
        "rebuild remains unproven",
        "no automatic adoption",
    ):
        if phrase not in rules:
            raise V1.HarnessError(f"authority package safety rule missing: {phrase}")
    return V1.sha256_bytes(package_path.read_bytes())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--digest-file", type=Path)
    args = parser.parse_args()
    try:
        path = args.package.resolve()
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
