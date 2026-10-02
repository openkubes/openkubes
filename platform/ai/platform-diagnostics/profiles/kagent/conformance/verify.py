#!/usr/bin/env python3
"""Verify ADR-021 RBAC and Talos/RKE2 capability-delta conformance."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, FormatChecker


HERE = Path(__file__).resolve().parent
RBAC_PATH = HERE.parent / "rbac.yaml"
PROFILES_DIR = HERE / "profiles"
FIXTURES_DIR = HERE / "fixtures"
OPENAPI_PATH = HERE.parents[2] / "contract" / "openapi.yaml"
ALLOWED_VERBS = {"get", "list", "watch"}
BASE_CAPABILITIES = {
    "workload_events",
    "workload_logs",
    "cilium_diagnostics",
    "host_journal",
    "node_shell",
}
DELTA_EVIDENCE_TYPES = {"host_journal", "node_shell"}

#: The normative contract this matrix was written against. Pinned because the
#: spec path is resolved relative to the checkout: without it, a branch that has
#: fallen behind validates happily against an older contract.
CONTRACT_VERSION = "1.1.0"

#: How a distribution profile came to exist. ``measured`` means someone observed
#: the running provider; ``assumed`` means the profile states an intention;
#: ``out-of-scope`` means a decision excluded the distribution from the
#: acceptance criteria entirely. All three are legitimate, but only one is
#: evidence, and the difference has to survive into the output — a declaration
#: nobody measured cannot fail a static check, it can only be wrong.
PROVENANCE_STATES = {"measured", "assumed", "out-of-scope"}
MEASURED_KEYS = {"cluster", "observed_at", "record"}
ASSUMED_KEYS = {"reason", "missing", "record"}
OUT_OF_SCOPE_KEYS = {"reason", "decision", "record"}
REQUIRED_PROVENANCE_KEYS = {
    "measured": MEASURED_KEYS,
    "assumed": ASSUMED_KEYS,
    "out-of-scope": OUT_OF_SCOPE_KEYS,
}


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


def verify_provenance(profile: dict[str, Any]) -> str:
    """Return the profile's provenance state, or fail if it does not declare one."""
    distribution = profile.get("distribution")
    provenance = profile.get("provenance")
    if not isinstance(provenance, dict):
        raise ConformanceError(
            f"{distribution} declares no provenance; a capability profile must say "
            f"whether it was measured or assumed"
        )
    state = provenance.get("state")
    if state not in PROVENANCE_STATES:
        raise ConformanceError(
            f"{distribution} provenance state {state!r} is not one of "
            f"{sorted(PROVENANCE_STATES)}"
        )
    required = REQUIRED_PROVENANCE_KEYS[state]
    missing_keys = sorted(required - set(provenance))
    if missing_keys:
        raise ConformanceError(
            f"{distribution} provenance is {state} but omits {missing_keys}"
        )
    record = HERE / str(provenance["record"])
    if not record.is_file():
        raise ConformanceError(
            f"{distribution} points at a provenance record that does not exist: "
            f"{provenance['record']}"
        )
    if state == "assumed":
        steps = provenance.get("missing")
        if not isinstance(steps, list) or not steps or any(
            not str(step).strip() for step in steps
        ):
            raise ConformanceError(
                f"{distribution} is assumed but names no steps to measure it; an "
                f"open gap without a route to close it is not a plan"
            )
    if state == "out-of-scope":
        decision = provenance.get("decision")
        reference = decision.get("reference") if isinstance(decision, dict) else None
        if not str(reference or "").strip():
            raise ConformanceError(
                f"{distribution} is out-of-scope but names no decision reference; "
                f"an exclusion without a decision behind it is a silent drop"
            )
    return state


