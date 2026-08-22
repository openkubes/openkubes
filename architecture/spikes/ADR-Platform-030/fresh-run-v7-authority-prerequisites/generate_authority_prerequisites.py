#!/usr/bin/env python3
"""Generate the non-authorizing Fresh-Run-v7 writer prerequisites."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml


HERE = Path(__file__).resolve().parent
FRESH = HERE.parent / "fresh-run-v7"
PLAN = "sha256:4f61e81b3f3dba5a2819e5be93764486d5a936f3fb2ba153a80d5866801af19c"
PROVIDER_POLICY = "sha256:06c7aed0997611819acc0606dd16efc7a966a8b8d8589b290b887bed256a0a01"
MGMT_NAME = "ok147-fresh-run-v7-management-writer"
GITOPS_NAME = "ok147-fresh-run-v7-gitops-writer"


def digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def documents(path: Path) -> list[dict]:
    return [item for item in yaml.safe_load_all(path.read_text()) if item]


def identities(path: Path) -> list[tuple[str, str, str]]:
    return [(item["apiVersion"].split("/", 1)[0] if "/" in item["apiVersion"] else "",
             item["kind"], item["metadata"]["name"]) for item in documents(path)]


def dump(path: Path, values: list[dict]) -> None:
    path.write_text(yaml.safe_dump_all(values, sort_keys=False, explicit_start=False))


def management_package() -> list[dict]:
    lifecycle = identities(FRESH / "artifacts/cluster-lifecycle.yaml")
    enablement = identities(FRESH / "artifacts/enablement.yaml")
    names = {(group, kind): name for group, kind, name in lifecycle + enablement if kind != "Namespace"}
    names[("", "Secret")] = "external-infra-kubeconfig-disposable-ok141"
    exact = [
        ("", "secrets", names[("", "Secret")]),
        ("cluster.x-k8s.io", "clusters", names[("cluster.x-k8s.io", "Cluster")]),
        ("cluster.x-k8s.io", "machinedeployments", names[("cluster.x-k8s.io", "MachineDeployment")]),
        ("infrastructure.cluster.x-k8s.io", "kubevirtclusters", names[("infrastructure.cluster.x-k8s.io", "KubevirtCluster")]),
        ("infrastructure.cluster.x-k8s.io", "kubevirtmachinetemplates", names[("infrastructure.cluster.x-k8s.io", "KubevirtMachineTemplate")]),
        ("controlplane.cluster.x-k8s.io", "taloscontrolplanes", names[("controlplane.cluster.x-k8s.io", "TalosControlPlane")]),
        ("bootstrap.cluster.x-k8s.io", "talosconfigtemplates", names[("bootstrap.cluster.x-k8s.io", "TalosConfigTemplate")]),
        ("addons.cluster.x-k8s.io", "helmchartproxies", names[("addons.cluster.x-k8s.io", "HelmChartProxy")]),
    ]
    machine_template_names = sorted(name for group, kind, name in lifecycle if kind == "KubevirtMachineTemplate")
    clauses = []
    for group, resource, name in exact:
        accepted = machine_template_names if resource == "kubevirtmachinetemplates" else [name]
        names_expr = " || ".join(f"object.metadata.name == '{item}'" for item in accepted)
        clauses.append(f"(request.resource.group == '{group}' && request.resource.resource == '{resource}' && ({names_expr}))")
    expression = (
        "request.userInfo.username != 'system:serviceaccount:openkubes-execution-system:ok147-management-writer' || "
        "(request.namespace == 'disposable-ok141' && (" + " || ".join(clauses) + "))"
    )
    rules = [
        {"apiGroups": [""], "resources": ["secrets"], "verbs": ["get", "create"]},
        {"apiGroups": ["cluster.x-k8s.io"], "resources": ["clusters", "machinedeployments"], "verbs": ["get", "create"]},
        {"apiGroups": ["infrastructure.cluster.x-k8s.io"], "resources": ["kubevirtclusters", "kubevirtmachinetemplates"], "verbs": ["get", "create"]},
        {"apiGroups": ["controlplane.cluster.x-k8s.io"], "resources": ["taloscontrolplanes"], "verbs": ["get", "create"]},
        {"apiGroups": ["bootstrap.cluster.x-k8s.io"], "resources": ["talosconfigtemplates"], "verbs": ["get", "create"]},
        {"apiGroups": ["addons.cluster.x-k8s.io"], "resources": ["helmchartproxies"], "verbs": ["get", "create"]},
    ]
    versions = {
        "": "v1",
        "cluster.x-k8s.io": "v1beta2",
        "infrastructure.cluster.x-k8s.io": "v1alpha1",
        "controlplane.cluster.x-k8s.io": "v1alpha3",
        "bootstrap.cluster.x-k8s.io": "v1alpha3",
        "addons.cluster.x-k8s.io": "v1alpha1",
    }
    resource_rules = [
        {"apiGroups": rule["apiGroups"], "apiVersions": [versions[rule["apiGroups"][0]]],
         "operations": ["CREATE"], "resources": rule["resources"], "scope": "Namespaced"}
        for rule in rules
    ]
    return [
        {"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "ClusterRole",
         "metadata": {"name": MGMT_NAME}, "rules": rules},
        {"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "ClusterRoleBinding",
         "metadata": {"name": MGMT_NAME},
         "roleRef": {"apiGroup": "rbac.authorization.k8s.io", "kind": "ClusterRole", "name": MGMT_NAME},
         "subjects": [{"kind": "ServiceAccount", "name": "ok147-management-writer", "namespace": "openkubes-execution-system"}]},
        {"apiVersion": "admissionregistration.k8s.io/v1", "kind": "ValidatingAdmissionPolicy",
         "metadata": {"name": MGMT_NAME},
         "spec": {"failurePolicy": "Fail", "matchConstraints": {"resourceRules": resource_rules},
                  "validations": [{"expression": expression,
                                   "message": "Fresh-Run-v7 management writer is restricted to exact disposable objects"}]}},
        {"apiVersion": "admissionregistration.k8s.io/v1", "kind": "ValidatingAdmissionPolicyBinding",
         "metadata": {"name": MGMT_NAME},
         "spec": {"policyName": MGMT_NAME, "validationActions": ["Deny"]}},
    ]


def gitops_package() -> list[dict]:
    registration = identities(FRESH / "artifacts/target-registration.yaml")
    applications = identities(FRESH / "artifacts/platform-applications.yaml")
    project = next(name for _, kind, name in registration if kind == "AppProject")
    secret = next(name for _, kind, name in registration if kind == "Secret")
    app_names = sorted(name for _, kind, name in applications if kind == "Application")
    app_expr = " || ".join(f"object.metadata.name == '{name}'" for name in app_names)
    expression = (
        "request.userInfo.username != 'system:serviceaccount:argocd:ok147-gitops-writer' || "
        "(request.namespace == 'argocd' && ("
        f"(request.resource.group == '' && request.resource.resource == 'secrets' && object.metadata.name == '{secret}') || "
        f"(request.resource.group == 'argoproj.io' && request.resource.resource == 'appprojects' && object.metadata.name == '{project}') || "
        f"(request.resource.group == 'argoproj.io' && request.resource.resource == 'applications' && ({app_expr}))"
        "))"
    )
    return [
        {"apiVersion": "v1", "kind": "ServiceAccount",
         "metadata": {"name": "ok147-gitops-writer", "namespace": "argocd"},
         "automountServiceAccountToken": False},
        {"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "Role",
         "metadata": {"name": GITOPS_NAME, "namespace": "argocd"},
         "rules": [
             {"apiGroups": [""], "resources": ["secrets"], "resourceNames": [secret], "verbs": ["get"]},
             {"apiGroups": [""], "resources": ["secrets"], "verbs": ["create"]},
             {"apiGroups": ["argoproj.io"], "resources": ["appprojects"], "resourceNames": [project], "verbs": ["get"]},
             {"apiGroups": ["argoproj.io"], "resources": ["appprojects"], "verbs": ["create"]},
             {"apiGroups": ["argoproj.io"], "resources": ["applications"], "resourceNames": app_names, "verbs": ["get"]},
             {"apiGroups": ["argoproj.io"], "resources": ["applications"], "verbs": ["create"]},
         ]},
        {"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "RoleBinding",
         "metadata": {"name": GITOPS_NAME, "namespace": "argocd"},
         "roleRef": {"apiGroup": "rbac.authorization.k8s.io", "kind": "Role", "name": GITOPS_NAME},
         "subjects": [{"kind": "ServiceAccount", "name": "ok147-gitops-writer", "namespace": "argocd"}]},
        {"apiVersion": "admissionregistration.k8s.io/v1", "kind": "ValidatingAdmissionPolicy",
         "metadata": {"name": GITOPS_NAME},
         "spec": {"failurePolicy": "Fail", "matchConstraints": {"resourceRules": [
             {"apiGroups": [""], "apiVersions": ["v1"], "operations": ["CREATE"], "resources": ["secrets"], "scope": "Namespaced"},
             {"apiGroups": ["argoproj.io"], "apiVersions": ["v1alpha1"], "operations": ["CREATE"],
              "resources": ["appprojects", "applications"], "scope": "Namespaced"},
         ]}, "validations": [{"expression": expression,
                               "message": "Fresh-Run-v7 GitOps writer is restricted to exact disposable objects"}]}},
        {"apiVersion": "admissionregistration.k8s.io/v1", "kind": "ValidatingAdmissionPolicyBinding",
         "metadata": {"name": GITOPS_NAME},
         "spec": {"policyName": GITOPS_NAME, "validationActions": ["Deny"]}},
    ]


def main() -> None:
    management = HERE / "ok-mgmt-authority.yaml"
    gitops = HERE / "ok-shared-authority.yaml"
    dump(management, management_package())
    dump(gitops, gitops_package())
    inventory = {
        "ok-mgmt": [{"kind": item["kind"], "namespace": item.get("metadata", {}).get("namespace", ""),
                     "name": item["metadata"]["name"]} for item in management_package()],
        "ok-shared": [{"kind": item["kind"], "namespace": item.get("metadata", {}).get("namespace", ""),
                       "name": item["metadata"]["name"]} for item in gitops_package()],
    }
    manifest = {
        "format": "ok147-fresh-run-v7-authority-prerequisites/v1",
        "authorizationState": "NO-GO",
        "planDigest": PLAN,
        "providerAccessPolicyDigest": PROVIDER_POLICY,
        "packages": {
            "ok-mgmt-authority.yaml": digest(management.read_bytes()),
            "ok-shared-authority.yaml": digest(gitops.read_bytes()),
        },
        "inventory": inventory,
        "boundaries": {"credentialsIncluded": False, "clusterContact": False,
                       "mutationAuthorized": False, "wildcardsAllowed": False},
    }
    (HERE / "package-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    main()
