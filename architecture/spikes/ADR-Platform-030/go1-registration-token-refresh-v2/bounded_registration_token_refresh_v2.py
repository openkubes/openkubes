#!/usr/bin/env python3
"""Refresh the disposable OK-141 Argo target token exactly once.

The program deliberately uses exact raw API paths.  It never lists or watches,
and it retains no credential or endpoint payload in its evidence.
"""

from __future__ import annotations

import argparse
import base64
import copy
import datetime as dt
import hashlib
import json
import os
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import yaml


HERE = Path(__file__).resolve().parent
CANDIDATE = HERE / "registration-token-refresh-candidate-v2.json"


class RefreshError(RuntimeError):
    pass


def digest_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def digest_file(path: Path) -> str:
    return digest_bytes(path.read_bytes())


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise RefreshError(f"expected mapping: {path}")
    return value


def expect(actual: Any, expected: Any, context: str) -> None:
    if actual != expected:
        raise RefreshError(f"{context}: expected {expected!r}, got {actual!r}")


def safe_file(path: Path, expected_digest: str | None = None) -> None:
    if path.is_symlink() or not path.is_file():
        raise RefreshError(f"unsafe file: {path}")
    if stat.S_IMODE(path.stat().st_mode) != 0o600 and path.suffix in (".yaml", ".json"):
        raise RefreshError(f"unsafe mode: {path}")
    if expected_digest is not None:
        expect(digest_file(path), expected_digest, f"digest {path}")


