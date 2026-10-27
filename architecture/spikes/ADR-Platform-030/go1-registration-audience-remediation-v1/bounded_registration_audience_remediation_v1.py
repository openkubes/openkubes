#!/usr/bin/env python3
"""Replace the bound Argo registration token with a default-audience token once."""

from __future__ import annotations

import argparse
import base64
import copy
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
CANDIDATE = HERE / "registration-audience-remediation-candidate-v1.yaml"
DEFAULT_DIR = SPIKE / "go1-default-audience-diagnostic-v1"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(value)
    return value


DEFAULT = load_module("ok141_default_audience_for_remediation", DEFAULT_DIR / "bounded_default_audience_diagnostic_v1.py")
REG = DEFAULT.REG
CAUSE = DEFAULT.CAUSE


class RemediationError(ValueError):
    pass


def sha_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def sha(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def read(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text())
    if not isinstance(value, dict):
        raise RemediationError(f"expected mapping: {path}")
    return value


def expect(actual: Any, expected: Any, context: str) -> None:
    if actual != expected:
        raise RemediationError(f"{context}: expected {expected!r}, got {actual!r}")


def parse_time(value: str | dt.datetime) -> dt.datetime:
    parsed = value if isinstance(value, dt.datetime) else dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise RemediationError("timestamp lacks timezone")
    return parsed.astimezone(dt.timezone.utc)


TRUE = (
    "exactTokenRequestGranted", "exactTargetProbeGranted",
    "exactRegistrationSecretReadGranted", "exactRegistrationSecretReplaceGranted",
    "optimisticConcurrencyGranted", "automaticArgoReconciliationAcknowledged",
)
FALSE = (
    "retryGranted", "rollbackOrCleanupGranted",
    "platformObserverOrCapabilityTestGranted", "evidencePublicationGranted",
    "failureInjectionGranted",
)


def validate_candidate(path: Path = CANDIDATE) -> dict[str, Any]:
    value = read(path)
    expect(value.get("kind"), "GO1RegistrationAudienceRemediationCandidate", "kind")
    spec = value["spec"]
    expect((spec["version"], spec["state"]), ("ok141-go1-registration-audience-remediation/v1", "OFFLINE-PROVEN-BLOCKED-NO-GO"), "candidate state")
    expect(sha(HERE / spec["predecessor"]["closurePath"]), spec["predecessor"]["closureDigest"], "closure digest")
    closure = read(HERE / spec["predecessor"]["closurePath"])
    expect((closure.get("result"), closure.get("classification"), closure.get("targetProbeSucceeded")), ("PASS-DEFAULT-AUDIENCE-DIAGNOSTIC", "SUCCESS", True), "closure result")
    evidence = DEFAULT.safe_private(Path(spec["predecessor"]["privateEvidencePath"]), spec["predecessor"]["privateEvidenceDigest"], "default audience evidence")
    expect((evidence.get("semanticDigest"), evidence.get("targetProbeSucceeded"), evidence.get("returnedAudienceMatchesOldBoundAudience")), (spec["predecessor"]["privateEvidenceSemanticDigest"], True, False), "private evidence")
    expect(spec["target"]["requestedAudiences"], [], "default audience")
    expect(spec["target"]["expirationSeconds"], 10800, "token lifetime")
    expect(sha(HERE / spec["tool"]["path"]), spec["tool"]["digest"], "tool digest")
    expect(spec["authorization"]["decision"], "NO-GO", "authorization")
    if any(item for key, item in spec["authorization"].items() if key.endswith("Granted") or key.endswith("Acknowledged")):
        raise RemediationError("candidate grants authority")
    return value


def validate_grant(candidate_path: Path, grant_path: Path, now: dt.datetime | None = None) -> dict[str, Any]:
    validate_candidate(candidate_path)
    grant = read(grant_path)
    expect(grant.get("kind"), "GO1RegistrationAudienceRemediationGrant", "grant kind")
    spec = grant["spec"]
    expect((spec.get("decision"), spec.get("authority"), spec.get("singleRun"), spec.get("consumed")), ("GO", "github:arashkaffamanesh", True, False), "grant identity")
    expect(spec.get("candidateDigest"), sha(candidate_path), "candidate digest")
    if any(spec.get(key) is not True for key in TRUE) or any(spec.get(key) is not False for key in FALSE):
        raise RemediationError("grant authority is incomplete or overbroad")
    current = now or dt.datetime.now(dt.timezone.utc)
    issued, expires = parse_time(spec["issuedAt"]), parse_time(spec["expiresAt"])
    if not issued <= current <= expires or expires - issued > dt.timedelta(minutes=20):
        raise RemediationError("grant inactive or exceeds 20 minutes")
    if not spec.get("grantID"):
        raise RemediationError("grant ID missing")
    return grant


def safe_kubeconfig(path: Path, expected_identity: str) -> None:
    if path.is_symlink() or not path.is_file() or (path.stat().st_mode & 0o777) != 0o600:
        raise RemediationError(f"unsafe Kubeconfig: {path}")
    expect(REG.CAUSE.V1.EXECUTOR.inspect_identity(path)["identityDigest"], expected_identity, "credential identity")


def raw_replace(client: Path, kubeconfig: Path, uri: str, document: dict[str, Any], runner: Callable[..., Any]) -> tuple[int, bytes, bytes]:
    command = [str(client), "--kubeconfig", str(kubeconfig), "replace", "--raw", uri, "--filename", "-"]
    payload = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    completed = runner(command, input=payload, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    return completed.returncode, completed.stdout, completed.stderr


def replacement_secret(current: dict[str, Any], token: str, expiration: str) -> dict[str, Any]:
    value = copy.deepcopy(current)
    metadata = value.setdefault("metadata", {})
    for key in ("managedFields", "selfLink"):
        metadata.pop(key, None)
    annotations = metadata.setdefault("annotations", {})
    annotations["openkubes.io/token-expiration"] = expiration
    config = json.loads(base64.b64decode(value["data"]["config"], validate=True))
    config["bearerToken"] = token
    value["data"]["config"] = base64.b64encode(json.dumps(config, sort_keys=True, separators=(",", ":")).encode()).decode()
    config = {}
    return value


def execute(candidate_path: Path, grant_path: Path, runner: Callable[..., Any] = subprocess.run) -> dict[str, Any]:
    candidate = validate_candidate(candidate_path)
    grant = validate_grant(candidate_path, grant_path)
    spec = candidate["spec"]
    _, binding = DEFAULT.validate_predecessors({"spec": {"predecessor": {
        "privateEvidenceDigest": "sha256:d3382b75d2df4910ffe791c173cd0df169cc33461796beb1934d38fce2e86c0c",
        "privateEvidenceSemanticDigest": "sha256:50c55e6e7770109baabe9e4e62eb17330d1f346b6ff609032b8e1d90c6bd3a25",
    }, "runtimeBinding": spec["runtimeBinding"]}})
    management, shared, target = spec["management"], spec["shared"], spec["target"]
    mgmt_client, shared_client, target_client = Path(management["clientPath"]), Path(shared["clientPath"]), Path(target["clientPath"])
    expect(sha(mgmt_client), management["clientDigest"], "management client")
    expect(sha(shared_client), shared["clientDigest"], "shared client")
    expect(sha(target_client), target["clientDigest"], "target client")
    mgmt_config, shared_config = Path(management["credentialPath"]), Path(shared["credentialPath"])
    safe_kubeconfig(mgmt_config, management["credentialIdentityDigest"])
    safe_kubeconfig(shared_config, shared["credentialIdentityDigest"])
    admin_path, token_path = Path(target["ephemeralAdminKubeconfigPath"]), Path(target["ephemeralTokenKubeconfigPath"])
    if any(path.exists() or path.is_symlink() for path in (admin_path, token_path)):
        raise RemediationError("ephemeral path already exists")
    token = ""; ca_data = ""; server = ""; evidence: dict[str, Any] | None = None
    try:
        admin_path = DEFAULT.materialize_admin({"spec": spec}, binding, runner)
        request = DEFAULT.token_request_document(target["expirationSeconds"])
        code, stdout, _ = DEFAULT.raw_request(target_client, admin_path, "create", target["tokenRequestURI"], json.dumps(request, sort_keys=True, separators=(",", ":")).encode(), runner)
        if code != 0:
            raise RemediationError("default-audience TokenRequest failed; output suppressed")
        response = json.loads(stdout)
        token, expiration = str(response.get("status", {}).get("token", "")), str(response.get("status", {}).get("expirationTimestamp", ""))
        claims = REG.decode_jwt_payload(token)
        audience = claims.get("aud", [])
        audiences = [audience] if isinstance(audience, str) else list(audience)
        now_epoch = int(dt.datetime.now(dt.timezone.utc).timestamp())
        claim_checks = {
            "subjectMatches": claims.get("sub") == target["serviceAccountSubject"],
            "tokenUnexpired": int(claims.get("exp", 0)) > now_epoch,
            "expirationReturned": bool(expiration),
            "audienceReturned": bool(audiences),
            "oldBoundAudienceAbsent": binding["spec"]["target"]["tokenAudience"] not in audiences,
        }
        if not all(claim_checks.values()):
            raise RemediationError("new token claims do not close the bound mismatch")
        server, ca_data = binding["spec"]["target"]["workloadAPIServer"], binding["spec"]["target"]["caData"]
        token_config = {"apiVersion": "v1", "kind": "Config", "clusters": [{"name": "target", "cluster": {"server": server, "certificate-authority-data": ca_data}}], "users": [{"name": "token", "user": {"token": token}}], "contexts": [{"name": "target", "context": {"cluster": "target", "user": "token"}}], "current-context": "target"}
        REG.write_exclusive(token_path, yaml.safe_dump(token_config, sort_keys=True).encode())
        probe_code, probe_stdout, probe_stderr = DEFAULT.raw_request(target_client, token_path, "get", target["exactProbeURI"], None, runner)
        classification, _ = CAUSE.classify(probe_code, probe_stdout, probe_stderr)
        if classification != "SUCCESS":
            raise RemediationError(f"new token target probe failed: {classification}")
        read_code, secret_stdout, _ = REG.raw_get(shared_client, shared_config, shared["registrationSecretURI"], runner)
        if read_code != 0:
            raise RemediationError("registration Secret GET failed; output suppressed")
        current = json.loads(secret_stdout)
        uid, resource_version = current.get("metadata", {}).get("uid", ""), current.get("metadata", {}).get("resourceVersion", "")
        if not uid or not resource_version:
            raise RemediationError("registration Secret lacks optimistic-concurrency identity")
        old_config = json.loads(base64.b64decode(current.get("data", {}).get("config", ""), validate=True))
        old_claims = REG.decode_jwt_payload(str(old_config.get("bearerToken", "")))
        old_aud = old_claims.get("aud", [])
        old_audiences = [old_aud] if isinstance(old_aud, str) else list(old_aud)
        if binding["spec"]["target"]["tokenAudience"] not in old_audiences:
            raise RemediationError("existing registration no longer contains the proven bad audience")
        replacement = replacement_secret(current, token, expiration)
        replace_code, replace_stdout, _ = raw_replace(shared_client, shared_config, shared["registrationSecretURI"], replacement, runner)
        if replace_code != 0:
            raise RemediationError("registration Secret replace failed; partial state preserved")
        replaced = json.loads(replace_stdout)
        new_uid, new_rv = replaced.get("metadata", {}).get("uid", ""), replaced.get("metadata", {}).get("resourceVersion", "")
        evidence = {
            "apiVersion": "evidence.openkubes.io/v1alpha1",
            "kind": "GO1RegistrationAudienceRemediationEvidence",
            "candidateDigest": sha(candidate_path), "grantID": grant["spec"]["grantID"],
            "claimChecks": claim_checks, "preReplaceTargetProbe": classification,
            "secretReadPerformed": True, "secretReplaced": True,
            "uidPreserved": new_uid == uid, "resourceVersionAdvanced": bool(new_rv and new_rv != resource_version),
            "optimisticConcurrencyUsed": True, "automaticArgoReconciliationMayResume": True,
            "credentialPayloadRetained": False, "rawResponseRetained": False,
            "retryPerformed": False, "rollbackOrCleanupPerformed": False,
            "platformObserverOrCapabilityTestPerformed": False, "failureInjectionPerformed": False,
        }
        if not evidence["uidPreserved"] or not evidence["resourceVersionAdvanced"]:
            raise RemediationError("replacement identity verification failed")
        response = {}; claims = {}; token_config = {}; current = {}; replacement = {}; replaced = {}; old_config = {}; old_claims = {}
        stdout = b""; probe_stdout = b""; probe_stderr = b""; secret_stdout = b""; replace_stdout = b""
    finally:
        token = ""; ca_data = ""; server = ""
        token_path.unlink(missing_ok=True); admin_path.unlink(missing_ok=True)
    if evidence is None:
        raise RemediationError("remediation produced no evidence")
    evidence["adminKubeconfigRemoved"] = not admin_path.exists() and not admin_path.is_symlink()
    evidence["tokenKubeconfigRemoved"] = not token_path.exists() and not token_path.is_symlink()
    if not evidence["adminKubeconfigRemoved"] or not evidence["tokenKubeconfigRemoved"]:
        raise RemediationError("ephemeral cleanup failed")
    evidence["semanticDigest"] = sha_bytes(json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode())
    output = Path(spec["outputPath"])
    if output.exists() or output.is_symlink():
        raise RemediationError("exclusive output already exists")
    REG.write_exclusive(output, (json.dumps(evidence, sort_keys=True, separators=(",", ":")) + "\n").encode())
    return {"result": "PASS-REGISTRATION-AUDIENCE-REMEDIATION", "outputPath": str(output), "outputDigest": sha(output)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "verify-grant", "remediate"))
    parser.add_argument("--candidate", type=Path, default=CANDIDATE)
    parser.add_argument("--grant", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "verify": validate_candidate(args.candidate.resolve()); print(sha(args.candidate.resolve()))
        elif args.command == "verify-grant":
            if args.grant is None: raise RemediationError("grant required")
            validate_grant(args.candidate.resolve(), args.grant.resolve()); print(sha(args.grant.resolve()))
        else:
            if args.grant is None or not args.execute: raise RemediationError("remediate requires grant and --execute")
            print(json.dumps(execute(args.candidate.resolve(), args.grant.resolve()), sort_keys=True))
        return 0
    except Exception as error:
        print(f"ERROR: {type(error).__name__}: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
