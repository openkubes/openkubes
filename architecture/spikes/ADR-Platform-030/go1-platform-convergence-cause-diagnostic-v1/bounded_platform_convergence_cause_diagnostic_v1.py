#!/usr/bin/env python3
"""Classify Argo convergence causes without retaining raw messages."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Callable

import yaml


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
CANDIDATE = HERE / "platform-convergence-cause-diagnostic-candidate-v1.yaml"
V1_CANDIDATE = SPIKE / "go1-platform-convergence-diagnostic-v1" / "platform-convergence-diagnostic-candidate-v1.yaml"
V1_TOOL = SPIKE / "go1-platform-convergence-diagnostic-v1" / "bounded_platform_convergence_diagnostic_v1.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(value)
    return value


V1 = load_module("ok141_platform_diag_v1_for_cause", V1_TOOL)


class CauseDiagnosticError(ValueError):
    pass


def sha_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def sha(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def read(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text())
    if not isinstance(value, dict):
        raise CauseDiagnosticError(f"expected mapping: {path}")
    return value


def expect(actual: Any, expected: Any, context: str) -> None:
    if actual != expected:
        raise CauseDiagnosticError(f"{context}: expected {expected!r}, got {actual!r}")


def parse_time(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise CauseDiagnosticError("timestamp lacks timezone")
    return parsed.astimezone(dt.timezone.utc)


def safe_private(path: Path, expected_digest: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or (path.stat().st_mode & 0o777) != 0o600:
        raise CauseDiagnosticError("unsafe predecessor evidence")
    expect(sha(path), expected_digest, "predecessor evidence digest")
    return read(path)


def validate_candidate(path: Path = CANDIDATE) -> dict[str, Any]:
    value = read(path)
    expect(value.get("kind"), "GO1PlatformConvergenceCauseDiagnosticCandidate", "kind")
    spec = value["spec"]
    expect((spec["version"], spec["state"]), ("ok141-go1-platform-convergence-cause-diagnostic/v1", "OFFLINE-PROVEN-BLOCKED-NO-GO"), "candidate state")
    expect(sha(V1_CANDIDATE), spec["predecessor"]["candidate"]["digest"], "v1 candidate")
    V1.validate_candidate(V1_CANDIDATE)
    expect(spec["classification"]["rawMessagesRetained"], False, "message boundary")
    expect(sha(HERE / spec["tool"]["path"]), spec["tool"]["digest"], "tool digest")
    expect(spec["authorization"]["decision"], "NO-GO", "authorization")
    if any(item for key, item in spec["authorization"].items() if key.endswith("Granted")):
        raise CauseDiagnosticError("candidate grants authority")
    return value


TRUE = ("clusterContactGranted", "credentialUseGranted", "exactApplicationReadsGranted", "causeClassificationGranted")
FALSE = ("secretReadGranted", "podOrLogReadGranted", "targetClusterAccessGranted", "mutationGranted", "retryGranted", "rollbackOrCleanupGranted", "happyRunResumeGranted", "evidencePublicationGranted", "failureInjectionGranted")


def validate_predecessor(candidate: dict[str, Any]) -> dict[str, Any]:
    spec = candidate["spec"]["predecessor"]
    evidence = safe_private(Path(spec["privateEvidencePath"]), spec["privateEvidenceDigest"])
    expect((evidence.get("kind"), evidence.get("semanticDigest")), ("GO1PlatformConvergenceDiagnosticEvidence", spec["privateEvidenceSemanticDigest"]), "predecessor identity")
    expected = spec["result"]
    expect((evidence.get("readyCount"), evidence.get("allReady"), evidence.get("queryCount")), (expected["readyCount"], expected["allReady"], expected["queryCount"]), "predecessor result")
    expect((evidence.get("mutationPerformed"), evidence.get("retryPerformed"), evidence.get("happyRunResumed")), (False, False, False), "predecessor boundary")
    return evidence


def validate_grant(candidate_path: Path, grant_path: Path, now: dt.datetime | None = None) -> dict[str, Any]:
    candidate = validate_candidate(candidate_path)
    grant = read(grant_path)
    expect(grant.get("kind"), "GO1PlatformConvergenceCauseDiagnosticGrant", "grant kind")
    spec = grant["spec"]
    expect((spec.get("decision"), spec.get("authority"), spec.get("singleRun"), spec.get("consumed")), ("GO", "github:arashkaffamanesh", True, False), "grant identity")
    expect(spec.get("candidateDigest"), sha(candidate_path), "candidate digest")
    if any(spec.get(key) is not True for key in TRUE) or any(spec.get(key) is not False for key in FALSE):
        raise CauseDiagnosticError("grant authority is incomplete or overbroad")
    current = now or dt.datetime.now(dt.timezone.utc)
    issued, expires = parse_time(spec["issuedAt"]), parse_time(spec["expiresAt"])
    if not issued <= current <= expires or expires - issued > dt.timedelta(minutes=20):
        raise CauseDiagnosticError("grant inactive or exceeds 20 minutes")
    if not spec.get("grantID"):
        raise CauseDiagnosticError("grant ID missing")
    validate_predecessor(candidate)
    return grant


INDICATORS = {
    "TARGET-CONNECTION": ("failed to load live state", "failed to get cluster info", "connection refused", "i/o timeout", "context deadline exceeded", "no route to host", "network is unreachable", "dial tcp"),
    "TLS": ("x509:", "tls handshake", "certificate signed by unknown authority", "certificate is not valid"),
    "AUTHORIZATION": ("forbidden", "unauthorized", "permission denied", "authentication required"),
    "REPOSITORY": ("repository not found", "unable to resolve git revision", "failed to list refs", "git fetch", "repo server", "repository service"),
    "MANIFEST-GENERATION": ("failed to generate manifest", "manifest generation", "helm template", "path does not exist", "error converting yaml"),
    "CACHE": ("cache", "cached app", "redis"),
    "RPC": ("rpc error", "code = unknown", "code = unavailable", "code = deadlineexceeded"),
}


def classify(value: str) -> dict[str, Any]:
    lowered = value.lower()
    indicators = sorted(name for name, phrases in INDICATORS.items() if any(phrase in lowered for phrase in phrases))
    if not indicators:
        indicators = ["OTHER"]
    rpc_codes = sorted(set(re.findall(r"code\s*=\s*([A-Za-z]+)", value, flags=re.IGNORECASE)))
    return {"messageDigest": sha_bytes(value.encode()), "indicators": indicators, "rpcCodes": rpc_codes}


def application_causes(value: dict[str, Any], name: str, expected_revision: str) -> dict[str, Any]:
    expect(value.get("kind"), "Application", "Application kind")
    expect(value.get("metadata", {}).get("name"), name, "Application name")
    status = value.get("status", {})
    messages = []
    for condition in status.get("conditions", []) or []:
        messages.append({"source": "condition", "type": condition.get("type"), **classify(str(condition.get("message", "")))})
    operation = status.get("operationState", {}) or {}
    if operation.get("message"):
        messages.append({"source": "operation", "type": operation.get("phase"), **classify(str(operation["message"]))})
    observed = status.get("sync", {}).get("revision")
    return {"name": name, "observedRevision": observed, "revisionMatches": observed == expected_revision, "sync": status.get("sync", {}).get("status"), "health": status.get("health", {}).get("status"), "messages": messages}


def write_exclusive(path: Path, value: dict[str, Any]) -> None:
    raw = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)


def execute(candidate_path: Path, grant_path: Path, runner: Callable[..., Any] = subprocess.run) -> dict[str, Any]:
    candidate = validate_candidate(candidate_path)
    grant = validate_grant(candidate_path, grant_path)
    v1_spec = V1.validate_candidate(V1_CANDIDATE)["spec"]
    client, kubeconfig = Path(v1_spec["argo"]["clientPath"]), Path(v1_spec["argo"]["credentialPath"])
    if sha(client) != v1_spec["argo"]["clientDigest"]:
        raise CauseDiagnosticError("kubectl identity mismatch")
    if kubeconfig.is_symlink() or not kubeconfig.is_file() or (kubeconfig.stat().st_mode & 0o777) != 0o600:
        raise CauseDiagnosticError("unsafe ok-shared kubeconfig")
    expect(V1.EXECUTOR.inspect_identity(kubeconfig)["identityDigest"], v1_spec["argo"]["credentialIdentityDigest"], "ok-shared identity")
    output = Path(candidate["spec"]["outputPath"])
    if output.exists() or output.is_symlink():
        raise CauseDiagnosticError("exclusive cause diagnostic output already exists")
    applications = []
    for name in v1_spec["argo"]["applications"]:
        uri = f"/apis/argoproj.io/v1alpha1/namespaces/{v1_spec['argo']['namespace']}/applications/{name}"
        applications.append(application_causes(V1.raw_get(client, kubeconfig, uri, runner), name, v1_spec["argo"]["expectedRevision"]))
    counts = Counter(indicator for app in applications for message in app["messages"] for indicator in message["indicators"])
    common = sorted(indicator for indicator, count in counts.items() if count >= len(applications))
    evidence = {
        "apiVersion": "evidence.openkubes.io/v1alpha1", "kind": "GO1PlatformConvergenceCauseDiagnosticEvidence",
        "candidateDigest": sha(candidate_path), "grantID": grant["spec"]["grantID"],
        "predecessorEvidenceDigest": candidate["spec"]["predecessor"]["privateEvidenceDigest"],
        "applications": applications, "indicatorCounts": dict(sorted(counts.items())), "commonIndicators": common,
        "queryCount": 3, "rawMessagesRetained": False, "rawObjectsRetained": False,
        "secretReadPerformed": False, "podOrLogReadPerformed": False, "targetClusterContacted": False,
        "mutationPerformed": False, "retryPerformed": False, "happyRunResumed": False,
    }
    evidence["semanticDigest"] = sha_bytes(json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode())
    write_exclusive(output, evidence)
    return {"result": "PASS-READ-ONLY-CAUSE-DIAGNOSTIC", "outputPath": str(output), "outputDigest": sha(output), "commonIndicators": common}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "verify-grant", "diagnose"))
    parser.add_argument("--candidate", type=Path, default=CANDIDATE)
    parser.add_argument("--grant", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "verify":
            validate_candidate(args.candidate.resolve()); print(sha(args.candidate.resolve()))
        elif args.command == "verify-grant":
            if args.grant is None: raise CauseDiagnosticError("grant required")
            validate_grant(args.candidate.resolve(), args.grant.resolve()); print(sha(args.grant.resolve()))
        else:
            if args.grant is None or not args.execute: raise CauseDiagnosticError("diagnose requires grant and --execute")
            print(json.dumps(execute(args.candidate.resolve(), args.grant.resolve()), sort_keys=True))
        return 0
    except Exception as error:
        print(f"ERROR: {type(error).__name__}: {error}", file=sys.stderr); return 2


if __name__ == "__main__":
    raise SystemExit(main())
