#!/usr/bin/env python3
"""Fail-closed verifier for the non-authorizing OK-141 M0b-I protocol."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import yaml


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
HARNESS = SPIKE / "harness"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


V4 = _load("ok141_phase_r_v4_m0bi", HARNESS / "ok141_phase_r_v4.py")
V1 = V4.V1

GO1_DIGEST = "sha256:2718d719c322190e36036f98730edcb9aaa679c434fb04f151f7f24fc2626705"
PARTITION_DIGEST = "sha256:a12a5e30f5bd5479d502f0dbf80e709e14216702ba804f986afcb408f0c32be9"
HISTORICAL_M0B_DIGEST = "sha256:22f37eb2f81d9a37819ef9ae65ec3bdea78f81d5b8e5786c044843f00d17934c"
LOCK_DIGEST = "sha256:6322722bd9abc788b99a0f9d57ac96ed610e0105f14e91279e14719cea9567a1"
NAMESPACE_DIGEST = "sha256:0a2c5ac85283184d1392ae712f7e8bd4b8d19f837e28055664399046532f7844"
COMBINED_DIGEST = "sha256:811b07f7face5d56df3434d083b9efedc5f8b28f8a264985c4b9616f0b2fd9d8"
PRE_IDS = {
    "M0BI-AUTHORITY-PLACEMENT", "M0BI-BASELINE-CAPACITY",
    "M0BI-SOURCE-MATERIALIZATION", "M0BI-INSTALLER-IDENTITY",
    "M0BI-EXACT-OBJECT-SUBMISSION", "M0BI-CONTROLLER-RBAC-SECURITY",
    "M0BI-IMAGE-COMPATIBILITY", "M0BI-OBSERVERS-EVIDENCE", "M0BI-RECOVERY",
}
RUNTIME_IDS = {
    "M0BI-INVENTORY-IDENTITY", "M0BI-CRD-API-READY",
    "M0BI-CONTROL-PLANE-READY", "M0BI-IMAGE-IDENTITY",
    "M0BI-NO-TARGET-STATE", "M0BI-EVIDENCE-BUNDLE",
}
PHASE_IDS = {"M0BI-G0", "M0BI-G1", "M0BI-G2", "M0BI-G3"}
FILE_LOCKS = {
    "ha-namespace-install": ("sha256:cfe6b1e3c0fc483d2c93822cac53bf2542fd5035161a3d30ba781486378bcc57", "sha256:c058afb0a8be119787b94433731ceec4647e5fb07ca32cbd4df27b070fc27fe6", 139547, 61),
    "application-crd": ("sha256:fa8a0c7f8127f85bbbf57467e7c659ec7d47e7d162cc76c1b07482ebf2b98f49", "sha256:a30d786c22f9895ab3fb70b169f3c870e226c083b4e56cfc001d1b413a9b7133", 396773, 1),
    "applicationset-crd": ("sha256:51f69883c692698fbcf3c82455c07c0f6413899ac9d96565a9e8395c0196f58d", "sha256:42a101f4c42f575d4634265aa6e02d176e1ff2d2ba60aa41197eab113689cdc5", 1385775, 1),
    "appproject-crd": ("sha256:7b99337686905b444864c84b1305938a7bfbca9b5f4e2c5d5d2de4acae16ceb3", "sha256:d89d247abcd91192feac0ea0d27b5da3673259fe1b9b950801de441481ea4542", 16502, 1),
}
KINDS = {
    "Namespace": 1, "CustomResourceDefinition": 3, "ConfigMap": 9,
    "Deployment": 6, "NetworkPolicy": 8, "Role": 7, "RoleBinding": 7,
    "Secret": 2, "Service": 12, "ServiceAccount": 8, "StatefulSet": 2,
}
IMAGES = {
    "quay.io/argoproj/argocd:v3.4.2": "sha256:a8679d1bbf7679ad27bf39fadbd30e486f59446eadd4f5c2c11ce6a41053a216",
    "ghcr.io/dexidp/dex:v2.45.0": "sha256:8a9281c3a115180415b0726ca160e38fc40f9284bc9a2d1032c839a3a934695c",
    "public.ecr.aws/docker/library/haproxy:3.0.8-alpine": "sha256:3ad414bdb5c94d712e0e9a7dc1517eca45cce652afc85a002fd7bb42b44d5dde",
    "public.ecr.aws/docker/library/redis:8.2.3-alpine": "sha256:e499175dfb27569cd40010c2eee346113db95fdd0efc88ab9fd70a9e807f4542",
}


def _expect(actual: Any, expected: Any, claim: str) -> None:
    if actual != expected:
        raise V1.HarnessError(f"M0b-I {claim} mismatch")


def _resolve(protocol_path: Path, requested: str) -> Path:
    candidate = (protocol_path.parent / requested).resolve()
    if SPIKE.resolve() not in candidate.parents or not candidate.is_file():
        raise V1.HarnessError(f"M0b-I reference missing or outside spike root: {requested}")
    return candidate


def _indexed(items: list[dict[str, Any]], claim: str) -> dict[str, dict[str, Any]]:
    result = {item.get("id"): item for item in items}
    if None in result or len(result) != len(items):
        raise V1.HarnessError(f"M0b-I {claim} contains missing or duplicate IDs")
    return result


def validate(document: dict[str, Any], protocol_path: Path) -> str:
    schema = json.loads((HERE / "m0b-installation-v1.schema.json").read_text())
    V1.normalize(document, schema)
    spec = document["spec"]
    _expect(spec["protocolState"], "BLOCKED", "protocol state")

    references = spec["references"]
    expected_references = {
        "go1Protocol": GO1_DIGEST,
        "gatePartition": PARTITION_DIGEST,
        "historicalM0b": HISTORICAL_M0B_DIGEST,
    }
    for name, digest in expected_references.items():
        claim = references[name]
        _expect(claim["digest"], digest, f"{name} declared digest")
        _expect(V1.sha256_bytes(_resolve(protocol_path, claim["path"]).read_bytes()), digest, f"{name} raw digest")

    boundary = spec["authorityBoundary"]
    _expect(boundary["gate"], "M0B-I", "gate identity")
    for field in ("mayAuthorizeTargetRegistration", "mayAuthorizeTargetConvergence", "mayAuthorizeGO1", "mayCreateTargetCredentials", "maySubmitAppProject", "maySubmitApplication"):
        _expect(boundary[field], False, f"authority boundary {field}")

    authorization = spec["authorization"]
    _expect(authorization["decision"], "NO-GO", "decision")
    for field in ("mutationAuthorized", "m0bInstallationGranted", "m0bTargetRegistrationGranted", "m0bTargetConvergenceGranted", "go1Granted"):
        _expect(authorization[field], False, f"authorization {field}")
    for field in ("grantID", "authorizedProtocolDigest", "decidedAt"):
        _expect(authorization[field], None, f"authorization {field}")

    placement = spec["placement"]
    _expect(placement["candidatePlane"], "ok-shared", "placement candidate")
    _expect(placement["productionHAClaimAllowed"], False, "production HA claim")
    _expect(placement["placementAuthority"], "UNRESOLVED", "placement authority")

    source = spec["source"]
    lock_path = _resolve(protocol_path, source["lockPath"])
    _expect(V1.sha256_bytes(lock_path.read_bytes()), LOCK_DIGEST, "source lock raw digest")
    _expect(source["lockDigest"], LOCK_DIGEST, "declared source lock digest")
    lock = V1.read_yaml_or_json(lock_path)["spec"]
    files = _indexed(lock["files"], "source-lock files")
    _expect(set(files), set(FILE_LOCKS), "source-lock membership")
    for item_id, expected in FILE_LOCKS.items():
        item = files[item_id]
        actual = (item["rawDigest"], item["semanticDigest"], item["sizeBytes"], item["objectCount"])
        _expect(actual, expected, f"{item_id} source lock")
        if not item["url"].startswith("https://raw.githubusercontent.com/argoproj/argo-cd/v3.4.2/"):
            raise V1.HarnessError(f"M0b-I {item_id} is not locked to the reviewed upstream tag")

    namespace_path = _resolve(protocol_path, source["namespacePath"])
    _expect(V1.sha256_bytes(namespace_path.read_bytes()), NAMESPACE_DIGEST, "Namespace raw digest")
    _expect(source["namespaceRawDigest"], NAMESPACE_DIGEST, "declared Namespace digest")
    namespace = V1.read_yaml_or_json(namespace_path)
    _expect((namespace["kind"], namespace["metadata"]["name"]), ("Namespace", "argocd"), "Namespace identity")
    _expect(lock["localNamespace"]["rawDigest"], NAMESPACE_DIGEST, "source-lock Namespace digest")
    _expect(lock["combined"]["semanticDigest"], COMBINED_DIGEST, "source-lock combined digest")
    _expect(source["combinedSemanticDigest"], COMBINED_DIGEST, "declared combined digest")
    _expect(source["combinedObjectCount"], 65, "combined object count")
    _expect(source["objectKinds"], KINDS, "combined kind inventory")
    _expect(source["remoteContentRetained"], False, "remote retention state")
    _expect(source["materializationRequiredBeforeInstallation"], True, "materialization requirement")
    _expect(lock["combined"]["contentMaterialization"], "REQUIRED-BEFORE-INSTALLATION", "source-lock materialization state")
    images = {item["reference"]: item["linuxAmd64Digest"] for item in source["controllerImages"]}
    _expect(images, IMAGES, "controller image identities")

    submission = spec["submission"]
    _expect(submission["operation"], "MaterializeVerifyAndApplyReviewedInstallationSet", "submission operation")
    _expect(submission["enabled"], False, "submission state")
    _expect(submission["freeFormShellEndpoint"], False, "shell boundary")
    _expect(submission["targetPlane"], "ok-shared", "submission plane")
    _expect((submission["expectedObjectCount"], submission["expectedSemanticDigest"]), (65, COMBINED_DIGEST), "submission object-set identity")

    pre = _indexed(spec["preInstallationRequirements"], "pre-installation requirements")
    _expect(set(pre), PRE_IDS, "pre-installation membership")
    if any(item["status"] != "BLOCKED" for item in pre.values()):
        raise V1.HarnessError("M0b-I pre-installation requirement was closed without a new protocol")

    runtime = _indexed(spec["runtimeObligations"], "runtime obligations")
    _expect(set(runtime), RUNTIME_IDS, "runtime obligation membership")
    for item in runtime.values():
        if item["status"] != "PENDING-RUNTIME" or item["phase"] not in {"M0BI-G2", "M0BI-G3"}:
            raise V1.HarnessError("M0b-I runtime obligation was closed early or assigned to an invalid phase")
        if item["mayBeClosedBeforeRuntime"] is not False or item["onFailure"] != "STOP-NOT-SUCCESS":
            raise V1.HarnessError("M0b-I runtime obligation does not fail closed")

    phases = _indexed(spec["phases"], "phases")
    _expect(set(phases), PHASE_IDS, "phase membership")
    if any(item["enabled"] is not False for item in phases.values()):
        raise V1.HarnessError("M0b-I phase enabled without authorization")
    if {item_id for item_id, item in phases.items() if item["mutating"]} != {"M0BI-G1"}:
        raise V1.HarnessError("M0b-I G1 is not the sole prospective installation phase")

    rollback = spec["rollback"]
    _expect(rollback["enabled"], False, "rollback state")
    _expect(rollback["authorizationRequired"], True, "rollback authorization")
    if len(rollback["preconditions"]) < 5 or "STOP" not in rollback["preconditions"][0]:
        raise V1.HarnessError("M0b-I rollback does not fail closed on explicit STOP")
    excluded = " ".join(spec["excludedScenarios"]).lower()
    for phrase in ("target registration", "appproject", "restart", "go-1", "management outage"):
        if phrase not in excluded:
            raise V1.HarnessError(f"M0b-I exclusion missing: {phrase}")

    return V1.sha256_bytes(protocol_path.read_bytes())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--digest-file", type=Path)
    args = parser.parse_args()
    try:
        digest = validate(V1.read_yaml_or_json(args.protocol), args.protocol.resolve())
        if args.digest_file:
            expected = args.digest_file.read_text().split()[0]
            _expect(digest.removeprefix("sha256:"), expected, "raw protocol digest")
        print(digest)
        return 0
    except (V1.HarnessError, OSError, ValueError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
