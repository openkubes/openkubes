#!/usr/bin/env python3
"""Resume OK-141 only after the private LB remediation evidence is verified."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import os
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
CANDIDATE = HERE / "happy-run-resume-candidate-v2.yaml"
V1_CANDIDATE = SPIKE / "go1-happy-run-resume-v1" / "happy-run-resume-candidate-v1.yaml"
V1_CANDIDATE_DIGEST = "sha256:804ffad444c2a2155a098c0485a9f5d887d3798a9c2718085d1e2d3b61f678fc"
REMEDIATION_CANDIDATE = SPIKE / "go1-l-lb-namespace-remediation-v1" / "lb-namespace-remediation-candidate-v1.yaml"
REMEDIATION_CANDIDATE_DIGEST = "sha256:f2cff408032898997a589bcc829ece7fad73b0b9bbda9afa1c1080674fae02ca"
REMEDIATION_EVIDENCE_PATH = Path("/private/tmp/ok141-lb-namespace-remediation-v1-evidence.json")


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(value)
    return value


V1 = load_module("ok141_happy_run_resume_v1_for_v2", SPIKE / "go1-happy-run-resume-v1" / "bounded_happy_run_resume_v1.py")


class ResumeV2Error(ValueError):
    pass


def sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text())
    if not isinstance(value, dict):
        raise ResumeV2Error(f"expected mapping: {path}")
    return value


def expect(actual: Any, expected: Any, context: str) -> None:
    if actual != expected:
        raise ResumeV2Error(f"{context}: expected {expected!r}, got {actual!r}")


def write_exclusive(path: Path, value: dict[str, Any]) -> None:
    raw = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)


def validate_candidate(path: Path = CANDIDATE) -> dict[str, Any]:
    value = read(path)
    expect(value.get("kind"), "GO1HappyRunResumeCandidateV2", "kind")
    spec = value["spec"]
    expect(spec["version"], "ok141-go1-happy-run-resume/v2", "version")
    expect(spec["state"], "OFFLINE-PROVEN-BLOCKED-NO-GO", "state")
    expect(sha(V1_CANDIDATE), V1_CANDIDATE_DIGEST, "v1 resume candidate")
    expect(spec["supersedes"]["digest"], V1_CANDIDATE_DIGEST, "v1 resume binding")
    V1.validate_candidate(V1_CANDIDATE)
    expect(sha(REMEDIATION_CANDIDATE), REMEDIATION_CANDIDATE_DIGEST, "remediation candidate")
    expect(spec["requiredRemediation"]["candidateDigest"], REMEDIATION_CANDIDATE_DIGEST, "remediation binding")
    expect(spec["requiredRemediation"]["privateEvidencePath"], str(REMEDIATION_EVIDENCE_PATH), "private evidence path")
    expect(spec["requiredRemediation"]["digestPublishedInCandidate"], False, "private evidence boundary")
    expect(spec["resumeBoundary"]["startsAfter"], "LB-REMEDIATION", "resume boundary")
    expect(spec["resumeBoundary"]["preflightReexecutionAllowed"], False, "preflight boundary")
    expect(spec["resumeBoundary"]["g1ReexecutionAllowed"], False, "G1 boundary")
    expect(sha(HERE / spec["tool"]["path"]), spec["tool"]["digest"], "tool digest")
    auth = spec["authorization"]
    expect(auth["decision"], "NO-GO", "authorization")
    if any(value for key, value in auth.items() if key.endswith("Granted")):
        raise ResumeV2Error("candidate grants authority")
    return value


def safe_private_evidence(path: Path, expected_digest: str) -> dict[str, Any]:
    if path != REMEDIATION_EVIDENCE_PATH or path.is_symlink() or not path.is_file() or (path.stat().st_mode & 0o777) != 0o600:
        raise ResumeV2Error("unsafe remediation evidence")
    expect(sha(path), expected_digest, "remediation evidence digest")
    value = read(path)
    expect(value.get("kind"), "LBNamespaceRemediationEvidence", "remediation evidence kind")
    spec = value["spec"]
    expect(spec["candidateDigest"], REMEDIATION_CANDIDATE_DIGEST, "remediation candidate")
    expect(spec["result"], "REMEDIATED-PRESERVE-HAPPY-RUN", "remediation result")
    expect(spec["targetService"]["vip"], "192.168.100.213", "remediated VIP")
    expect(spec["targetService"]["endpointAddressCount"] > 0, True, "target endpoints")
    expect(spec["endpointsAfterTrigger"], {
        "cluster": {"host": "192.168.100.213", "port": 6443},
        "kubevirtCluster": {"host": "192.168.100.213", "port": 6443},
    }, "restored endpoints")
    expect((spec["secretBytesEmitted"], spec["secretDigestEmitted"], spec["retryPerformed"], spec["rollbackOrGeneralCleanupPerformed"], spec["happyRunResumed"]), (False, False, False, False, False), "remediation exclusions")
    return value


def adapt_grant(grant: dict[str, Any]) -> dict[str, Any]:
    adapted = deepcopy(grant)
    adapted["kind"] = "GO1HappyRunResumeGrant"
    adapted["spec"]["candidateDigest"] = V1_CANDIDATE_DIGEST
    return adapted


def validate_grant(candidate_path: Path, grant_path: Path, now: dt.datetime | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    validate_candidate(candidate_path)
    grant = read(grant_path)
    expect(grant.get("kind"), "GO1HappyRunResumeGrantV2", "grant kind")
    spec = grant["spec"]
    expect(spec["candidateDigest"], sha(candidate_path), "grant candidate")
    expect(spec["remediationCandidateDigest"], REMEDIATION_CANDIDATE_DIGEST, "grant remediation candidate")
    expect(spec["remediationEvidencePath"], str(REMEDIATION_EVIDENCE_PATH), "grant remediation path")
    expect(spec["remediationEvidenceBindingGranted"], True, "remediation binding authority")
    evidence = safe_private_evidence(Path(spec["remediationEvidencePath"]), spec["remediationEvidenceDigest"])

    adapted = adapt_grant(grant)
    temporary = Path(f"/private/tmp/ok141-happy-resume-v2-validate-{spec.get('runID', 'invalid')}.json")
    if temporary.exists() or temporary.is_symlink():
        raise ResumeV2Error("adapted validation grant already exists")
    write_exclusive(temporary, adapted)
    try:
        V1.validate_grant(V1_CANDIDATE, temporary, now)
    finally:
        temporary.unlink(missing_ok=True)
    return grant, evidence


def execute(candidate_path: Path, grant_path: Path, capability_script: Path) -> dict[str, Any]:
    grant, remediation = validate_grant(candidate_path, grant_path)
    adapted = adapt_grant(grant)
    adapted_path = Path(f"/private/tmp/ok141-happy-resume-v2-run-{grant['spec']['runID']}.json")
    if adapted_path.exists() or adapted_path.is_symlink():
        raise ResumeV2Error("adapted execution grant already exists")
    write_exclusive(adapted_path, adapted)
    try:
        result = V1.execute(V1_CANDIDATE, adapted_path, capability_script)
    finally:
        adapted_path.unlink(missing_ok=True)
    result["candidateDigest"] = sha(candidate_path)
    result["remediationCandidateDigest"] = REMEDIATION_CANDIDATE_DIGEST
    result["remediationEvidenceDigest"] = grant["spec"]["remediationEvidenceDigest"]
    result["remediationRunID"] = remediation["spec"]["runID"]
    result["preflightReexecuted"] = False
    result["g1Reexecuted"] = False
    return result


def plan(path: Path = CANDIDATE) -> dict[str, Any]:
    value = validate_candidate(path)
    return {
        "candidateDigest": sha(path),
        "supersedes": V1_CANDIDATE_DIGEST,
        "requiredRemediation": value["spec"]["requiredRemediation"],
        "authorization": "NO-GO",
        "clusterContacted": False,
        "mutationPerformed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "verify-grant", "run"))
    parser.add_argument("--candidate", type=Path, default=CANDIDATE)
    parser.add_argument("--grant", type=Path)
    parser.add_argument("--capability-script", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        candidate = args.candidate.resolve()
        if args.command == "verify":
            print(json.dumps(plan(candidate), indent=2, sort_keys=True))
        elif args.command == "verify-grant":
            if args.grant is None:
                raise ResumeV2Error("grant required")
            validate_grant(candidate, args.grant.resolve())
            print(sha(args.grant.resolve()))
        else:
            if not args.execute or args.grant is None or args.capability_script is None:
                raise ResumeV2Error("run requires --execute, --grant and --capability-script")
            print(json.dumps(execute(candidate, args.grant.resolve(), args.capability_script.resolve()), indent=2, sort_keys=True))
        return 0
    except Exception as error:
        print(f"ERROR: {type(error).__name__}: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
