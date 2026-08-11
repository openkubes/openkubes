#!/usr/bin/env python3
"""Verify the offline-only M0a v2 authorization and admission boundary."""

from __future__ import annotations

import argparse
import hashlib
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent


class VerificationError(ValueError):
    pass


RESOURCE = {
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
TUPLE_RE = re.compile(
    r"\{'group':'(?P<group>[^']*)','resource':'(?P<resource>[^']*)',"
    r"'namespace':'(?P<namespace>[^']*)','name':'(?P<name>[^']*)'\}"
)


def sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def expect(actual: Any, expected: Any, claim: str) -> None:
    if actual != expected:
        raise VerificationError(f"{claim}: expected {expected!r}, got {actual!r}")


def documents(path: Path) -> list[dict[str, Any]]:
    return [item for item in yaml.safe_load_all(path.read_text()) if item]


def resolve(reference: Path, expected_digest: str | None = None) -> Path:
    target = (HERE / reference).resolve()
    if SPIKE.resolve() not in target.parents or not target.is_file():
        raise VerificationError(f"reference missing or outside spike root: {reference}")
    if expected_digest:
        expect(sha(target), expected_digest, f"digest for {reference}")
    return target


def identity(item: dict[str, Any]) -> tuple[str, str, str, str]:
    api_version = item["apiVersion"]
    group = "" if "/" not in api_version else api_version.split("/", 1)[0]
    return (
        group,
        RESOURCE[item["kind"]],
        item["metadata"].get("namespace", ""),
        item["metadata"]["name"],
    )


def verify(candidate_path: Path) -> str:
    candidate = yaml.safe_load(candidate_path.read_text())["spec"]
    expect(candidate["state"], "BLOCKED-OFFLINE-CANDIDATE", "candidate state")
    expect(candidate["cause"]["firstRunResult"], "STOP-NOT-SUCCESS", "historical result")
    expect(candidate["cause"]["grantConsumed"], True, "grant consumption")
    evidence = resolve(Path(candidate["cause"]["evidencePath"]), candidate["cause"]["evidenceDigest"])
    expect(yaml.safe_load(evidence.read_text())["spec"]["execution"]["retryAuthorized"], False, "historical retry")

    protocol_path = resolve(
        Path(candidate["immutableInputs"]["installationProtocolPath"]),
        candidate["immutableInputs"]["installationProtocolDigest"],
    )
    protocol = yaml.safe_load(protocol_path.read_text())["spec"]
    source_path = (protocol_path.parent / protocol["source"]["manifestPath"]).resolve()
    reviewed = documents(source_path)
    expect(len(reviewed), 19, "reviewed object count")
    expected_identities = {identity(item) for item in reviewed}
    expect(len(expected_identities), 19, "unique reviewed identities")

    rbac_path = resolve(Path(candidate["credentialBoundary"]["rbacPath"]), candidate["credentialBoundary"]["rbacDigest"])
    rbac = documents(rbac_path)
    expect([item["kind"] for item in rbac], ["ServiceAccount", "ClusterRole", "ClusterRoleBinding"], "RBAC object set")
    rules = rbac[1]["rules"]
    forbidden = {"patch", "update", "delete", "deletecollection", "list", "watch", "impersonate", "bind", "escalate", "*"}
    if any(forbidden.intersection(rule["verbs"]) for rule in rules):
        raise VerificationError("RBAC contains a forbidden verb")
    if any("*" in rule["apiGroups"] or "*" in rule["resources"] for rule in rules):
        raise VerificationError("RBAC contains a wildcard")

    expected_types = {(group, resource) for group, resource, _, _ in expected_identities}
    create_types = {
        (group, resource)
        for rule in rules
        if rule["verbs"] == ["create"]
        for group in rule["apiGroups"]
        for resource in rule["resources"]
    }
    expect(create_types, expected_types, "create resource types")
    get_names: dict[tuple[str, str], set[str]] = defaultdict(set)
    for rule in rules:
        if rule["verbs"] == ["get"]:
            expect(len(rule["apiGroups"]), 1, "get rule API group count")
            expect(len(rule["resources"]), 1, "get rule resource count")
            get_names[(rule["apiGroups"][0], rule["resources"][0])].update(rule["resourceNames"])
    expected_names: dict[tuple[str, str], set[str]] = defaultdict(set)
    for group, resource, _, name in expected_identities:
        expected_names[(group, resource)].add(name)
    expect(dict(get_names), dict(expected_names), "get exact names")

    admission_path = resolve(Path(candidate["admissionBoundary"]["manifestPath"]), candidate["admissionBoundary"]["manifestDigest"])
    admission = documents(admission_path)
    expect([item["kind"] for item in admission], ["ValidatingAdmissionPolicy", "ValidatingAdmissionPolicyBinding"], "admission object set")
    policy, binding = admission
    expect(policy["spec"]["failurePolicy"], "Fail", "admission failure policy")
    expect(binding["spec"]["validationActions"], ["Deny"], "admission action")
    expect(binding["spec"]["policyName"], policy["metadata"]["name"], "admission binding")
    expect(policy["spec"]["matchConditions"], [{
        "name": "exact-installer-principal",
        "expression": "request.userInfo.username == 'system:serviceaccount:openkubes-system:ok141-m0a-installer-v2'",
    }], "installer principal match")
    rules_types = {
        (group, resource)
        for rule in policy["spec"]["matchConstraints"]["resourceRules"]
        if rule["operations"] == ["CREATE"]
        for group in rule["apiGroups"]
        for resource in rule["resources"]
    }
    expect(rules_types, expected_types, "admission resource types")
    expression = policy["spec"]["validations"][0]["expression"]
    admitted_identities = {
        (match["group"], match["resource"], match["namespace"], match["name"])
        for match in TUPLE_RE.finditer(expression)
    }
    expect(admitted_identities, expected_identities, "admission exact identities")
    expect(len(admitted_identities), candidate["admissionBoundary"]["allowedIdentities"], "admission identity count")

    expect(candidate["credentialBoundary"]["allowedVerbs"], ["create", "get"], "allowed verbs")
    for claim in ("patchAllowed", "updateAllowed", "deleteAllowed", "listAllowed", "watchAllowed"):
        expect(candidate["credentialBoundary"][claim], False, claim)
    expect(candidate["revocationBoundary"]["individualTokenRevocationAvailable"], False, "individual revocation")
    expect(candidate["revocationBoundary"]["immediateRejectionClaim"], False, "immediate rejection claim")
    expect(candidate["revocationBoundary"]["hardUpperExposureBound"], "token-expiry-at-most-10m", "token expiry boundary")
    expect(candidate["authorization"], {
        "decision": "NO-GO",
        "mutationAuthorized": False,
        "credentialGrantRequired": True,
        "admissionBootstrapGrantRequired": True,
        "installationGrantRequired": True,
        "retryGranted": False,
        "m0bInstallationGranted": False,
        "go1Granted": False,
        "evidencePublicationGranted": False,
        "failureInjectionGranted": False,
    }, "authorization boundary")
    return sha(candidate_path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--digest-file", type=Path)
    args = parser.parse_args()
    try:
        result = verify(args.candidate.resolve())
        if args.digest_file:
            expect(args.digest_file.read_text().strip(), result, "candidate digest")
        print(result)
        return 0
    except (OSError, KeyError, TypeError, ValueError, VerificationError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
