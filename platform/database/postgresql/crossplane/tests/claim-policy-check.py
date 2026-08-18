#!/usr/bin/env python3
"""Validate the DatabaseClaim schema and fail-closed delegated-authority boundary."""

from __future__ import annotations

import argparse
import copy
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
EXPECTED = (
    "oidc:database-claim-editors",
    "openkubes-system",
    "ok-robotics",
    "ok-robotics",
    "database-ok-robotics",
    "database-ok-robotics-app",
    "crossplane-system",
)
TUPLE_KEYS = (
    "group",
    "claimNamespace",
    "claimName",
    "clusterRef",
    "namespace",
    "credentialsSecretName",
    "credentialsSecretNamespace",
)
EXPECTED_ALLOCATION_EXPRESSION = "variables.authorizations.exists(a, request.namespace == a['claimNamespace'] && object.metadata.name == a['claimName'] && object.spec.clusterRef == a['clusterRef'] && object.spec.namespace == a['namespace'] && object.spec.credentialsSecretRef.name == a['credentialsSecretName'] && object.spec.credentialsSecretRef.namespace == a['credentialsSecretNamespace'])"
EXPECTED_CLAIMANT_EXPRESSION = "variables.authorizations.exists(a, request.userInfo.groups.exists(g, g == a['group']) && request.namespace == a['claimNamespace'] && object.metadata.name == a['claimName'] && object.spec.clusterRef == a['clusterRef'] && object.spec.namespace == a['namespace'] && object.spec.credentialsSecretRef.name == a['credentialsSecretName'] && object.spec.credentialsSecretRef.namespace == a['credentialsSecretNamespace'])"


def documents(path: str) -> list[dict]:
    return [item for item in yaml.safe_load_all((ROOT / path).read_text()) if item]


def load_inputs() -> dict:
    policy, binding = documents("claim-admission-policy.yaml")
    return {
        "policy": policy,
        "binding": binding,
        "role": documents("rbac/claim-editor-role.yaml")[0],
        "rolebinding": documents("rbac/claim-editor-binding.yaml")[0],
        "xrd": documents("xrd.yaml")[0],
        "composition_text": (ROOT / "composition.yaml").read_text(),
    }


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def mapping(policy: dict) -> tuple[str, ...]:
    variables = {v["name"]: v["expression"] for v in policy["spec"]["variables"]}
    expression = variables.get("authorizations", "")
    values = []
    for key in TUPLE_KEYS:
        found = re.findall(rf"'{key}':\s*'([^']+)'", expression)
        require(len(found) == 1, f"authorization tuple must contain exactly one {key}")
        values.append(found[0])
    require(expression.count("{") == 1 and expression.count("}") == 1,
            "authorization must remain an explicit single tuple list")
    return tuple(values)


