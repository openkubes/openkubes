#!/usr/bin/env python3
"""Fail-closed verifier for recorded OK-141 authority inputs."""

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


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


AUTHORITY = _load(
    "ok141_authority_inputs_source",
    SPIKE / "authority-decision-package" / "verify_authority_decisions.py",
)
V1 = AUTHORITY.V1
PRINCIPAL = "github:arashkaffamanesh"
ROLES = {
    "ok-141-m0a-installation-authority",
    "ok-141-caaph-security-authority",
    "ok-141-mgmt-recovery-authority",
    "ok-141-m0b-installation-authority",
    "ok-141-gitops-placement-authority",
    "ok-141-argocd-security-authority",
    "ok-141-shared-recovery-authority",
}
SOURCE_DIGEST = "sha256:786c8e38c5b4c527b5809e3e9b7d500ccb4e8972ffb5ffedcf409fc7533a81c7"


def _expect(actual: Any, expected: Any, claim: str) -> None:
    if actual != expected:
        raise V1.HarnessError(f"authority inputs {claim} mismatch")


def validate(document: dict[str, Any], input_path: Path) -> str:
    schema = json.loads((HERE / "authority-inputs-v1.schema.json").read_text())
    V1.normalize(document, schema)
    spec = document["spec"]
    _expect(spec["state"], "RECORDED-PARTIAL-INPUTS-NO-GO", "state")

    source = spec["sourcePackage"]
    source_path = (input_path.parent / source["path"]).resolve()
    if SPIKE.resolve() not in source_path.parents or not source_path.is_file():
        raise V1.HarnessError("authority inputs source package is missing or outside spike")
    _expect(source["digest"], SOURCE_DIGEST, "source declared digest")
    _expect(V1.sha256_bytes(source_path.read_bytes()), SOURCE_DIGEST, "source raw digest")
    _expect(source["state"], "PREPARED-UNDECIDED-NO-GO", "source state")
    source_document = V1.read_yaml_or_json(source_path)
    _expect({item["outcome"] for item in source_document["spec"]["decisions"]}, {"UNDECIDED"}, "historical outcomes")

    principal = spec["authorityPrincipal"]
    _expect(principal["decision"], "CONFIRMED", "principal decision")
    _expect(principal["principal"], PRINCIPAL, "principal")
    _expect(set(principal["roles"]), ROLES, "authority role membership")
    if len(principal["roles"]) != len(ROLES):
        raise V1.HarnessError("authority inputs contain duplicate roles")
    for phrase in ("does not accept rbac", "bind a window", "issue credentials", "authorize mutation"):
        if phrase not in principal["boundary"].lower():
            raise V1.HarnessError(f"authority inputs principal boundary missing {phrase}")

    solo = spec["governanceException"]
    _expect((solo["decision"], solo["model"], solo["acceptedBy"]), ("ACCEPTED", "DEV-SOLO", PRINCIPAL), "solo acceptance")
    _expect(solo["statement"], "Ich akzeptiere für OK-141 das DEV-Solo-Modell ohne unabhängigen menschlichen Security-Review und mit den dokumentierten Claim-Grenzen.", "solo statement")
    _expect((solo["independentHumanSecurityReview"], solo["separationOfDuties"], solo["automatedVerificationRequired"]), (False, "LIMITED", True), "solo controls")
    _expect(solo["allowedScope"], "OK-141-DEV-SPIKE-ONLY", "solo scope")
    _expect(solo["claimBoundaries"], {
        "independentHumanReviewClaimAllowed": False,
        "productionUseAllowed": False,
        "highAvailabilityClaimAllowed": False,
        "disasterRecoveryClaimAllowed": False,
        "lifecycleContinuityClaimAllowed": False,
        "automaticAdoptionClaimAllowed": False,
    }, "solo claim boundaries")
    if len(solo["compensatingControls"]) != 5:
        raise V1.HarnessError("authority inputs compensating controls changed")

    placement = spec["gitOpsPlacementBoundary"]
    _expect((placement["decision"], placement["acceptedBy"], placement["controlPlane"]), ("ACCEPTED", PRINCIPAL, "ok-shared"), "placement decision")
    _expect(placement["boundIncarnation"], {
        "kubeSystemNamespaceUID": "46b9ecf7-2e7a-48b1-a6eb-7d11df396efb",
        "apiServer": "https://192.168.100.206:6443",
        "kubernetesVersion": "v1.34.1",
        "platform": "linux/amd64",
    }, "placement incarnation")
    _expect(
        (placement["externalWorkloadClustersOnly"], placement["manageLocalOkSharedResources"], placement["selfManagementAllowed"], placement["existingHelmManagedResourcesRemainOutsideArgoOwnership"]),
        (True, False, False, True),
        "placement ownership boundary",
    )

    unresolved = spec["unresolvedInputs"]
    _expect(unresolved["evidenceDestination"]["status"], "UNDECIDED", "evidence destination")
    _expect(unresolved["evidenceDestination"]["candidate"], "ghcr.io/openkubes/ok141-evidence", "evidence candidate")
    window = unresolved["executionWindow"]
    _expect((window["status"], window["proposedDurationMinutes"], window["validFrom"], window["validUntil"]), ("NOT-BOUND", 180, None, None), "execution window")
    _expect(unresolved["automatedObservers"]["status"], "NOT-IMPLEMENTED", "observer implementation")
    _expect(unresolved["rbacSecurityDecisions"], {"m0a": "UNDECIDED", "m0b": "UNDECIDED"}, "RBAC decisions")
    _expect(unresolved["installerCredentials"], {"m0a": "NOT-AUTHORIZED", "m0b": "NOT-AUTHORIZED"}, "credentials")

    authorization = spec["authorization"]
    _expect(authorization["decision"], "NO-GO", "authorization decision")
    for field in ("mutationAuthorized", "m0aInstallationGranted", "m0bInstallationGranted", "go1Granted"):
        _expect(authorization[field], False, f"authorization {field}")
    _expect(spec["summary"], {"confirmedInputGroups": 3, "authorityRolesAssigned": 7, "authorityDecisionOutcomesChanged": 0, "installationGatesGranted": 0, "unresolvedInputGroups": 5}, "summary")

    rules = " ".join(spec["rules"]).lower()
    for phrase in ("does not alter", "permits no independent-human-review claim", "is not rbac acceptance", "external workload clusters only", "binds no window", "remain no-go"):
        if phrase not in rules:
            raise V1.HarnessError(f"authority inputs safety rule missing: {phrase}")
    return V1.sha256_bytes(input_path.read_bytes())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--digest-file", type=Path)
    args = parser.parse_args()
    try:
        path = args.inputs.resolve()
        digest = validate(V1.read_yaml_or_json(path), path)
        if args.digest_file:
            _expect(digest.removeprefix("sha256:"), args.digest_file.read_text().split()[0], "raw digest")
        print(digest)
        return 0
    except (V1.HarnessError, OSError, ValueError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
