#!/usr/bin/env python3
"""Refresh the disposable Argo registration token under an external grant."""

from __future__ import annotations

import argparse
import base64
import copy
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

import yaml


HERE = Path(__file__).resolve().parent
CANDIDATE = HERE / "platform-baseline-token-refresh-candidate-v1.yaml"


class RefreshError(RuntimeError):
    pass


def sha_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def digest(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def read_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text())
    if not isinstance(value, dict):
        raise RefreshError(f"expected mapping: {path}")
    return value


def expect(actual: Any, expected: Any, context: str) -> None:
    if actual != expected:
        raise RefreshError(f"{context}: expected {expected!r}, got {actual!r}")


def parse_time(value: str | dt.datetime) -> dt.datetime:
    parsed = value if isinstance(value, dt.datetime) else dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise RefreshError("timestamp lacks timezone")
    return parsed.astimezone(dt.timezone.utc)


def validate_candidate(path: Path = CANDIDATE) -> dict[str, Any]:
    value = read_yaml(path)
    expect(value.get("kind"), "PlatformBaselineTokenRefreshCandidate", "kind")
    spec = value["spec"]
    expect(spec["state"], "PREPARED-NO-GO", "state")
    expect(spec["ticket"], "OK-141", "ticket")
    expect(spec["expirationSeconds"], 10800, "token lifetime")
    expect(spec["requestedAudiences"], [], "default audience")
    expect(digest(HERE / spec["tool"]["path"]), spec["tool"]["digest"], "tool")
    authorization = spec["authorization"]
    expect(authorization["decision"], "NO-GO", "authorization")
    if any(item for key, item in authorization.items() if key.endswith("Granted")):
        raise RefreshError("candidate grants live authority")
    return value


def validate_grant(
    candidate_path: Path,
    grant_path: Path,
    current: dt.datetime | None = None,
) -> dict[str, Any]:
    validate_candidate(candidate_path)
    grant = read_yaml(grant_path)
    expect(grant.get("kind"), "PlatformBaselineTokenRefreshGrant", "grant kind")
    spec = grant["spec"]
    expect(spec["decision"], "GO", "decision")
    expect(spec["candidateDigest"], digest(candidate_path), "candidate digest")
    expect(spec["authority"], "github:arashkaffamanesh", "authority")
    required = (
        "registrationSecretReadGranted",
        "workloadAdminCredentialUseGranted",
        "tokenRequestGranted",
        "targetProbeGranted",
        "registrationSecretReplaceGranted",
        "applicationObservationGranted",
    )
    forbidden = (
        "retryGranted",
        "rollbackGranted",
        "cleanupGranted",
        "failureInjectionGranted",
        "evidencePublicationGranted",
    )
    if any(spec.get(key) is not True for key in required):
        raise RefreshError("grant lacks required authority")
    if any(spec.get(key) is not False for key in forbidden):
        raise RefreshError("grant expands forbidden authority")
    if spec.get("singleRun") is not True or spec.get("consumed") is not False:
        raise RefreshError("grant is not an unused single run")
    point = current or dt.datetime.now(dt.timezone.utc)
    issued, expires = parse_time(spec["issuedAt"]), parse_time(spec["expiresAt"])
    if not issued <= point <= expires or expires - issued > dt.timedelta(minutes=35):
        raise RefreshError("grant inactive or exceeds 35 minutes")
    return grant


def safe_file(path: Path, expected_digest: str) -> None:
    if path.is_symlink() or not path.is_file() or digest(path) != expected_digest:
        raise RefreshError("bound file identity mismatch")
    if path.suffix in (".yaml", ".yml") and (path.stat().st_mode & 0o777) != 0o600:
        raise RefreshError("unsafe kubeconfig mode")


