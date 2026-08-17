#!/usr/bin/env python3
"""Identify the failing exact GET in the OK-141 runtime-binding boundary."""

from __future__ import annotations

import argparse
import base64
import binascii
import datetime as dt
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

import yaml


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
CANDIDATE = HERE / "runtime-binding-diagnostic-candidate-v1.yaml"
RESUME_CANDIDATE = SPIKE / "go1-happy-run-resume-v6" / "happy-run-resume-candidate-v6.yaml"
BINDING_CANDIDATE = SPIKE / "go1-runtime-binding-v2" / "runtime-binding-candidate-v2.yaml"
BINDING_TOOL = SPIKE / "go1-runtime-binding-v2" / "bounded_runtime_binding_v2.py"
OUTPUT = Path("/private/tmp/ok141-runtime-binding-diagnostic-v1-evidence.json")
EPHEMERAL = Path("/private/tmp/ok141-runtime-binding-diagnostic-v1-kubeconfig.yaml")
NETWORK_EVIDENCE = Path("/private/tmp/ok141-go1-l-network-ready-observer-cache-freshness-v1-evidence.json")


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


BINDING = load_module("ok141_runtime_binding_for_diagnostic", BINDING_TOOL)


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


def write_exclusive(path: Path, value: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(value)


def validate_candidate(path: Path = CANDIDATE) -> dict[str, Any]:
    value = read(path)
    expect(value.get("kind"), "GO1RuntimeBindingDiagnosticCandidate", "kind")
    spec = value["spec"]
    expect(spec["version"], "ok141-runtime-binding-diagnostic/v1", "version")
    expect(spec["state"], "OFFLINE-PROVEN-BLOCKED-NO-GO", "state")
    predecessor = spec["predecessor"]
    expect(sha(RESUME_CANDIDATE), predecessor["resumeCandidateDigest"], "resume candidate")
    expect(sha(BINDING_CANDIDATE), predecessor["runtimeBindingCandidateDigest"], "binding candidate")
    binding = BINDING.validate_candidate(BINDING_CANDIDATE)["spec"]
    expect(spec["exactReads"], {
        "managementSecret": binding["management"]["secretRawURI"],
        "workloadKubeSystem": binding["workload"]["queries"]["kubeSystem"],
        "workloadLocalPath": binding["workload"]["queries"]["localPath"],
    }, "exact read boundary")
    expect(spec["output"]["path"], str(OUTPUT), "output")
    expect(sha(HERE / spec["tool"]["path"]), spec["tool"]["digest"], "tool digest")
    expect(spec["authorization"]["decision"], "NO-GO", "authorization")
    if any(item for key, item in spec["authorization"].items() if key.endswith("Granted")):
        raise DiagnosticError("candidate grants authority")
    return value


TRUE = (
    "clusterContactGranted", "managementCredentialUseGranted", "exactSecretReadGranted",
    "ephemeralCredentialMaterializationGranted", "workloadCredentialUseGranted",
    "exactKubeSystemReadGranted", "exactLocalPathReadGranted",
)
FALSE = (
    "happyRunResumeGranted", "storageInstallationGranted", "persistentMutationGranted",
    "retryGranted", "rollbackOrCleanupGranted", "evidencePublicationGranted",
    "failureInjectionGranted",
)


def validate_network_evidence(grant_spec: dict[str, Any]) -> dict[str, Any]:
    path = Path(grant_spec["networkReadyEvidencePath"])
    expect(path, NETWORK_EVIDENCE, "network evidence path")
    if path.is_symlink() or not path.is_file() or (path.stat().st_mode & 0o777) != 0o600:
        raise DiagnosticError("unsafe network evidence")
    expect(sha(path), grant_spec["networkReadyEvidenceDigest"], "network evidence digest")
    value = read(path)
    expect((value.get("kind"), value.get("closureState"), value.get("NetworkReady")), ("GO1LNetworkReadyEvidence", "PASS-NETWORK-READY", True), "network result")
    expect(value.get("workloadTargetIdentityDigest"), grant_spec["workloadTargetIdentityDigest"], "target identity")
    return value


def validate_grant(candidate_path: Path, grant_path: Path, now: dt.datetime | None = None):
    validate_candidate(candidate_path)
    grant = read(grant_path)
    expect(grant.get("kind"), "GO1RuntimeBindingDiagnosticGrant", "grant kind")
    spec = grant["spec"]
    expect((spec.get("decision"), spec.get("authority"), spec.get("singleRun"), spec.get("consumed")), ("GO", "github:arashkaffamanesh", True, False), "grant identity")
    expect(spec.get("candidateDigest"), sha(candidate_path), "candidate digest")
    if any(spec.get(key) is not True for key in TRUE) or any(spec.get(key) is not False for key in FALSE):
        raise DiagnosticError("diagnostic authority incomplete or overbroad")
    current = now or dt.datetime.now(dt.timezone.utc)
    issued, expires = parse_time(spec["issuedAt"]), parse_time(spec["expiresAt"])
    if not issued <= current <= expires or expires - issued > dt.timedelta(minutes=15):
        raise DiagnosticError("grant inactive or exceeds 15 minutes")
    return grant, validate_network_evidence(spec)


def query(client: Path, kubeconfig: Path, uri: str, runner: Callable[..., Any]) -> tuple[dict[str, Any], bytes | None]:
    completed = runner([str(client), "--kubeconfig", str(kubeconfig), "get", "--raw", uri], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    result = {
        "exitCode": completed.returncode,
        "stdoutDigest": sha_bytes(completed.stdout),
        "stderrDigest": sha_bytes(completed.stderr),
    }
    if completed.returncode != 0:
        result["category"] = "NOT-FOUND" if completed.returncode == 1 and b"NotFound" in completed.stderr else "GET-FAILED"
        return result, None
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError:
        result["category"] = "INVALID-JSON"
        return result, None
    if not isinstance(value, dict):
        result["category"] = "NON-OBJECT"
        return result, None
    result["category"] = "PASS-OBJECT"
    return result, completed.stdout


def execute(candidate_path: Path, grant_path: Path, runner: Callable[..., Any] = subprocess.run) -> dict[str, Any]:
    candidate = validate_candidate(candidate_path)
    grant, network = validate_grant(candidate_path, grant_path)
    spec = candidate["spec"]
    binding = BINDING.validate_candidate(BINDING_CANDIDATE)["spec"]
    if OUTPUT.exists() or EPHEMERAL.exists():
        raise DiagnosticError("exclusive diagnostic path already exists")
    management_client = Path(binding["management"]["clientPath"])
    workload_client = Path(binding["workload"]["clientPath"])
    for path, expected in ((management_client, binding["management"]["clientDigest"]), (workload_client, binding["workload"]["clientDigest"])):
        expect(sha(path), expected, "client digest")
    management_kubeconfig = Path(binding["management"]["credentialPath"])
    if management_kubeconfig.is_symlink() or not management_kubeconfig.is_file() or (management_kubeconfig.stat().st_mode & 0o777) != 0o600:
        raise DiagnosticError("unsafe management kubeconfig")
    expect(BINDING.EXECUTOR.inspect_identity(management_kubeconfig)["identityDigest"], binding["management"]["credentialIdentityDigest"], "management identity")

    stages: dict[str, Any] = {}
    secret_result, secret_raw = query(management_client, management_kubeconfig, spec["exactReads"]["managementSecret"], runner)
    stages["managementSecret"] = secret_result
    identity_validated = False
    if secret_result["category"] == "PASS-OBJECT" and secret_raw is not None:
        try:
            secret = json.loads(secret_raw)
            kubeconfig_raw = base64.b64decode(secret["data"]["value"], validate=True)
            write_exclusive(EPHEMERAL, kubeconfig_raw)
            identity = BINDING.EXECUTOR.inspect_identity(EPHEMERAL)
            expect(identity["identityDigest"], grant["spec"]["workloadTargetIdentityDigest"], "workload identity")
            identity_validated = True
            for stage, key in (("workloadKubeSystem", "workloadKubeSystem"), ("workloadLocalPath", "workloadLocalPath")):
                result, _ = query(workload_client, EPHEMERAL, spec["exactReads"][key], runner)
                stages[stage] = result
        except (KeyError, TypeError, ValueError, binascii.Error):
            stages["secretMaterialization"] = {"category": "INVALID-SECRET-PAYLOAD"}
        finally:
            EPHEMERAL.unlink(missing_ok=True)
    result_categories = {key: item["category"] for key, item in stages.items() if "category" in item}
    if result_categories == {"managementSecret": "PASS-OBJECT", "workloadKubeSystem": "PASS-OBJECT", "workloadLocalPath": "NOT-FOUND"} and identity_validated:
        finding = "LOCAL-PATH-ABSENT"
    elif result_categories == {"managementSecret": "PASS-OBJECT", "workloadKubeSystem": "PASS-OBJECT", "workloadLocalPath": "PASS-OBJECT"} and identity_validated:
        finding = "ALL-READS-PASS-NONREPRODUCED"
    else:
        finding = "OTHER-BOUNDED-READ-FAILURE"
    evidence = {
        "apiVersion": "evidence.openkubes.io/v1alpha1",
        "kind": "GO1RuntimeBindingDiagnosticEvidence",
        "candidateDigest": sha(candidate_path),
        "grantID": grant["spec"]["grantID"],
        "networkReadyEvidenceDigest": sha(NETWORK_EVIDENCE),
        "workloadTargetIdentityDigest": network["workloadTargetIdentityDigest"],
        "finding": finding,
        "stages": stages,
        "workloadIdentityValidated": identity_validated,
        "ephemeralKubeconfigRemoved": not EPHEMERAL.exists(),
        "secretPayloadRetained": False,
        "rawObjectPayloadRetained": False,
        "rawErrorTextRetained": False,
        "persistentMutationPerformed": False,
        "happyRunResumed": False,
    }
    write_exclusive(OUTPUT, (json.dumps(evidence, sort_keys=True, separators=(",", ":")) + "\n").encode())
    return {"finding": finding, "outputPath": str(OUTPUT), "persistentMutationPerformed": False, "happyRunResumed": False}


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
                raise DiagnosticError("grant is required")
            validate_grant(args.candidate.resolve(), args.grant.resolve())
            print(sha(args.grant.resolve()))
        else:
            if args.grant is None or not args.execute:
                raise DiagnosticError("diagnose requires --grant and --execute")
            print(json.dumps(execute(args.candidate.resolve(), args.grant.resolve()), sort_keys=True))
        return 0
    except (DiagnosticError, OSError, KeyError, TypeError, ValueError, yaml.YAMLError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
