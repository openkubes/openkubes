#!/usr/bin/env python3
"""Classify one exact target GET without retaining registration credentials or raw output."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

import yaml


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
CANDIDATE = HERE / "target-access-cause-diagnostic-candidate-v1.yaml"
REG_DIR = SPIKE / "go1-registration-integrity-diagnostic-v1"
REG_CANDIDATE = REG_DIR / "registration-integrity-diagnostic-candidate-v1.yaml"
REG_EVIDENCE = Path("/private/tmp/ok141-registration-integrity-diagnostic-v1-evidence.json")


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(value)
    return value


REG = load_module("ok141_registration_for_target_cause", REG_DIR / "bounded_registration_integrity_diagnostic_v1.py")


class TargetCauseError(ValueError):
    pass


def sha_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def sha(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def read(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text())
    if not isinstance(value, dict):
        raise TargetCauseError(f"expected mapping: {path}")
    return value


def expect(actual: Any, expected: Any, context: str) -> None:
    if actual != expected:
        raise TargetCauseError(f"{context}: expected {expected!r}, got {actual!r}")


def parse_time(value: str | dt.datetime) -> dt.datetime:
    parsed = value if isinstance(value, dt.datetime) else dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise TargetCauseError("timestamp lacks timezone")
    return parsed.astimezone(dt.timezone.utc)


def safe_private(path: Path, expected: str, context: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or (path.stat().st_mode & 0o777) != 0o600:
        raise TargetCauseError(f"unsafe {context}")
    expect(sha(path), expected, f"{context} digest")
    return read(path)


def validate_candidate(path: Path = CANDIDATE) -> dict[str, Any]:
    value = read(path)
    expect(value.get("kind"), "GO1TargetAccessCauseDiagnosticCandidate", "kind")
    spec = value["spec"]
    expect((spec["version"], spec["state"]), ("ok141-go1-target-access-cause-diagnostic/v1", "OFFLINE-PROVEN-BLOCKED-NO-GO"), "candidate state")
    expect(sha(REG_CANDIDATE), spec["predecessor"]["candidate"]["digest"], "registration candidate")
    REG.validate_candidate(REG_CANDIDATE)
    expect(spec["exactReadPath"]["sharedSecretURI"], REG.read(REG_CANDIDATE)["spec"]["registration"]["secretURI"], "shared Secret URI")
    expect(spec["exactReadPath"]["targetURI"], REG.read(REG_CANDIDATE)["spec"]["targetProbe"]["exactURI"], "target URI")
    expect(sha(HERE / spec["tool"]["path"]), spec["tool"]["digest"], "tool digest")
    expect(spec["authorization"]["decision"], "NO-GO", "authorization")
    if any(item for key, item in spec["authorization"].items() if key.endswith("Granted")):
        raise TargetCauseError("candidate grants authority")
    return value


TRUE = (
    "sharedClusterContactGranted", "sharedCredentialUseGranted",
    "exactRegistrationSecretReadGranted", "registrationIntegrityGranted",
    "tokenClaimInspectionGranted", "ephemeralTargetKubeconfigGranted",
    "targetCredentialUseGranted", "exactTargetNamespaceGetGranted",
    "responseClassificationGranted",
)
FALSE = (
    "mutationGranted", "podOrLogReadGranted", "retryGranted",
    "rollbackOrCleanupGranted", "happyRunResumeGranted",
    "evidencePublicationGranted", "failureInjectionGranted",
)


def validate_predecessor(candidate: dict[str, Any]) -> dict[str, Any]:
    spec = candidate["spec"]["predecessor"]
    evidence = safe_private(REG_EVIDENCE, spec["privateEvidenceDigest"], "registration evidence")
    expect((evidence.get("kind"), evidence.get("semanticDigest")), ("GO1RegistrationIntegrityDiagnosticEvidence", spec["privateEvidenceSemanticDigest"]), "registration evidence")
    expect((evidence.get("registrationValid"), evidence.get("targetProbeAttempted"), evidence.get("targetProbeSucceeded")), (True, True, False), "registration result")
    expect((evidence.get("secretBytesRetained"), evidence.get("tokenRetained"), evidence.get("caPayloadRetained"), evidence.get("endpointRetained"), evidence.get("jwtPayloadRetained")), (False, False, False, False, False), "registration evidence retention")
    expect((evidence.get("mutationPerformed"), evidence.get("retryPerformed"), evidence.get("happyRunResumed")), (False, False, False), "registration boundaries")
    return evidence


def validate_grant(candidate_path: Path, grant_path: Path, now: dt.datetime | None = None) -> dict[str, Any]:
    candidate = validate_candidate(candidate_path)
    grant = read(grant_path)
    expect(grant.get("kind"), "GO1TargetAccessCauseDiagnosticGrant", "grant kind")
    spec = grant["spec"]
    expect((spec.get("decision"), spec.get("authority"), spec.get("singleRun"), spec.get("consumed")), ("GO", "github:arashkaffamanesh", True, False), "grant identity")
    expect(spec.get("candidateDigest"), sha(candidate_path), "candidate digest")
    if any(spec.get(key) is not True for key in TRUE) or any(spec.get(key) is not False for key in FALSE):
        raise TargetCauseError("grant authority is incomplete or overbroad")
    current = now or dt.datetime.now(dt.timezone.utc)
    issued, expires = parse_time(spec["issuedAt"]), parse_time(spec["expiresAt"])
    if not issued <= current <= expires or expires - issued > dt.timedelta(minutes=20):
        raise TargetCauseError("grant inactive or exceeds 20 minutes")
    if not spec.get("grantID"):
        raise TargetCauseError("grant ID missing")
    validate_predecessor(candidate)
    return grant


PATTERNS = {
    "DNS": ("no such host", "name or service not known", "temporary failure in name resolution"),
    "TLS": ("x509", "certificate", "tls handshake", "unknown authority"),
    "AUTHENTICATION": ("unauthorized", "authentication required", "invalid bearer token"),
    "AUTHORIZATION": ("forbidden", "cannot get resource", "permission denied"),
    "TARGET-CONNECTION": ("connection refused", "no route to host", "i/o timeout", "context deadline exceeded", "connection timed out", "network is unreachable"),
    "NOT-FOUND": ("notfound", "not found"),
}


def classify(code: int, stdout: bytes, stderr: bytes) -> tuple[str, int | None]:
    status_code: int | None = None
    reason = ""
    try:
        value = json.loads(stdout)
        if isinstance(value, dict):
            reason = str(value.get("reason", ""))
            raw_code = value.get("code")
            status_code = raw_code if isinstance(raw_code, int) else None
    except (json.JSONDecodeError, UnicodeDecodeError):
        pass
    text = (reason + "\n" + stderr.decode(errors="replace")).lower()
    if code == 0:
        return "SUCCESS", status_code
    for category in ("DNS", "TLS", "AUTHENTICATION", "AUTHORIZATION", "TARGET-CONNECTION", "NOT-FOUND"):
        if any(pattern in text for pattern in PATTERNS[category]):
            return category, status_code
    return "UNKNOWN", status_code


def registration_material(candidate: dict[str, Any], runner: Callable[..., Any]) -> tuple[dict[str, Any], str, str, str]:
    reg_candidate = REG.validate_candidate(REG_CANDIDATE)
    _, binding = REG.validate_predecessors(reg_candidate)
    spec = reg_candidate["spec"]["registration"]
    client, kubeconfig = Path(spec["clientPath"]), Path(spec["credentialPath"])
    expect(sha(client), spec["clientDigest"], "shared client")
    if kubeconfig.is_symlink() or not kubeconfig.is_file() or (kubeconfig.stat().st_mode & 0o777) != 0o600:
        raise TargetCauseError("unsafe ok-shared kubeconfig")
    expect(REG.CAUSE.V1.EXECUTOR.inspect_identity(kubeconfig)["identityDigest"], spec["credentialIdentityDigest"], "ok-shared identity")
    code, stdout, _ = REG.raw_get(client, kubeconfig, candidate["spec"]["exactReadPath"]["sharedSecretURI"], runner)
    if code != 0:
        raise TargetCauseError("exact registration Secret GET failed; output suppressed")
    secret = json.loads(stdout)
    fields = {name: REG.decode_secret_field(secret, name) for name in ("name", "server", "namespaces", "clusterResources", "project", "config")}
    config = json.loads(fields["config"])
    token = str(config.get("bearerToken", ""))
    ca_data = str(config.get("tlsClientConfig", {}).get("caData", ""))
    payload = REG.decode_jwt_payload(token)
    target, expected = binding["spec"]["target"], spec["expected"]
    audience = payload.get("aud", [])
    audiences = [audience] if isinstance(audience, str) else audience
    checks = {
        "secretTypeLabelMatches": secret.get("metadata", {}).get("labels", {}).get("argocd.argoproj.io/secret-type") == "cluster",
        "nameMatches": fields["name"] == expected["name"],
        "serverMatchesRuntimeBinding": fields["server"] == target["workloadAPIServer"],
        "namespacesMatch": fields["namespaces"] == expected["namespaces"],
        "clusterResourcesMatch": fields["clusterResources"] == expected["clusterResources"],
        "projectMatches": fields["project"] == expected["project"],
        "caMatchesRuntimeBinding": ca_data == target["caData"],
        "tlsVerificationEnabled": config.get("tlsClientConfig", {}).get("insecure") is False,
        "tokenSubjectMatches": payload.get("sub") == expected["serviceAccountSubject"],
        "tokenAudienceMatches": target["tokenAudience"] in audiences,
        "tokenUnexpired": int(payload.get("exp", 0)) > int(dt.datetime.now(dt.timezone.utc).timestamp()),
    }
    if not all(checks.values()):
        raise TargetCauseError("registration drifted; target probe suppressed")
    fields["config"] = ""
    config = {}; payload = {}; secret = {}
    return checks, fields["server"], ca_data, token


def execute(candidate_path: Path, grant_path: Path, runner: Callable[..., Any] = subprocess.run) -> dict[str, Any]:
    candidate = validate_candidate(candidate_path)
    grant = validate_grant(candidate_path, grant_path)
    spec = candidate["spec"]
    checks, server, ca_data, token = registration_material(candidate, runner)
    reg_spec = REG.read(REG_CANDIDATE)["spec"]["targetProbe"]
    target_client = Path(reg_spec["clientPath"])
    expect(sha(target_client), reg_spec["clientDigest"], "target client")
    ephemeral = Path(spec["exactReadPath"]["ephemeralKubeconfigPath"])
    if ephemeral.exists() or ephemeral.is_symlink():
        raise TargetCauseError("unsafe target Kubeconfig path")
    code, stdout, stderr, created = REG.probe_target(True, target_client, ephemeral, spec["exactReadPath"]["targetURI"], server, ca_data, token, runner)
    category, status_code = classify(code, stdout, stderr)
    token = ""; ca_data = ""; server = ""
    evidence = {
        "apiVersion": "evidence.openkubes.io/v1alpha1",
        "kind": "GO1TargetAccessCauseDiagnosticEvidence",
        "candidateDigest": sha(candidate_path),
        "grantID": grant["spec"]["grantID"],
        "registrationChecks": checks,
        "classification": category,
        "httpStatusCode": status_code,
        "targetProbeExitCode": code,
        "responseDigest": sha_bytes(stdout + stderr),
        "temporaryKubeconfigCreated": created,
        "temporaryKubeconfigRemoved": not ephemeral.exists(),
        "secretBytesRetained": False,
        "tokenOrJWTRetained": False,
        "caOrEndpointRetained": False,
        "rawResponseRetained": False,
        "mutationPerformed": False,
        "retryPerformed": False,
        "happyRunResumed": False,
    }
    expect(category in spec["classification"]["allowed"], True, "classification")
    evidence["semanticDigest"] = sha_bytes(json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode())
    output = Path(spec["outputPath"])
    if output.exists() or output.is_symlink():
        raise TargetCauseError("exclusive output already exists")
    REG.write_exclusive(output, (json.dumps(evidence, sort_keys=True, separators=(",", ":")) + "\n").encode())
    return {"result": "PASS-READ-ONLY-TARGET-CAUSE-DIAGNOSTIC", "classification": category, "outputPath": str(output), "outputDigest": sha(output)}


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
            if args.grant is None: raise TargetCauseError("grant required")
            validate_grant(args.candidate.resolve(), args.grant.resolve()); print(sha(args.grant.resolve()))
        else:
            if args.grant is None or not args.execute: raise TargetCauseError("diagnose requires grant and --execute")
            print(json.dumps(execute(args.candidate.resolve(), args.grant.resolve()), sort_keys=True))
        return 0
    except Exception as error:
        print(f"ERROR: {type(error).__name__}: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
