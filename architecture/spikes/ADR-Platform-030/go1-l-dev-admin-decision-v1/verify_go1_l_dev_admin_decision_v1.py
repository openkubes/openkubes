#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
DECISION = HERE / "go1-l-dev-admin-decision-v1.yaml"
DIGEST = HERE / "go1-l-dev-admin-decision-v1.sha256"
HARNESS = SPIKE / "harness"
BOUNDARY = "sha256:ba2d8fdcc773ab333af2560436ad48f27dbb6c7222a627add44ed03b3ce8fa38"
SUBMITTER = "sha256:e5b4185b7dcd4f1e3fb026d03ce29b5b35e0b6c5c6e51f29d921a240636b73cc"
STATEMENT = "Ich wähle für OK-141 das DEV-ADMIN-CREATE-Modell mit der dokumentierten Administrator- und Create-Content-Grenze. Diese Auswahl allein erteilt noch keine Credential-, GO1-L- oder GO-1-Freigabe."


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


V4 = load_module("ok141_phase_r_v4_dev_admin_decision", HARNESS / "ok141_phase_r_v4.py")
V1 = V4.V1


class DecisionError(ValueError):
    pass


def sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def expect(actual, expected, context):
    if actual != expected:
        raise DecisionError(f"{context}: expected {expected!r}, got {actual!r}")


def resolve(requested: str) -> Path:
    path = (HERE / requested).resolve()
    if SPIKE.resolve() not in path.parents or not path.is_file():
        raise DecisionError(f"invalid source path: {requested}")
    return path


def validate(decision: dict) -> str:
    expect(decision["apiVersion"], "security.openkubes.io/v1alpha1", "apiVersion")
    expect(decision["kind"], "GO1LCredentialModelDecision", "kind")
    spec = decision["spec"]
    expect(spec["state"], "SELECTED-NON-AUTHORIZING", "state")
    expect(spec["decisionAuthority"], "github:arashkaffamanesh", "decision authority")
    boundary = spec["sourceBoundary"]
    expect(sha(resolve(boundary["path"])), BOUNDARY, "boundary source")
    expect(boundary["digest"], BOUNDARY, "boundary binding")
    expect(boundary["priorSelectedModel"], "UNRESOLVED", "prior model")
    submitter = spec["sourceSubmitter"]
    expect(sha(resolve(submitter["path"])), SUBMITTER, "submitter source")
    expect(submitter["digest"], SUBMITTER, "submitter binding")
    expect(submitter["state"], "OFFLINE-PROVEN-BLOCKED-NO-GO", "submitter state")
    selection = spec["selection"]
    expect(selection["model"], "DEV-ADMIN-CREATE", "selected model")
    expect(selection["exactStatement"], STATEMENT, "selection statement")
    expect(selection["administratorBoundaryAcknowledged"], True, "administrator boundary")
    expect(selection["createContentBoundaryAcknowledged"], True, "create-content boundary")
    expect(selection["executionRiskAccepted"], False, "execution risk")
    credential = spec["futureCredentialRequirements"]
    expect(credential["credentialMaterial"], "UNRESOLVED", "credential material")
    expect(credential["separateCredentialBindingPerOperation"], True, "operation credential split")
    expect(credential["maximumOperationGrantMinutes"], 20, "grant duration")
    authorization = spec["authorization"]
    expect(authorization["decision"], "NO-GO", "authorization decision")
    expect(authorization["grantIDs"], [], "grant IDs")
    expect(authorization["authorizedDigest"], None, "authorized digest")
    if any(value for key, value in authorization.items() if key.endswith("Granted") or key == "operationGrantIssued"):
        raise DecisionError("decision artifact grants authority")
    conclusions = spec["conclusions"]
    expect(conclusions["credentialModelSelected"], True, "model conclusion")
    for key in ("credentialMaterialReady", "submitterReadyForExecution", "go1LReadyForDecision", "infrastructureMutationAuthorized"):
        expect(conclusions[key], False, key)
    return sha(DECISION)


def main() -> int:
    try:
        decision = V1.read_yaml_or_json(DECISION)
        actual = validate(decision)
        if DIGEST.exists():
            expect(DIGEST.read_text().strip(), actual, "digest file")
        print(json.dumps({
            "decisionDigest": actual,
            "state": decision["spec"]["state"],
            "selectedModel": decision["spec"]["selection"]["model"],
            "credentialIssuanceGranted": False,
            "go1LGranted": False,
            "go1Granted": False,
            "clusterContacted": False,
            "mutationAuthorized": False,
        }, sort_keys=True))
        return 0
    except (DecisionError, KeyError, OSError, TypeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