def write_exclusive(path: Path, payload: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(descriptor, payload)
    finally:
        os.close(descriptor)


def run_raw(
    client: Path,
    kubeconfig: Path,
    method: str,
    uri: str,
    payload: bytes | None = None,
) -> tuple[int, bytes, bytes]:
    command = [str(client), "--kubeconfig", str(kubeconfig), method, "--raw", uri]
    if payload is not None:
        command += ["--filename", "-"]
    completed = subprocess.run(
        command,
        input=payload,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return completed.returncode, completed.stdout, completed.stderr


def exact_get(client: Path, kubeconfig: Path, uri: str) -> dict[str, Any]:
    code, stdout, _ = run_raw(client, kubeconfig, "get", uri)
    if code != 0:
        raise RefreshError(f"exact GET failed: {uri}; output suppressed")
    value = json.loads(stdout)
    if not isinstance(value, dict):
        raise RefreshError(f"exact GET returned non-object: {uri}")
    return value


def decode_jwt(token: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 3:
        raise RefreshError("token is not a JWT")
    padded = parts[1] + "=" * (-len(parts[1]) % 4)
    value = json.loads(base64.urlsafe_b64decode(padded))
    if not isinstance(value, dict):
        raise RefreshError("JWT payload is not an object")
    return value


def kubeconfig_identity(raw: bytes) -> tuple[str, str]:
    value = yaml.safe_load(raw)
    clusters = value.get("clusters", []) if isinstance(value, dict) else []
    if len(clusters) != 1:
        raise RefreshError("workload Kubeconfig must contain exactly one cluster")
    cluster = clusters[0].get("cluster", {})
    server = str(cluster.get("server", ""))
    ca_data = str(cluster.get("certificate-authority-data", ""))
    if not server or not ca_data:
        raise RefreshError("workload Kubeconfig lacks server or CA data")
    return digest_bytes(server.encode()), digest_bytes(base64.b64decode(ca_data, validate=True))


def validate_candidate(path: Path = CANDIDATE) -> dict[str, Any]:
    value = load_json(path)
    expect(value.get("kind"), "OK141RegistrationTokenRefreshCandidate", "kind")
    spec = value.get("spec", {})
    expect(spec.get("version"), "ok141-registration-token-refresh/v2", "version")
    expect(
        spec.get("state"),
        "LIVE-AUTHORIZED-ONCE-AFTER-ZERO-WRITE-PREFLIGHT",
        "state",
    )
    expect(spec.get("ticket"), "OK-141", "ticket")
    expect(spec.get("expirationSeconds"), 10800, "token lifetime")
    expect(spec.get("requestedAudiences"), [], "default audience")
    expect(spec.get("stopPolicy"), "STOP-PRESERVE-NO-RETRY", "stop policy")
    if not spec.get("standingGrantAcknowledged"):
        raise RefreshError("standing grant not acknowledged")
    tool = Path(spec["toolPath"])
    if not tool.is_absolute():
        tool = HERE / tool
    expect(digest_file(tool), spec.get("toolDigest"), "tool digest")
    return value


def replacement_secret(current: dict[str, Any], token: str, expiration: str) -> dict[str, Any]:
    value = copy.deepcopy(current)
    metadata = value.setdefault("metadata", {})
    metadata.pop("managedFields", None)
    metadata.pop("selfLink", None)
    annotations = metadata.setdefault("annotations", {})
    annotations["openkubes.io/token-expiration"] = expiration
    config = json.loads(base64.b64decode(value["data"]["config"], validate=True))
    config["bearerToken"] = token
    value["data"]["config"] = base64.b64encode(
        json.dumps(config, sort_keys=True, separators=(",", ":")).encode()
    ).decode()
    config = {}
    return value


def app_summary(value: dict[str, Any]) -> dict[str, Any]:
    status = value.get("status", {})
    return {
        "sync": status.get("sync", {}).get("status", "Unknown"),
        "health": status.get("health", {}).get("status", "Unknown"),
        "conditionTypes": sorted(
            item.get("type", "") for item in status.get("conditions", []) if item.get("type")
        ),
        "reconciledAtPresent": bool(status.get("reconciledAt")),
    }


def execute(candidate_path: Path) -> dict[str, Any]:
    candidate = validate_candidate(candidate_path)
    spec = candidate["spec"]
    output = Path(spec["outputPath"])
    admin_path = Path(spec["ephemeralAdminKubeconfigPath"])
    token_path = Path(spec["ephemeralTokenKubeconfigPath"])
    for path in (output, admin_path, token_path):
        if path.exists() or path.is_symlink():
            raise RefreshError(f"exclusive path already exists: {path}")

    mgmt_client = Path(spec["management"]["clientPath"])
    shared_client = Path(spec["shared"]["clientPath"])
    target_client = Path(spec["target"]["clientPath"])
    mgmt_config = Path(spec["management"]["kubeconfigPath"])
    shared_config = Path(spec["shared"]["kubeconfigPath"])
    safe_file(mgmt_client, spec["management"]["clientDigest"])
    safe_file(shared_client, spec["shared"]["clientDigest"])
    safe_file(target_client, spec["target"]["clientDigest"])
    safe_file(mgmt_config)
    safe_file(shared_config)

    token = ""
    evidence: dict[str, Any] | None = None
    try:
        kubeconfig_secret = exact_get(
            mgmt_client, mgmt_config, spec["management"]["workloadKubeconfigSecretURI"]
        )
        admin_raw = base64.b64decode(
            kubeconfig_secret.get("data", {}).get("value", ""), validate=True
        )
        if not admin_raw:
            raise RefreshError("workload Kubeconfig Secret is empty")
        workload_server_digest, workload_ca_digest = kubeconfig_identity(admin_raw)
        write_exclusive(admin_path, admin_raw)

        registration = exact_get(
            shared_client, shared_config, spec["shared"]["registrationSecretURI"]
        )
        metadata = registration.get("metadata", {})
        uid = str(metadata.get("uid", ""))
        resource_version = str(metadata.get("resourceVersion", ""))
        if not uid or not resource_version:
            raise RefreshError("registration Secret lacks UID or resourceVersion")
        registration_config = json.loads(
            base64.b64decode(registration.get("data", {}).get("config", ""), validate=True)
        )
        registration_server_digest = digest_bytes(
            base64.b64decode(
                registration.get("data", {}).get("server", ""), validate=True
            )
        )
        registration_ca_digest = digest_bytes(
            base64.b64decode(registration_config.get("tlsClientConfig", {}).get("caData", ""), validate=True)
        )
        if (registration_server_digest, registration_ca_digest) != (
            workload_server_digest,
            workload_ca_digest,
        ):
            raise RefreshError("registration target identity differs from CAPI Kubeconfig")

        request = {
            "apiVersion": "authentication.k8s.io/v1",
            "kind": "TokenRequest",
            "spec": {"expirationSeconds": spec["expirationSeconds"]},
        }
        code, stdout, _ = run_raw(
            target_client,
            admin_path,
            "create",
            spec["target"]["tokenRequestURI"],
            json.dumps(request, sort_keys=True, separators=(",", ":")).encode(),
        )
        if code != 0:
            raise RefreshError("TokenRequest failed; output suppressed")
        response = json.loads(stdout)
        token = str(response.get("status", {}).get("token", ""))
        expiration = str(response.get("status", {}).get("expirationTimestamp", ""))
        claims = decode_jwt(token)
        audience = claims.get("aud", [])
        audiences = [audience] if isinstance(audience, str) else list(audience)
        now_epoch = int(dt.datetime.now(dt.timezone.utc).timestamp())
        claim_checks = {
            "subjectMatches": claims.get("sub") == spec["target"]["serviceAccountSubject"],
            "tokenUnexpired": int(claims.get("exp", 0)) > now_epoch,
            "tokenLifetimeBounded": int(claims.get("exp", 0)) - now_epoch <= 10900,
            "expirationReturned": bool(expiration),
            "defaultAudienceReturned": bool(audiences),
        }
        if not all(claim_checks.values()):
            raise RefreshError("TokenRequest claims failed closed")

        token_kubeconfig = {
            "apiVersion": "v1",
            "kind": "Config",
            "clusters": [{"name": "target", "cluster": {
                "server": yaml.safe_load(admin_raw)["clusters"][0]["cluster"]["server"],
                "certificate-authority-data": yaml.safe_load(admin_raw)["clusters"][0]["cluster"]["certificate-authority-data"],
            }}],
            "users": [{"name": "token", "user": {"token": token}}],
            "contexts": [{"name": "target", "context": {"cluster": "target", "user": "token"}}],
            "current-context": "target",
        }
        write_exclusive(token_path, yaml.safe_dump(token_kubeconfig, sort_keys=True).encode())
        probe_code, _, _ = run_raw(
            target_client, token_path, "get", spec["target"]["probeURI"]
        )
        if probe_code != 0:
            raise RefreshError("fresh token target probe failed; output suppressed")

        replacement = replacement_secret(registration, token, expiration)
        replace_code, replace_stdout, _ = run_raw(
            shared_client,
            shared_config,
            "replace",
            spec["shared"]["registrationSecretURI"],
            json.dumps(replacement, sort_keys=True, separators=(",", ":")).encode(),
        )
        if replace_code != 0:
            raise RefreshError("registration Secret replace failed; output suppressed")
        replaced = json.loads(replace_stdout)
        replaced_metadata = replaced.get("metadata", {})
        if str(replaced_metadata.get("uid", "")) != uid:
            raise RefreshError("registration Secret UID changed")
        if str(replaced_metadata.get("resourceVersion", "")) == resource_version:
            raise RefreshError("registration Secret resourceVersion did not advance")

        observations: list[dict[str, Any]] = []
        final: dict[str, dict[str, Any]] = {}
        for iteration in range(spec["observation"]["maxIterations"]):
            current: dict[str, dict[str, Any]] = {}
            for name, uri in spec["shared"]["applicationURIs"].items():
                current[name] = app_summary(exact_get(shared_client, shared_config, uri))
            observations.append({"iteration": iteration + 1, "applications": current})
            final = current
            if all(item["sync"] == "Synced" and item["health"] == "Healthy" for item in current.values()):
                break
            if iteration + 1 < spec["observation"]["maxIterations"]:
                time.sleep(spec["observation"]["intervalSeconds"])

        evidence = {
            "apiVersion": "evidence.openkubes.io/v1alpha1",
            "kind": "OK141RegistrationTokenRefreshEvidence",
            "candidateDigest": digest_file(candidate_path),
            "targetIdentityMatched": True,
            "claimChecks": claim_checks,
            "targetProbeSucceeded": True,
            "registrationSecretRead": True,
            "registrationSecretReplaced": True,
            "optimisticConcurrencyUsed": True,
            "uidPreserved": True,
            "resourceVersionAdvanced": True,
            "automaticArgoReconciliationAcknowledged": True,
            "observationIterations": len(observations),
            "finalApplications": final,
            "allApplicationsSyncedHealthy": all(
                item["sync"] == "Synced" and item["health"] == "Healthy"
                for item in final.values()
            ),
            "retryPerformed": False,
            "rollbackOrCleanupPerformed": False,
            "failureInjectionPerformed": False,
            "credentialPayloadRetained": False,
            "endpointPayloadRetained": False,
            "rawApplicationPayloadRetained": False,
            "observationDigest": digest_bytes(
                json.dumps(observations, sort_keys=True, separators=(",", ":")).encode()
            ),
        }
        evidence["semanticDigest"] = digest_bytes(
            json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
        )
    finally:
        token = ""
        admin_path.unlink(missing_ok=True)
        token_path.unlink(missing_ok=True)

    if evidence is None:
        raise RefreshError("refresh produced no evidence")
    evidence["ephemeralAdminRemoved"] = not admin_path.exists() and not admin_path.is_symlink()
    evidence["ephemeralTokenRemoved"] = not token_path.exists() and not token_path.is_symlink()
    if not evidence["ephemeralAdminRemoved"] or not evidence["ephemeralTokenRemoved"]:
        raise RefreshError("ephemeral credential cleanup failed")
    write_exclusive(
        output,
        (json.dumps(evidence, sort_keys=True, separators=(",", ":")) + "\n").encode(),
    )
    return {
        "result": "PASS-REGISTRATION-TOKEN-REFRESH"
        if evidence["allApplicationsSyncedHealthy"]
        else "STOP-PLATFORM-NOT-CONVERGED",
        "outputPath": str(output),
        "outputDigest": digest_file(output),
        "observationIterations": evidence["observationIterations"],
        "finalApplications": evidence["finalApplications"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "refresh"))
    parser.add_argument("--candidate", type=Path, default=CANDIDATE)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "verify":
            validate_candidate(args.candidate.resolve())
            print(digest_file(args.candidate.resolve()))
        else:
            if not args.execute:
                raise RefreshError("refresh requires --execute")
            print(json.dumps(execute(args.candidate.resolve()), sort_keys=True))
        return 0
    except Exception as error:
        print(f"ERROR: {type(error).__name__}: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
