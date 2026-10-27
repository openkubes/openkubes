#!/usr/bin/env python3
"""Resume OK-141 after G3 while treating bound G3 evidence as required state."""

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
CANDIDATE = HERE / "happy-run-resume-candidate-v4.yaml"
V3_CANDIDATE = SPIKE / "go1-happy-run-resume-v3" / "happy-run-resume-candidate-v3.yaml"
V3_DIGEST = "sha256:096a43c7636dcdbfc86f50f6ac22cd51303b4b7dc731d143b1503897a6807b0d"
OPERATIONS = ("provider-prerequisites", "management-namespace", "provider-access-secret", "capi-lifecycle")
RUN_ID = re.compile(r"ok141-go1-l-[a-z0-9-]+")


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(value)
    return value


V3 = load_module("ok141_happy_resume_v3_for_v4", SPIKE / "go1-happy-run-resume-v3" / "bounded_happy_run_resume_v3.py")


class ResumeV4Error(ValueError):
    pass


def sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text())
    if not isinstance(value, dict):
        raise ResumeV4Error(f"expected mapping: {path}")
    return value


def expect(actual: Any, expected: Any, context: str) -> None:
    if actual != expected:
        raise ResumeV4Error(f"{context}: expected {expected!r}, got {actual!r}")


def write_exclusive(path: Path, value: dict[str, Any]) -> None:
    raw = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)


def validate_candidate(path: Path = CANDIDATE) -> dict[str, Any]:
    value = read(path)
    expect(value.get("kind"), "GO1HappyRunResumeCandidateV4", "kind")
    spec = value["spec"]
    expect(spec["version"], "ok141-go1-happy-run-resume/v4", "version")
    expect(spec["state"], "OFFLINE-PROVEN-BLOCKED-NO-GO", "state")
    expect(sha(V3_CANDIDATE), V3_DIGEST, "resume v3 candidate")
    V3.validate_candidate(V3_CANDIDATE)
    expect(spec["supersedes"]["digest"], V3_DIGEST, "resume v3 binding")
    amendment = spec["validatorAmendment"]
    expect(amendment["historicalRule"], "G3-EVIDENCE-MUST-BE-ABSENT", "historical rule")
    expect(amendment["resumeRule"], "EXACT-BOUND-G3-EVIDENCE-MUST-BE-PRESENT", "resume rule")
    expect(amendment["g3ReexecutionAllowed"], False, "G3 reexecution")
    expect(sha(HERE / spec["tool"]["path"]), spec["tool"]["digest"], "tool digest")
    expect(spec["authorization"]["decision"], "NO-GO", "authorization")
    if any(item for key, item in spec["authorization"].items() if key.endswith("Granted")):
        raise ResumeV4Error("candidate grants authority")
    return value


def validate_pre_g3_values(preflight: dict[str, Any], summary: dict[str, Any], operations: dict[str, dict[str, Any]], run_id: str) -> None:
    expect((preflight.get("kind"), preflight.get("spec", {}).get("result"), preflight.get("spec", {}).get("mutationPerformed")), ("GO1V6PreflightEvidence", "PASS-FRESH-BASELINE-AND-PREREQUISITES", False), "preflight result")
    spec = summary.get("spec", {})
    expect((summary.get("kind"), spec.get("stage"), spec.get("result")), ("GO1LStageEvidence", "G1", "SUBMITTED-STOP-PRESERVE"), "G1 summary")
    expect((spec.get("runID"), spec.get("mutationCount")), (run_id, 12), "G1 identity")
    expect((spec.get("retryPerformed"), spec.get("rollbackOrCleanupPerformed")), (False, False), "G1 exclusions")
    expect(sorted(spec.get("operationEvidenceDigests", {})), sorted(OPERATIONS), "G1 operation set")
    expect(sorted(operations), sorted(OPERATIONS), "operation values")
    for name, evidence in operations.items():
        item = evidence.get("spec", {})
        expect((evidence.get("kind"), item.get("operation"), item.get("runID")), ("GO1LOperationEvidence", name, run_id), f"{name} identity")
        expect((item.get("retryPerformed"), item.get("rollbackOrCleanupPerformed")), (False, False), f"{name} exclusions")


