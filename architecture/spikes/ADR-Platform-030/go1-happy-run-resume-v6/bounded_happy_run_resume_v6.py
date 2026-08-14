#!/usr/bin/env python3
"""Resume OK-141 with source-bound Cilium cached-health freshness."""

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
CANDIDATE = HERE / "happy-run-resume-candidate-v6.yaml"
V5_CANDIDATE = SPIKE / "go1-happy-run-resume-v5" / "happy-run-resume-candidate-v5.yaml"
V5_TOOL = SPIKE / "go1-happy-run-resume-v5" / "bounded_happy_run_resume_v5.py"
FRESH_CANDIDATE = SPIKE / "go1-network-cache-freshness-v1" / "network-cache-freshness-candidate-v1.yaml"
FRESH_TOOL = SPIKE / "go1-network-cache-freshness-v1" / "network_cache_freshness_v1.py"
V5_DIGEST = "sha256:3e2ef69489668a6157867331ff11dced512b265162218b7a06c6d5d0008b01a2"
V5_TOOL_DIGEST = "sha256:6cb8643ee1944bbfab61cdaacd1749973243b9ff7042fa6e5e67ef8bc839a543"
FRESH_DIGEST = "sha256:181f376512ca22e4b828a37c6f0bc448781ed88e5cf8d3913243edaa00f8f39d"
FRESH_TOOL_DIGEST = "sha256:f5c7bc8a04c7720ea205ef73f38a2f79ee4b66c22ce6c85e9ae594b5d347c5b0"
STALE_PATH = Path("/private/tmp/ok141-go1-l-network-ready-observer-status-v1-evidence.json")
TIMING_PATH = Path("/private/tmp/ok141-network-cache-timing-diagnostic-v1-evidence.json")
NEW_NETWORK_OUTPUT = Path("/private/tmp/ok141-go1-l-network-ready-observer-cache-freshness-v1-evidence.json")


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(value)
    return value


V5 = load_module("ok141_happy_resume_v5_for_v6", V5_TOOL)
FRESH = load_module("ok141_cache_freshness_for_resume_v6", FRESH_TOOL)


class ResumeV6Error(ValueError):
    pass


def sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text())
    if not isinstance(value, dict):
        raise ResumeV6Error(f"expected mapping: {path}")
    return value


def expect(actual: Any, expected: Any, context: str) -> None:
    if actual != expected:
        raise ResumeV6Error(f"{context}: expected {expected!r}, got {actual!r}")


def write_exclusive(path: Path, value: dict[str, Any]) -> None:
    raw = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)


def validate_candidate(path: Path = CANDIDATE) -> dict[str, Any]:
    value = read(path)
    expect(value.get("kind"), "GO1HappyRunResumeCandidateV6", "kind")
    spec = value["spec"]
    expect(spec["version"], "ok141-go1-happy-run-resume/v6", "version")
    expect(spec["state"], "OFFLINE-PROVEN-BLOCKED-NO-GO", "state")
    expect(sha(V5_CANDIDATE), V5_DIGEST, "resume v5 candidate")
    expect(sha(V5_TOOL), V5_TOOL_DIGEST, "resume v5 tool")
    V5.validate_candidate(V5_CANDIDATE)
    expect(spec["supersedes"]["digest"], V5_DIGEST, "resume v5 binding")
    expect(sha(FRESH_CANDIDATE), FRESH_DIGEST, "freshness candidate")
    expect(sha(FRESH_TOOL), FRESH_TOOL_DIGEST, "freshness tool")
    FRESH.validate_candidate(FRESH_CANDIDATE)
    expect(spec["cacheFreshness"]["candidateDigest"], FRESH_DIGEST, "freshness binding")
    expect(spec["cacheFreshness"]["outputPath"], str(NEW_NETWORK_OUTPUT), "new output")
    expect(sha(HERE / spec["tool"]["path"]), spec["tool"]["digest"], "tool digest")
    expect(spec["authorization"]["decision"], "NO-GO", "authorization")
    if any(item for key, item in spec["authorization"].items() if key.endswith("Granted")):
        raise ResumeV6Error("candidate grants authority")
    return value


def safe_private(path: Path, expected_path: Path, expected_digest: str, context: str) -> dict[str, Any]:
    expect(path, expected_path, f"{context} path")
    if path.is_symlink() or not path.is_file() or (path.stat().st_mode & 0o777) != 0o600:
        raise ResumeV6Error(f"unsafe {context} evidence")
    expect(sha(path), expected_digest, f"{context} digest")
    return read(path)


