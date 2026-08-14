#!/usr/bin/env python3
"""Poll exactly three bound Argo Applications after credential remediation."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

import yaml


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
CANDIDATE = HERE / "post-remediation-platform-observer-candidate-v1.yaml"
DIAG_DIR = SPIKE / "go1-platform-convergence-diagnostic-v1"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(value)
    return value


DIAG = load_module("ok141_platform_diag_for_post_remediation", DIAG_DIR / "bounded_platform_convergence_diagnostic_v1.py")


class ObserverError(ValueError):
    pass


def sha_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def sha(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def read(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text())
    if not isinstance(value, dict):
        raise ObserverError(f"expected mapping: {path}")
    return value


def expect(actual: Any, expected: Any, context: str) -> None:
    if actual != expected:
        raise ObserverError(f"{context}: expected {expected!r}, got {actual!r}")


TRUE = ("sharedClusterContactGranted", "sharedCredentialUseGranted", "exactApplicationReadsGranted", "boundedPollingGranted")
FALSE = ("secretOrTargetReadGranted", "mutationGranted", "capabilityTestGranted", "retryGranted", "cleanupGranted", "evidencePublicationGranted", "failureInjectionGranted")


def parse_time(value: str | dt.datetime) -> dt.datetime:
    parsed = value if isinstance(value, dt.datetime) else dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ObserverError("timestamp lacks timezone")
    return parsed.astimezone(dt.timezone.utc)


def validate_candidate(path: Path = CANDIDATE) -> dict[str, Any]:
    value = read(path); spec = value["spec"]
    expect(value.get("kind"), "GO1PostRemediationPlatformObserverCandidate", "kind")
    expect((spec["version"], spec["state"]), ("ok141-go1-post-remediation-platform-observer/v1", "OFFLINE-PROVEN-BLOCKED-NO-GO"), "state")
    evidence = DIAG.read(Path(spec["remediation"]["privateEvidencePath"]))
    if Path(spec["remediation"]["privateEvidencePath"]).is_symlink() or (Path(spec["remediation"]["privateEvidencePath"]).stat().st_mode & 0o777) != 0o600:
        raise ObserverError("unsafe remediation evidence")
    expect(sha(Path(spec["remediation"]["privateEvidencePath"])), spec["remediation"]["privateEvidenceDigest"], "remediation evidence")
    expect((evidence.get("kind"), evidence.get("semanticDigest"), evidence.get("secretReplaced")), ("GO1RegistrationAudienceRemediationEvidence", spec["remediation"]["privateEvidenceSemanticDigest"], True), "remediation result")
    expect((len(spec["argo"]["applications"]), spec["observation"]), (3, {"intervalSeconds": 15, "maxIterations": 40}), "bounded observation")
    expect(sha(HERE / spec["tool"]["path"]), spec["tool"]["digest"], "tool digest")
    expect(spec["authorization"]["decision"], "NO-GO", "authorization")
    if any(item for key, item in spec["authorization"].items() if key.endswith("Granted")):
        raise ObserverError("candidate grants authority")
    return value


def validate_grant(candidate_path: Path, grant_path: Path, now: dt.datetime | None = None) -> dict[str, Any]:
    validate_candidate(candidate_path); grant = read(grant_path); spec = grant["spec"]
    expect(grant.get("kind"), "GO1PostRemediationPlatformObserverGrant", "grant kind")
    expect((spec.get("decision"), spec.get("authority"), spec.get("singleRun"), spec.get("consumed")), ("GO", "github:arashkaffamanesh", True, False), "grant identity")
    expect(spec.get("candidateDigest"), sha(candidate_path), "candidate digest")
    if any(spec.get(key) is not True for key in TRUE) or any(spec.get(key) is not False for key in FALSE):
        raise ObserverError("grant authority incomplete or overbroad")
    current = now or dt.datetime.now(dt.timezone.utc); issued, expires = parse_time(spec["issuedAt"]), parse_time(spec["expiresAt"])
    if not issued <= current <= expires or expires - issued > dt.timedelta(minutes=15):
        raise ObserverError("grant inactive or exceeds 15 minutes")
    return grant


def write_exclusive(path: Path, value: dict[str, Any]) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump(value, stream, sort_keys=True, separators=(",", ":")); stream.write("\n")


def execute(candidate_path: Path, grant_path: Path, runner: Callable[..., Any] = subprocess.run, sleeper: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    candidate = validate_candidate(candidate_path); grant = validate_grant(candidate_path, grant_path); spec = candidate["spec"]
    client, kubeconfig = Path(spec["argo"]["clientPath"]), Path(spec["argo"]["credentialPath"])
    expect(sha(client), spec["argo"]["clientDigest"], "client")
    if kubeconfig.is_symlink() or not kubeconfig.is_file() or (kubeconfig.stat().st_mode & 0o777) != 0o600:
        raise ObserverError("unsafe shared Kubeconfig")
    expect(DIAG.EXECUTOR.inspect_identity(kubeconfig)["identityDigest"], spec["argo"]["credentialIdentityDigest"], "shared identity")
    output = Path(spec["outputPath"])
    if output.exists() or output.is_symlink(): raise ObserverError("exclusive output already exists")
    final: list[dict[str, Any]] = []; history: list[int] = []
    for iteration in range(1, spec["observation"]["maxIterations"] + 1):
        current = []
        for name in spec["argo"]["applications"]:
            uri = f"/apis/argoproj.io/v1alpha1/namespaces/{spec['argo']['namespace']}/applications/{name}"
            current.append(DIAG.summarize_application(DIAG.raw_get(client, kubeconfig, uri, runner), name, spec["argo"]["expectedRevision"]))
        final = current; history.append(sum(item["ready"] for item in current))
        if all(item["ready"] for item in current): break
        if iteration < spec["observation"]["maxIterations"]: sleeper(spec["observation"]["intervalSeconds"])
    evidence = {"apiVersion": "evidence.openkubes.io/v1alpha1", "kind": "GO1PostRemediationPlatformObserverEvidence", "candidateDigest": sha(candidate_path), "grantID": grant["spec"]["grantID"], "applications": final, "readyCount": sum(item["ready"] for item in final), "allReady": all(item["ready"] for item in final), "iterations": len(history), "readyCountHistory": history, "queryCount": len(history) * 3, "secretOrTargetReadPerformed": False, "mutationPerformed": False, "capabilityTestPerformed": False, "retryPerformed": False, "cleanupPerformed": False, "rawObjectsRetained": False, "rawMessagesRetained": False}
    evidence["semanticDigest"] = sha_bytes(json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode())
    write_exclusive(output, evidence)
    return {"result": "PASS-POST-REMEDIATION-PLATFORM-OBSERVATION", "allReady": evidence["allReady"], "readyCount": evidence["readyCount"], "iterations": evidence["iterations"], "outputPath": str(output), "outputDigest": sha(output)}


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("command", choices=("verify", "verify-grant", "observe")); parser.add_argument("--candidate", type=Path, default=CANDIDATE); parser.add_argument("--grant", type=Path); parser.add_argument("--execute", action="store_true"); args = parser.parse_args()
    try:
        if args.command == "verify": validate_candidate(args.candidate.resolve()); print(sha(args.candidate.resolve()))
        elif args.command == "verify-grant":
            if args.grant is None: raise ObserverError("grant required")
            validate_grant(args.candidate.resolve(), args.grant.resolve()); print(sha(args.grant.resolve()))
        else:
            if args.grant is None or not args.execute: raise ObserverError("observe requires grant and --execute")
            print(json.dumps(execute(args.candidate.resolve(), args.grant.resolve()), sort_keys=True))
        return 0
    except Exception as error:
        print(f"ERROR: {type(error).__name__}: {error}", file=sys.stderr); return 2


if __name__ == "__main__": raise SystemExit(main())