def validate(data: dict) -> None:
    policy = data["policy"]
    pspec = policy["spec"]
    require(pspec.get("failurePolicy") == "Fail", "admission policy must fail closed")
    rules = pspec["matchConstraints"]["resourceRules"]
    require(pspec["matchConstraints"].get("matchPolicy") == "Exact",
            "admission resource matching must be exact")
    require(rules == [{
        "apiGroups": ["platform.openkubes.ai"],
        "apiVersions": ["v1alpha1"],
        "operations": ["CREATE", "UPDATE"],
        "resources": ["databaseclaims"],
        "scope": "Namespaced",
    }], "admission policy must cover exactly DatabaseClaim CREATE and UPDATE")
    require(mapping(policy) == EXPECTED, "authorization tuple differs from the reviewed allocation")

    variables = {v["name"]: v["expression"] for v in pspec["variables"]}
    allocation = variables["allocationIsAuthorized"]
    claimant = variables["claimantIsAuthorized"]
    require(" ".join(allocation.split()) == EXPECTED_ALLOCATION_EXPRESSION,
            "allocation authorization must exactly match the reviewed conjunction")
    require(" ".join(claimant.split()) == EXPECTED_CLAIMANT_EXPRESSION,
            "claimant authorization must exactly match the reviewed conjunction")
    for token in (
        "request.namespace == a['claimNamespace']",
        "object.metadata.name == a['claimName']",
        "object.spec.clusterRef == a['clusterRef']",
        "object.spec.namespace == a['namespace']",
        "object.spec.credentialsSecretRef.name == a['credentialsSecretName']",
        "object.spec.credentialsSecretRef.namespace == a['credentialsSecretNamespace']",
    ):
        require(token in allocation and token in claimant,
                f"authorization expressions omitted exact coordinate: {token}")
    require("request.userInfo.groups.exists" in claimant,
            "claimant authorization must inspect authenticated groups")
    require(variables["isCrossplaneControllerUpdate"].count(
        "system:serviceaccount:crossplane-system:crossplane") == 1,
        "controller UPDATE exception must name only the exact Crossplane service account")

    binding = data["binding"]
    require(binding["spec"].get("validationActions") == ["Deny"],
            "admission binding must deny")
    require(binding["spec"].get("policyName") == policy["metadata"]["name"],
            "admission binding must select this policy")
    require("namespaceSelector" not in binding["spec"] and "matchResources" not in binding["spec"],
            "admission binding must not create a namespace bypass")

    role = data["role"]
    require(role["metadata"].get("namespace") == "openkubes-system",
            "claim-editor Role must remain namespaced to openkubes-system")
    require(role["rules"] == [{
        "apiGroups": ["platform.openkubes.ai"],
        "resources": ["databaseclaims"],
        "verbs": ["create", "get", "list", "patch", "update", "watch"],
    }], "claim-editor Role must cover DatabaseClaims only and exclude delete/Secrets")
    rb = data["rolebinding"]
    require(rb["subjects"] == [{
        "kind": "Group", "name": EXPECTED[0], "apiGroup": "rbac.authorization.k8s.io"
    }], "claim-editor RoleBinding must pin the reviewed OIDC group")
    require(rb["roleRef"] == {
        "kind": "Role", "name": "database-claim-editor",
        "apiGroup": "rbac.authorization.k8s.io",
    }, "claim-editor RoleBinding must select the claim-only Role")

    xrd = data["xrd"]
    require(xrd["spec"]["group"] == "platform.openkubes.ai", "XRD API group regression")
    require(xrd["spec"]["names"]["kind"] == "Database", "XR kind regression")
    require(xrd["spec"]["names"]["plural"] == "databases", "XR plural regression")
    require(xrd["spec"]["claimNames"] == {
        "kind": "DatabaseClaim", "plural": "databaseclaims"
    }, "Claim identity regression")
    version = next(v for v in xrd["spec"]["versions"] if v["name"] == "v1alpha1")
    served = {v["name"] for v in xrd["spec"]["versions"] if v.get("served")}
    require(served == {"v1alpha1"}, "admission policy must cover every served Claim version")
    spec = version["schema"]["openAPIV3Schema"]["properties"]["spec"]["properties"]
    require("dataPolicyRef" not in spec, "v1 must not expose unresolved dataPolicyRef authority")
    require(spec["engine"]["properties"]["name"].get("enum") == ["postgresql"],
            "engine.name must remain closed to postgresql")
    capabilities = spec["engine"]["properties"]["capabilities"]["items"]["properties"]
    require(capabilities["name"].get("enum") == ["postgresql.extension.pgvector"] and
            capabilities["versionPolicy"].get("enum") == ["platform"],
            "capability name/version policy must remain platform-governed")
    require(spec["performance"]["properties"]["class"].get("enum") == ["standard"],
            "performance.class must remain closed")
    require(spec["availability"]["properties"]["mode"].get("enum") == ["single", "ha"],
            "availability.mode must remain closed")
    pooling = spec["connectivity"]["properties"]["pooling"]["properties"]
    require(pooling["mode"].get("enum") == ["session", "transaction"],
            "connectivity.pooling.mode must remain closed")
    require(spec["isolation"]["properties"]["class"].get("enum") == ["dedicated"],
            "isolation.class must remain closed")
    require(spec["protection"]["properties"]["policyRef"].get("enum") == ["development", "production"],
            "protection.policyRef must remain closed")
    maintenance = spec["maintenance"]["properties"]
    require(maintenance["upgradePolicy"].get("enum") == ["controlled"] and
            maintenance["windowRef"].get("enum") == ["saturday-night"] and
            maintenance["majorVersionStrategy"].get("enum") == ["blueGreen"],
            "maintenance authority must remain controlled and blueGreen-only")
    require("enum" not in spec["clusterRef"] and "enum" not in spec["namespace"],
            "portable target syntax must be authorized by admission, not environment enums")
    creds = spec["credentialsSecretRef"]["properties"]
    require(creds["name"].get("enum") == [EXPECTED[5]], "credential Secret name must be schema-pinned")
    require(creds["namespace"].get("enum") == [EXPECTED[6]],
            "credential Secret namespace must be schema-pinned")

    composition = data["composition_text"]
    # Absolute bans: these appear only as deprecated CNPG Cluster status fields, or as the
    # deprecated in-tree backup stanza, so any occurrence at all is wrong.
    for forbidden in (
        "lastSuccessfulBackupByMethod", "firstRecoverabilityPointByMethod", "barmanObjectStore",
    ):
        require(forbidden not in composition, f"Composition uses forbidden/deprecated field {forbidden}")
    # Context-sensitive, and a name-only ban got this wrong: the Barman plugin's ObjectStore
    # publishes status.serverRecoveryWindow[<server>] with lastSuccessfulBackupTime,
    # firstRecoverabilityPoint and lastFailedBackupTime. `firstRecoverabilityPoint` is spelled
    # IDENTICALLY to the deprecated Cluster field, and `lastSuccessfulBackupTime` merely contains
    # the deprecated name as a substring — so banning the names rejected a correct Composition
    # (measured 2026-08-17). What is actually forbidden is reading freshness FROM THE CLUSTER,
    # because CNPG does not populate those Cluster fields for plugin-based backups.
    cluster_sources = ("$clusterStatus", "$clusterManifest")
    for number, line in enumerate(composition.splitlines(), 1):
        if not any(source in line for source in cluster_sources):
            continue
        for name in ("lastSuccessfulBackup", "firstRecoverabilityPoint", "lastFailedBackup"):
            require(
                name not in line,
                f"Composition line {number} reads deprecated freshness field {name} from Cluster "
                "status; plugin backups leave it unset — read the ObjectStore recovery window",
            )
    for required in ('dig "phase"', 'dig "stoppedAt"', 'dig "backupId"'):
        require(required in composition, f"Composition must read Backup status via {required}")


