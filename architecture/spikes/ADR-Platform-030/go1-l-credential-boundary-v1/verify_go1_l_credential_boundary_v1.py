#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
BOUNDARY = HERE / "go1-l-credential-boundary-v1.yaml"
DIGEST = HERE / "go1-l-credential-boundary-v1.sha256"
HARNESS = SPIKE / "harness"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


V4 = load_module("ok141_phase_r_v4_credential_boundary", HARNESS / "ok141_phase_r_v4.py")
V1 = V4.V1


class BoundaryError(ValueError):
    pass


def sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def expect(actual, expected, context):
    if actual != expected:
        raise BoundaryError(f"{context}: expected {expected!r}, got {actual!r}")


def resolve(requested: str) -> Path:
    path = (HERE / requested).resolve()
    if SPIKE.resolve() not in path.parents or not path.is_file():
        raise BoundaryError(f"invalid source path: {requested}")
    return path


def validate(boundary: dict) -> str:
    expect(boundary["apiVersion"], "security.openkubes.io/v1alpha1", "apiVersion")
    expect(boundary["kind"], "GO1LCredentialBoundary", "kind")
    spec = boundary["spec"]
    expect(spec["state"], "ANALYZED-BLOCKED-NO-GO", "state")
    source = spec["sourceSubmitter"]
    path = resolve(source["path"])
    expect(sha(path), source["digest"], "submitter digest")
    submitter = V1.read_yaml_or_json(path)
    expect(submitter["spec"]["state"], "OFFLINE-PROVEN-BLOCKED-NO-GO", "submitter state")
    expect((source["transport"], source["operations"], source["objects"]), ("CreateReviewedObjectSet", 3, 12), "source bounds")
    finding = spec["authoritativeFinding"]
    expect(finding["nativeRBACCanEnforceExactObjectNamesOnCreate"], False, "create name boundary")
    expect(finding["nativeRBACCanEnforceExactObjectContentOnCreate"], False, "create content boundary")
    expect(finding["permissionsAreAdditiveWithoutDenyRules"], True, "additive RBAC boundary")
    exposures = spec["operationExposure"]
    expect([item["id"] for item in exposures], ["provider-prerequisites", "capi-lifecycle", "helmchartproxy"], "operation inventory")
    expect([item["targetPlane"] for item in exposures], ["ok-infra", "ok-mgmt", "ok-mgmt"], "authority planes")
    if any(item["exactNameEnforcedByNativeRBAC"] or item["exactContentEnforcedByNativeRBAC"] for item in exposures):
        raise BoundaryError("operation overclaims native RBAC enforcement")
    expect(spec["bootstrapConstraint"]["namespaceScopedRoleCanExistBeforeTargetNamespace"], False, "namespace bootstrap")
    models = spec["candidateModels"]
    expect([item["id"] for item in models], ["DEV-ADMIN-CREATE", "TEMPORARY-ADMISSION-PLUS-SCOPED-CREATE", "PATCH-BY-NAME-PLUS-ADMISSION"], "candidate models")
    decision = spec["decision"]
    expect(decision["selectedModel"], "UNRESOLVED", "selected model")
    if any(decision[key] for key in ("credentialIssuanceAuthorized", "admissionInstallationAuthorized", "administratorCredentialAuthorized", "go1LAuthorized")):
        raise BoundaryError("credential boundary grants authority")
    conclusions = spec["conclusions"]
    expect(conclusions["submitterArtifactProven"], True, "submitter conclusion")
    expect(conclusions["nativeLeastPrivilegeCredentialSufficient"], False, "native credential conclusion")
    expect(conclusions["newOpenKubesReconcilerRequired"], False, "reconciler conclusion")
    return sha(BOUNDARY)


def main() -> int:
    try:
        boundary = V1.read_yaml_or_json(BOUNDARY)
        actual = validate(boundary)
        if DIGEST.exists():
            expect(DIGEST.read_text().strip(), actual, "digest file")
        print(json.dumps({
            "boundaryDigest": actual,
            "state": boundary["spec"]["state"],
            "selectedModel": boundary["spec"]["decision"]["selectedModel"],
            "credentialIssuanceAuthorized": False,
            "clusterContacted": False,
            "mutationAuthorized": False,
        }, sort_keys=True))
        return 0
    except (BoundaryError, KeyError, OSError, TypeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
