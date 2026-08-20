#!/usr/bin/env python3
"""Fail-closed D1 read-only target-correlation preflight."""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml


class PreflightError(ValueError):
    pass


HERE = Path(__file__).resolve().parent
EXPECTED_BASE = "5730b05149acb138db9a9e5e4d6791aaa73b6056"
EXPECTED_PROTOCOL_SEMANTIC = "sha256:4cd457c5f40bdf3ae871cbe56ba7c151f7ac3242bd73129557f25cf620a2d0bc"
EXPECTED_D0_CANDIDATE = "sha256:771c09a760940afa8c04a26a79e3e921c11d87d96ae949c1781f4fd7c846074b"
EXPECTED_D0_CLOSURE = "sha256:eb4f5366e95519ffe2ad21971a0efca928858e6dc462be72579c77ebccfb1edb"
EXPECTED_KUBECTL = "sha256:bb211f2b31f2b3bc60562b44cc1e3b712a16a98e9072968ba255beb04cefcfdf"
APP_IDS = ("application-dashboards", "application-alerting", "application-core")
APP_NAMES = {
    "application-dashboards": "disposable-ok141-observability-dashboards",
    "application-alerting": "disposable-ok141-observability-alerting",
    "application-core": "disposable-ok141-observability-core",
}


def sha256_bytes(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def file_digest(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_digest(value: object) -> str:
    return sha256_bytes(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def parse_time(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def read_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text())
    if not isinstance(value, dict):
        raise PreflightError(f"{path}: expected one YAML object")
    return value


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise PreflightError(f"{path}: expected one JSON object")
    return value


def write_exclusive(path: Path, value: object) -> None:
    if path.parent != Path("/private/tmp") or path.exists():
        raise PreflightError(f"unsafe or existing private output: {path}")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump(value, stream, sort_keys=True, separators=(",", ":"))
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def verify_candidate(path: Path) -> dict[str, Any]:
    candidate = read_yaml(path)
    spec = candidate.get("spec", {})
    errors: list[str] = []
    if spec.get("version") != "ok141-delete-d1-preflight/v1" or spec.get("state") != "READY-FOR-EXPLICIT-READ-ONLY-GRANT":
        errors.append("candidate identity mismatch")
    if spec.get("baseCommit") != EXPECTED_BASE:
        errors.append("base commit mismatch")
    bindings = spec.get("bindings", {})
    protocol = (path.parent / bindings.get("protocolPath", "")).resolve()
    d0_candidate = (path.parent / bindings.get("d0CandidatePath", "")).resolve()
    d0_closure = (path.parent / bindings.get("d0ClosurePath", "")).resolve()
    if bindings.get("protocolSemanticDigest") != EXPECTED_PROTOCOL_SEMANTIC or canonical_digest(read_yaml(protocol)) != EXPECTED_PROTOCOL_SEMANTIC:
        errors.append("protocol binding mismatch")
    if bindings.get("d0CandidateDigest") != EXPECTED_D0_CANDIDATE or file_digest(d0_candidate) != EXPECTED_D0_CANDIDATE:
        errors.append("D0 candidate binding mismatch")
    if bindings.get("d0ClosureDigest") != EXPECTED_D0_CLOSURE or file_digest(d0_closure) != EXPECTED_D0_CLOSURE:
        errors.append("D0 closure binding mismatch")
    queries = spec.get("queries", {})
    items = queries.get("items", [])
    if queries.get("plane") != "ok-shared" or queries.get("sealedGetCount") != 6 or len(items) != 6:
        errors.append("query boundary mismatch")
    if any(not item.get("rawURI", "").startswith(("/api/", "/apis/")) for item in items):
        errors.append("invalid raw query")
    assertions = spec.get("assertions", {})
    required_true = ("requireNoFinalizers", "requireNoDeletionTimestamp", "compareDestinationToRegistrationInMemory", "persistTargetIdentityDigestOnly", "requireExactD0MetadataEquality")
    if any(assertions.get(key) is not True for key in required_true):
        errors.append("assertion boundary mismatch")
    tool = spec.get("tool", {})
    if tool.get("executorDigest") != file_digest(Path(__file__).resolve()) or tool.get("kubectlDigest") != EXPECTED_KUBECTL:
        errors.append("tool binding mismatch")
    outputs = spec.get("privateOutputs", {})
    if outputs.get("bindingPath") != "/private/tmp/ok141-delete-d1-runtime-binding-v1.json" or outputs.get("evidencePath") != "/private/tmp/ok141-delete-d1-preflight-evidence-v1.json":
        errors.append("private output path mismatch")
    if outputs.get("mode") != "0600" or outputs.get("maximumBindingAgeMinutes") != 5:
        errors.append("private output boundary mismatch")
    auth = spec.get("authorization", {})
    if auth.get("decision") != "NO-GO" or any(value is not False for key, value in auth.items() if key.endswith("Granted")):
        errors.append("candidate grants authority")
    if errors:
        raise PreflightError("; ".join(errors))
    return candidate


def verify_grant(candidate_path: Path, grant_path: Path, d0_path: Path, now: dt.datetime | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    candidate = verify_candidate(candidate_path)
    grant = read_yaml(grant_path).get("spec", {})
    d0 = read_json(d0_path)
    errors: list[str] = []
    if grant.get("state") != "GRANTED" or grant.get("candidateDigest") != file_digest(candidate_path):
        errors.append("grant identity mismatch")
    if grant.get("d0BindingDigest") != file_digest(d0_path):
        errors.append("D0 runtime digest mismatch")
    if grant.get("maximumRuns") != 1 or grant.get("consumed") is not False:
        errors.append("grant is not fresh and single-use")
    for key in ("readOnlyAuthorized", "credentialUseAuthorized", "secretContentReadAuthorized"):
        if grant.get(key) is not True:
            errors.append(f"{key} is required")
    for key in ("mutationAuthorized", "deleteAuthorized", "cleanupAuthorized", "retryAuthorized", "rollbackAuthorized", "publicationAuthorized", "outageAuthorized", "failureInjectionAuthorized"):
        if grant.get(key) is not False:
            errors.append(f"{key} must be false")
    current = now or dt.datetime.now(dt.timezone.utc)
    start, end = parse_time(grant.get("notBefore", "")), parse_time(grant.get("notAfter", ""))
    if not start <= current <= end or (end - start).total_seconds() > 600:
        errors.append("grant window inactive or exceeds ten minutes")
    if d0.get("format") != "ok141-delete-d0-runtime-binding/v3" or d0.get("candidateDigest") != EXPECTED_D0_CANDIDATE:
        errors.append("D0 runtime identity mismatch")
    if current > parse_time(d0.get("expiresAt", "")):
        errors.append("D0 runtime binding expired")
    if d0.get("mutationPerformed") is not False or d0.get("deletePerformed") is not False:
        errors.append("D0 runtime boundary mismatch")
    outputs = candidate["spec"]["privateOutputs"]
    if grant.get("bindingPath") != outputs["bindingPath"] or grant.get("evidencePath") != outputs["evidencePath"]:
        errors.append("grant output paths differ")
    if errors:
        raise PreflightError("; ".join(errors))
    return candidate, d0


def decode_field(secret: dict[str, Any], key: str) -> str:
    try:
        return base64.b64decode(secret.get("data", {})[key], validate=True).decode()
    except (KeyError, ValueError, UnicodeDecodeError) as error:
        raise PreflightError(f"registration field {key} invalid") from error


def metadata_identity(item: dict[str, Any]) -> dict[str, str]:
    metadata = item.get("metadata", {})
    result = {key: metadata.get(key) for key in ("name", "namespace", "uid", "resourceVersion")}
    if not all(result.values()):
        raise PreflightError("incomplete metadata identity")
    if metadata.get("finalizers", []) or metadata.get("deletionTimestamp") is not None:
        raise PreflightError("target has finalizer or deletion timestamp")
    return result


def build_binding(candidate: dict[str, Any], d0: dict[str, Any], live: dict[str, Any], now: dt.datetime) -> dict[str, Any]:
    d0_shared = d0["planes"]["ok-shared"]
    applications = [live[query_id] for query_id in APP_IDS]
    project_items = [item for item in live["project-applications"].get("items", []) if item.get("spec", {}).get("project") == "openkubes-disposable"]
    if len(project_items) != 3 or {item.get("metadata", {}).get("name") for item in project_items} != set(APP_NAMES.values()):
        raise PreflightError("project Application membership mismatch")
    secret = live["registration-secret"]
    if secret.get("metadata", {}).get("labels", {}).get("argocd.argoproj.io/secret-type") != "cluster":
        raise PreflightError("registration Secret type mismatch")
    registered_server = decode_field(secret, "server")
    registered_name = decode_field(secret, "name")
    if not registered_server or not registered_name:
        raise PreflightError("registration identity empty")
    target_digest = canonical_digest({"server": registered_server, "name": registered_name})

    records = []
    for query_id, application in zip(APP_IDS, applications, strict=True):
        spec = application.get("spec", {})
        status = application.get("status", {})
        if spec.get("project") != "openkubes-disposable" or status.get("sync", {}).get("status") != "Synced" or status.get("health", {}).get("status") != "Healthy":
            raise PreflightError("Application baseline mismatch")
        destination = spec.get("destination", {})
        if destination.get("server"):
            if destination["server"] != registered_server:
                raise PreflightError("Application server target mismatch")
        elif destination.get("name") != registered_name:
            raise PreflightError("Application named target mismatch")
        current = metadata_identity(application)
        previous = d0_shared[query_id][0]
        if any(current[key] != previous.get(key) for key in ("name", "namespace", "uid", "resourceVersion")):
            raise PreflightError("Application differs from D0 binding")
        records.append({"queryID": query_id, **current})

    for query_id in ("app-project", "registration-secret"):
        current = metadata_identity(live[query_id])
        previous = d0_shared[query_id][0]
        if any(current[key] != previous.get(key) for key in ("name", "namespace", "uid", "resourceVersion")):
            raise PreflightError(f"{query_id} differs from D0 binding")
        records.append({"queryID": query_id, **current})

    return {
        "format": "ok141-delete-d1-runtime-binding/v1",
        "state": "PASS-D1-PREFLIGHT-PRIVATE-BOUND-NO-GO",
        "candidateDigest": canonical_digest(candidate),
        "d0BindingDigest": canonical_digest(d0),
        "observedAt": now.isoformat(),
        "expiresAt": (now + dt.timedelta(minutes=5)).isoformat(),
        "targetIdentityDigest": target_digest,
        "deleteOrder": records,
        "secretContentRetained": False,
        "endpointRetained": False,
        "mutationPerformed": False,
        "deletePerformed": False,
    }


def exact_get(kubectl: Path, kubeconfig: Path, uri: str) -> dict[str, Any]:
    result = subprocess.run([str(kubectl), "--kubeconfig", str(kubeconfig), "get", "--raw", uri], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20, check=False)
    if result.returncode != 0 or len(result.stdout) > 5 * 1024 * 1024:
        raise PreflightError("exact GET failed or exceeded bound")
    value = json.loads(result.stdout)
    if not isinstance(value, dict):
        raise PreflightError("invalid GET response")
    return value


def snapshot(candidate_path: Path, grant_path: Path, d0_path: Path, kubectl: Path) -> dict[str, Any]:
    candidate, d0 = verify_grant(candidate_path, grant_path, d0_path)
    if file_digest(kubectl) != EXPECTED_KUBECTL:
        raise PreflightError("kubectl digest mismatch")
    kubeconfig = Path(candidate["spec"]["queries"]["kubeconfigPath"])
    if kubeconfig.is_symlink() or not kubeconfig.is_file() or stat.S_IMODE(kubeconfig.stat().st_mode) != 0o600:
        raise PreflightError("unsafe kubeconfig")
    live = {query["id"]: exact_get(kubectl, kubeconfig, query["rawURI"]) for query in candidate["spec"]["queries"]["items"]}
    now = dt.datetime.now(dt.timezone.utc)
    binding = build_binding(candidate, d0, live, now)
    outputs = candidate["spec"]["privateOutputs"]
    binding_path = Path(outputs["bindingPath"])
    write_exclusive(binding_path, binding)
    evidence = {
        "format": "ok141-delete-d1-preflight-private-evidence/v1",
        "state": "PASS-D1-PREFLIGHT-PRIVATE-BOUND-NO-GO",
        "candidateDigest": file_digest(candidate_path),
        "grantID": read_yaml(grant_path)["spec"]["grantID"],
        "bindingDigest": file_digest(binding_path),
        "sealedGetCount": 6,
        "deleteTargetCount": 5,
        "targetCorrelationPassed": True,
        "secretContentRetained": False,
        "endpointRetained": False,
        "mutationPerformed": False,
        "deletePerformed": False,
    }
    write_exclusive(Path(outputs["evidencePath"]), evidence)
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "verify-grant", "snapshot"))
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--grant", type=Path)
    parser.add_argument("--d0-binding", type=Path)
    parser.add_argument("--kubectl", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    candidate_path = args.candidate.resolve()
    if args.command == "verify":
        candidate = verify_candidate(candidate_path)
        print(json.dumps({"candidateDigest": file_digest(candidate_path), "semanticDigest": canonical_digest(candidate), "state": "PASS-D1-PREFLIGHT-CANDIDATE-OFFLINE-NO-GO"}, sort_keys=True))
    elif args.command == "verify-grant":
        if args.grant is None or args.d0_binding is None:
            raise PreflightError("grant and D0 binding are required")
        verify_grant(candidate_path, args.grant.resolve(), args.d0_binding.resolve())
        print(file_digest(args.grant.resolve()))
    else:
        if not args.execute or args.grant is None or args.d0_binding is None or args.kubectl is None:
            raise PreflightError("snapshot requires --execute, grant, D0 binding and kubectl")
        print(json.dumps(snapshot(candidate_path, args.grant.resolve(), args.d0_binding.resolve(), args.kubectl.resolve()), sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (PreflightError, OSError, ValueError, KeyError, json.JSONDecodeError, subprocess.TimeoutExpired) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
