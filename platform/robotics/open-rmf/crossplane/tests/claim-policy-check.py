#!/usr/bin/env python3
"""Assert the portable Claim schema and fail-closed authority boundary."""

from __future__ import annotations

import argparse
import copy
import json
import re
from pathlib import Path

import jsonschema
import yaml

ROOT = Path(__file__).resolve().parent.parent
CONTROL_FIELDS = (
    "compositionRef",
    "compositionSelector",
    "compositionRevisionRef",
    "compositionRevisionSelector",
    "compositionUpdatePolicy",
    "compositeDeletePolicy",
    "resourceRef",
    "writeConnectionSecretToRef",
)
EXPECTED_MAPPING = (
    "oidc:openrmf-claim-editors",
    "openkubes-system",
    "ok-robotics",
    "ok-robotics",
    "rmf",
    "robotics.openkubes.local",
)
KNOWN_CLAIM_SPEC_FIELDS = {
    "clusterRef",
    "namespace",
    "mode",
    "hostname",
    "credentialsSecretRef",
    *CONTROL_FIELDS,
}


def load(path: str):
    return yaml.safe_load((ROOT / path).read_text())


def load_documents(path: str):
    return list(yaml.safe_load_all((ROOT / path).read_text()))


def inputs() -> dict:
    policy, binding = load_documents("claim-admission-policy.yaml")
    return {
        "xrd": load("xrd.yaml"),
        "policy": policy,
        "binding": binding,
        "claim": load("examples/ok-robotics.yaml"),
        "composition": load("composition.yaml"),
        "role": load("rbac/claim-editor-role.yaml"),
        "makefile": (ROOT / "Makefile").read_text(),
    }


def mapping_from(policy: dict) -> list[tuple[str, str, str, str, str, str]]:
    variables = {v["name"]: v["expression"] for v in policy["spec"]["variables"]}
    expression = variables.get("authorizations", "")
    matches = re.findall(
        r"'group':\s*'([^']+)'\s*,\s*"
        r"'claimNamespace':\s*'([^']+)'\s*,\s*"
        r"'claimName':\s*'([^']+)'\s*,\s*"
        r"'clusterRef':\s*'([^']+)'\s*,\s*"
        r"'namespace':\s*'([^']+)'\s*,\s*"
        r"'hostname':\s*'([^']+)'",
        expression,
    )
    assert expression.count("{") == len(matches), (
        "every CEL authorization entry must use the canonical parsed key order and quoting"
    )
    assert matches and matches[0] == EXPECTED_MAPPING, (
        "authorization mapping must retain the reviewed initial allocation first: "
        + repr(matches)
    )
    assert len(matches) == len(set(matches)), "authorization mappings must be unique"
    return matches


def authorized(
    groups: tuple[str, ...],
    claim_namespace: str,
    claim_name: str,
    cluster_ref: str,
    namespace: str,
    hostname: str,
    policy: dict,
) -> bool:
    request = (claim_namespace, claim_name, cluster_ref, namespace, hostname)
    return any(groups and mapping[0] in groups and request == mapping[1:]
               for mapping in mapping_from(policy))


