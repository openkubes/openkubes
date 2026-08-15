#!/usr/bin/env python3
"""Exact, read-only Argo Application diagnostic for OK-141."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Callable

import yaml


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
CANDIDATE = HERE / "platform-convergence-diagnostic-candidate-v1.yaml"
RESUME_CANDIDATE = SPIKE / "go1-happy-run-resume-v7" / "happy-run-resume-candidate-v7.yaml"
EXECUTOR_TOOL = SPIKE / "go1-l-executor-v2" / "bounded_go1_l_executor_v2.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(value)
    return value


EXECUTOR = load_module("ok141_executor_for_platform_diagnostic", EXECUTOR_TOOL)


class DiagnosticError(ValueError):
    pass


def sha_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def sha(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def read(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text())
    if not isinstance(value, dict):
        raise DiagnosticError(f"expected mapping: {path}")
    return value


def expect(actual: Any, expected: Any, context: str) -> None:
    if actual != expected:
        raise DiagnosticError(f"{context}: expected {expected!r}, got {actual!r}")


def parse_time(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise DiagnosticError("timestamp lacks timezone")
    return parsed.astimezone(dt.timezone.utc)


def validate_candidate(path: Path = CANDIDATE) -> dict[str, Any]:
    value = read(path)
    expect(value.get("kind"), "GO1PlatformConvergenceDiagnosticCandidate", "kind")
    spec = value["spec"]
    expect((spec["version"], spec["state"]), ("ok141-go1-platform-convergence-diagnostic/v1", "OFFLINE-PROVEN-BLOCKED-NO-GO"), "candidate state")
    expect(sha(RESUME_CANDIDATE), spec["failedRun"]["resumeCandidate"]["digest"], "resume candidate")
    expect(spec["failedRun"]["retryAllowed"], False, "retry boundary")
    expect(len(spec["argo"]["applications"]), 3, "Application count")
    if len(set(spec["argo"]["applications"])) != 3:
        raise DiagnosticError("Application identities are not unique")
    expect(sha(HERE / spec["tool"]["path"]), spec["tool"]["digest"], "tool digest")
    expect(spec["authorization"]["decision"], "NO-GO", "authorization")
    if any(item for key, item in spec["authorization"].items() if key.endswith("Granted")):
        raise DiagnosticError("candidate grants authority")
    return value


TRUE = ("clusterContactGranted", "credentialUseGranted", "exactApplicationReadsGranted", "readOnlyDiagnosticGranted")
FALSE = ("secretReadGranted", "podOrLogReadGranted", "targetClusterAccessGranted", "mutationGranted", "retryGranted", "rollbackOrCleanupGranted", "happyRunResumeGranted", "evidencePublicationGranted", "failureInjectionGranted")


def validate_grant(candidate_path: Path, grant_path: Path, now: dt.datetime | None = None) -> dict[str, Any]:
    validate_candidate(candidate_path)
    grant = read(grant_path)
    expect(grant.get("kind"), "GO1PlatformConvergenceDiagnosticGrant", "grant kind")
    spec = grant["spec"]
    expect((spec.get("decision"), spec.get("authority"), spec.get("singleRun"), spec.get("consumed")), ("GO", "github:arashkaffamanesh", True, False), "grant identity")
    expect(spec.get("candidateDigest"), sha(candidate_path), "candidate digest")
    if any(spec.get(key) is not True for key in TRUE) or any(spec.get(key) is not False for key in FALSE):
        raise DiagnosticError("grant authority is incomplete or overbroad")
    current = now or dt.datetime.now(dt.timezone.utc)
    issued, expires = parse_time(spec["issuedAt"]), parse_time(spec["expiresAt"])
    if not issued <= current <= expires or expires - issued > dt.timedelta(minutes=20):
        raise DiagnosticError("grant inactive or exceeds 20 minutes")
    if not spec.get("grantID"):
        raise DiagnosticError("grant ID missing")
    return grant


def classify_message(value: str) -> str:
    lowered = value.lower()
    if any(item in lowered for item in ("forbidden", "unauthorized", "permission denied")):
        return "AUTHORIZATION"
    if any(item in lowered for item in ("manifest generation", "failed to load target state", "comparisonerror", "repository")):
        return "SOURCE-OR-RENDER"
    if any(item in lowered for item in ("sharedresourcewarning", "repeatedresourcewarning")):
        return "OWNERSHIP"
    if any(item in lowered for item in ("sync failed", "syncerror", "hookfailed")):
        return "SYNC"
    return "OTHER"


def summarize_application(value: dict[str, Any], expected_name: str, expected_revision: str) -> dict[str, Any]:
    expect(value.get("kind"), "Application", "Application kind")
    expect(value.get("metadata", {}).get("name"), expected_name, "Application name")
    spec, status = value.get("spec", {}), value.get("status", {})
    conditions = []
    for item in status.get("conditions", []) or []:
        message = str(item.get("message", ""))
        conditions.append({"type": item.get("type"), "lastTransitionTime": item.get("lastTransitionTime"), "messageCategory": classify_message(message), "messageDigest": sha_bytes(message.encode())})
    operation = status.get("operationState", {}) or {}
    operation_message = str(operation.get("message", ""))
    resources = Counter()
    for item in status.get("resources", []) or []:
        key = (str(item.get("group", "")), str(item.get("kind", "")), str(item.get("status", "Unknown")), str(item.get("health", {}).get("status", "Unknown")))
        resources[key] += 1
    resource_summary = [{"group": key[0], "kind": key[1], "sync": key[2], "health": key[3], "count": count} for key, count in sorted(resources.items())]
    desired = spec.get("source", {}).get("targetRevision")
    observed = status.get("sync", {}).get("revision")
    sync = status.get("sync", {}).get("status", "Unknown")
    health = status.get("health", {}).get("status", "Unknown")
    return {
        "name": expected_name, "desiredRevision": desired, "observedRevision": observed,
        "expectedRevision": expected_revision, "revisionMatches": observed == expected_revision,
        "sync": sync, "health": health, "ready": observed == expected_revision and sync == "Synced" and health == "Healthy",
        "reconciledAt": status.get("reconciledAt"), "conditions": conditions,
        "operation": {"phase": operation.get("phase"), "finishedAt": operation.get("finishedAt"), "messageCategory": classify_message(operation_message), "messageDigest": sha_bytes(operation_message.encode())},
        "resources": resource_summary,
    }


def raw_get(client: Path, kubeconfig: Path, uri: str, runner: Callable[..., Any]) -> dict[str, Any]:
    completed = runner([str(client), "--kubeconfig", str(kubeconfig), "get", "--raw", uri], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if completed.returncode != 0:
        raise DiagnosticError("bounded Application GET failed; output suppressed")
    value = json.loads(completed.stdout)
    if not isinstance(value, dict):
        raise DiagnosticError("bounded Application GET returned non-object")
    return value


def write_exclusive(path: Path, value: dict[str, Any]) -> None:
    raw = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)


def execute(candidate_path: Path, grant_path: Path, runner: Callable[..., Any] = subprocess.run) -> dict[str, Any]:
    candidate = validate_candidate(candidate_path)
    grant = validate_grant(candidate_path, grant_path)
    spec, grant_spec = candidate["spec"], grant["spec"]
    client, kubeconfig = Path(spec["argo"]["clientPath"]), Path(spec["argo"]["credentialPath"])
    if sha(client) != spec["argo"]["clientDigest"]:
        raise DiagnosticError("kubectl identity mismatch")
    if kubeconfig.is_symlink() or not kubeconfig.is_file() or (kubeconfig.stat().st_mode & 0o777) != 0o600:
        raise DiagnosticError("unsafe ok-shared kubeconfig")
    expect(EXECUTOR.inspect_identity(kubeconfig)["identityDigest"], spec["argo"]["credentialIdentityDigest"], "ok-shared identity")
    output = Path(spec["outputPath"])
    if output.exists() or output.is_symlink():
        raise DiagnosticError("exclusive diagnostic output already exists")
    applications = []
    for name in spec["argo"]["applications"]:
        uri = f"/apis/argoproj.io/v1alpha1/namespaces/{spec['argo']['namespace']}/applications/{name}"
        applications.append(summarize_application(raw_get(client, kubeconfig, uri, runner), name, spec["argo"]["expectedRevision"]))
    evidence = {
        "apiVersion": "evidence.openkubes.io/v1alpha1", "kind": "GO1PlatformConvergenceDiagnosticEvidence",
        "candidateDigest": sha(candidate_path), "grantID": grant_spec["grantID"],
        "failedResumeCandidateDigest": spec["failedRun"]["resumeCandidate"]["digest"],
        "applicationSubmissionEvidenceDigest": spec["failedRun"]["applicationSubmissionEvidenceDigest"],
        "applications": applications, "readyCount": sum(item["ready"] for item in applications),
        "allReady": all(item["ready"] for item in applications), "queryCount": 3,
        "rawObjectsRetained": False, "rawMessagesRetained": False, "secretReadPerformed": False,
        "podOrLogReadPerformed": False, "targetClusterContacted": False, "mutationPerformed": False,
        "retryPerformed": False, "happyRunResumed": False,
    }
    evidence["semanticDigest"] = sha_bytes(json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode())
    write_exclusive(output, evidence)
    return {"result": "PASS-READ-ONLY-DIAGNOSTIC", "outputPath": str(output), "outputDigest": sha(output), "readyCount": evidence["readyCount"], "allReady": evidence["allReady"]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "verify-grant", "diagnose"))
    parser.add_argument("--candidate", type=Path, default=CANDIDATE)
    parser.add_argument("--grant", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "verify":
            validate_candidate(args.candidate.resolve())
            print(sha(args.candidate.resolve()))
        elif args.command == "verify-grant":
            if args.grant is None:
                raise DiagnosticError("grant required")
            validate_grant(args.candidate.resolve(), args.grant.resolve())
            print(sha(args.grant.resolve()))
        else:
            if args.grant is None or not args.execute:
                raise DiagnosticError("diagnose requires grant and --execute")
            print(json.dumps(execute(args.candidate.resolve(), args.grant.resolve()), sort_keys=True))
        return 0
    except Exception as error:
        print(f"ERROR: {type(error).__name__}: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
