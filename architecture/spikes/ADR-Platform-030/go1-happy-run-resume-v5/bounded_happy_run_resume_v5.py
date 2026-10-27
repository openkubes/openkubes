#!/usr/bin/env python3
"""Resume OK-141 with the source-proven Cilium health status semantics."""

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
CANDIDATE = HERE / "happy-run-resume-candidate-v5.yaml"
V4_CANDIDATE = SPIKE / "go1-happy-run-resume-v4" / "happy-run-resume-candidate-v4.yaml"
V4_TOOL = SPIKE / "go1-happy-run-resume-v4" / "bounded_happy_run_resume_v4.py"
STATUS_CANDIDATE = SPIKE / "go1-network-status-semantics-v1" / "network-status-semantics-candidate-v1.yaml"
STATUS_TOOL = SPIKE / "go1-network-status-semantics-v1" / "network_status_semantics_v1.py"

V4_DIGEST = "sha256:003e31fe5e99ae76d463946c5b6412b792fbb4b8c948acc44ec485be8f8b6721"
V4_TOOL_DIGEST = "sha256:9af849bd30bea0d8defdaa4ab1d119802cf0deda685f5936e6c5d160a4e21c86"
STATUS_DIGEST = "sha256:d2ef66ab787d93fb486b170a7010ab221251b696e0a855e4a3a546764f5b797b"
STATUS_TOOL_DIGEST = "sha256:2e3fcf0a44a87ab50a775d52a13acd6abab301f762705b13299c353c9732a0c6"
LATEST_FAILED_PATH = Path("/private/tmp/ok141-go1-l-network-ready-observer-defaulting-v1-evidence.json")
DIAGNOSTIC_PATH = Path("/private/tmp/ok141-network-functional-diagnostic-v1-evidence.json")
NEW_NETWORK_OUTPUT = Path("/private/tmp/ok141-go1-l-network-ready-observer-status-v1-evidence.json")
NULL_DIGEST = "sha256:74234e98afe7498fb5daf1f36ac2d78acc339464f950703b8c019892f982b90b"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(value)
    return value


V4 = load_module("ok141_happy_resume_v4_for_v5", V4_TOOL)
STATUS = load_module("ok141_network_status_semantics_for_resume_v5", STATUS_TOOL)


class ResumeV5Error(ValueError):
    pass


def sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text())
    if not isinstance(value, dict):
        raise ResumeV5Error(f"expected mapping: {path}")
    return value


def expect(actual: Any, expected: Any, context: str) -> None:
    if actual != expected:
        raise ResumeV5Error(f"{context}: expected {expected!r}, got {actual!r}")


def write_exclusive(path: Path, value: dict[str, Any]) -> None:
    raw = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)


def validate_candidate(path: Path = CANDIDATE) -> dict[str, Any]:
    value = read(path)
    expect(value.get("kind"), "GO1HappyRunResumeCandidateV5", "kind")
    spec = value["spec"]
    expect(spec["version"], "ok141-go1-happy-run-resume/v5", "version")
    expect(spec["state"], "OFFLINE-PROVEN-BLOCKED-NO-GO", "state")
    expect(sha(V4_CANDIDATE), V4_DIGEST, "resume v4 candidate")
    expect(sha(V4_TOOL), V4_TOOL_DIGEST, "resume v4 tool")
    V4.validate_candidate(V4_CANDIDATE)
    expect(spec["supersedes"]["digest"], V4_DIGEST, "resume v4 binding")
    expect(sha(STATUS_CANDIDATE), STATUS_DIGEST, "status candidate")
    expect(sha(STATUS_TOOL), STATUS_TOOL_DIGEST, "status tool")
    STATUS.validate_candidate(STATUS_CANDIDATE)
    expect(spec["networkStatusSemantics"]["candidateDigest"], STATUS_DIGEST, "status binding")
    expect(spec["networkStatusSemantics"]["toolDigest"], STATUS_TOOL_DIGEST, "status tool binding")
    expect(spec["networkStatusSemantics"]["outputPath"], str(NEW_NETWORK_OUTPUT), "new output path")
    expect({key: item["path"] for key, item in spec["requiredPrivateEvidence"].items()}, {
        "failedNetwork": str(LATEST_FAILED_PATH),
        "functionalDiagnostic": str(DIAGNOSTIC_PATH),
    }, "private evidence paths")
    for key in ("preflightReexecutionAllowed", "g1ReexecutionAllowed", "remediationReexecutionAllowed", "lifecycleReexecutionAllowed", "g3ReexecutionAllowed"):
        expect(spec["resumeBoundary"][key], False, key)
    expect(sha(HERE / spec["tool"]["path"]), spec["tool"]["digest"], "tool digest")
    expect(spec["authorization"]["decision"], "NO-GO", "authorization")
    if any(item for key, item in spec["authorization"].items() if key.endswith("Granted")):
        raise ResumeV5Error("candidate grants authority")
    return value


