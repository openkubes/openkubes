#!/usr/bin/env python3
"""Test the Kubernetes API server's default service-account audience once."""

from __future__ import annotations

import argparse
import base64
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
CANDIDATE = HERE / "default-audience-diagnostic-candidate-v1.yaml"
CAUSE_DIR = SPIKE / "go1-target-access-cause-diagnostic-v1"
CAUSE_CANDIDATE = CAUSE_DIR / "target-access-cause-diagnostic-candidate-v1.yaml"
CAUSE_EVIDENCE = Path("/private/tmp/ok141-target-access-cause-diagnostic-v1-evidence.json")


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(value)
    return value


CAUSE = load_module("ok141_target_cause_for_default_audience", CAUSE_DIR / "bounded_target_access_cause_diagnostic_v1.py")
REG = CAUSE.REG


class DefaultAudienceError(ValueError):
    pass


def sha_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def sha(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def read(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text())
    if not isinstance(value, dict):
        raise DefaultAudienceError(f"expected mapping: {path}")
    return value


def expect(actual: Any, expected: Any, context: str) -> None:
    if actual != expected:
        raise DefaultAudienceError(f"{context}: expected {expected!r}, got {actual!r}")


def parse_time(value: str | dt.datetime) -> dt.datetime:
    parsed = value if isinstance(value, dt.datetime) else dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise DefaultAudienceError("timestamp lacks timezone")
    return parsed.astimezone(dt.timezone.utc)


def safe_private(path: Path, expected: str, context: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or (path.stat().st_mode & 0o777) != 0o600:
        raise DefaultAudienceError(f"unsafe {context}")
    expect(sha(path), expected, f"{context} digest")
    return read(path)


def validate_candidate(path: Path = CANDIDATE) -> dict[str, Any]:
    value = read(path)
    expect(value.get("kind"), "GO1DefaultAudienceDiagnosticCandidate", "kind")
    spec = value["spec"]
    expect((spec["version"], spec["state"]), ("ok141-go1-default-audience-diagnostic/v1", "OFFLINE-PROVEN-BLOCKED-NO-GO"), "candidate state")
    expect(sha(CAUSE_CANDIDATE), spec["predecessor"]["candidate"]["digest"], "cause candidate")
    CAUSE.validate_candidate(CAUSE_CANDIDATE)
    expect(spec["target"]["requestedAudiences"], [], "default audience request")
    expect(spec["target"]["expirationSeconds"], 600, "token lifetime")
    expect(sha(HERE / spec["tool"]["path"]), spec["tool"]["digest"], "tool digest")
    expect(spec["authorization"]["decision"], "NO-GO", "authorization")
    if any(item for key, item in spec["authorization"].items() if key.endswith("Granted")):
        raise DefaultAudienceError("candidate grants authority")
    return value


TRUE = (
    "managementClusterContactGranted", "managementCredentialUseGranted",
    "exactWorkloadKubeconfigSecretReadGranted", "ephemeralAdminKubeconfigGranted",
    "targetAdminCredentialUseGranted", "exactTokenRequestGranted",
    "defaultAudienceSelectionGranted", "ephemeralTokenKubeconfigGranted",
    "exactTargetNamespaceGetGranted", "responseClassificationGranted",
)
FALSE = (
    "persistentMutationGranted", "podOrLogReadGranted", "retryGranted",
    "rollbackOrCleanupGranted", "happyRunResumeGranted",
    "evidencePublicationGranted", "failureInjectionGranted",
)


def validate_predecessors(candidate: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    spec = candidate["spec"]
    cause = safe_private(CAUSE_EVIDENCE, spec["predecessor"]["privateEvidenceDigest"], "cause evidence")
    expect((cause.get("kind"), cause.get("semanticDigest"), cause.get("classification")), ("GO1TargetAccessCauseDiagnosticEvidence", spec["predecessor"]["privateEvidenceSemanticDigest"], "AUTHENTICATION"), "cause evidence")
    expect((cause.get("rawResponseRetained"), cause.get("mutationPerformed"), cause.get("retryPerformed"), cause.get("happyRunResumed")), (False, False, False, False), "cause boundaries")
    binding = safe_private(Path(spec["runtimeBinding"]["path"]), spec["runtimeBinding"]["digest"], "Runtime Binding")
    expect((binding.get("kind"), binding.get("spec", {}).get("semanticDigest")), ("GO1RuntimeBinding", spec["runtimeBinding"]["semanticDigest"]), "Runtime Binding")
    return cause, binding


def validate_grant(candidate_path: Path, grant_path: Path, now: dt.datetime | None = None) -> dict[str, Any]:
    candidate = validate_candidate(candidate_path)
    grant = read(grant_path)
    expect(grant.get("kind"), "GO1DefaultAudienceDiagnosticGrant", "grant kind")
    spec = grant["spec"]
    expect((spec.get("decision"), spec.get("authority"), spec.get("singleRun"), spec.get("consumed")), ("GO", "github:arashkaffamanesh", True, False), "grant identity")
    expect(spec.get("candidateDigest"), sha(candidate_path), "candidate digest")
    if any(spec.get(key) is not True for key in TRUE) or any(spec.get(key) is not False for key in FALSE):
        raise DefaultAudienceError("grant authority is incomplete or overbroad")
    current = now or dt.datetime.now(dt.timezone.utc)
    issued, expires = parse_time(spec["issuedAt"]), parse_time(spec["expiresAt"])
    if not issued <= current <= expires or expires - issued > dt.timedelta(minutes=20):
        raise DefaultAudienceError("grant inactive or exceeds 20 minutes")
    if not spec.get("grantID"):
        raise DefaultAudienceError("grant ID missing")
    validate_predecessors(candidate)
    return grant


def token_request_document(expiration: int) -> dict[str, Any]:
    return {
        "apiVersion": "authentication.k8s.io/v1",
        "kind": "TokenRequest",
        # Match `kubectl create token` with no --audience: the API server
        # selects its configured API audience.  An explicit guessed audience
        # is the behavior this diagnostic is testing and must not reappear.
        "spec": {"expirationSeconds": expiration},
    }


def raw_request(client: Path, kubeconfig: Path, method: str, uri: str, payload: bytes | None, runner: Callable[..., Any]) -> tuple[int, bytes, bytes]:
    command = [str(client), "--kubeconfig", str(kubeconfig), method, "--raw", uri]
    if payload is not None:
        command += ["--filename", "-"]
    completed = runner(command, input=payload, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    return completed.returncode, completed.stdout, completed.stderr


def materialize_admin(candidate: dict[str, Any], binding: dict[str, Any], runner: Callable[..., Any]) -> Path:
    spec = candidate["spec"]
    management = spec["management"]
    client, kubeconfig = Path(management["clientPath"]), Path(management["credentialPath"])
    expect(sha(client), management["clientDigest"], "management client")
    if kubeconfig.is_symlink() or not kubeconfig.is_file() or (kubeconfig.stat().st_mode & 0o777) != 0o600:
        raise DefaultAudienceError("unsafe management Kubeconfig")
    expect(REG.CAUSE.V1.EXECUTOR.inspect_identity(kubeconfig)["identityDigest"], management["credentialIdentityDigest"], "management identity")
    code, stdout, _ = REG.raw_get(client, kubeconfig, management["workloadKubeconfigSecretURI"], runner)
    if code != 0:
        raise DefaultAudienceError("exact workload Kubeconfig Secret GET failed; output suppressed")
    secret = json.loads(stdout)
    raw = base64.b64decode(secret.get("data", {}).get("value", ""), validate=True)
    path = Path(spec["target"]["ephemeralAdminKubeconfigPath"])
    if not raw or path.exists() or path.is_symlink():
        raise DefaultAudienceError("unsafe admin Kubeconfig materialization")
    REG.write_exclusive(path, raw)
    identity = REG.CAUSE.V1.EXECUTOR.inspect_identity(path)
    target = binding["spec"]["target"]
    expect(identity["server"], target["workloadAPIServer"], "target server")
    expect(identity["caFingerprint"], target["workloadAPICAFingerprint"], "target CA")
    secret = {}; raw = b""
    return path


def execute(candidate_path: Path, grant_path: Path, runner: Callable[..., Any] = subprocess.run) -> dict[str, Any]:
    candidate = validate_candidate(candidate_path)
    grant = validate_grant(candidate_path, grant_path)
    _, binding = validate_predecessors(candidate)
    spec, target = candidate["spec"], candidate["spec"]["target"]
    client = Path(target["clientPath"])
    expect(sha(client), target["clientDigest"], "target client")
    admin_path = Path(target["ephemeralAdminKubeconfigPath"])
    token_path = Path(target["ephemeralTokenKubeconfigPath"])
    if admin_path.exists() or admin_path.is_symlink() or token_path.exists() or token_path.is_symlink():
        raise DefaultAudienceError("ephemeral path already exists")
    token = ""; ca_data = ""; server = ""
    admin_created = token_created = False
    evidence: dict[str, Any] | None = None
    classification = "UNKNOWN"
    probe_code = 1
    try:
        admin_path = materialize_admin(candidate, binding, runner); admin_created = True
        request = json.dumps(token_request_document(target["expirationSeconds"]), sort_keys=True, separators=(",", ":")).encode()
        code, stdout, stderr = raw_request(client, admin_path, "create", target["tokenRequestURI"], request, runner)
        if code != 0:
            raise DefaultAudienceError("default-audience TokenRequest failed; output suppressed")
        response = json.loads(stdout)
        token = str(response.get("status", {}).get("token", ""))
        expiration_timestamp = str(response.get("status", {}).get("expirationTimestamp", ""))
        payload = REG.decode_jwt_payload(token)
        returned = payload.get("aud", [])
        audiences = [returned] if isinstance(returned, str) else list(returned)
        old_audience = binding["spec"]["target"]["tokenAudience"]
        issuer = str(payload.get("iss", ""))
        now_epoch = int(dt.datetime.now(dt.timezone.utc).timestamp())
        claim_checks = {
            "subjectMatches": payload.get("sub") == target["serviceAccountSubject"],
            "tokenUnexpired": int(payload.get("exp", 0)) > now_epoch,
            "expirationReturned": bool(expiration_timestamp),
            "audienceReturned": len(audiences) > 0,
            "issuerMatchesReturnedAudience": issuer in audiences,
        }
        # A cluster may configure --api-audiences independently from its
        # service-account issuer.  The issuer/audience comparison is useful
        # evidence but is not itself a validity requirement.
        if not all(claim_checks[key] for key in ("subjectMatches", "tokenUnexpired", "expirationReturned", "audienceReturned")):
            raise DefaultAudienceError("default-audience token claims invalid")
        server = binding["spec"]["target"]["workloadAPIServer"]
        ca_data = binding["spec"]["target"]["caData"]
        kubeconfig = {"apiVersion": "v1", "kind": "Config", "clusters": [{"name": "target", "cluster": {"server": server, "certificate-authority-data": ca_data}}], "users": [{"name": "token", "user": {"token": token}}], "contexts": [{"name": "target", "context": {"cluster": "target", "user": "token"}}], "current-context": "target"}
        REG.write_exclusive(token_path, yaml.safe_dump(kubeconfig, sort_keys=True).encode()); token_created = True
        probe_code, probe_stdout, probe_stderr = raw_request(client, token_path, "get", target["exactProbeURI"], None, runner)
        classification, status_code = CAUSE.classify(probe_code, probe_stdout, probe_stderr)
        evidence = {
            "apiVersion": "evidence.openkubes.io/v1alpha1",
            "kind": "GO1DefaultAudienceDiagnosticEvidence",
            "candidateDigest": sha(candidate_path),
            "grantID": grant["spec"]["grantID"],
            "requestedAudienceCount": 0,
            "returnedAudienceCount": len(audiences),
            "returnedAudienceMatchesOldBoundAudience": old_audience in audiences,
            "claimChecks": claim_checks,
            "classification": classification,
            "httpStatusCode": status_code,
            "targetProbeExitCode": probe_code,
            "targetProbeSucceeded": probe_code == 0,
            "responseDigest": sha_bytes(probe_stdout + probe_stderr),
            "tokenRequestPerformed": True,
            "persistentObjectCreated": False,
            "adminKubeconfigCreated": admin_created,
            "tokenKubeconfigCreated": token_created,
            "credentialPayloadRetained": False,
            "rawResponseRetained": False,
            "retryPerformed": False,
            "happyRunResumed": False,
        }
        response = {}; payload = {}; kubeconfig = {}; request = b""
        stdout = b""; stderr = b""; probe_stdout = b""; probe_stderr = b""
    finally:
        token = ""; ca_data = ""; server = ""
        token_path.unlink(missing_ok=True)
        admin_path.unlink(missing_ok=True)
    if evidence is None:
        raise DefaultAudienceError("diagnostic produced no evidence")
    evidence["adminKubeconfigRemoved"] = not admin_path.exists() and not admin_path.is_symlink()
    evidence["tokenKubeconfigRemoved"] = not token_path.exists() and not token_path.is_symlink()
    if not evidence["adminKubeconfigRemoved"] or not evidence["tokenKubeconfigRemoved"]:
        raise DefaultAudienceError("ephemeral cleanup failed")
    evidence["semanticDigest"] = sha_bytes(json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode())
    output = Path(spec["outputPath"])
    if output.exists() or output.is_symlink():
        raise DefaultAudienceError("exclusive output already exists")
    REG.write_exclusive(output, (json.dumps(evidence, sort_keys=True, separators=(",", ":")) + "\n").encode())
    return {"result": "PASS-DEFAULT-AUDIENCE-DIAGNOSTIC", "classification": classification, "targetProbeSucceeded": probe_code == 0, "outputPath": str(output), "outputDigest": sha(output)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "verify-grant", "diagnose"))
    parser.add_argument("--candidate", type=Path, default=CANDIDATE)
    parser.add_argument("--grant", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "verify": validate_candidate(args.candidate.resolve()); print(sha(args.candidate.resolve()))
        elif args.command == "verify-grant":
            if args.grant is None: raise DefaultAudienceError("grant required")
            validate_grant(args.candidate.resolve(), args.grant.resolve()); print(sha(args.grant.resolve()))
        else:
            if args.grant is None or not args.execute: raise DefaultAudienceError("diagnose requires grant and --execute")
            print(json.dumps(execute(args.candidate.resolve(), args.grant.resolve()), sort_keys=True))
        return 0
    except Exception as error:
        print(f"ERROR: {type(error).__name__}: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