def verify_contract_version(spec: dict[str, Any]) -> None:
    info = spec.get("info")
    version = info.get("version") if isinstance(info, dict) else None
    if version != CONTRACT_VERSION:
        raise ConformanceError(
            f"{OPENAPI_PATH} declares contract version {version!r}, but this matrix "
            f"was written against {CONTRACT_VERSION}. Adopt the new contract "
            f"deliberately instead of validating against whatever the checkout holds."
        )


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
    evidence_ids = [item.get("id") for item in evidence if isinstance(item, dict)]
    if len(evidence_ids) != len(set(evidence_ids)) or any(
        not item for item in evidence_ids
    ):
        raise ConformanceError(
            f"{distribution} EvidenceRef.id values must be present and unique"
        )
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
    if len(set(top_level_shapes)) != 1:
        raise ConformanceError("distribution responses have different contract fields")


def verify_response_schema(response: dict[str, Any]) -> None:
    spec = load_yaml(OPENAPI_PATH)
    verify_contract_version(spec)
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "components": spec["components"],
        "$ref": "#/components/schemas/EvidenceBundle",
    }
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(
            schema, format_checker=FormatChecker()
        ).iter_errors(response),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        formatted = "; ".join(
            f"{'/'.join(map(str, error.absolute_path)) or '<root>'}: {error.message}"
            for error in errors
        )
        raise ConformanceError(f"response violates normative EvidenceBundle: {formatted}")


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


def verify_all() -> list[dict[str, Any]]:
    """Run the static matrix and report what each distribution actually rests on."""
    verify_rbac_documents(load_rbac_documents())
    profiles, responses = load_matrix()
    report: list[dict[str, Any]] = []
    for profile, response in zip(profiles, responses):
        state = verify_provenance(profile)
        verify_profile(profile)
        verify_response_schema(response)
        verify_response(profile, response)
        report.append(
            {
                "distribution": profile["distribution"],
                "state": state,
                "provenance": profile["provenance"],
            }
        )
    verify_capability_identity(profiles)
    verify_contract_identity(responses)
    return report


def assumed_entries(report: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Entries in `report` still resting on an assumption, not a measurement.

    `out-of-scope` is deliberately excluded here: it is not evidence either,
    but a decision already accounted for it, so ``--require-measured`` must
    not re-flag it.
    """
    return [entry for entry in report if entry["state"] == "assumed"]


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    require_measured = "--require-measured" in arguments

    report = verify_all()
    print("PASS: Profile A RBAC is get/list/watch-only, secret-free, and wildcard-free")
    print("PASS: Talos/RKE2 profiles expose the same contract capability keys")
    print(
        f"PASS: distribution fixtures validate against the normative "
        f"EvidenceBundle ({CONTRACT_VERSION})"
    )
    print()

    label_width = 13
    for entry in report:
        provenance = entry["provenance"]
        if entry["state"] == "measured":
            print(
                f"{'PASS':<{label_width}}{entry['distribution']}: capability delta "
                f"measured on {provenance['cluster']} ({provenance['observed_at']}) "
                f"— {provenance['record']}"
            )
            continue
        if entry["state"] == "out-of-scope":
            print(
                f"{'OUT-OF-SCOPE':<{label_width}}{entry['distribution']}: excluded "
                f"by decision {provenance['decision']['date']} — "
                f"{' '.join(str(provenance['reason']).split())}"
            )
            continue
        print(
            f"{'BLOCKED':<{label_width}}{entry['distribution']}: declared, not "
            f"measured — {' '.join(str(provenance['reason']).split())}"
        )
        for step in provenance["missing"]:
            print(f"{'':<{label_width}}to close: {step}")
        print(f"{'':<{label_width}}record: {provenance['record']}")

    in_scope = [entry for entry in report if entry["state"] != "out-of-scope"]
    measured_in_scope = [entry for entry in in_scope if entry["state"] == "measured"]
    assumed = assumed_entries(report)
    print()
    print(
        f"{len(measured_in_scope)} of {len(in_scope)} in-scope distributions "
        "measured. The static checks above prove the matrix is internally "
        "consistent; for an assumed distribution they cannot prove it is right."
    )
    if assumed and require_measured:
        print(
            "FAIL: --require-measured was set and "
            f"{', '.join(entry['distribution'] for entry in assumed)} "
            "is still an assumption."
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
