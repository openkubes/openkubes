#!/usr/bin/env python3
"""Verify ADR-021 RBAC and Talos/RKE2 capability-delta conformance."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml


HERE = Path(__file__).resolve().parent
RBAC_PATH = HERE.parent / "rbac.yaml"
PROFILES_DIR = HERE / "profiles"
FIXTURES_DIR = HERE / "fixtures"
ALLOWED_VERBS = {"get", "list", "watch"}
BASE_CAPABILITIES = {
    "workload_events",
    "workload_logs",
    "cilium_diagnostics",
    "host_journal",
    "node_shell",
}
DELTA_EVIDENCE_TYPES = {"host_journal", "node_shell"}


class ConformanceError(AssertionError):
    """Raised when a profile violates the diagnostics contract."""


def load_yaml(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ConformanceError(f"{path} must contain one YAML object")
    return document


def load_json(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ConformanceError(f"{path} must contain one JSON object")
    return document


def load_rbac_documents(path: Path = RBAC_PATH) -> list[dict[str, Any]]:
    return [
        document
        for document in yaml.safe_load_all(path.read_text(encoding="utf-8"))
        if isinstance(document, dict)
    ]


def one_kind(documents: list[dict[str, Any]], kind: str) -> dict[str, Any]:
    matches = [document for document in documents if document.get("kind") == kind]
    if len(matches) != 1:
        raise ConformanceError(f"expected exactly one {kind}, found {len(matches)}")
    return matches[0]


def verify_rbac_documents(documents: list[dict[str, Any]]) -> None:
    service_account = one_kind(documents, "ServiceAccount")
    role = one_kind(documents, "ClusterRole")
    binding = one_kind(documents, "ClusterRoleBinding")

    for rule in role.get("rules", []):
        verbs = set(rule.get("verbs", []))
        resources = set(rule.get("resources", []))
        api_groups = set(rule.get("apiGroups", []))
        extra_verbs = verbs - ALLOWED_VERBS
        if extra_verbs:
            raise ConformanceError(f"write or escalation verbs present: {sorted(extra_verbs)}")
        if "secrets" in resources:
            raise ConformanceError("Secrets must never be readable by the provider identity")
        if "*" in verbs | resources | api_groups:
            raise ConformanceError("wildcards are forbidden in Profile A RBAC")

    role_name = role.get("metadata", {}).get("name")
    role_ref = binding.get("roleRef", {})
    if role_ref.get("kind") != "ClusterRole" or role_ref.get("name") != role_name:
        raise ConformanceError("ClusterRoleBinding does not reference the declared role")

    sa_metadata = service_account.get("metadata", {})
    expected_subject = {
        "kind": "ServiceAccount",
        "name": sa_metadata.get("name"),
        "namespace": sa_metadata.get("namespace"),
    }
    subjects = binding.get("subjects", [])
    if expected_subject not in subjects:
        raise ConformanceError("ClusterRoleBinding does not bind the provider ServiceAccount")


def verify_profile(profile: dict[str, Any]) -> None:
    distribution = profile.get("distribution")
    capabilities = profile.get("provider_capabilities")
    expectations = profile.get("evidence_expectations")
    if distribution not in {"talos", "rke2"}:
        raise ConformanceError(f"unsupported distribution profile: {distribution!r}")
    if not isinstance(capabilities, dict) or set(capabilities) != BASE_CAPABILITIES:
        raise ConformanceError(
            f"{distribution} provider capability keys differ from the contract"
        )
    if any(not isinstance(value, bool) for value in capabilities.values()):
        raise ConformanceError(f"{distribution} capabilities must be boolean")
    if not isinstance(expectations, dict) or set(expectations) != DELTA_EVIDENCE_TYPES:
        raise ConformanceError(f"{distribution} must define both delta evidence expectations")

    for evidence_type, expectation in expectations.items():
        capability = capabilities[evidence_type]
        expected_status = "available" if capability else "unavailable"
        if expectation.get("status") != expected_status:
            raise ConformanceError(
                f"{distribution}.{evidence_type} status disagrees with capability declaration"
            )
        if not capability and not expectation.get("reason_required"):
            raise ConformanceError(
                f"{distribution}.{evidence_type} must require an unavailable reason"
            )
        if capability and not expectation.get("uri_required"):
            raise ConformanceError(
                f"{distribution}.{evidence_type} must require an evidence URI"
            )


def verify_response(profile: dict[str, Any], response: dict[str, Any]) -> None:
    distribution = profile["distribution"]
    capabilities = profile["provider_capabilities"]
    if response.get("provider_capabilities") != capabilities:
        raise ConformanceError(f"{distribution} response capability declaration drifted")
    evidence = response.get("evidence")
    if not isinstance(evidence, list):
        raise ConformanceError(f"{distribution} response has no evidence list")
    by_type = {item.get("type"): item for item in evidence if isinstance(item, dict)}

    for evidence_type, expectation in profile["evidence_expectations"].items():
        if evidence_type not in by_type:
            raise ConformanceError(
                f"{distribution} silently omitted requested evidence: {evidence_type}"
            )
        item = by_type[evidence_type]
        if item.get("status") != expectation["status"]:
            raise ConformanceError(f"{distribution}.{evidence_type} has the wrong status")
        if expectation["reason_required"] and not str(item.get("reason") or "").strip():
            raise ConformanceError(f"{distribution}.{evidence_type} has no reason")
        if expectation["uri_required"] and not str(item.get("uri") or "").strip():
            raise ConformanceError(f"{distribution}.{evidence_type} has no evidence URI")


def verify_contract_identity(responses: list[dict[str, Any]]) -> None:
    top_level_shapes = [frozenset(response) for response in responses]
    evidence_shapes = [
        frozenset(frozenset(item) for item in response.get("evidence", []))
        for response in responses
    ]
    if len(set(top_level_shapes)) != 1:
        raise ConformanceError("distribution responses have different contract fields")
    if len(set(evidence_shapes)) != 1:
        raise ConformanceError("distribution EvidenceRef objects have different fields")


def verify_capability_identity(profiles: list[dict[str, Any]]) -> None:
    capability_shapes = [
        frozenset(profile.get("provider_capabilities", {})) for profile in profiles
    ]
    if len(set(capability_shapes)) != 1:
        raise ConformanceError("distributions declare different provider capability keys")


def load_matrix() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    profiles = [
        load_yaml(PROFILES_DIR / "talos.yaml"),
        load_yaml(PROFILES_DIR / "rke2.yaml"),
    ]
    responses = [
        load_json(FIXTURES_DIR / "talos-evidence-bundle.json"),
        load_json(FIXTURES_DIR / "rke2-evidence-bundle.json"),
    ]
    return profiles, responses


def verify_all() -> None:
    verify_rbac_documents(load_rbac_documents())
    profiles, responses = load_matrix()
    for profile, response in zip(profiles, responses):
        verify_profile(profile)
        verify_response(profile, response)
    verify_capability_identity(profiles)
    verify_contract_identity(responses)


def main() -> int:
    verify_all()
    print("PASS: Profile A RBAC is get/list/watch-only, secret-free, and wildcard-free")
    print("PASS: Talos/RKE2 profiles expose the same contract capability keys")
    print("PASS: unavailable Talos evidence is explicit and reasoned")
    print("PASS: available RKE2 evidence requires retrievable references")
    print("PASS: distribution fixtures retain an identical response shape")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