def validate(data: dict) -> None:
    xrd = data["xrd"]
    version = next(v for v in xrd["spec"]["versions"] if v["name"] == "v1alpha1")
    schema = version["schema"]["openAPIV3Schema"]
    spec = schema["properties"]["spec"]["properties"]

    assert "enum" not in spec["clusterRef"], (
        "generic Claim schema regression: clusterRef authorization must not be an API enum"
    )
    assert "enum" not in spec["namespace"], (
        "generic Claim schema regression: namespace authorization must not be an API enum"
    )
    assert spec["clusterRef"]["minLength"] == 1 and spec["clusterRef"]["maxLength"] == 253
    assert spec["namespace"]["minLength"] == 1 and spec["namespace"]["maxLength"] == 63
    secret = spec["credentialsSecretRef"]["properties"]
    assert secret["name"]["enum"] == ["rmf-credentials"], (
        "credential schema pin regression: Secret name must stay rmf-credentials"
    )
    assert secret["namespace"]["enum"] == ["crossplane-system"], (
        "credential schema pin regression: Secret namespace must stay crossplane-system"
    )

    claim = data["claim"]
    validator = jsonschema.Draft7Validator(schema)
    validator.validate(claim)
    generic_candidate = copy.deepcopy(claim)
    generic_candidate["spec"]["clusterRef"] = "second-cluster"
    generic_candidate["spec"]["namespace"] = "second-tenant"
    validator.validate(generic_candidate)

    for path, value in (
        (("spec", "credentialsSecretRef", "name"), "another-secret"),
        (("spec", "credentialsSecretRef", "namespace"), "default"),
    ):
        candidate = copy.deepcopy(claim)
        node = candidate
        for part in path[:-1]:
            node = node[part]
        node[path[-1]] = value
        errors = list(validator.iter_errors(candidate))
        assert any(tuple(error.path) == path and error.validator == "enum" for error in errors), (
            f"credential schema pin did not reject {'.'.join(path)}={value!r}: {errors}"
        )

    role = data["role"]
    assert len(role["rules"]) == 1
    assert role["rules"][0]["verbs"] == ["create", "get", "list", "patch", "update", "watch"], (
        "claim-editor verbs must exclude delete and remain exact: " + repr(role["rules"][0]["verbs"])
    )

    policy = data["policy"]
    binding = data["binding"]
    pspec = policy["spec"]
    assert pspec["failurePolicy"] == "Fail", "failurePolicy guard: expected Fail"
    constraints = pspec["matchConstraints"]
    assert constraints.get("matchPolicy") == "Exact", "resource match guard: expected Exact"
    assert constraints["resourceRules"] == [{
        "apiGroups": ["platform.openkubes.ai"],
        "apiVersions": ["v1alpha1"],
        "operations": ["CREATE", "UPDATE"],
        "resources": ["openrmfclaims"],
        "scope": "Namespaced",
    }], "resource match guard: expected exact OpenRMFClaim CREATE/UPDATE rule"
    served_versions = {v["name"] for v in xrd["spec"]["versions"] if v["served"]}
    matched_versions = set(constraints["resourceRules"][0]["apiVersions"])
    assert served_versions == matched_versions, (
        "served Claim versions must exactly match admission policy coverage: "
        f"served={served_versions}, matched={matched_versions}"
    )
    assert binding["spec"]["policyName"] == policy["metadata"]["name"]
    assert binding["spec"]["validationActions"] == ["Deny"], (
        "validationActions guard: expected Deny"
    )
    assert "matchResources" not in binding["spec"], (
        "namespace bypass guard: binding must not narrow policy matches"
    )
    assert "namespaceSelector" not in binding["spec"], (
        "namespace bypass guard: binding must cover every namespace"
    )

    mapping_from(policy)
    allocation = EXPECTED_MAPPING[1:]
    assert authorized((EXPECTED_MAPPING[0],), *allocation, policy)
    assert authorized(("oidc:another-group", EXPECTED_MAPPING[0]), *allocation, policy), (
        "additional groups must not invalidate an allowed group"
    )
    assert not authorized((), *allocation, policy)
    assert not authorized((EXPECTED_MAPPING[0],), *(
        "openkubes-system", "ok-robotics", "ok-shared", "rmf", "robotics.openkubes.local"
    ), policy)
    assert not authorized((EXPECTED_MAPPING[0],), *(
        "openkubes-system", "ok-robotics", "ok-robotics", "another-tenant", "robotics.openkubes.local"
    ), policy)
    assert not authorized((EXPECTED_MAPPING[0],), *(
        "openkubes-system", "another-claim", "ok-robotics", "rmf", "robotics.openkubes.local"
    ), policy)
    assert not authorized((EXPECTED_MAPPING[0],), *(
        "openkubes-system", "ok-robotics", "ok-robotics", "rmf", "shadow.example.com"
    ), policy)

    variables = {v["name"]: v["expression"] for v in pspec["variables"]}
    assert "request.userInfo.groups.exists" in variables["claimantIsAuthorized"], (
        "identity guard must accept any matching group even when other groups are present"
    )
    for token in (
        "request.namespace == a['claimNamespace']",
        "object.metadata.name == a['claimName']",
        "object.spec.clusterRef == a['clusterRef']",
        "object.spec.namespace == a['namespace']",
        "object.spec.hostname == a['hostname']",
    ):
        assert token in variables["allocationIsAuthorized"], (
            f"allocation guard omitted {token}"
        )
        assert token in variables["claimantIsAuthorized"], (
            f"claimant allocation guard omitted {token}"
        )
    assert variables["isCrossplaneControllerUpdate"].count(
        "system:serviceaccount:crossplane-system:crossplane"
    ) == 1, "controller exception must name only the Crossplane service account"
    validations = pspec["validations"]
    assert len(validations) == 3, (
        "policy must contain exact allocation, generated spec, and metadata guards"
    )
    authority = validations[0]
    assert authority["reason"] == "Forbidden"
    assert "allocationIsAuthorized" in authority["expression"]
    assert "claimantIsAuthorized" in authority["expression"]
    assert "isCrossplaneControllerUpdate" in authority["expression"]
    assert "allocation authorization denied" in authority["message"]
    controls = validations[1]
    assert controls["reason"] == "Forbidden"
    assert "control fields are controller-owned" in controls["message"]
    for field in CONTROL_FIELDS:
        assert f"object.spec.{field}" in controls["expression"], (
            f"generated Claim control guard omitted {field}"
        )
        assert f"oldObject.spec.{field}" in controls["expression"], (
            f"generated Claim UPDATE immutability guard omitted {field}"
        )
    referenced_fields = set(
        re.findall(r"(?:oldObject|object)\.spec\.([A-Za-z][A-Za-z0-9]*)", controls["expression"])
    )
    unknown_fields = referenced_fields - KNOWN_CLAIM_SPEC_FIELDS
    assert not unknown_fields, (
        "policy references unknown Claim spec fields and will not enforce: " + repr(unknown_fields)
    )

    assert "object.spec.compositeDeletePolicy == 'Background'" in controls["expression"], (
        "defaulted compositeDeletePolicy guard must allow only Crossplane's Background default"
    )
    metadata_controls = validations[2]
    assert metadata_controls["reason"] == "Forbidden"
    assert "metadata controls are controller-owned" in metadata_controls["message"]
    for field in ("ownerReferences", "finalizers", "labels", "annotations"):
        assert f"object.metadata.{field}" in metadata_controls["expression"], (
            f"Claim metadata guard omitted {field}"
        )
    assert "crossplane.io/" in metadata_controls["expression"]
    assert "finalizer.apiextensions.crossplane.io" in metadata_controls["expression"], (
        "Claim UPDATE must pin the Crossplane finalizer"
    )

    makefile = data["makefile"]
    assert "DEPLOY_ARGS := --as='$(DEPLOY_USER)'" in makefile, (
        "deploy username must be one quoted impersonation argument"
    )
    assert "DEPLOY_USER contains unsupported characters" in makefile, (
        "deploy username must reject argument-injection characters"
    )
    authz_recipe = makefile.split("authz-check:", 1)[1].split("\nclaim-schema-check:", 1)[0]
    assert "if $(MGMT_KUBECTL) get openrmfclaim/$(CLUSTER)" in authz_recipe
    assert "create --dry-run=server -f examples/$(CLUSTER).yaml $(POS_ARGS)" in authz_recipe, (
        "authz-check must prove admission CREATE on a clean bootstrap"
    )

    setup_recipe = makefile.split("setup:", 1)[1].split("\nbind:", 1)[0]
    assert "create --dry-run=server" in setup_recipe, (
        "setup probe must issue a unique CREATE; a no-op apply of the existing Claim proves nothing"
    )
    assert "ok-robotics-policy-setup-probe" in setup_recipe, (
        "setup probe must use a unique object name rather than the existing Claim"
    )
    assert "--as=system:serviceaccount:crossplane-system:crossplane" in setup_recipe, (
        "setup probe must use the confirmed RBAC-capable but CREATE-unmapped controller identity"
    )
    assert ">/dev/null 2>&1" not in setup_recipe, (
        "setup inventory must not turn CRD lookup failures into an empty inventory"
    )
    assert "get crd/openrmfclaims.platform.openkubes.ai --ignore-not-found -o name" in setup_recipe, (
        "setup inventory must distinguish a missing CRD from a failed lookup"
    )
    assert "delete rolebinding/openrmf-claim-editor" in setup_recipe, (
        "setup must suspend delegated writes before changing the policy"
    )
    assert "apply -f rbac/claim-editor-binding.yaml" in setup_recipe, (
        "setup must restore delegated writes after successful policy rollout"
    )
    suspend = setup_recipe.index("delete rolebinding/openrmf-claim-editor")
    inventory = setup_recipe.index("--claims-json")
    policy_apply = setup_recipe.index("apply -f claim-admission-policy.yaml", inventory)
    restore = setup_recipe.index("apply -f rbac/claim-editor-binding.yaml", policy_apply)
    assert suspend < inventory < policy_apply < restore, (
        "setup must suspend delegated writes before inventory and restore them only after policy rollout"
    )
    assert "for verb in create update patch" in setup_recipe and (
        "delegated group can still $$verb OpenRMFClaims" in setup_recipe
    ), "setup must prove RoleBinding suspension removed delegated create/update/patch"
    assert 'openrmfclaims.platform.openkubes.ai -n $(CLAIM_NAMESPACE) $(POS_ARGS)' in setup_recipe, (
        "setup suspension proof must query the namespaced RoleBinding scope"
    )
    assert "live Claim RoleBinding differs from the reviewed manifest" in setup_recipe, (
        "setup must refuse to restore a live RoleBinding that differs from the reviewed manifest"
    )
    assert "claim-admission-check.py --schema-only" in setup_recipe, (
        "setup must inspect the generated Claim CRD before restoring delegation"
    )
    assert "patch validatingadmissionpolicy/" in setup_recipe, (
        "setup must force and observe a post-XRD CEL generation"
    )
    xrd_apply = setup_recipe.index("apply -f xrd.yaml", policy_apply)
    recheck_patch = setup_recipe.index("patch validatingadmissionpolicy/", xrd_apply)
    post_patch_check = setup_recipe.index("check_policy;", recheck_patch)
    policy_reapply = setup_recipe.index("apply -f claim-admission-policy.yaml", post_patch_check)
    final_policy_check = setup_recipe.index("check_policy;", policy_reapply)
    schema_check = setup_recipe.index("claim-admission-check.py --schema-only", final_policy_check)
    post_xrd_probe = setup_recipe.index("prove_admission;", schema_check)
    assert xrd_apply < recheck_patch < post_patch_check < policy_reapply < final_policy_check < schema_check < post_xrd_probe < restore, (
        "setup must force and observe a post-XRD CEL generation, restore the candidate, then inspect schema and admission"
    )
    assert "SAFE FAILURE: Claim delegation remains suspended" in setup_recipe, (
        "setup failures after suspension must print explicit restore guidance"
    )

    composition = data["composition"]
    resource = composition["spec"]["pipeline"][0]["input"]["resources"][0]
    refs = [entry["valueFrom"]["secretKeyRef"] for entry in resource["base"]["spec"]["forProvider"]["set"]]
    expected = [
        {"name": "rmf-credentials", "namespace": "crossplane-system", "key": "rmfWebDatabasePassword"},
        {"name": "rmf-credentials", "namespace": "crossplane-system", "key": "rmfWebAdminPassword"},
    ]
    assert refs == expected, "Composition credential pin regression: " + repr(refs)
    patch_sources = [patch.get("fromFieldPath", "") for patch in resource["patches"]]
    assert not [p for p in patch_sources if p.startswith("spec.credentialsSecretRef")], (
        "Composition must not consume claimant credential fields: " + repr(patch_sources)
    )
    assert "spec.clusterRef" in patch_sources
    assert "spec.namespace" in patch_sources


