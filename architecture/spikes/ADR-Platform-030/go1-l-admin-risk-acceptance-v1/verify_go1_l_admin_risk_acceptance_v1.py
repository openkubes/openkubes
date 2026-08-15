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
ACCEPTANCE = HERE / "go1-l-admin-risk-acceptance-v1.yaml"
DIGEST = HERE / "go1-l-admin-risk-acceptance-v1.sha256"
CANDIDATE = "sha256:fad8675a362e78d81356b430bcbb1cedb701739d772bc07292801f735ed8da84"
STATEMENT = "Ich akzeptiere für OK-141/GO1-L das dokumentierte DEV-ADMIN-CREATE-Risiko: die Administrator- und Create-Content-Grenze, die nur prozedurale Zeitbegrenzung eines möglicherweise langlebigen Admin-Credentials, das Absence-to-Create-TOCTOU-Fenster, nicht-atomaren Partial-State mit fortlaufender Controller-Reconciliation sowie den akzeptierten DEV-Rebuild-on-Loss-Pfad. Diese Akzeptanz erteilt keine Credential-Nutzung, keinen Preflight-Lauf, keine Objekt-Submission, keinen Retry oder Rollback und weder GO1-L noch GO-1."


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


V4 = load_module("ok141_phase_r_v4_admin_risk_acceptance", HARNESS / "ok141_phase_r_v4.py")
V1 = V4.V1


class AcceptanceError(ValueError):
    pass


def sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def expect(actual, expected, context):
    if actual != expected:
        raise AcceptanceError(f"{context}: expected {expected!r}, got {actual!r}")


def resolve(requested: str) -> Path:
    path = (HERE / requested).resolve()
    if SPIKE.resolve() not in path.parents or not path.is_file():
        raise AcceptanceError(f"invalid source path: {requested}")
    return path


def validate(document: dict) -> str:
    expect(document["apiVersion"], "security.openkubes.io/v1alpha1", "apiVersion")
    expect(document["kind"], "GO1LAdminRiskAcceptance", "kind")
    spec = document["spec"]
    expect(spec["state"], "ACCEPTED-NON-AUTHORIZING", "state")
    expect(spec["authority"], "github:arashkaffamanesh", "authority")
    source = spec["sourceCandidate"]
    expect(sha(resolve(source["path"])), CANDIDATE, "candidate source")
    expect(source["digest"], CANDIDATE, "candidate binding")
    expect(source["priorState"], "RISK-ACCEPTANCE-REQUIRED-NO-GO", "prior state")
    acceptance = spec["acceptance"]
    expect(acceptance["accepted"], True, "accepted")
    expect(acceptance["acceptedCandidateDigest"], CANDIDATE, "accepted digest")
    expect(acceptance["exactStatement"], STATEMENT, "acceptance statement")
    authorization = spec["authorization"]
    expect(authorization["decision"], "NO-GO", "authorization decision")
    expect(authorization["grantIDs"], [], "grant IDs")
    expect(authorization["authorizedDigest"], None, "authorized digest")
    if any(value for key, value in authorization.items() if key.endswith("Granted")):
        raise AcceptanceError("risk acceptance grants execution authority")
    conclusions = spec["conclusions"]
    expect(conclusions["riskAcceptanceComplete"], True, "risk conclusion")
    for key in ("credentialIdentityResolved", "runtimeGrantCandidatesComplete", "credentialUseReadyForDecision", "go1LReadyForDecision", "clusterContacted", "mutationAuthorized"):
        expect(conclusions[key], False, key)
    return sha(ACCEPTANCE)


def main() -> int:
    try:
        document = V1.read_yaml_or_json(ACCEPTANCE)
        actual = validate(document)
        if DIGEST.exists():
            expect(DIGEST.read_text().strip(), actual, "digest file")
        print(json.dumps({
            "acceptanceDigest": actual,
            "acceptedCandidateDigest": CANDIDATE,
            "state": document["spec"]["state"],
            "credentialUseGranted": False,
            "go1LGranted": False,
            "clusterContacted": False,
            "mutationAuthorized": False,
        }, sort_keys=True))
        return 0
    except (AcceptanceError, KeyError, OSError, TypeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
