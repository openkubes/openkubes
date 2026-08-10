#!/usr/bin/env python3
"""Normalize RBAC from an exact reviewed installation object set."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


INSTALLER = _load("ok141_bounded_installer_rbac", HERE / "bounded_installer.py")
V1 = INSTALLER.V1


def _sorted(value: Any) -> list[str]:
    return sorted(value or [])


def _rule(rule: dict[str, Any]) -> dict[str, Any]:
    return {
        "apiGroups": _sorted(rule.get("apiGroups")),
        "resources": _sorted(rule.get("resources")),
        "resourceNames": _sorted(rule.get("resourceNames")),
        "nonResourceURLs": _sorted(rule.get("nonResourceURLs")),
        "verbs": _sorted(rule.get("verbs")),
    }


def _findings(role: dict[str, Any], rule: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    verbs = set(rule["verbs"])
    resources = set(rule["resources"])
    api_groups = set(rule["apiGroups"])
    base = {"roleKind": role["kind"], "roleNamespace": role["namespace"], "roleName": role["name"]}

    def add(finding: str, reason: str) -> None:
        result.append({**base, "finding": finding, "reason": reason})

    if "*" in verbs:
        add("WILDCARD-VERB", "Rule authorizes every verb for its resource scope.")
    if "*" in resources or "*" in api_groups:
        add("WILDCARD-RESOURCE-SCOPE", "Rule contains a wildcard resource or API-group scope.")
    if "secrets" in resources and verbs & {"get", "list", "watch"}:
        add("SECRET-READ", "Rule can read Secret data in its role scope.")
    if "secrets" in resources and verbs & {"create", "patch", "update", "delete", "deletecollection", "*"}:
        add("SECRET-WRITE", "Rule can mutate Secrets in its role scope.")
    if resources & {"pods/exec", "pods/attach", "pods/portforward"}:
        add("POD-INTERACTIVE-SUBRESOURCE", "Rule can access an interactive Pod subresource.")
    if "tokenreviews" in resources and "authentication.k8s.io" in api_groups:
        add("TOKENREVIEW", "Rule can submit delegated authentication reviews.")
    if "subjectaccessreviews" in resources and "authorization.k8s.io" in api_groups:
        add("SUBJECTACCESSREVIEW", "Rule can submit delegated authorization reviews.")
    if verbs & {"impersonate", "escalate", "bind"}:
        add("RBAC-ESCALATION-VERB", "Rule contains impersonate, escalate, or bind.")
    return result


def analyze(reviewed: INSTALLER.ReviewedObjectSet, protocol_path: Path) -> dict[str, Any]:
    roles = []
    findings = []
    for document in reviewed.documents:
        if document["kind"] not in {"Role", "ClusterRole"}:
            continue
        metadata = document.get("metadata", {})
        role = {
            "kind": document["kind"],
            "namespace": metadata.get("namespace"),
            "name": metadata["name"],
            "rules": [_rule(rule) for rule in document.get("rules", [])],
        }
        role["rules"].sort(key=V1.jcs)
        roles.append(role)
        for rule in role["rules"]:
            findings.extend(_findings(role, rule))
    roles.sort(key=lambda item: (item["kind"], item["namespace"] or "", item["name"]))

    bindings = []
    for document in reviewed.documents:
        if document["kind"] not in {"RoleBinding", "ClusterRoleBinding"}:
            continue
        metadata = document.get("metadata", {})
        subjects = [
            {
                "kind": subject["kind"],
                "namespace": subject.get("namespace"),
                "name": subject["name"],
            }
            for subject in document.get("subjects", [])
        ]
        subjects.sort(key=V1.jcs)
        bindings.append({
            "kind": document["kind"],
            "namespace": metadata.get("namespace"),
            "name": metadata["name"],
            "roleRef": document["roleRef"],
            "subjects": subjects,
        })
    bindings.sort(key=lambda item: (item["kind"], item["namespace"] or "", item["name"]))
    findings.sort(key=V1.jcs)
    return {
        "apiVersion": "evidence.openkubes.io/v1alpha1",
        "kind": "RBACAnalysis",
        "metadata": {"name": f"ok141-{reviewed.gate.lower()}-rbac"},
        "spec": {
            "gate": reviewed.gate,
            "protocolDigest": V1.sha256_bytes(protocol_path.read_bytes()),
            "installationSemanticDigest": reviewed.semantic_digest,
            "roles": roles,
            "bindings": bindings,
            "findings": findings,
            "summary": {
                "roles": len(roles),
                "bindings": len(bindings),
                "findings": len(findings),
                "byFinding": dict(sorted(__import__("collections").Counter(item["finding"] for item in findings).items())),
            },
            "decision": "ANALYZED-NOT-ACCEPTED",
            "mutationAuthorized": False,
            "toolDigest": V1.sha256_bytes(Path(__file__).read_bytes()),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--materialized-dir", type=Path)
    args = parser.parse_args()
    protocol_path = args.protocol.resolve()
    protocol = V1.read_yaml_or_json(protocol_path)
    reviewed = INSTALLER.verify_reviewed_object_set(protocol, protocol_path, args.materialized_dir)
    print(json.dumps(analyze(reviewed, protocol_path), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
