#!/usr/bin/env python3
"""Fail-closed verifier for the Fresh-Run-v7 authority prerequisites."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import yaml


HERE = Path(__file__).resolve().parent
PLAN = "sha256:4f61e81b3f3dba5a2819e5be93764486d5a936f3fb2ba153a80d5866801af19c"
PROVIDER_POLICY = "sha256:06c7aed0997611819acc0606dd16efc7a966a8b8d8589b290b887bed256a0a01"
FORBIDDEN_VERBS = {"update", "patch", "delete", "deletecollection", "bind", "escalate", "impersonate"}


def digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def load_yaml(path: Path) -> list[dict]:
    return [item for item in yaml.safe_load_all(path.read_text()) if item]


def verify(root: Path = HERE) -> bool:
    try:
        manifest = json.loads((root / "package-manifest.json").read_text())
        if manifest.get("format") != "ok147-fresh-run-v7-authority-prerequisites/v1":
            return False
        if manifest.get("authorizationState") != "NO-GO" or manifest.get("planDigest") != PLAN:
            return False
        if manifest.get("providerAccessPolicyDigest") != PROVIDER_POLICY:
            return False
        boundaries = manifest.get("boundaries", {})
        if boundaries != {"credentialsIncluded": False, "clusterContact": False,
                           "mutationAuthorized": False, "wildcardsAllowed": False}:
            return False
        packages = manifest.get("packages", {})
        expected_counts = {"ok-mgmt-authority.yaml": 4, "ok-shared-authority.yaml": 5}
        all_documents = {}
        for name, count in expected_counts.items():
            raw = (root / name).read_bytes()
            if packages.get(name) != digest(raw):
                return False
            docs = load_yaml(root / name)
            if len(docs) != count:
                return False
            all_documents[name] = docs
        for docs in all_documents.values():
            for item in docs:
                for rule in item.get("rules", []):
                    values = rule.get("apiGroups", []) + rule.get("resources", []) + rule.get("verbs", [])
                    if "*" in values or FORBIDDEN_VERBS.intersection(rule.get("verbs", [])):
                        return False
                if item["kind"] == "ValidatingAdmissionPolicy":
                    if item.get("spec", {}).get("failurePolicy") != "Fail":
                        return False
                    for rule in item.get("spec", {}).get("matchConstraints", {}).get("resourceRules", []):
                        values = rule.get("apiGroups", []) + rule.get("apiVersions", []) + rule.get("resources", [])
                        if "*" in values or rule.get("operations") != ["CREATE"]:
                            return False
                if item["kind"] == "ValidatingAdmissionPolicyBinding":
                    if item.get("spec", {}).get("validationActions") != ["Deny"]:
                        return False
        mgmt = all_documents["ok-mgmt-authority.yaml"]
        mgmt_expression = next(x for x in mgmt if x["kind"] == "ValidatingAdmissionPolicy")["spec"]["validations"][0]["expression"]
        mgmt_names = {
            "disposable-ok141", "external-infra-kubeconfig-disposable-ok141", "disposable-ok141-cp",
            "disposable-ok141-workers", "disposable-ok141-workers-v1-9-6",
            "disposable-ok141-cp-7f5dd4276432", "disposable-ok141-workers-7f5dd4276432",
            "disposable-ok141-cilium",
        }
        if not all(name in mgmt_expression for name in mgmt_names):
            return False
        gitops = all_documents["ok-shared-authority.yaml"]
        if [x["kind"] for x in gitops] != ["ServiceAccount", "Role", "RoleBinding", "ValidatingAdmissionPolicy", "ValidatingAdmissionPolicyBinding"]:
            return False
        gitops_expression = next(x for x in gitops if x["kind"] == "ValidatingAdmissionPolicy")["spec"]["validations"][0]["expression"]
        gitops_names = {"openkubes-disposable", "disposable-ok141-cluster",
                        "disposable-ok141-observability-core", "disposable-ok141-observability-alerting",
                        "disposable-ok141-observability-dashboards"}
        if not all(name in gitops_expression for name in gitops_names):
            return False
        inventory = manifest.get("inventory", {})
        for cluster, filename in (("ok-mgmt", "ok-mgmt-authority.yaml"), ("ok-shared", "ok-shared-authority.yaml")):
            expected = [{"kind": x["kind"], "namespace": x.get("metadata", {}).get("namespace", ""),
                         "name": x["metadata"]["name"]} for x in all_documents[filename]]
            if inventory.get(cluster) != expected:
                return False
        return True
    except (KeyError, OSError, ValueError, TypeError, yaml.YAMLError):
        return False


if __name__ == "__main__":
    root = Path(sys.argv[1]) if len(sys.argv) == 2 else HERE
    if not verify(root):
        raise SystemExit("Fresh-Run-v7 authority prerequisite verification failed")
    print("Fresh-Run-v7 authority prerequisite verification PASS")
