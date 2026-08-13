#!/usr/bin/env python3
"""Offline-verifiable GO1-L DEV administrator absence preflight."""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import importlib.util
import json
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

import yaml


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
REPOSITORY = SPIKE.parents[2]
HARNESS = SPIKE / "harness"
CANDIDATE = HERE / "go1-l-admin-preflight-candidate-v1.yaml"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


V4 = load_module("ok141_phase_r_v4_admin_preflight", HARNESS / "ok141_phase_r_v4.py")
V1 = V4.V1


class PreflightError(ValueError):
    pass


def sha_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def sha(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def expect(actual: Any, expected: Any, context: str) -> None:
    if actual != expected:
        raise PreflightError(f"{context}: expected {expected!r}, got {actual!r}")


def resolve(candidate_path: Path, requested: str) -> Path:
    path = (candidate_path.parent / requested).resolve()
    if SPIKE.resolve() not in path.parents or not path.is_file():
        raise PreflightError(f"reference missing or outside spike root: {requested}")
    return path


def load_candidate(path: Path = CANDIDATE) -> dict[str, Any]:
    return V1.read_yaml_or_json(path)


def validate_candidate(candidate: dict[str, Any], candidate_path: Path = CANDIDATE) -> None:
    expect(candidate.get("apiVersion"), "security.openkubes.io/v1alpha1", "apiVersion")
    expect(candidate.get("kind"), "GO1LAdminPreflightCandidate", "kind")
    spec = candidate["spec"]
    expect(spec["version"], "ok141-go1-l-admin-preflight/v1", "version")
    expect(spec["state"], "OFFLINE-PROVEN-BLOCKED-NO-GO", "state")
    for source_name, expected_digest in (
        ("sourceDecision", "sha256:f5cebe20bfe8059cec2bbf55324d753821df0cb439568495194242d253595c5c"),
        ("sourceSubmitter", "sha256:e5b4185b7dcd4f1e3fb026d03ce29b5b35e0b6c5c6e51f29d921a240636b73cc"),
    ):
        source = spec[source_name]
        expect(sha(resolve(candidate_path, source["path"])), expected_digest, f"{source_name} source")
        expect(source["digest"], expected_digest, f"{source_name} binding")
    tool = spec["tool"]
    expect(sha(resolve(candidate_path, tool["path"])), tool["digest"], "tool digest")
    expect(tool["arbitraryQueryAllowed"], False, "query boundary")
    authorization = spec["authorization"]
    expect(authorization["decision"], "NO-GO", "authorization")
    expect(authorization["grantIDs"], [], "grant IDs")
    expect(authorization["authorizedDigest"], None, "authorized digest")
    if any(value for key, value in authorization.items() if key.endswith("Granted")):
        raise PreflightError("candidate grants credential use or execution")
    credential = spec["credentialContract"]
    expect(credential["material"], "UNRESOLVED", "credential material")
    expect(credential["administratorCredential"], True, "administrator model")
    expect(credential["fileMode"], "0600", "credential mode")
    expect(credential["outsideRepository"], True, "credential location")
    expect(credential["insecureTLSAllowed"], False, "TLS boundary")
    expect(credential["proxyURLAllowed"], False, "proxy boundary")
    expect(credential["execOrAuthProviderAllowed"], False, "credential plugin boundary")
    expect(credential["externalTokenOrCertificateFileAllowed"], False, "external credential boundary")
    expect(credential["embeddedClientCertificateKeyOrTokenRequired"], True, "embedded credential boundary")
    expected_operations = ["provider-prerequisites", "capi-lifecycle", "helmchartproxy"]
    expect([item["id"] for item in spec["operations"]], expected_operations, "operation inventory")
    expected_queries = {
        "provider-prerequisites": [
            ("namespaces", None, "disposable-ok141", "direct-absence"),
            ("roles.rbac.authorization.k8s.io", "ok-images", "disposable-ok141-talos-golden-image-cloner", "direct-absence"),
            ("rolebindings.rbac.authorization.k8s.io", "ok-images", "disposable-ok141-talos-golden-image-cloner", "direct-absence"),
        ],
        "capi-lifecycle": [
            ("namespaces", None, "disposable-ok141", "namespace-absence-implies-seven-contained-objects-absent"),
        ],
        "helmchartproxy": [
            ("helmchartproxies.addons.cluster.x-k8s.io", "disposable-ok141", "disposable-ok141-cilium", "direct-absence"),
        ],
    }
    for operation in spec["operations"]:
        expect(operation["targetPlane"], "ok-infra" if operation["id"] == "provider-prerequisites" else "ok-mgmt", f"{operation['id']} authority")
        actual = [(item["resource"], item.get("namespace"), item["name"], item["proofRule"]) for item in operation["queries"]]
        expect(actual, expected_queries[operation["id"]], f"{operation['id']} query plan")
        expect(operation["preflightState"], "NOT-RUN", f"{operation['id']} state")
    transport = spec["queryTransport"]
    expect(transport["verb"], "get", "query verb")
    expect(transport["exactNameOnly"], True, "exact-name query")
    expect(transport["listWatchAllowed"], False, "list/watch boundary")
    expect(transport["mutationAllowed"], False, "mutation boundary")


def build_command(query: dict[str, Any], credential_file: Path | None = None) -> list[str]:
    command = [
        "kubectl",
        "--kubeconfig",
        str(credential_file) if credential_file else "RUNTIME-ADMIN-CREDENTIAL-FILE",
        "get",
        query["resource"],
        query["name"],
    ]
    if query.get("namespace"):
        command.extend(["--namespace", query["namespace"]])
    command.extend(["--ignore-not-found=true", "--output=json"])
    return command


def build_plan(candidate: dict[str, Any], candidate_path: Path, operation_id: str) -> dict[str, Any]:
    validate_candidate(candidate, candidate_path)
    operations = {item["id"]: item for item in candidate["spec"]["operations"]}
    if operation_id not in operations:
        raise PreflightError("unsupported operation")
    operation = operations[operation_id]
    return {
        "operation": operation_id,
        "targetPlane": operation["targetPlane"],
        "commands": [build_command(item) for item in operation["queries"]],
        "queryCount": len(operation["queries"]),
        "credentialUseGranted": False,
        "clusterContacted": False,
        "mutationAuthorized": False,
    }


def parse_time(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise PreflightError("timestamp must include timezone")
    return parsed


def inspect_kubeconfig(path: Path) -> dict[str, str]:
    if not path.is_file() or path.is_symlink() or path.stat().st_size == 0:
        raise PreflightError("credential file must be a non-empty regular non-symlink file")
    if stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise PreflightError("credential file mode must be 0600")
    if REPOSITORY.resolve() in path.resolve().parents:
        raise PreflightError("credential file must remain outside the repository")
    config = V1.read_yaml_or_json(path)
    context_name = config.get("current-context")
    contexts = {item["name"]: item["context"] for item in config.get("contexts", [])}
    if context_name not in contexts:
        raise PreflightError("kubeconfig current-context is missing")
    cluster_name = contexts[context_name].get("cluster")
    user_name = contexts[context_name].get("user")
    clusters = {item["name"]: item["cluster"] for item in config.get("clusters", [])}
    users = {item["name"]: item["user"] for item in config.get("users", [])}
    if cluster_name not in clusters or user_name not in users:
        raise PreflightError("kubeconfig cluster or user identity is missing")
    cluster = clusters[cluster_name]
    if cluster.get("insecure-skip-tls-verify") is True or cluster.get("proxy-url"):
        raise PreflightError("insecure TLS or proxy redirection is forbidden")
    user = users[user_name]
    if user.get("exec") or user.get("auth-provider") or user.get("tokenFile"):
        raise PreflightError("external credential execution or loading is forbidden")
    embedded_certificate = user.get("client-certificate-data") and user.get("client-key-data")
    embedded_token = user.get("token")
    if not embedded_certificate and not embedded_token:
        raise PreflightError("embedded client certificate/key or token is required")
    if cluster.get("certificate-authority-data"):
        try:
            ca_bytes = base64.b64decode(cluster["certificate-authority-data"], validate=True)
        except ValueError as error:
            raise PreflightError("invalid certificate-authority-data") from error
    elif cluster.get("certificate-authority"):
        ca_path = (path.parent / cluster["certificate-authority"]).resolve()
        if not ca_path.is_file():
            raise PreflightError("certificate-authority file is missing")
        ca_bytes = ca_path.read_bytes()
    else:
        raise PreflightError("verified CA material is required")
    if not ca_bytes:
        raise PreflightError("CA material is empty")
    identity = {
        "context": context_name,
        "cluster": cluster_name,
        "user": user_name,
        "server": cluster.get("server", ""),
        "caFingerprint": sha_bytes(ca_bytes),
    }
    if not identity["server"].startswith("https://"):
        raise PreflightError("HTTPS API server is required")
    identity["credentialIdentityDigest"] = sha_bytes(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode())
    return identity


def validate_grant(
    candidate: dict[str, Any],
    candidate_path: Path,
    operation_id: str,
    grant: dict[str, Any],
    credential_identity: dict[str, str],
    now: dt.datetime,
) -> None:
    spec = grant["spec"]
    expect(spec["decision"], "GO", "grant decision")
    expect(spec["credentialUseGranted"], True, "credential-use grant")
    expect(spec["absencePreflightGranted"], True, "preflight grant")
    expect(spec["mutationAuthorized"], False, "mutation authority")
    expect(spec["operation"], operation_id, "grant operation")
    expect(spec["candidateDigest"], sha(candidate_path), "grant candidate")
    operation = next(item for item in candidate["spec"]["operations"] if item["id"] == operation_id)
    expect(spec["targetPlane"], operation["targetPlane"], "grant target")
    expect(spec["expectedServer"], credential_identity["server"], "server identity")
    expect(spec["expectedCAFingerprint"], credential_identity["caFingerprint"], "CA identity")
    if not spec.get("grantID") or spec.get("singleRun") is not True:
        raise PreflightError("single-run grant identity is missing")
    issued = parse_time(spec["issuedAt"])
    expires = parse_time(spec["expiresAt"])
    if not issued <= now <= expires or expires - issued > dt.timedelta(minutes=15):
        raise PreflightError("grant is outside its maximum 15-minute window")


def run_absence_preflight(
    candidate: dict[str, Any],
    candidate_path: Path,
    operation_id: str,
    grant: dict[str, Any],
    credential_file: Path,
    now: dt.datetime,
    runner: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    validate_candidate(candidate, candidate_path)
    identity = inspect_kubeconfig(credential_file)
    validate_grant(candidate, candidate_path, operation_id, grant, identity, now)
    operation = next(item for item in candidate["spec"]["operations"] if item["id"] == operation_id)
    observations = []
    for query in operation["queries"]:
        completed = runner(build_command(query, credential_file), check=False, capture_output=True, text=True)
        if completed.returncode != 0:
            raise PreflightError(f"absence query failed for {query['resource']}/{query['name']}")
        if completed.stdout.strip():
            raise PreflightError(f"reviewed identity already exists: {query['resource']}/{query['name']}")
        observations.append({
            "resource": query["resource"],
            "namespace": query.get("namespace"),
            "name": query["name"],
            "proofRule": query["proofRule"],
            "state": "ABSENT",
        })
    return {
        "operation": operation_id,
        "targetPlane": operation["targetPlane"],
        "server": identity["server"],
        "caFingerprint": identity["caFingerprint"],
        "credentialIdentityDigest": identity["credentialIdentityDigest"],
        "grantID": grant["spec"]["grantID"],
        "observedAt": now.isoformat().replace("+00:00", "Z"),
        "expiresAt": (now + dt.timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
        "observations": observations,
        "credentialBytesEmitted": False,
        "mutationPerformed": False,
        "preflightResult": "PASS-ABSENT",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "plan"))
    parser.add_argument("--candidate", type=Path, default=CANDIDATE)
    parser.add_argument("--operation", choices=("provider-prerequisites", "capi-lifecycle", "helmchartproxy"))
    args = parser.parse_args()
    try:
        path = args.candidate.resolve()
        candidate = load_candidate(path)
        validate_candidate(candidate, path)
        if args.command == "verify":
            result = {
                "candidateDigest": sha(path),
                "state": candidate["spec"]["state"],
                "operations": 3,
                "queries": sum(len(item["queries"]) for item in candidate["spec"]["operations"]),
                "credentialUseGranted": False,
                "clusterContacted": False,
                "mutationAuthorized": False,
            }
        else:
            if args.operation is None:
                raise PreflightError("plan requires --operation")
            result = build_plan(candidate, path, args.operation)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (KeyError, OSError, PreflightError, TypeError, ValueError, yaml.YAMLError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
