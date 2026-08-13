#!/usr/bin/env python3
"""Verify the additive M0a-v7.1 admission correction offline."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import yaml


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
PARTITION = SPIKE / "m0a-execution-v7" / "m0a-v7-authority-partition-v1.yaml"
OLD_ADMISSION = SPIKE / "m0a-execution-v7" / "m0a-installer-admission-v7.yaml"
ADMISSION = HERE / "m0a-installer-admission-v7-1.yaml"
INVALIDATION = HERE / "m0a-v7-execution-invalidation-v1.yaml"


class AdmissionError(ValueError):
    pass


def _load_boundary():
    path = SPIKE / "m0a-execution-v7" / "verify_m0a_v7_boundary.py"
    spec = importlib.util.spec_from_file_location("ok141_m0a_v7_boundary_for_v71", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


V7 = _load_boundary()


def sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def expect(actual: Any, expected: Any, claim: str) -> None:
    if actual != expected:
        raise AdmissionError(f"{claim}: expected {expected!r}, got {actual!r}")


def expression(identities: list[dict[str, str]]) -> str:
    cluster = [item for item in identities if not item["namespace"]]
    namespaced = [item for item in identities if item["namespace"]]
    cluster_expression = V7.expected_expression(cluster, False)
    namespace_expression = V7.expected_expression(namespaced, True).replace(
        "request.namespace == x.namespace",
        "(has(request.namespace) ? request.namespace : '') == x.namespace",
    )
    return f"{cluster_expression} || {namespace_expression}"


def verify() -> dict[str, Any]:
    partition = yaml.safe_load(PARTITION.read_text())["spec"]
    identities = partition["authorityDomains"]["temporaryInstaller"]["identities"]
    old = [item for item in yaml.safe_load_all(OLD_ADMISSION.read_text()) if item][0]
    corrected = [item for item in yaml.safe_load_all(ADMISSION.read_text()) if item]
    expect(len(old["spec"]["validations"]), 2, "invalidated v7 validation count")
    expect([item["kind"] for item in corrected], ["ValidatingAdmissionPolicy", "ValidatingAdmissionPolicyBinding"], "corrected admission objects")
    policy, binding = corrected
    expect(policy["spec"]["failurePolicy"], "Fail", "failure policy")
    expect(len(policy["spec"]["validations"]), 1, "corrected validation count")
    actual_expression = policy["spec"]["validations"][0]["expression"]
    expect(actual_expression, expression(identities), "OR identity expression")
    expect(actual_expression.count(" || "), 1, "OR branch count")
    expect(actual_expression.count("has(request.namespace)"), 1, "namespace presence guard")
    expect(binding["spec"]["policyName"], policy["metadata"]["name"], "binding")
    expect(binding["spec"]["validationActions"], ["Deny"], "validation action")
    invalidation = yaml.safe_load(INVALIDATION.read_text())["spec"]
    expect(invalidation["state"], "INVALID-FOR-EXECUTION", "v7 execution state")
    expect(invalidation["defect"]["observedValidationEntries"], 2, "defect observation")
    expect(invalidation["resolution"]["newRiskAcceptanceRequired"], True, "new risk decision")
    expect(invalidation["authorization"]["mutationAuthorized"], False, "mutation authorization")
    return {
        "state": "CORRECTED-OFFLINE-NO-GO",
        "oldValidationEntries": 2,
        "correctedValidationEntries": 1,
        "clusterScopedIdentities": sum(not item["namespace"] for item in identities),
        "namespacedIdentities": sum(bool(item["namespace"]) for item in identities),
        "correctedAdmissionDigest": sha(ADMISSION),
        "mutationAuthorized": False,
        "clusterContacted": False,
    }


def main() -> int:
    try:
        print(json.dumps(verify(), sort_keys=True, separators=(",", ":")))
        return 0
    except (AdmissionError, KeyError, OSError, TypeError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