def validate_preserved_pre_g3(spec: dict[str, Any]) -> dict[str, Any]:
    preflight_path = Path(spec["preflightEvidence"]["path"])
    expect(preflight_path, Path("/private/tmp/ok141-go1-v6-preflight-v2-evidence.json"), "preflight path")
    preflight = V3.V2.V1.safe_file(preflight_path, spec["preflightEvidence"]["digest"], "preflight")
    run_id = spec["priorGO1LRunID"]
    if not RUN_ID.fullmatch(run_id):
        raise ResumeV4Error("invalid prior GO1-L run ID")
    base = Path("/private/tmp/ok141-go1-l-runtime-v1") / run_id
    summary_path = Path(spec["g1Summary"]["path"])
    expect(summary_path, base / "g1-summary.json", "G1 summary path")
    summary = V3.V2.V1.safe_file(summary_path, spec["g1Summary"]["digest"], "G1 summary")
    digests = summary["spec"]["operationEvidenceDigests"]
    operations = {
        name: V3.V2.V1.safe_file(base / f"evidence-{name}.json", digests[name], name)
        for name in OPERATIONS
    }
    validate_pre_g3_values(preflight, summary, operations, run_id)
    g3_path = Path(spec["priorEvidence"]["g3Path"])
    expect(g3_path, base / "evidence-helmchartproxy.json", "required G3 path")
    if not g3_path.is_file():
        raise ResumeV4Error("required G3 evidence is absent")
    return {"preflight": preflight_path, "summary": summary_path, "summaryValue": summary["spec"], "runtimeDirectory": base}


def adapt_grant(grant: dict[str, Any]) -> dict[str, Any]:
    value = deepcopy(grant)
    value["kind"] = "GO1HappyRunResumeGrantV3"
    value["spec"]["candidateDigest"] = V3_DIGEST
    return value


def validate_grant(candidate_path: Path, grant_path: Path, now: dt.datetime | None = None) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    validate_candidate(candidate_path)
    grant = read(grant_path)
    expect(grant.get("kind"), "GO1HappyRunResumeGrantV4", "grant kind")
    expect(grant["spec"].get("candidateDigest"), sha(candidate_path), "candidate digest")
    adapted = adapt_grant(grant)
    temporary = Path(f"/private/tmp/ok141-happy-resume-v4-validate-{grant['spec'].get('runID', 'invalid')}.json")
    if temporary.exists() or temporary.is_symlink():
        raise ResumeV4Error("adapted validation grant already exists")
    write_exclusive(temporary, adapted)
    try:
        outer, prior = V3.validate_grant(V3_CANDIDATE, temporary, now)
    finally:
        temporary.unlink(missing_ok=True)
    preserved = validate_preserved_pre_g3(grant["spec"])
    remediation = V3.V2.safe_private_evidence(Path(grant["spec"]["remediationEvidencePath"]), grant["spec"]["remediationEvidenceDigest"])
    return outer, prior, preserved, remediation


def execute(candidate_path: Path, grant_path: Path, capability_script: Path) -> dict[str, Any]:
    outer, _, preserved, remediation = validate_grant(candidate_path, grant_path)
    adapted = adapt_grant(outer)
    adapted_path = Path(f"/private/tmp/ok141-happy-resume-v4-adapted-{outer['spec']['runID']}.json")
    if adapted_path.exists() or adapted_path.is_symlink():
        raise ResumeV4Error("adapted execution grant already exists")
    write_exclusive(adapted_path, adapted)

    original_v2_validate = V3.V2.validate_grant
    original_v1_validate = V3.V2.V1.validate_grant

    def validate_for_v2(_candidate, path, now=None):
        return read(path), remediation

    def validate_for_v1(_candidate, path, now=None):
        return read(path), preserved

    V3.V2.validate_grant = validate_for_v2
    V3.V2.V1.validate_grant = validate_for_v1
    try:
        result = V3.execute(V3_CANDIDATE, adapted_path, capability_script)
    finally:
        V3.V2.validate_grant = original_v2_validate
        V3.V2.V1.validate_grant = original_v1_validate
        adapted_path.unlink(missing_ok=True)
    result["candidateDigest"] = sha(candidate_path)
    result["supersededCandidateDigest"] = V3_DIGEST
    result["boundG3PresenceAccepted"] = True
    result["g3Reexecuted"] = False
    return result


def plan(path: Path = CANDIDATE) -> dict[str, Any]:
    value = validate_candidate(path)
    return {
        "candidateDigest": sha(path),
        "supersedes": V3_DIGEST,
        "validatorAmendment": value["spec"]["validatorAmendment"],
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
        if args.command == "verify":
            print(json.dumps(plan(args.candidate.resolve()), indent=2, sort_keys=True))
        elif args.command == "verify-grant":
            if args.grant is None:
                raise ResumeV4Error("grant required")
            validate_grant(args.candidate.resolve(), args.grant.resolve())
            print(sha(args.grant.resolve()))
        else:
            if not args.execute or args.grant is None or args.capability_script is None:
                raise ResumeV4Error("run requires --execute, grant and capability script")
            print(json.dumps(execute(args.candidate.resolve(), args.grant.resolve(), args.capability_script.resolve()), indent=2, sort_keys=True))
        return 0
    except Exception as error:
        print(f"ERROR: {type(error).__name__}: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