def validate_claim_inventory(policy: dict, inventory: dict) -> None:
    allowed = {mapping[1:] for mapping in mapping_from(policy)}
    violations = []
    for claim in inventory.get("items", []):
        metadata = claim.get("metadata", {})
        spec = claim.get("spec", {})
        allocation = (
            metadata.get("namespace"),
            metadata.get("name"),
            spec.get("clusterRef"),
            spec.get("namespace"),
            spec.get("hostname"),
        )
        if allocation not in allowed:
            violations.append("/".join(str(value) for value in allocation))
    assert not violations, (
        "live Claim inventory contains an allocation absent from the candidate policy: "
        + repr(violations)
    )


def negative_controls() -> None:
    cases = []

    def add(name, expected, mutate):
        cases.append((name, expected, mutate))

    def add_served_version(data):
        version = copy.deepcopy(data["xrd"]["spec"]["versions"][0])
        version.update(name="v1beta1", referenceable=False, served=True)
        data["xrd"]["spec"]["versions"].append(version)

    def replace_in_setup(data, old, new):
        before, remainder = data["makefile"].split("setup:", 1)
        setup, after = remainder.split("\nbind:", 1)
        assert old in setup
        data["makefile"] = before + "setup:" + setup.replace(old, new) + "\nbind:" + after

    add("Fail->Ignore", "failurePolicy guard", lambda d: d["policy"]["spec"].update(failurePolicy="Ignore"))
    add("Deny->Audit", "validationActions guard", lambda d: d["binding"]["spec"].update(validationActions=["Audit"]))
    add(
        "remove authorization mapping",
        "authorization mapping",
        lambda d: d["policy"]["spec"]["variables"][0].update(expression="[]"),
    )
    add(
        "unparsed extra authorization mapping",
        "every CEL authorization entry must use the canonical parsed key order and quoting",
        lambda d: d["policy"]["spec"]["variables"][0].update(
            expression=d["policy"]["spec"]["variables"][0]["expression"][:-1]
            + ", {'hostname': 'shadow.example.com', 'group': 'oidc:shadow'}]"
        ),
    )
    add(
        "generic clusterRef schema regression",
        "generic Claim schema regression",
        lambda d: next(v for v in d["xrd"]["spec"]["versions"] if v["name"] == "v1alpha1")
        ["schema"]["openAPIV3Schema"]["properties"]["spec"]["properties"]["clusterRef"].update(enum=["ok-robotics"]),
    )
    add(
        "unguarded served Claim version",
        "served Claim versions must exactly match admission policy coverage",
        add_served_version,
    )
    add(
        "missing metadata control guard",
        "policy must contain exact allocation, generated spec, and metadata guards",
        lambda d: d["policy"]["spec"]["validations"].pop(),
    )
    add(
        "claim delete delegation",
        "claim-editor verbs must exclude delete",
        lambda d: d["role"]["rules"][0]["verbs"].insert(1, "delete"),
    )
    add(
        "credential schema pin regression",
        "credential schema pin regression",
        lambda d: next(v for v in d["xrd"]["spec"]["versions"] if v["name"] == "v1alpha1")
        ["schema"]["openAPIV3Schema"]["properties"]["spec"]["properties"]["credentialsSecretRef"]
        ["properties"]["name"].update(enum=["another-secret"]),
    )
    add(
        "Composition credential pin regression",
        "Composition credential pin regression",
        lambda d: d["composition"]["spec"]["pipeline"][0]["input"]["resources"][0]
        ["base"]["spec"]["forProvider"]["set"][0]["valueFrom"]["secretKeyRef"].update(name="another-secret"),
    )
    add(
        "unknown generated Claim field",
        "policy references unknown Claim spec fields",
        lambda d: d["policy"]["spec"]["validations"][1].update(
            expression=d["policy"]["spec"]["validations"][1]["expression"]
            + " && !has(object.spec.publishConnectionDetailsTo)"
        ),
    )
    add(
        "hostname allocation omission",
        "allocation guard omitted object.spec.hostname",
        lambda d: next(
            v for v in d["policy"]["spec"]["variables"] if v["name"] == "allocationIsAuthorized"
        ).update(
            expression=next(
                v for v in d["policy"]["spec"]["variables"] if v["name"] == "allocationIsAuthorized"
            )["expression"].replace("object.spec.hostname == a['hostname']", "true")
        ),
    )
    add(
        "defaulted compositeDeletePolicy regression",
        "defaulted compositeDeletePolicy guard",
        lambda d: d["policy"]["spec"]["validations"][1].update(
            expression=d["policy"]["spec"]["validations"][1]["expression"].replace(
                "object.spec.compositeDeletePolicy == 'Background'",
                "object.spec.compositeDeletePolicy == 'Foreground'",
            )
        ),
    )
    add(
        "deploy username argument injection",
        "deploy username must be one quoted impersonation argument",
        lambda d: d.update(
            makefile=d["makefile"].replace(
                "DEPLOY_ARGS := --as='$(DEPLOY_USER)'", "DEPLOY_ARGS := --as=$(DEPLOY_USER)"
            )
        ),
    )
    add(
        "missing clean-bootstrap CREATE proof",
        "authz-check must prove admission CREATE on a clean bootstrap",
        lambda d: d.update(
            makefile=d["makefile"].replace(
                "create --dry-run=server -f examples/$(CLUSTER).yaml $(POS_ARGS)",
                "replace --dry-run=server -f $$probe $(POS_ARGS)",
            )
        ),
    )
    add(
        "no-op UPDATE setup probe",
        "setup probe must issue a unique CREATE",
        lambda d: replace_in_setup(
            d, "create --dry-run=server", "apply --dry-run=server"
        ),
    )
    add(
        "silent CRD inventory failure",
        "setup inventory must",
        lambda d: d.update(
            makefile=d["makefile"].replace(
                "--ignore-not-found -o name", ">/dev/null 2>&1"
            )
        ),
    )
    add(
        "missing post-XRD schema inspection",
        "setup must inspect the generated Claim CRD",
        lambda d: d.update(
            makefile=d["makefile"].replace(
                "claim-admission-check.py --schema-only", "claim-admission-check.py"
            )
        ),
    )
    add(
        "wrong-scope delegation suspension proof",
        "setup suspension proof must query the namespaced RoleBinding scope",
        lambda d: replace_in_setup(
            d,
            "openrmfclaims.platform.openkubes.ai -n $(CLAIM_NAMESPACE) $(POS_ARGS)",
            "openrmfclaims.platform.openkubes.ai --all-namespaces $(POS_ARGS)",
        ),
    )
    add(
        "missing forced post-XRD CEL generation",
        "setup must force and observe a post-XRD CEL generation",
        lambda d: replace_in_setup(
            d, "patch validatingadmissionpolicy/", "get validatingadmissionpolicy/"
        ),
    )
    add(
        "unverified delegation suspension",
        "setup must prove RoleBinding suspension",
        lambda d: d.update(
            makefile=d["makefile"].replace(
                "for verb in create update patch", "for verb in create"
            )
        ),
    )
    add(
        "unsuspended policy update",
        "setup must suspend delegated writes",
        lambda d: d.update(
            makefile=d["makefile"].replace(
                "delete rolebinding/openrmf-claim-editor",
                "get rolebinding/openrmf-claim-editor",
            )
        ),
    )
    for name, expected, mutate in cases:
        candidate = copy.deepcopy(inputs())
        mutate(candidate)
        try:
            validate(candidate)
        except AssertionError as error:
            assert expected in str(error), f"{name} failed for an unexpected reason: {error}"
            print(f"EXPECTED FAILURE [{name}]: {error}")
        else:
            raise AssertionError(f"negative control unexpectedly passed: {name}")

    data = inputs()
    unauthorized_inventory = {
        "items": [{
            "metadata": {"namespace": "openkubes-system", "name": "unauthorized"},
            "spec": {"clusterRef": "ok-shared", "namespace": "rmf"},
        }]
    }
    try:
        validate_claim_inventory(data["policy"], unauthorized_inventory)
    except AssertionError as error:
        assert "live Claim inventory contains an allocation absent" in str(error), error
        print(f"EXPECTED FAILURE [unauthorized live Claim inventory]: {error}")
    else:
        raise AssertionError("unauthorized live Claim inventory unexpectedly passed")

    validate(data)
    validate_claim_inventory(data["policy"], {"items": []})
    print("RESTORED GREEN: all original guard inputs pass")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--negative-controls", action="store_true")
    parser.add_argument("--claims-json", type=Path)
    args = parser.parse_args()
    if args.negative_controls:
        negative_controls()
        return
    data = inputs()
    validate(data)
    if args.claims_json:
        inventory = json.loads(args.claims_json.read_text())
        validate_claim_inventory(data["policy"], inventory)
        print(f"INVENTORIED: {len(inventory.get('items', []))} live Claim(s) use authorized allocations")
    print("ACCEPTED: allowed group (including with additional groups) -> exact OpenRMF allocation")
    print("REJECTED: unmapped identity and altered Claim/target/hostname allocations")
    print("PINNED: schema and Composition credentials are not claimant-controlled")
    print("PINNED: generated Claim composition/revision/resource/connection controls")


if __name__ == "__main__":
    main()
