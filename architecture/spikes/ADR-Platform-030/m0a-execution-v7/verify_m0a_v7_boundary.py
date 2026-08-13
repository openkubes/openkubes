#!/usr/bin/env python3
"""Fail-closed verifier for the offline M0a-v7 authority partition."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import yaml


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
PARTITION = HERE / "m0a-v7-authority-partition-v1.yaml"

KIND_RESOURCE = {
    "Namespace": "namespaces",
    "CustomResourceDefinition": "customresourcedefinitions",
    "ServiceAccount": "serviceaccounts",
    "Role": "roles",
    "ClusterRole": "clusterroles",
    "RoleBinding": "rolebindings",
    "ClusterRoleBinding": "clusterrolebindings",
    "ConfigMap": "configmaps",
    "Service": "services",
    "Deployment": "deployments",
    "Certificate": "certificates",
    "Issuer": "issuers",
    "MutatingWebhookConfiguration": "mutatingwebhookconfigurations",
    "ValidatingWebhookConfiguration": "validatingwebhookconfigurations",
}
RBAC_KINDS = {"Role", "ClusterRole", "RoleBinding", "ClusterRoleBinding"}


class BoundaryError(ValueError):
    pass


def _load_harness():
    path = SPIKE / "harness" / "ok141_harness.py"
    spec = importlib.util.spec_from_file_location("ok141_m0a_v7_harness", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


HARNESS = _load_harness()


def sha_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def expect(actual: Any, expected: Any, claim: str) -> None:
    if actual != expected:
        raise BoundaryError(f"{claim}: expected {expected!r}, got {actual!r}")


def api_group(document: dict[str, Any]) -> str:
    version = document["apiVersion"]
    return "" if "/" not in version else version.split("/", 1)[0]


def identity(document: dict[str, Any]) -> dict[str, str]:
    return {
        "group": api_group(document),
        "resource": KIND_RESOURCE[document["kind"]],
        "namespace": document["metadata"].get("namespace", ""),
        "name": document["metadata"]["name"],
    }


def identity_key(value: dict[str, str]) -> tuple[str, str, str, str]:
    return tuple(value[field] for field in ("group", "resource", "namespace", "name"))


def resolve(base: Path, requested: str) -> Path:
    path = (base / requested).resolve()
    if SPIKE.resolve() not in path.parents or not path.is_file():
        raise BoundaryError(f"reference missing or outside spike root: {requested}")
    return path


def expected_expression(identities: list[dict[str, str]], namespaced: bool) -> str:
    fields = ("group", "resource", "namespace", "name") if namespaced else ("group", "resource", "name")
    values = []
    for item in identities:
        body = ",".join(f"'{field}':'{item[field]}'" for field in fields)
        values.append("{" + body + "}")
    comparisons = [
        "request.resource.group == x.group",
        "request.resource.resource == x.resource",
    ]
    if namespaced:
        comparisons.append("request.namespace == x.namespace")
    comparisons.append("object.metadata.name == x.name")
    return "[" + ",".join(values) + "].exists(x, " + " && ".join(comparisons) + ")"


def rule_inventory(policy: dict[str, Any]) -> set[tuple[str, str]]:
    result: set[tuple[str, str]] = set()
    for rule in policy["spec"]["matchConstraints"]["resourceRules"]:
        expect(rule["operations"], ["CREATE"], "admission operation")
        expect(rule["apiVersions"], ["v1"], "admission API version")
        for group in rule["apiGroups"]:
            for resource in rule["resources"]:
                result.add((group, resource))
    return result


def verify(path: Path = PARTITION) -> dict[str, Any]:
    model = yaml.safe_load(path.read_text())
    spec = model["spec"]
    expect(spec["version"], "ok141-m0a-authority-partition/v1", "partition version")
    expect(spec["state"], "OFFLINE-ONLY-NO-GO", "partition state")
    expect(spec["authorization"]["mutationAuthorized"], False, "mutation authorization")
    expect(spec["authorization"]["publicationGranted"], False, "publication authorization")

    source_path = resolve(path.parent, spec["source"]["path"])
    raw = source_path.read_bytes()
    documents = [item for item in yaml.safe_load_all(raw) if item]
    expect(sha_bytes(raw), spec["source"]["rawDigest"], "source raw digest")
    expect(HARNESS.semantic_revision(documents), spec["source"]["semanticDigest"], "source semantic digest")
    expect(len(documents), spec["source"]["objectCount"], "source object count")
    source_by_key = {identity_key(identity(item)): item for item in documents}
    expect(len(source_by_key), len(documents), "unique source identities")

    domains: dict[str, list[dict[str, Any]]] = {}
    domain_keys: dict[str, set[tuple[str, str, str, str]]] = {}
    for name in ("administrator", "temporaryInstaller"):
        domain = spec["authorityDomains"][name]
        keys = [identity_key(item) for item in domain["identities"]]
        expect(len(keys), len(set(keys)), f"unique {name} identities")
        unknown = set(keys) - set(source_by_key)
        expect(unknown, set(), f"{name} identities in reviewed source")
        selected = [item for item in documents if identity_key(identity(item)) in set(keys)]
        expect(len(selected), domain["expectedCount"], f"{name} object count")
        expect(HARNESS.semantic_revision(selected), domain["expectedSemanticDigest"], f"{name} semantic digest")
        domains[name] = selected
        domain_keys[name] = set(keys)

    expect(domain_keys["administrator"] & domain_keys["temporaryInstaller"], set(), "authority domains disjoint")
    expect(domain_keys["administrator"] | domain_keys["temporaryInstaller"], set(source_by_key), "authority domains cover source")
    admin_kinds = Counter(item["kind"] for item in domains["administrator"])
    expect(admin_kinds, Counter({"Namespace": 1, "Role": 1, "ClusterRole": 3, "RoleBinding": 1, "ClusterRoleBinding": 2}), "administrator kind boundary")
    if any(item["kind"] == "Namespace" or item["kind"] in RBAC_KINDS for item in domains["temporaryInstaller"]):
        raise BoundaryError("temporary installer contains Namespace or RBAC")

    admission_path = resolve(path.parent, spec["admission"]["path"])
    admission_raw = admission_path.read_bytes()
    expect(sha_bytes(admission_raw), spec["admission"]["rawDigest"], "admission raw digest")
    admission = [item for item in yaml.safe_load_all(admission_raw) if item]
    expect([item["kind"] for item in admission], ["ValidatingAdmissionPolicy", "ValidatingAdmissionPolicyBinding"], "admission object set")
    policy, binding = admission
    expect(policy["spec"]["failurePolicy"], "Fail", "admission failure policy")
    expect(binding["spec"]["policyName"], policy["metadata"]["name"], "admission binding")
    expect(binding["spec"]["validationActions"], ["Deny"], "admission action")
    expect(policy["spec"]["matchConditions"], [{"name": "exact-installer-principal", "expression": f"request.userInfo.username == '{spec['admission']['principal']}'"}], "installer principal")

    installer_identities = spec["authorityDomains"]["temporaryInstaller"]["identities"]
    cluster = [item for item in installer_identities if not item["namespace"]]
    namespaced = [item for item in installer_identities if item["namespace"]]
    validations = policy["spec"]["validations"]
    expect(len(validations), 2, "admission validation count")
    expect(validations[0]["expression"], expected_expression(cluster, False), "cluster-scoped identity expression")
    expect(validations[1]["expression"], expected_expression(namespaced, True), "namespaced identity expression")
    expect(rule_inventory(policy), {(item["group"], item["resource"]) for item in installer_identities}, "admission resource boundary")
    serialized = json.dumps(policy, sort_keys=True)
    if "rbac.authorization.k8s.io" in serialized or "namespaces" in serialized or "escalate" in serialized or "bind" in serialized:
        raise BoundaryError("temporary admission contains administrator or escalation capability")

    return {
        "state": spec["state"],
        "sourceObjects": len(documents),
        "administratorObjects": len(domains["administrator"]),
        "temporaryInstallerObjects": len(domains["temporaryInstaller"]),
        "clusterScopedAdmissionIdentities": len(cluster),
        "namespacedAdmissionIdentities": len(namespaced),
        "mutationAuthorized": False,
        "clusterContacted": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--partition", type=Path, default=PARTITION)
    args = parser.parse_args()
    try:
        print(json.dumps(verify(args.partition.resolve()), sort_keys=True, separators=(",", ":")))
        return 0
    except (BoundaryError, KeyError, OSError, TypeError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