def safe_private(path: Path, expected: Path, expected_digest: str, context: str) -> dict[str, Any]:
    expect(path, expected, f"{context} path")
    if path.is_symlink() or not path.is_file() or (path.stat().st_mode & 0o777) != 0o600:
        raise ResumeV5Error(f"unsafe {context} evidence")
    expect(sha(path), expected_digest, f"{context} digest")
    return read(path)


def validate_latest_evidence(spec: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    latest_binding = spec["latestFailedNetworkEvidence"]
    latest = safe_private(Path(latest_binding["path"]), LATEST_FAILED_PATH, latest_binding["digest"], "latest failed NetworkReady")
    expect((latest.get("kind"), latest.get("closureState"), latest.get("NetworkReady")), ("GO1LNetworkReadyEvidence", "FAIL-FUNCTIONAL-CONNECTIVITY", False), "latest result")
    expect((latest.get("fixedPodExecProbePerformed"), latest.get("persistentMutationPerformed")), (True, False), "latest boundary")
    pod = latest.get("details", {}).get("probePod", {})
    if not pod.get("name") or not pod.get("uid") or not latest.get("workloadTargetIdentityDigest"):
        raise ResumeV5Error("latest evidence lacks bound identities")

    diagnostic_binding = spec["functionalDiagnosticEvidence"]
    diagnostic = safe_private(Path(diagnostic_binding["path"]), DIAGNOSTIC_PATH, diagnostic_binding["digest"], "functional diagnostic")
    expect(
        (diagnostic.get("kind"), diagnostic.get("candidateDigest"), diagnostic.get("result"), diagnostic.get("probeExitCode")),
        (
            "GO1NetworkFunctionalDiagnosticEvidence",
            "sha256:449291425a457424aa68afbd42bf1c6046ddbfbd38703c74dd315e706f7a7c3b",
            "OBSERVED-FUNCTIONAL-CONNECTIVITY-FAILURE",
            0,
        ),
        "diagnostic identity",
    )
    expect(diagnostic.get("failedNetworkEvidenceDigest"), sha(LATEST_FAILED_PATH), "diagnostic predecessor")
    expect((diagnostic.get("podIdentityVerified"), diagnostic.get("probePod")), (True, pod), "diagnostic pod")
    expect((diagnostic.get("persistentMutationPerformed"), diagnostic.get("happyRunResumed")), (False, False), "diagnostic mutation boundary")
    expect((diagnostic.get("rawProbeOutputRetained"), diagnostic.get("secretPayloadRetained"), diagnostic.get("workloadKubeconfigRemoved")), (False, False, True), "diagnostic retention boundary")
    paths = diagnostic.get("details", {}).get("paths", [])
    expect(diagnostic.get("details", {}).get("pathCount"), 8, "diagnostic path count")
    if len(paths) != 8 or any(item.get("category") != "INVALID" or item.get("statusDigest") != NULL_DIGEST or not item.get("lastProbed") for item in paths):
        raise ResumeV5Error("diagnostic does not match the bound omitted-status finding")
    expected_paths = {
        (node, section, protocol)
        for node in latest.get("details", {}).get("nodeNames", [])
        for section in ("host", "health-endpoint")
        for protocol in ("http", "icmp")
    }
    actual_paths = {(item.get("node"), item.get("section"), item.get("protocol")) for item in paths}
    expect(actual_paths, expected_paths, "diagnostic path identities")
    try:
        for item in paths:
            STATUS.parse_time(item["lastProbed"])
    except (ValueError, STATUS.StatusSemanticsError) as error:
        raise ResumeV5Error("diagnostic contains invalid path timestamp") from error
    return latest, diagnostic


def adapt_grant(grant: dict[str, Any]) -> dict[str, Any]:
    value = deepcopy(grant)
    value["kind"] = "GO1HappyRunResumeGrantV4"
    value["spec"]["candidateDigest"] = V4_DIGEST
    return value


def validate_grant(candidate_path: Path, grant_path: Path, now: dt.datetime | None = None):
    validate_candidate(candidate_path)
    grant = read(grant_path)
    expect(grant.get("kind"), "GO1HappyRunResumeGrantV5", "grant kind")
    spec = grant["spec"]
    expect(spec.get("candidateDigest"), sha(candidate_path), "candidate digest")
    expect(spec.get("networkStatusSemanticsCandidateDigest"), STATUS_DIGEST, "status candidate")
    expect(spec.get("correctedNetworkObserverGranted"), True, "corrected observer authority")
    latest, diagnostic = validate_latest_evidence(spec)
    adapted = adapt_grant(grant)
    temporary = Path(f"/private/tmp/ok141-happy-resume-v5-validate-{spec.get('runID', 'invalid')}.json")
    if temporary.exists() or temporary.is_symlink():
        raise ResumeV5Error("adapted validation grant already exists")
    write_exclusive(temporary, adapted)
    try:
        outer, prior, preserved, remediation = V4.validate_grant(V4_CANDIDATE, temporary, now)
    finally:
        temporary.unlink(missing_ok=True)
    return outer, prior, preserved, remediation, latest, diagnostic


def execute(candidate_path: Path, grant_path: Path, capability_script: Path) -> dict[str, Any]:
    outer, _, _, _, latest, diagnostic = validate_grant(candidate_path, grant_path)
    adapted = adapt_grant(outer)
    adapted_path = Path(f"/private/tmp/ok141-happy-resume-v5-adapted-{outer['spec']['runID']}.json")
    if adapted_path.exists() or adapted_path.is_symlink():
        raise ResumeV5Error("adapted execution grant already exists")
    write_exclusive(adapted_path, adapted)

    network = V4.V3.HAPPY.NETWORK
    original_evaluate_probe = network.evaluate_probe
    original_amended_candidate = V4.V3.amended_network_candidate

    def amended_candidate(original: dict[str, Any]) -> dict[str, Any]:
        value = original_amended_candidate(original)
        value["spec"]["observation"]["outputPath"] = str(NEW_NETWORK_OUTPUT)
        return value

    network.evaluate_probe = STATUS.evaluate_probe
    V4.V3.amended_network_candidate = amended_candidate
    try:
        result = V4.execute(V4_CANDIDATE, adapted_path, capability_script)
    finally:
        network.evaluate_probe = original_evaluate_probe
        V4.V3.amended_network_candidate = original_amended_candidate
        adapted_path.unlink(missing_ok=True)
    result["candidateDigest"] = sha(candidate_path)
    result["networkStatusSemanticsCandidateDigest"] = STATUS_DIGEST
    result["latestFailedNetworkEvidenceDigest"] = sha(LATEST_FAILED_PATH)
    result["functionalDiagnosticEvidenceDigest"] = sha(DIAGNOSTIC_PATH)
    result["previousNetworkFailureReused"] = latest.get("closureState") == "FAIL-FUNCTIONAL-CONNECTIVITY"
    result["diagnosticReexecuted"] = False
    return result


def plan(path: Path = CANDIDATE) -> dict[str, Any]:
    value = validate_candidate(path)
    return {
        "candidateDigest": sha(path),
        "supersedes": V4_DIGEST,
        "networkStatusSemantics": STATUS_DIGEST,
        "newNetworkOutput": str(NEW_NETWORK_OUTPUT),
        "resumeBoundary": value["spec"]["resumeBoundary"]["startsAfter"],
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
                raise ResumeV5Error("grant required")
            validate_grant(args.candidate.resolve(), args.grant.resolve())
            print(sha(args.grant.resolve()))
        else:
            if not args.execute or args.grant is None or args.capability_script is None:
                raise ResumeV5Error("run requires --execute, grant and capability script")
            print(json.dumps(execute(args.candidate.resolve(), args.grant.resolve(), args.capability_script.resolve()), indent=2, sort_keys=True))
        return 0
    except Exception as error:
        print(f"ERROR: {type(error).__name__}: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
