#!/usr/bin/env python3
"""Resume exactly the failed OK-141 Runtime Binding stage after storage closure."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any

import yaml


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
CANDIDATE = HERE / "runtime-binding-resume-candidate-v1.yaml"
BINDING_CANDIDATE = SPIKE / "go1-runtime-binding-v2" / "runtime-binding-candidate-v2.yaml"
BINDING_TOOL = SPIKE / "go1-runtime-binding-v2" / "bounded_runtime_binding_v2.py"
DIAGNOSTIC_CANDIDATE = SPIKE / "go1-runtime-binding-diagnostic-v1" / "runtime-binding-diagnostic-candidate-v1.yaml"
STORAGE_CANDIDATE = SPIKE / "go1-local-path-prerequisite-v1" / "local-path-prerequisite-candidate-v1.yaml"
LIFECYCLE = Path("/private/tmp/ok141-go1-l-lifecycle-api-observer-v1-evidence.json")
NETWORK = Path("/private/tmp/ok141-go1-l-network-ready-observer-cache-freshness-v1-evidence.json")
STORAGE = Path("/private/tmp/ok141-local-path-prerequisite-v1-evidence.json")
ADAPTED = Path("/private/tmp/ok141-runtime-binding-resume-v1-adapted-grant.json")


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


BINDING = load_module("ok141_runtime_binding_for_resume", BINDING_TOOL)


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
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ResumeError("timestamp lacks timezone")
    return parsed.astimezone(dt.timezone.utc)


def write_exclusive(path: Path, value: dict[str, Any]) -> None:
    raw = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)


def safe(path: Path, expected: str, context: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or (path.stat().st_mode & 0o777) != 0o600:
        raise ResumeError(f"unsafe {context}")
    expect(sha(path), expected, f"{context} digest")
    return read(path)


def validate_candidate(path: Path = CANDIDATE) -> dict[str, Any]:
    value = read(path)
    expect(value.get("kind"), "GO1RuntimeBindingResumeCandidate", "kind")
    spec = value["spec"]
    expect((spec["version"], spec["state"]), ("ok141-runtime-binding-resume/v1", "OFFLINE-PROVEN-BLOCKED-NO-GO"), "state")
    expect(sha(BINDING_CANDIDATE), spec["predecessor"]["runtimeBindingCandidateDigest"], "binding candidate")
    expect(sha(DIAGNOSTIC_CANDIDATE), spec["predecessor"]["diagnosticCandidateDigest"], "diagnostic candidate")
    expect(sha(STORAGE_CANDIDATE), spec["predecessor"]["storageCandidateDigest"], "storage candidate")
    BINDING.validate_candidate(BINDING_CANDIDATE)
    expect(sha(HERE / spec["tool"]["path"]), spec["tool"]["digest"], "tool digest")
    expect(spec["authorization"]["decision"], "NO-GO", "authorization")
    if any(item for key, item in spec["authorization"].items() if key.endswith("Granted")):
        raise ResumeError("candidate grants authority")
    return value


TRUE = ("clusterContactGranted", "credentialUseGranted", "secretReadGranted", "ephemeralMaterializationGranted", "readOnlyQueriesGranted", "runtimeBindingResumeGranted", "retryOfFailedBindingGranted")
FALSE = ("persistentMutationGranted", "targetAccessGranted", "tokenRequestGranted", "registrationGranted", "platformSubmissionGranted", "happyRunResumeGranted", "cleanupGranted", "evidencePublicationGranted", "failureInjectionGranted")


def validate_grant(candidate_path: Path, grant_path: Path, now: dt.datetime | None = None):
    validate_candidate(candidate_path)
    grant = read(grant_path)
    expect(grant.get("kind"), "GO1RuntimeBindingResumeGrant", "grant kind")
    spec = grant["spec"]
    expect((spec.get("decision"), spec.get("authority"), spec.get("singleRun"), spec.get("consumed")), ("GO", "github:arashkaffamanesh", True, False), "grant identity")
    expect(spec.get("candidateDigest"), sha(candidate_path), "candidate digest")
    if any(spec.get(key) is not True for key in TRUE) or any(spec.get(key) is not False for key in FALSE):
        raise ResumeError("grant incomplete or overbroad")
    current = now or dt.datetime.now(dt.timezone.utc)
    issued, expires = parse_time(spec["issuedAt"]), parse_time(spec["expiresAt"])
    if not issued <= current <= expires or expires - issued > dt.timedelta(minutes=15):
        raise ResumeError("grant inactive or exceeds 15 minutes")
    lifecycle = safe(LIFECYCLE, spec["lifecycleEvidenceDigest"], "lifecycle evidence")
    network = safe(NETWORK, spec["networkReadyEvidenceDigest"], "NetworkReady evidence")
    storage = safe(STORAGE, spec["storageEvidenceDigest"], "storage evidence")
    expect((lifecycle.get("kind"), lifecycle.get("closureState")), ("GO1LLifecycleAPIEvidence", "PASS-CURRENT-LIFECYCLE-API-EVIDENCE"), "lifecycle result")
    expect((network.get("kind"), network.get("closureState"), network.get("NetworkReady")), ("GO1LNetworkReadyEvidence", "PASS-NETWORK-READY", True), "network result")
    expect(network.get("lifecycleEvidenceDigest"), sha(LIFECYCLE), "network/lifecycle correlation")
    expect((storage.get("kind"), storage.get("result"), len(storage.get("created", []))), ("GO1LocalPathPrerequisiteEvidence", "SUCCESS-STORAGE-PREREQUISITE-READY", 9), "storage result")
    expect(storage.get("workloadTargetIdentityDigest"), network.get("workloadTargetIdentityDigest"), "storage/network target")
    return grant, lifecycle, network, storage


def adapted_grant(candidate_path: Path, grant: dict[str, Any]) -> dict[str, Any]:
    binding = BINDING.validate_candidate(BINDING_CANDIDATE)["spec"]
    outer = grant["spec"]
    return {
        "apiVersion": "authorization.openkubes.io/v1alpha1", "kind": "GO1RuntimeBindingGrant",
        "spec": {
            "decision": "GO", "authority": outer["authority"], "candidateDigest": sha(BINDING_CANDIDATE),
            "protocolDigest": binding["protocol"]["digest"], "grantID": outer["grantID"] + "/BIND",
            "singleRun": True, "consumed": False, "issuedAt": outer["issuedAt"], "expiresAt": outer["expiresAt"],
            "lifecycleEvidenceDigest": outer["lifecycleEvidenceDigest"], "networkEvidenceDigest": outer["networkReadyEvidenceDigest"],
            "clusterContactGranted": True, "credentialUseGranted": True, "secretReadGranted": True,
            "ephemeralMaterializationGranted": True, "readOnlyQueriesGranted": True,
            "persistentMutationGranted": False, "registrationGranted": False, "platformSubmissionGranted": False,
            "go1Granted": False, "retryGranted": False, "cleanupGranted": False,
        },
    }


def execute(candidate_path: Path, grant_path: Path) -> dict[str, Any]:
    grant, _, _, storage = validate_grant(candidate_path, grant_path)
    if ADAPTED.exists() or Path(BINDING.validate_candidate(BINDING_CANDIDATE)["spec"]["outputPath"]).exists():
        raise ResumeError("exclusive Runtime Binding path already exists")
    write_exclusive(ADAPTED, adapted_grant(candidate_path, grant))
    binding_spec = BINDING.validate_candidate(BINDING_CANDIDATE)["spec"]
    try:
        result = BINDING.execute(BINDING_CANDIDATE, ADAPTED, LIFECYCLE, NETWORK, Path(binding_spec["management"]["clientPath"]), Path(binding_spec["workload"]["clientPath"]))
    finally:
        ADAPTED.unlink(missing_ok=True)
    result["resumeCandidateDigest"] = sha(candidate_path)
    result["storageEvidenceDigest"] = sha(STORAGE)
    result["storageResult"] = storage["result"]
    result["platformMutationPerformed"] = False
    result["happyRunResumed"] = False
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "verify-grant", "resume"))
    parser.add_argument("--candidate", type=Path, default=CANDIDATE)
    parser.add_argument("--grant", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "verify":
            validate_candidate(args.candidate.resolve()); print(sha(args.candidate.resolve()))
        elif args.command == "verify-grant":
            if args.grant is None: raise ResumeError("grant required")
            validate_grant(args.candidate.resolve(), args.grant.resolve()); print(sha(args.grant.resolve()))
        else:
            if args.grant is None or not args.execute: raise ResumeError("resume requires grant and --execute")
            print(json.dumps(execute(args.candidate.resolve(), args.grant.resolve()), sort_keys=True))
        return 0
    except (ResumeError, OSError, KeyError, TypeError, ValueError, yaml.YAMLError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr); return 2


if __name__ == "__main__":
    raise SystemExit(main())
