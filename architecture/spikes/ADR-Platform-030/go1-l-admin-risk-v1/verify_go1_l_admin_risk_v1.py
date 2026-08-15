#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
HARNESS = SPIKE / "harness"
CANDIDATE = HERE / "go1-l-admin-risk-candidate-v1.yaml"
DIGEST = HERE / "go1-l-admin-risk-candidate-v1.sha256"
SOURCES = {
    "sourceDecision": "sha256:f5cebe20bfe8059cec2bbf55324d753821df0cb439568495194242d253595c5c",
    "sourcePreflight": "sha256:3a3187c79779e048337fd2d6c35473a3c97f900330082721e3b318a5c9e6a12f",
    "sourceSubmitter": "sha256:e5b4185b7dcd4f1e3fb026d03ce29b5b35e0b6c5c6e51f29d921a240636b73cc",
}
RISK_IDS = {
    "administratorAuthority", "grantVersusCredentialLifetime", "absenceCreateRace",
    "nonAtomicOperations", "controllerContinuation", "devRebuildBoundary",
}


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


V4 = load_module("ok141_phase_r_v4_admin_risk", HARNESS / "ok141_phase_r_v4.py")
V1 = V4.V1


class RiskError(ValueError):
    pass


def sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def expect(actual, expected, context):
    if actual != expected:
        raise RiskError(f"{context}: expected {expected!r}, got {actual!r}")


def resolve(requested: str) -> Path:
    path = (HERE / requested).resolve()
    if SPIKE.resolve() not in path.parents or not path.is_file():
        raise RiskError(f"invalid source path: {requested}")
    return path


def validate(candidate: dict) -> str:
    expect(candidate["apiVersion"], "security.openkubes.io/v1alpha1", "apiVersion")
    expect(candidate["kind"], "GO1LAdminRiskCandidate", "kind")
    spec = candidate["spec"]
    expect(spec["state"], "RISK-ACCEPTANCE-REQUIRED-NO-GO", "state")
    for source_name, digest in SOURCES.items():
        source = spec[source_name]
        expect(sha(resolve(source["path"])), digest, f"{source_name} source")
        expect(source["digest"], digest, f"{source_name} binding")
    expect(set(spec["riskClaims"]), RISK_IDS, "risk inventory")
    for risk_id, risk in spec["riskClaims"].items():
        expect(risk["residualRisk"], "ACCEPTANCE-REQUIRED", f"{risk_id} residual risk")
        if not all(risk.get(field) for field in ("claim", "consequence", "mitigation")):
            raise RiskError(f"{risk_id} is incomplete")
    acceptance = spec["requiredAcceptance"]
    expect(acceptance["authority"], "github:arashkaffamanesh", "acceptance authority")
    expect(acceptance["accepted"], False, "risk acceptance")
    expect(acceptance["acceptedCandidateDigest"], None, "accepted digest")
    if "keine Credential-Nutzung" not in acceptance["exactStatement"] or "weder GO1-L noch GO-1" not in acceptance["exactStatement"]:
        raise RiskError("acceptance statement loses non-authorizing boundary")
    authorization = spec["authorization"]
    expect(authorization["decision"], "NO-GO", "authorization decision")
    expect(authorization["grantIDs"], [], "grant IDs")
    expect(authorization["authorizedDigest"], None, "authorized digest")
    if any(value for key, value in authorization.items() if key.endswith("Granted")):
        raise RiskError("risk candidate grants authority")
    conclusions = spec["conclusions"]
    expect(conclusions["technicalCandidateComplete"], True, "technical conclusion")
    for key in ("riskAcceptanceComplete", "credentialUseReadyForDecision", "go1LReadyForDecision", "clusterContacted", "mutationAuthorized"):
        expect(conclusions[key], False, key)
    return sha(CANDIDATE)


def main() -> int:
    try:
        candidate = V1.read_yaml_or_json(CANDIDATE)
        actual = validate(candidate)
        if DIGEST.exists():
            expect(DIGEST.read_text().strip(), actual, "digest file")
        print(json.dumps({
            "candidateDigest": actual,
            "state": candidate["spec"]["state"],
            "risks": len(candidate["spec"]["riskClaims"]),
            "riskAccepted": False,
            "credentialUseGranted": False,
            "go1LGranted": False,
            "clusterContacted": False,
            "mutationAuthorized": False,
        }, sort_keys=True))
        return 0
    except (KeyError, OSError, RiskError, TypeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
