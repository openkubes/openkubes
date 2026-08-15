#!/usr/bin/env python3
import copy
import hashlib
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parent
SECURITY = ROOT / "m0b-runtime-registration-security-v1.yaml"
SECURITY_DIGEST = ROOT / "m0b-runtime-registration-security-v1.sha256"
RISK = ROOT / "m0b-runtime-registration-risk-acceptance-candidate-v1.yaml"
RISK_DIGEST = ROOT / "m0b-runtime-registration-risk-acceptance-candidate-v1.sha256"
PROTOCOL = ROOT.parent / "m0b-target-registration-v1/m0b-runtime-registration-protocol-v1.yaml"
PROJECT = ROOT.parent / "m0b-target-registration-v1/appproject-v5-candidate.yaml"
ACCESS = ROOT.parent / "m0b-target-registration-v1/target-access-v1.template.yaml"
REGISTRATION = ROOT.parent / "m0b-target-registration-v1/cluster-registration-v5.template.yaml"


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def docs(path: Path):
    return [item for item in yaml.safe_load_all(path.read_text()) if item]


def verify(security=None, risk=None) -> list[str]:
    errors = []
    security = security or yaml.safe_load(SECURITY.read_text())
    risk = risk or yaml.safe_load(RISK.read_text())
    protocol = yaml.safe_load(PROTOCOL.read_text())
    project = yaml.safe_load(PROJECT.read_text())
    access = docs(ACCESS)
    registration = yaml.safe_load(REGISTRATION.read_text())
    spec = security["spec"]
    risk_spec = risk["spec"]
    security_digest = digest(SECURITY)

    if spec["state"] != "READY-FOR-RISK-DECISION-NO-GO":
        errors.append("security candidate state mismatch")
    if spec["references"]["runtimeProtocol"]["digest"] != digest(PROTOCOL):
        errors.append("runtime protocol digest mismatch")
    if spec["references"]["appProject"]["digest"] != digest(PROJECT):
        errors.append("AppProject digest mismatch")
    if spec["references"]["targetAccess"]["digest"] != digest(ACCESS):
        errors.append("target access digest mismatch")
    if spec["references"]["registration"]["digest"] != digest(REGISTRATION):
        errors.append("registration digest mismatch")
    if SECURITY_DIGEST.read_text().strip() != security_digest:
        errors.append("security digest file mismatch")
    if RISK_DIGEST.read_text().strip() != digest(RISK):
        errors.append("risk candidate digest file mismatch")

    authorization = spec["authorization"]
    if authorization["securityRiskAccepted"] or authorization["mutationAuthorized"]:
        errors.append("security risk or mutation must not be accepted")
    if any(value for key, value in authorization.items() if key.endswith("Granted")):
        errors.append("all security candidate grants must remain false")
    risk_auth = risk_spec["authorization"]
    if risk_auth["decision"] != "NO-GO" or risk_auth["mutationAuthorized"]:
        errors.append("risk candidate must remain NO-GO")
    if any(value for key, value in risk_auth.items() if key.endswith("Granted")):
        errors.append("all risk candidate grants must remain false")
    acceptance = risk_spec["acceptance"]
    if acceptance["accepted"] or any(acceptance[key] is not None for key in ("acceptedBy", "acceptedAt", "acceptedCandidateDigest")):
        errors.append("risk acceptance must remain pending")
    if risk_spec["references"]["securityBoundary"]["digest"] != security_digest:
        errors.append("risk candidate security digest mismatch")
    if security_digest not in risk_spec["acceptanceText"]:
        errors.append("acceptance text does not bind exact security digest")

    claims = {item["id"] for item in spec["risksRequiringAcceptance"]}
    if claims != set(risk_spec["risks"]) or len(claims) != 8:
        errors.append("risk claim membership mismatch")
    if spec["runtimeAuthorityDomains"]["targetTokenRequest"]["maximumExpirationSeconds"] != 10800:
        errors.append("TokenRequest maximum must be exactly three hours")
    if spec["runtimeAuthorityDomains"]["targetTokenRequest"]["nativeArgoRotation"]:
        errors.append("native Argo token rotation must not be claimed")
    if spec["submissionBoundary"]["applicationSubmissionIncluded"]:
        errors.append("Application submission must remain outside this boundary")
    if not spec["submissionBoundary"]["partialStatePossible"]:
        errors.append("partial-state possibility must remain explicit")
    if any(spec["submissionBoundary"][key] for key in ("automaticRetryAllowed", "automaticRollbackAllowed", "cleanupAllowed")):
        errors.append("retry rollback and cleanup must remain unauthorized")
    if spec["compatibilityBoundary"]["exactCombinationExecutionProven"]:
        errors.append("target compatibility must remain unproven")
    if spec["targetAccessBoundary"]["wildcardAllowed"] or spec["targetAccessBoundary"]["semanticCreateRestrictionByRBAC"]:
        errors.append("target access wildcard/create-content claims mismatch")
    if project["spec"].get("permitOnlyProjectScopedClusters") is not True:
        errors.append("AppProject project-scoped control missing")
    if registration["stringData"].get("project") != "openkubes-disposable":
        errors.append("registration is not project-scoped")
    if len(access) != spec["references"]["targetAccess"]["objectCount"]:
        errors.append("target access object count mismatch")
    if "bearerToken" in REGISTRATION.read_text() or "clientKey" in REGISTRATION.read_text():
        errors.append("registration template must contain no credential bytes")
    return errors


def negative_controls() -> list[str]:
    failures = []
    base_security = yaml.safe_load(SECURITY.read_text())
    base_risk = yaml.safe_load(RISK.read_text())
    cases = []

    mutated = copy.deepcopy(base_security)
    mutated["spec"]["authorization"]["registrationGranted"] = True
    cases.append(("premature-registration-grant", {"security": mutated}))
    mutated = copy.deepcopy(base_security)
    mutated["spec"]["runtimeAuthorityDomains"]["targetTokenRequest"]["nativeArgoRotation"] = True
    cases.append(("false-rotation-claim", {"security": mutated}))
    mutated = copy.deepcopy(base_security)
    mutated["spec"]["submissionBoundary"]["automaticRollbackAllowed"] = True
    cases.append(("unauthorized-rollback", {"security": mutated}))
    mutated = copy.deepcopy(base_security)
    mutated["spec"]["compatibilityBoundary"]["exactCombinationExecutionProven"] = True
    cases.append(("unproven-compatibility-claimed", {"security": mutated}))
    mutated = copy.deepcopy(base_risk)
    mutated["spec"]["acceptance"]["accepted"] = True
    cases.append(("fabricated-risk-acceptance", {"risk": mutated}))
    mutated = copy.deepcopy(base_risk)
    mutated["spec"]["risks"].pop()
    cases.append(("missing-risk", {"risk": mutated}))

    for name, overrides in cases:
        if not verify(**overrides):
            failures.append(f"negative control did not fail closed: {name}")
    return failures


def main() -> int:
    errors = verify() + negative_controls()
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    print(f"PASS: M0b runtime registration security verified ({digest(SECURITY)}); 6 negative controls fail closed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
