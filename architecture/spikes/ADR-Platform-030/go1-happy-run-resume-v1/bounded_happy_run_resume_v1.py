#!/usr/bin/env python3
"""Resume the bounded OK-141 happy run from verified, preserved G1 evidence."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import os
import re
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
CANDIDATE = HERE / "happy-run-resume-candidate-v1.yaml"
V2_CANDIDATE = SPIKE / "go1-happy-run-v2" / "happy-run-candidate-v2.yaml"
V2_CANDIDATE_DIGEST = "sha256:f1c3460a725d120e54e4e6244102b184573039548903a26e1e3ff8869f38ab44"
OPERATIONS = ("provider-prerequisites", "management-namespace", "provider-access-secret", "capi-lifecycle")
RUN_ID = re.compile(r"ok141-happy-resume-[a-z0-9-]+")
GO1L_RUN_ID = re.compile(r"ok141-go1-l-[a-z0-9-]+")


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(value)
    return value


V2 = load_module("ok141_happy_run_v2_for_resume", SPIKE / "go1-happy-run-v2" / "bounded_happy_run_v2.py")


class ResumeError(ValueError):
    pass


def sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text())
    if not isinstance(value, dict):
        raise ResumeError(f"expected mapping: {path}")
    return value


def expect(actual: Any, expected: Any, context: str) -> None:
    if actual != expected:
        raise ResumeError(f"{context}: expected {expected!r}, got {actual!r}")


def parse_time(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def write_exclusive(path: Path, value: Any) -> None:
    raw = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)


def validate_candidate(candidate_path: Path = CANDIDATE) -> dict[str, Any]:
    candidate = read(candidate_path)
    expect(candidate.get("kind"), "GO1HappyRunResumeCandidate", "kind")
    spec = candidate["spec"]
    expect(spec["version"], "ok141-go1-happy-run-resume/v1", "version")
    expect(spec["state"], "OFFLINE-PROVEN-BLOCKED-NO-GO", "state")
    expect(sha(V2_CANDIDATE), V2_CANDIDATE_DIGEST, "v2 candidate")
    expect(spec["supersedes"]["digest"], V2_CANDIDATE_DIGEST, "v2 binding")
    V2.validate_candidate(V2_CANDIDATE)
    expect(sha(HERE / spec["tool"]["path"]), spec["tool"]["digest"], "tool digest")
    expect(spec["resumeBoundary"]["startsAfter"], "G1", "resume boundary")
    expect(spec["resumeBoundary"]["preflightReexecutionAllowed"], False, "preflight reexecution")
    expect(spec["resumeBoundary"]["g1ReexecutionAllowed"], False, "G1 reexecution")
    if any(spec["authorization"].get(key) for key in spec["authorization"] if key.endswith("Granted")):
        raise ResumeError("candidate grants authority")
    return candidate


TRUE = (
    "resumeFromG1Granted", "credentialUseGranted", "lifecycleObserverGranted", "g3Granted",
    "networkObserverGranted", "runtimeBindingGranted", "targetAccessGranted", "tokenRequestGranted",
    "registrationGranted", "credentialSecretGranted", "applicationSubmissionGranted",
    "platformObserverGranted", "capabilityTestGranted", "capabilityTestCleanupGranted",
    "go1LGranted", "go1Granted",
)
FALSE = (
    "preflightGranted", "g1Granted", "retryGranted", "rollbackGranted", "broadCleanupGranted",
    "evidencePublicationGranted", "failureInjectionGranted", "outageGranted",
)


def safe_file(path: Path, expected_digest: str, context: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or (path.stat().st_mode & 0o777) != 0o600:
        raise ResumeError(f"unsafe {context} file")
    expect(sha(path), expected_digest, f"{context} digest")
    return read(path)


def validate_resume_evidence(spec: dict[str, Any]) -> dict[str, Any]:
    preflight_path = Path(spec["preflightEvidence"]["path"])
    expect(preflight_path, Path("/private/tmp/ok141-go1-v6-preflight-v2-evidence.json"), "preflight path")
    preflight = safe_file(preflight_path, spec["preflightEvidence"]["digest"], "preflight")
    expect(preflight.get("kind"), "GO1V6PreflightEvidence", "preflight kind")
    expect(preflight["spec"]["result"], "PASS-FRESH-BASELINE-AND-PREREQUISITES", "preflight result")
    expect(preflight["spec"]["mutationPerformed"], False, "preflight mutation")

    prior_run = spec["priorGO1LRunID"]
    if not GO1L_RUN_ID.fullmatch(prior_run):
        raise ResumeError("invalid prior GO1-L run ID")
    base = Path("/private/tmp/ok141-go1-l-runtime-v1") / prior_run
    summary_path = Path(spec["g1Summary"]["path"])
    expect(summary_path, base / "g1-summary.json", "G1 summary path")
    summary = safe_file(summary_path, spec["g1Summary"]["digest"], "G1 summary")
    summary_spec = summary["spec"]
    expect((summary.get("kind"), summary_spec["stage"], summary_spec["result"]), ("GO1LStageEvidence", "G1", "SUBMITTED-STOP-PRESERVE"), "G1 summary identity")
    expect((summary_spec["runID"], summary_spec["mutationCount"]), (prior_run, 12), "G1 summary binding")
    expect((summary_spec["retryPerformed"], summary_spec["rollbackOrCleanupPerformed"]), (False, False), "G1 exclusions")
    expect(sorted(summary_spec["operationEvidenceDigests"]), sorted(OPERATIONS), "G1 operation set")
    for operation in OPERATIONS:
        path = base / f"evidence-{operation}.json"
        evidence = safe_file(path, summary_spec["operationEvidenceDigests"][operation], operation)
        expect((evidence.get("kind"), evidence["spec"]["operation"], evidence["spec"]["runID"]), ("GO1LOperationEvidence", operation, prior_run), f"{operation} identity")
        expect((evidence["spec"]["retryPerformed"], evidence["spec"]["rollbackOrCleanupPerformed"]), (False, False), f"{operation} exclusions")
    if (base / "evidence-helmchartproxy.json").exists():
        raise ResumeError("G3 evidence already exists")
    return {"preflight": preflight_path, "summary": summary_path, "summaryValue": summary_spec, "runtimeDirectory": base}


def validate_grant(candidate_path: Path, grant_path: Path, now: dt.datetime | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    validate_candidate(candidate_path)
    grant = read(grant_path)
    expect(grant.get("kind"), "GO1HappyRunResumeGrant", "grant kind")
    spec = grant["spec"]
    expect((spec["decision"], spec["authority"], spec["singleRun"], spec["consumed"]), ("GO", "github:arashkaffamanesh", True, False), "grant identity")
    expect(spec["candidateDigest"], sha(candidate_path), "candidate digest")
    expect(spec["protocolDigest"], V2.V1.validate_candidate(V2.V1_CANDIDATE)["spec"]["protocolDigest"], "protocol digest")
    expect(spec["fixtureDigest"], V2.V1.validate_candidate(V2.V1_CANDIDATE)["spec"]["fixture"]["fixtureDigest"], "fixture digest")
    if any(spec.get(key) is not True for key in TRUE) or any(spec.get(key) is not False for key in FALSE):
        raise ResumeError("resume authority is incomplete or overbroad")
    if not spec.get("grantID") or not RUN_ID.fullmatch(spec.get("runID", "")):
        raise ResumeError("invalid grant or run ID")
    current = now or dt.datetime.now(dt.timezone.utc)
    issued, expires = parse_time(spec["issuedAt"]), parse_time(spec["expiresAt"])
    if not issued <= current <= expires or expires - issued > dt.timedelta(hours=2):
        raise ResumeError("grant inactive or exceeds two hours")
    return grant, validate_resume_evidence(spec)


def amend_generated_grant(name: str, value: dict[str, Any], resume: dict[str, Any]) -> dict[str, Any]:
    amended = deepcopy(value)
    spec = amended["spec"]
    if name == "g1":
        spec["g1Granted"] = False
        spec["resumeFromG1Granted"] = True
        spec["priorG1SummaryDigest"] = sha(resume["summary"])
    elif name == "g3":
        spec["runID"] = resume["summaryValue"]["runID"]
    elif name == "lifecycle":
        lifecycle = V2.V1.LIFECYCLE.validate_candidate(V2.V1.LIFECYCLE.CANDIDATE)["spec"]
        spec["runtimePackageDigest"] = lifecycle["runtimePackage"]["digest"]
        spec["credentialIdentityDigest"] = lifecycle["credential"]["identityDigest"]
    return amended


def execute(candidate_path: Path, grant_path: Path, capability_script: Path) -> dict[str, Any]:
    outer, resume = validate_grant(candidate_path, grant_path)
    adapted = deepcopy(outer)
    adapted["kind"] = "GO1HappyRunGrant"
    adapted["spec"]["candidateDigest"] = V2_CANDIDATE_DIGEST
    adapted_path = Path(f"/private/tmp/ok141-happy-resume-adapted-{outer['spec']['runID']}.json")
    write_exclusive(adapted_path, adapted)

    original_v2_validate = V2.validate_grant
    original_v1_validate = V2.V1.validate_grant
    original_preflight = V2.V1.PREFLIGHT.run_preflight
    original_g1 = V2.V1.RUNTIME.execute_g1
    original_grant_file = V2.V1.grant_file

    def resume_v2_validate(_candidate, path):
        return read(path)

    def resume_v1_validate(_candidate, path, now=None):
        return read(path)

    def resume_preflight(_candidate, _grant, _now):
        return read(resume["preflight"])

    def resume_g1(_candidate, stage_grant, preflight, _now):
        stage = read(stage_grant)["spec"]
        expect((stage.get("g1Granted"), stage.get("resumeFromG1Granted")), (False, True), "resume G1 boundary")
        expect(stage.get("priorG1SummaryDigest"), sha(resume["summary"]), "prior G1 binding")
        projected = read(preflight)
        expect(projected["spec"]["sourceEvidenceDigest"], sha(resume["preflight"]), "projected preflight source")
        result = deepcopy(resume["summaryValue"])
        result["evidencePath"] = str(resume["summary"])
        result["evidenceDigest"] = sha(resume["summary"])
        return result

    def resume_grant_file(run_dir, name, value):
        return original_grant_file(run_dir, name, amend_generated_grant(name, value, resume))

    V2.validate_grant = resume_v2_validate
    V2.V1.validate_grant = resume_v1_validate
    V2.V1.PREFLIGHT.run_preflight = resume_preflight
    V2.V1.RUNTIME.execute_g1 = resume_g1
    V2.V1.grant_file = resume_grant_file
    try:
        result = V2.execute(V2_CANDIDATE, adapted_path, capability_script)
    finally:
        V2.validate_grant = original_v2_validate
        V2.V1.validate_grant = original_v1_validate
        V2.V1.PREFLIGHT.run_preflight = original_preflight
        V2.V1.RUNTIME.execute_g1 = original_g1
        V2.V1.grant_file = original_grant_file
    result["candidateDigest"] = sha(candidate_path)
    result["resumedFromG1EvidenceDigest"] = sha(resume["summary"])
    result["preflightReexecuted"] = False
    result["g1Reexecuted"] = False
    return result


def plan(candidate_path: Path = CANDIDATE) -> dict[str, Any]:
    candidate = validate_candidate(candidate_path)
    return {"candidateDigest": sha(candidate_path), "supersedes": V2_CANDIDATE_DIGEST, "resumeBoundary": candidate["spec"]["resumeBoundary"], "authorization": "NO-GO", "clusterContacted": False}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "verify-grant", "run"))
    parser.add_argument("--candidate", type=Path, default=CANDIDATE)
    parser.add_argument("--grant", type=Path)
    parser.add_argument("--capability-script", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "verify":
            print(json.dumps(plan(args.candidate.resolve()), indent=2, sort_keys=True))
        elif args.command == "verify-grant":
            if args.grant is None:
                raise ResumeError("grant required")
            validate_grant(args.candidate.resolve(), args.grant.resolve())
            print(sha(args.grant.resolve()))
        else:
            if not args.execute or args.grant is None or args.capability_script is None:
                raise ResumeError("run requires --execute, grant and capability script")
            print(json.dumps(execute(args.candidate.resolve(), args.grant.resolve(), args.capability_script.resolve()), indent=2, sort_keys=True))
        return 0
    except Exception as error:
        print(f"ERROR: {type(error).__name__}: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
