#!/usr/bin/env python3
"""Validate Argo registration and one exact target GET without retaining credentials."""

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
CANDIDATE = HERE / "registration-integrity-diagnostic-candidate-v1.yaml"
CAUSE_CANDIDATE = SPIKE / "go1-platform-convergence-cause-diagnostic-v1" / "platform-convergence-cause-diagnostic-candidate-v1.yaml"
CAUSE_EVIDENCE = Path("/private/tmp/ok141-platform-convergence-cause-diagnostic-v1-evidence.json")


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(value)
    return value


CAUSE = load_module("ok141_platform_cause_for_registration", SPIKE / "go1-platform-convergence-cause-diagnostic-v1" / "bounded_platform_convergence_cause_diagnostic_v1.py")


class RegistrationDiagnosticError(ValueError):
    pass


def sha_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def sha(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def read(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text())
    if not isinstance(value, dict):
        raise RegistrationDiagnosticError(f"expected mapping: {path}")
    return value


def expect(actual: Any, expected: Any, context: str) -> None:
    if actual != expected:
        raise RegistrationDiagnosticError(f"{context}: expected {expected!r}, got {actual!r}")


def parse_time(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise RegistrationDiagnosticError("timestamp lacks timezone")
    return parsed.astimezone(dt.timezone.utc)


def safe_private(path: Path, expected: str, context: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or (path.stat().st_mode & 0o777) != 0o600:
        raise RegistrationDiagnosticError(f"unsafe {context}")
    expect(sha(path), expected, f"{context} digest")
    return read(path)


def validate_candidate(path: Path = CANDIDATE) -> dict[str, Any]:
    value = read(path)
    expect(value.get("kind"), "GO1RegistrationIntegrityDiagnosticCandidate", "kind")
    spec = value["spec"]
    expect((spec["version"], spec["state"]), ("ok141-go1-registration-integrity-diagnostic/v1", "OFFLINE-PROVEN-BLOCKED-NO-GO"), "candidate state")
    expect(sha(CAUSE_CANDIDATE), spec["predecessor"]["candidate"]["digest"], "cause candidate")
    CAUSE.validate_candidate(CAUSE_CANDIDATE)
    expect(sha(HERE / spec["tool"]["path"]), spec["tool"]["digest"], "tool digest")
    expect(spec["authorization"]["decision"], "NO-GO", "authorization")
    if any(item for key, item in spec["authorization"].items() if key.endswith("Granted")):
        raise RegistrationDiagnosticError("candidate grants authority")
    return value


TRUE = ("sharedClusterContactGranted", "sharedCredentialUseGranted", "exactRegistrationSecretReadGranted", "registrationIntegrityGranted", "tokenClaimInspectionGranted", "ephemeralTargetKubeconfigGranted", "targetCredentialUseGranted", "exactTargetNamespaceGetGranted")
FALSE = ("mutationGranted", "podOrLogReadGranted", "retryGranted", "rollbackOrCleanupGranted", "happyRunResumeGranted", "evidencePublicationGranted", "failureInjectionGranted")


def validate_predecessors(candidate: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    spec = candidate["spec"]
    cause = safe_private(CAUSE_EVIDENCE, spec["predecessor"]["privateEvidenceDigest"], "cause evidence")
    expect((cause.get("kind"), cause.get("semanticDigest"), cause.get("commonIndicators")), ("GO1PlatformConvergenceCauseDiagnosticEvidence", spec["predecessor"]["privateEvidenceSemanticDigest"], ["CACHE", "TARGET-CONNECTION"]), "cause evidence")
    binding = safe_private(Path(spec["runtimeBinding"]["path"]), spec["runtimeBinding"]["digest"], "Runtime Binding")
    expect((binding.get("kind"), binding.get("spec", {}).get("semanticDigest")), ("GO1RuntimeBinding", spec["runtimeBinding"]["semanticDigest"]), "Runtime Binding")
    return cause, binding


def validate_grant(candidate_path: Path, grant_path: Path, now: dt.datetime | None = None) -> dict[str, Any]:
    candidate = validate_candidate(candidate_path)
    grant = read(grant_path)
    expect(grant.get("kind"), "GO1RegistrationIntegrityDiagnosticGrant", "grant kind")
    spec = grant["spec"]
    expect((spec.get("decision"), spec.get("authority"), spec.get("singleRun"), spec.get("consumed")), ("GO", "github:arashkaffamanesh", True, False), "grant identity")
    expect(spec.get("candidateDigest"), sha(candidate_path), "candidate digest")
    if any(spec.get(key) is not True for key in TRUE) or any(spec.get(key) is not False for key in FALSE):
        raise RegistrationDiagnosticError("grant authority is incomplete or overbroad")
    current = now or dt.datetime.now(dt.timezone.utc)
    issued, expires = parse_time(spec["issuedAt"]), parse_time(spec["expiresAt"])
    if not issued <= current <= expires or expires - issued > dt.timedelta(minutes=20):
        raise RegistrationDiagnosticError("grant inactive or exceeds 20 minutes")
    if not spec.get("grantID"):
        raise RegistrationDiagnosticError("grant ID missing")
    validate_predecessors(candidate)
    return grant


def decode_secret_field(secret: dict[str, Any], name: str) -> str:
    raw = base64.b64decode(secret.get("data", {}).get(name, ""), validate=True)
    if not raw:
        raise RegistrationDiagnosticError(f"registration field missing: {name}")
    return raw.decode()


def decode_jwt_payload(token: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 3:
        raise RegistrationDiagnosticError("token is not a JWT")
    padded = parts[1] + "=" * (-len(parts[1]) % 4)
    value = json.loads(base64.urlsafe_b64decode(padded.encode()))
    if not isinstance(value, dict):
        raise RegistrationDiagnosticError("JWT payload is not an object")
    return value


def write_exclusive(path: Path, raw: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)


def raw_get(client: Path, kubeconfig: Path, uri: str, runner: Callable[..., Any]) -> tuple[int, bytes, bytes]:
    completed = runner([str(client), "--kubeconfig", str(kubeconfig), "get", "--raw", uri], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    return completed.returncode, completed.stdout, completed.stderr


def probe_target(
    allowed: bool,
    client: Path,
    ephemeral: Path,
    uri: str,
    server: str,
    ca_data: str,
    token: str,
    runner: Callable[..., Any],
) -> tuple[int, bytes, bytes, bool]:
    if not allowed:
        return -1, b"", b"", False
    kubeconfig = {"apiVersion": "v1", "kind": "Config", "clusters": [{"name": "target", "cluster": {"server": server, "certificate-authority-data": ca_data}}], "users": [{"name": "token", "user": {"token": token}}], "contexts": [{"name": "target", "context": {"cluster": "target", "user": "token"}}], "current-context": "target"}
    created = False
    try:
        write_exclusive(ephemeral, yaml.safe_dump(kubeconfig, sort_keys=True).encode())
        created = True
        code, stdout, stderr = raw_get(client, ephemeral, uri, runner)
        return code, stdout, stderr, created
    finally:
        kubeconfig = {}
        ephemeral.unlink(missing_ok=True)


def execute(candidate_path: Path, grant_path: Path, runner: Callable[..., Any] = subprocess.run) -> dict[str, Any]:
    candidate = validate_candidate(candidate_path)
    grant = validate_grant(candidate_path, grant_path)
    _, binding = validate_predecessors(candidate)
    spec, grant_spec = candidate["spec"], grant["spec"]
    registration = spec["registration"]
    shared_client, shared_kubeconfig = Path(registration["clientPath"]), Path(registration["credentialPath"])
    if sha(shared_client) != registration["clientDigest"]:
        raise RegistrationDiagnosticError("shared kubectl identity mismatch")
    if shared_kubeconfig.is_symlink() or not shared_kubeconfig.is_file() or (shared_kubeconfig.stat().st_mode & 0o777) != 0o600:
        raise RegistrationDiagnosticError("unsafe ok-shared kubeconfig")
    expect(CAUSE.V1.EXECUTOR.inspect_identity(shared_kubeconfig)["identityDigest"], registration["credentialIdentityDigest"], "ok-shared identity")
    code, stdout, _ = raw_get(shared_client, shared_kubeconfig, registration["secretURI"], runner)
    if code != 0:
        raise RegistrationDiagnosticError("exact registration Secret GET failed; output suppressed")
    secret = json.loads(stdout)
    expected, target = registration["expected"], binding["spec"]["target"]
    fields = {name: decode_secret_field(secret, name) for name in ("name", "server", "namespaces", "clusterResources", "project", "config")}
    config = json.loads(fields["config"])
    token = str(config.get("bearerToken", ""))
    ca_data = str(config.get("tlsClientConfig", {}).get("caData", ""))
    payload = decode_jwt_payload(token)
    audience = payload.get("aud", [])
    audiences = [audience] if isinstance(audience, str) else audience
    now_epoch = int(dt.datetime.now(dt.timezone.utc).timestamp())
    expiration = int(payload.get("exp", 0))
    checks = {
        "secretTypeLabelMatches": secret.get("metadata", {}).get("labels", {}).get("argocd.argoproj.io/secret-type") == "cluster",
        "nameMatches": fields["name"] == expected["name"], "serverMatchesRuntimeBinding": fields["server"] == target["workloadAPIServer"],
        "namespacesMatch": fields["namespaces"] == expected["namespaces"], "clusterResourcesMatch": fields["clusterResources"] == expected["clusterResources"],
        "projectMatches": fields["project"] == expected["project"], "caMatchesRuntimeBinding": ca_data == target["caData"],
        "tlsVerificationEnabled": config.get("tlsClientConfig", {}).get("insecure") is False,
        "tokenSubjectMatches": payload.get("sub") == expected["serviceAccountSubject"],
        "tokenAudienceMatches": target["tokenAudience"] in audiences, "tokenUnexpired": expiration > now_epoch,
    }
    target_spec = spec["targetProbe"]
    target_client, ephemeral = Path(target_spec["clientPath"]), Path(target_spec["ephemeralKubeconfigPath"])
    if sha(target_client) != target_spec["clientDigest"] or ephemeral.exists() or ephemeral.is_symlink():
        raise RegistrationDiagnosticError("unsafe target probe prerequisites")
    probe_allowed = all(checks.values())
    probe_code, probe_stdout, probe_stderr, ephemeral_created = probe_target(
        probe_allowed, target_client, ephemeral, target_spec["exactURI"],
        fields["server"], ca_data, token, runner,
    )
    token = ""; fields["config"] = ""; config = {}; payload = {}
    evidence = {
        "apiVersion": "evidence.openkubes.io/v1alpha1", "kind": "GO1RegistrationIntegrityDiagnosticEvidence",
        "candidateDigest": sha(candidate_path), "grantID": grant_spec["grantID"], "checks": checks,
        "registrationValid": all(checks.values()), "tokenRemainingSeconds": max(0, expiration - now_epoch),
        "targetProbeAttempted": probe_allowed, "targetProbeSucceeded": probe_allowed and probe_code == 0,
        "targetProbeExitCode": probe_code, "targetProbeStdoutDigest": sha_bytes(probe_stdout), "targetProbeStderrDigest": sha_bytes(probe_stderr),
        "secretBytesRetained": False, "tokenRetained": False, "caPayloadRetained": False,
        "endpointRetained": False, "jwtPayloadRetained": False,
        "temporaryKubeconfigCreated": ephemeral_created,
        "temporaryKubeconfigRemoved": not ephemeral.exists(),
        "mutationPerformed": False, "retryPerformed": False, "happyRunResumed": False,
    }
    evidence["semanticDigest"] = sha_bytes(json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode())
    output = Path(spec["outputPath"])
    if output.exists() or output.is_symlink():
        raise RegistrationDiagnosticError("exclusive output already exists")
    write_exclusive(output, (json.dumps(evidence, sort_keys=True, separators=(",", ":")) + "\n").encode())
    return {"result": "PASS-READ-ONLY-REGISTRATION-DIAGNOSTIC", "outputPath": str(output), "outputDigest": sha(output), "registrationValid": evidence["registrationValid"], "targetProbeSucceeded": evidence["targetProbeSucceeded"]}


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
            if args.grant is None: raise RegistrationDiagnosticError("grant required")
            validate_grant(args.candidate.resolve(), args.grant.resolve()); print(sha(args.grant.resolve()))
        else:
            if args.grant is None or not args.execute: raise RegistrationDiagnosticError("diagnose requires grant and --execute")
            print(json.dumps(execute(args.candidate.resolve(), args.grant.resolve()), sort_keys=True))
        return 0
    except Exception as error:
        print(f"ERROR: {type(error).__name__}: {error}", file=sys.stderr); return 2


if __name__ == "__main__":
    raise SystemExit(main())