def validate_cache_evidence(spec: dict[str, Any]):
    stale_binding = spec["cacheStaleEvidence"]
    stale = safe_private(Path(stale_binding["path"]), STALE_PATH, stale_binding["digest"], "stale network")
    expect((stale.get("kind"), stale.get("closureState"), stale.get("NetworkReady")), ("GO1LNetworkReadyEvidence", "FAIL-STALE-FUNCTIONAL-PATH", False), "stale result")
    expect((stale.get("fixedPodExecProbePerformed"), stale.get("persistentMutationPerformed")), (True, False), "stale boundary")
    timing_binding = spec["cacheTimingDiagnosticEvidence"]
    timing = safe_private(Path(timing_binding["path"]), TIMING_PATH, timing_binding["digest"], "timing diagnostic")
    expect((timing.get("kind"), timing.get("candidateDigest"), timing.get("result"), timing.get("probeExitCode")), ("GO1NetworkCacheTimingDiagnosticEvidence", "sha256:0322bc040bb8b364263492ddbbb2a8f22d0a2ade38c8bd79e720d5a7dce4dbe9", "PASS-CACHED-HEALTH-TIMING-OBSERVED", 0), "timing result")
    expect(timing.get("failedEvidenceDigest"), sha(STALE_PATH), "timing predecessor")
    expect((timing.get("persistentMutationPerformed"), timing.get("happyRunResumed")), (False, False), "timing boundary")
    expect((timing.get("rawProbeOutputRetained"), timing.get("nodeNamesRetained"), timing.get("ipAddressesRetained"), timing.get("rawStatusesRetained"), timing.get("secretPayloadRetained"), timing.get("workloadKubeconfigRemoved")), (False, False, False, False, False, True), "timing retention")
    details = timing.get("details", {})
    expect((details.get("pathCount"), details.get("statusCategoryCounts")), (8, {"success": 8, "failure": 0, "invalid": 0}), "timing paths")
    maximum = details.get("probeIntervalSeconds", 0) + 60 + 10
    if not 0 < details.get("probeIntervalSeconds", 0) <= 300 or details.get("maximumPathAgeSeconds", maximum + 1) > maximum:
        raise ResumeV6Error("timing evidence is outside dynamic source bound")
    return stale, timing


def adapt_grant(grant: dict[str, Any]) -> dict[str, Any]:
    value = deepcopy(grant)
    value["kind"] = "GO1HappyRunResumeGrantV5"
    value["spec"]["candidateDigest"] = V5_DIGEST
    return value


def validate_grant(candidate_path: Path, grant_path: Path, now: dt.datetime | None = None):
    validate_candidate(candidate_path)
    grant = read(grant_path)
    expect(grant.get("kind"), "GO1HappyRunResumeGrantV6", "grant kind")
    spec = grant["spec"]
    expect(spec.get("candidateDigest"), sha(candidate_path), "candidate digest")
    expect(spec.get("cacheFreshnessCandidateDigest"), FRESH_DIGEST, "freshness candidate")
    expect(spec.get("cacheFreshnessAmendmentGranted"), True, "freshness authority")
    stale, timing = validate_cache_evidence(spec)
    adapted = adapt_grant(grant)
    temporary = Path(f"/private/tmp/ok141-happy-resume-v6-validate-{spec.get('runID', 'invalid')}.json")
    if temporary.exists() or temporary.is_symlink():
        raise ResumeV6Error("adapted validation grant already exists")
    write_exclusive(temporary, adapted)
    try:
        validated = V5.validate_grant(V5_CANDIDATE, temporary, now)
    finally:
        temporary.unlink(missing_ok=True)
    return (*validated, stale, timing)


def execute(candidate_path: Path, grant_path: Path, capability_script: Path) -> dict[str, Any]:
    validated = validate_grant(candidate_path, grant_path)
    grant = read(grant_path)
    adapted = adapt_grant(grant)
    adapted_path = Path(f"/private/tmp/ok141-happy-resume-v6-adapted-{grant['spec']['runID']}.json")
    if adapted_path.exists() or adapted_path.is_symlink():
        raise ResumeV6Error("adapted execution grant already exists")
    write_exclusive(adapted_path, adapted)
    original_validate = V5.validate_grant
    original_evaluate = V5.STATUS.evaluate_probe
    original_output = V5.NEW_NETWORK_OUTPUT
    V5.validate_grant = lambda *_args, **_kwargs: validated[:-2]
    V5.STATUS.evaluate_probe = FRESH.evaluate_probe
    V5.NEW_NETWORK_OUTPUT = NEW_NETWORK_OUTPUT
    try:
        result = V5.execute(V5_CANDIDATE, adapted_path, capability_script)
    finally:
        V5.validate_grant = original_validate
        V5.STATUS.evaluate_probe = original_evaluate
        V5.NEW_NETWORK_OUTPUT = original_output
        adapted_path.unlink(missing_ok=True)
    result["candidateDigest"] = sha(candidate_path)
    result["cacheFreshnessCandidateDigest"] = FRESH_DIGEST
    result["cacheStaleEvidenceDigest"] = sha(STALE_PATH)
    result["cacheTimingDiagnosticEvidenceDigest"] = sha(TIMING_PATH)
    result["timingDiagnosticReexecuted"] = False
    return result


def plan(path: Path = CANDIDATE) -> dict[str, Any]:
    validate_candidate(path)
    return {"candidateDigest": sha(path), "supersedes": V5_DIGEST, "cacheFreshness": FRESH_DIGEST, "newNetworkOutput": str(NEW_NETWORK_OUTPUT), "authorization": "NO-GO", "clusterContacted": False, "mutationPerformed": False}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "verify-grant", "run"))
    parser.add_argument("--candidate", type=Path, default=CANDIDATE)
    parser.add_argument("--grant", type=Path)
    parser.add_argument("--capability-script", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "verify": print(json.dumps(plan(args.candidate.resolve()), indent=2, sort_keys=True))
        elif args.command == "verify-grant":
            if args.grant is None: raise ResumeV6Error("grant required")
            validate_grant(args.candidate.resolve(), args.grant.resolve()); print(sha(args.grant.resolve()))
        else:
            if not args.execute or args.grant is None or args.capability_script is None: raise ResumeV6Error("run requires --execute, grant and capability script")
            print(json.dumps(execute(args.candidate.resolve(), args.grant.resolve(), args.capability_script.resolve()), indent=2, sort_keys=True))
        return 0
    except Exception as error:
        print(f"ERROR: {type(error).__name__}: {error}", file=sys.stderr); return 2


if __name__ == "__main__": raise SystemExit(main())