def negative_controls(source: dict) -> None:
    cases = []

    def schema_spec(data):
        version = next(v for v in data["xrd"]["spec"]["versions"] if v["name"] == "v1alpha1")
        return version["schema"]["openAPIV3Schema"]["properties"]["spec"]["properties"]

    def case(name, mutate, expected):
        candidate = copy.deepcopy(source)
        mutate(candidate)
        cases.append((name, candidate, expected))

    case("failurePolicy", lambda d: d["policy"]["spec"].update(failurePolicy="Ignore"), "fail closed")
    case("binding action", lambda d: d["binding"]["spec"].update(validationActions=["Warn"]), "must deny")
    case("CEL disjunction bypass", lambda d: [v.update(expression=f"({v['expression']}) || true") for v in d["policy"]["spec"]["variables"] if v["name"] in {"allocationIsAuthorized", "claimantIsAuthorized"}], "reviewed conjunction")
    case("CEL ternary bypass", lambda d: [v.update(expression=f"true ? true : ({v['expression']})") for v in d["policy"]["spec"]["variables"] if v["name"] in {"allocationIsAuthorized", "claimantIsAuthorized"}], "reviewed conjunction")
    case("namespace bypass", lambda d: d["binding"]["spec"].update(namespaceSelector={}), "namespace bypass")
    case("Role reaches Secrets", lambda d: d["role"]["rules"][0]["resources"].append("secrets"), "DatabaseClaims only")
    case("RoleBinding widens group", lambda d: d["rolebinding"]["subjects"].append(copy.deepcopy(d["rolebinding"]["subjects"][0])), "pin the reviewed")
    case("engine enum opens", lambda d: next(v for v in d["xrd"]["spec"]["versions"] if v["name"] == "v1alpha1")["schema"]["openAPIV3Schema"]["properties"]["spec"]["properties"]["engine"]["properties"]["name"].pop("enum"), "engine.name")
    case("capability enum opens", lambda d: schema_spec(d)["engine"]["properties"]["capabilities"]["items"]["properties"]["name"].pop("enum"), "capability name/version")
    case("performance enum opens", lambda d: schema_spec(d)["performance"]["properties"]["class"].pop("enum"), "performance.class")
    case("availability enum opens", lambda d: schema_spec(d)["availability"]["properties"]["mode"].pop("enum"), "availability.mode")
    case("pooling enum opens", lambda d: schema_spec(d)["connectivity"]["properties"]["pooling"]["properties"]["mode"].pop("enum"), "connectivity.pooling.mode")
    case("protection enum opens", lambda d: schema_spec(d)["protection"]["properties"]["policyRef"].pop("enum"), "protection.policyRef")
    case("isolation enum opens", lambda d: schema_spec(d)["isolation"]["properties"]["class"].pop("enum"), "isolation.class")
    case("major upgrade opens", lambda d: schema_spec(d)["maintenance"]["properties"]["majorVersionStrategy"]["enum"].append("inPlace"), "maintenance authority")
    case("credential name opens", lambda d: schema_spec(d)["credentialsSecretRef"]["properties"]["name"].pop("enum"), "credential Secret name")
    case("credential namespace opens", lambda d: schema_spec(d)["credentialsSecretRef"]["properties"]["namespace"].pop("enum"), "credential Secret namespace")
    case("unresolved data policy", lambda d: schema_spec(d).update(dataPolicyRef={"type": "string"}), "dataPolicyRef")
    case("deprecated freshness by method", lambda d: d.update(composition_text=d["composition_text"] + "\n# lastSuccessfulBackupByMethod\n"), "forbidden/deprecated")
    case("freshness read from Cluster status", lambda d: d.update(composition_text=d["composition_text"] + '\n{{- $x := dig "lastSuccessfulBackup" "" $clusterStatus }}\n'), "from Cluster status")
    case("deprecated in-tree backup", lambda d: d.update(composition_text=d["composition_text"] + "\n# barmanObjectStore\n"), "forbidden/deprecated")

    for name, candidate, expected in cases:
        try:
            validate(candidate)
        except AssertionError as error:
            require(expected in str(error), f"negative control {name} failed for wrong reason: {error}")
            print(f"REJECTED [{name}]: {error}")
        else:
            raise AssertionError(f"negative control unexpectedly passed: {name}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--negative-controls", action="store_true")
    args = parser.parse_args()
    data = load_inputs()
    if args.negative_controls:
        negative_controls(data)
        print("OK: claim policy negative controls were rejected for the intended reasons")
        return
    validate(data)
    print("OK: DatabaseClaim schema, tuple authorization, RBAC, and deprecated-field guards passed")


if __name__ == "__main__":
    main()