def raw(
    client: Path,
    kubeconfig: Path,
    verb: str,
    uri: str,
    payload: bytes | None = None,
    runner: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    command = [str(client), "--kubeconfig", str(kubeconfig), verb, "--raw", uri]
    if payload is not None:
        command.extend(["--filename", "-"])
    result = runner(
        command,
        input=payload,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise RefreshError(f"bounded {verb} failed; output suppressed")
    value = json.loads(result.stdout)
    if not isinstance(value, dict):
        raise RefreshError("API returned non-object")
    return value


def decode_jwt(token: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 3:
        raise RefreshError("TokenRequest returned non-JWT")
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    value = json.loads(base64.urlsafe_b64decode(payload))
    if not isinstance(value, dict):
        raise RefreshError("JWT claims are not a mapping")
    return value


def kubeconfig_identity(raw_value: bytes) -> tuple[str, str, dict[str, Any]]:
    value = yaml.safe_load(raw_value)
    clusters = value.get("clusters", []) if isinstance(value, dict) else []
    if len(clusters) != 1:
        raise RefreshError("workload kubeconfig must have exactly one cluster")
    cluster = clusters[0].get("cluster", {})
    server, ca_data = cluster.get("server"), cluster.get("certificate-authority-data")
    if not isinstance(server, str) or not isinstance(ca_data, str):
        raise RefreshError("workload kubeconfig lacks target identity")
    return sha_bytes(server.encode()), sha_bytes(base64.b64decode(ca_data, validate=True)), cluster


def registration_identity(secret: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    data = secret.get("data", {})
    if sorted(data) != ["clusterResources", "config", "name", "namespaces", "project", "server"]:
        raise RefreshError("registration Secret data shape drift")
    server = base64.b64decode(data["server"], validate=True)
    config = json.loads(base64.b64decode(data["config"], validate=True))
    ca_data = config.get("tlsClientConfig", {}).get("caData", "")
    if not ca_data:
        raise RefreshError("registration Secret lacks CA identity")
    return sha_bytes(server), sha_bytes(base64.b64decode(ca_data, validate=True)), config


def replacement_secret(
    current: dict[str, Any], token: str, expiration: str
) -> tuple[bytes, set[str]]:
    metadata = current.get("metadata", {})
    if not metadata.get("uid") or not metadata.get("resourceVersion"):
        raise RefreshError("registration Secret lacks concurrency identity")
    result = copy.deepcopy(current)
    result["metadata"].pop("managedFields", None)
    result["metadata"].pop("selfLink", None)
    result["metadata"].setdefault("annotations", {})[
        "openkubes.io/token-expiration"
    ] = expiration
    before_data = copy.deepcopy(result["data"])
    config = json.loads(base64.b64decode(result["data"]["config"], validate=True))
    before_config = copy.deepcopy(config)
    config["bearerToken"] = token
    result["data"]["config"] = base64.b64encode(
        json.dumps(config, sort_keys=True, separators=(",", ":")).encode()
    ).decode()
    unchanged_keys = set(before_data) - {"config"}
    if any(result["data"][key] != before_data[key] for key in unchanged_keys):
        raise RefreshError("registration Secret non-config data changed")
    before_config.pop("bearerToken", None)
    comparable = copy.deepcopy(config)
    comparable.pop("bearerToken", None)
    if comparable != before_config:
        raise RefreshError("registration config changed beyond bearerToken")
    result.pop("status", None)
    return json.dumps(result, sort_keys=True, separators=(",", ":")).encode(), unchanged_keys


def application_ready(value: dict[str, Any], revision: str) -> bool:
    status = value.get("status", {})
    error_types = {
        item.get("type")
        for item in status.get("conditions", [])
        if item.get("type") not in (None, "OrphanedResourceWarning")
    }
    return (
        status.get("sync", {}).get("status") == "Synced"
        and status.get("sync", {}).get("revision") == revision
        and status.get("health", {}).get("status") == "Healthy"
        and not error_types
    )


def write_exclusive(path: Path, value: dict[str, Any]) -> None:
    payload = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(payload)


def execute(
    candidate_path: Path,
    grant_path: Path,
    runner: Callable[..., Any] = subprocess.run,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    candidate = validate_candidate(candidate_path)
    grant = validate_grant(candidate_path, grant_path)
    spec, grant_spec = candidate["spec"], grant["spec"]
    shared_client, target_client = Path(spec["shared"]["clientPath"]), Path(spec["target"]["clientPath"])
    shared_config, target_config = Path(spec["shared"]["kubeconfigPath"]), Path(spec["target"]["kubeconfigPath"])
    safe_file(shared_client, spec["shared"]["clientDigest"])
    safe_file(target_client, spec["target"]["clientDigest"])
    safe_file(shared_config, spec["shared"]["kubeconfigDigest"])
    safe_file(target_config, spec["target"]["kubeconfigDigest"])
    output, ephemeral = Path(grant_spec["outputPath"]), Path(spec["ephemeralTokenKubeconfigPath"])
    if output.exists() or ephemeral.exists() or ephemeral.is_symlink():
        raise RefreshError("exclusive runtime path exists")
    evidence: dict[str, Any] = {
        "apiVersion": "evidence.openkubes.io/v1alpha1",
        "kind": "PlatformBaselineTokenRefreshEvidence",
        "candidateDigest": digest(candidate_path),
        "grantID": grant_spec["grantID"],
        "registrationSecretRead": False,
        "tokenRequested": False,
        "targetProbeSucceeded": False,
        "registrationSecretReplaced": False,
        "allApplicationsSyncedHealthy": False,
        "retryPerformed": False,
        "rollbackOrCleanupPerformed": False,
        "failureInjectionPerformed": False,
        "credentialPayloadRetained": False,
        "endpointPayloadRetained": False,
        "rawObjectsRetained": False,
    }
    token = ""
    try:
        registration = raw(
            shared_client,
            shared_config,
            "get",
            spec["shared"]["registrationSecretURI"],
            runner=runner,
        )
        evidence["registrationSecretRead"] = True
        uid, resource_version = registration["metadata"]["uid"], registration["metadata"]["resourceVersion"]
        reg_server, reg_ca, _ = registration_identity(registration)
        target_raw = target_config.read_bytes()
        target_server, target_ca, target_cluster = kubeconfig_identity(target_raw)
        if (reg_server, reg_ca) != (target_server, target_ca):
            raise RefreshError("registration and target identity differ")
        target_raw = b""

        request = {
            "apiVersion": "authentication.k8s.io/v1",
            "kind": "TokenRequest",
            "spec": {"expirationSeconds": spec["expirationSeconds"]},
        }
        response = raw(
            target_client,
            target_config,
            "create",
            spec["target"]["tokenRequestURI"],
            json.dumps(request, sort_keys=True, separators=(",", ":")).encode(),
            runner,
        )
        token = str(response.get("status", {}).get("token", ""))
        expiration = str(response.get("status", {}).get("expirationTimestamp", ""))
        claims = decode_jwt(token)
        current_epoch = int(dt.datetime.now(dt.timezone.utc).timestamp())
        audience = claims.get("aud")
        audiences = [audience] if isinstance(audience, str) else list(audience or [])
        checks = {
            "subjectMatches": claims.get("sub") == spec["target"]["serviceAccountSubject"],
            "tokenUnexpired": int(claims.get("exp", 0)) > current_epoch,
            "tokenLifetimeBounded": int(claims.get("exp", 0)) - current_epoch <= 10900,
            "defaultAudienceReturned": bool(audiences),
            "expirationReturned": bool(expiration),
        }
        if not all(checks.values()):
            raise RefreshError("TokenRequest claims failed closed")
        evidence["tokenRequested"] = True

        ephemeral_value = {
            "apiVersion": "v1",
            "kind": "Config",
            "clusters": [{"name": "target", "cluster": target_cluster}],
            "users": [{"name": "token", "user": {"token": token}}],
            "contexts": [{"name": "target", "context": {"cluster": "target", "user": "token"}}],
            "current-context": "target",
        }
        descriptor = os.open(ephemeral, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(yaml.safe_dump(ephemeral_value, sort_keys=True).encode())
        raw(target_client, ephemeral, "get", spec["target"]["probeURI"], runner=runner)
        evidence["targetProbeSucceeded"] = True

        payload, unchanged_keys = replacement_secret(registration, token, expiration)
        replaced = raw(
            shared_client,
            shared_config,
            "replace",
            spec["shared"]["registrationSecretURI"],
            payload,
            runner,
        )
        if replaced.get("metadata", {}).get("uid") != uid or replaced.get("metadata", {}).get("resourceVersion") == resource_version:
            raise RefreshError("registration Secret concurrency postcondition failed")
        if set(replaced.get("data", {})) != set(registration.get("data", {})):
            raise RefreshError("registration Secret data-key postcondition failed")
        evidence["registrationSecretReplaced"] = True
        evidence["unchangedDataFieldCount"] = len(unchanged_keys)

        applications = spec["shared"]["applicationURIs"]
        for iteration in range(1, spec["observation"]["maximumIterations"] + 1):
            current = {
                name: raw(shared_client, shared_config, "get", uri, runner=runner)
                for name, uri in applications.items()
            }
            if all(application_ready(item, spec["sourceRevision"]) for item in current.values()):
                evidence["allApplicationsSyncedHealthy"] = True
                evidence["observationIteration"] = iteration
                break
            if iteration < spec["observation"]["maximumIterations"]:
                sleeper(spec["observation"]["intervalSeconds"])
        if not evidence["allApplicationsSyncedHealthy"]:
            raise RefreshError("Platform baseline did not recover")
        evidence["state"] = "PASS-PLATFORM-BASELINE-RESTORED"
        write_exclusive(output, evidence)
        return {"state": evidence["state"], "evidenceDigest": digest(output)}
    except Exception as error:
        evidence["state"] = "STOP-PRESERVE-NO-RETRY"
        evidence["failureClass"] = type(error).__name__
        if not output.exists():
            write_exclusive(output, evidence)
        raise
    finally:
        token = ""
        ephemeral.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "execute"))
    parser.add_argument("--candidate", type=Path, default=CANDIDATE)
    parser.add_argument("--grant", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "verify":
            validate_candidate(args.candidate.resolve())
            print(digest(args.candidate.resolve()))
        else:
            if args.grant is None or not args.execute:
                raise RefreshError("execute requires --grant and --execute")
            print(json.dumps(execute(args.candidate.resolve(), args.grant.resolve()), sort_keys=True))
        return 0
    except Exception as error:
        print(f"ERROR: {type(error).__name__}: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
