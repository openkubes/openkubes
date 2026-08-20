#!/usr/bin/env python3
"""Execute the exact OK-141 D1 GitOps-quiescence deletion once."""

from __future__ import annotations

import argparse
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


class D1Error(ValueError):
    pass


HERE = Path(__file__).resolve().parent
EXPECTED_BASE = "29c961a36b03d9de226de28b2c6aab48842702b3"
EXPECTED_PROTOCOL = "sha256:4cd457c5f40bdf3ae871cbe56ba7c151f7ac3242bd73129557f25cf620a2d0bc"
EXPECTED_PREFLIGHT_CANDIDATE = "sha256:c5c78e4d82b689f645c63be3ccbb3a3c4c2f890b01d7004daad7915da6fa7276"
EXPECTED_PREFLIGHT_EXECUTOR = "sha256:08970c4761d7a4265b900fdb1e98433cd02a5deeb1248f6975795e445b8eae99"
EXPECTED_PREFLIGHT_CLOSURE = "sha256:3ab1b4b7421554198881324033b1be527ac0b3857744cbd6fd2adb6fddfec9dc"
EXPECTED_KUBECTL = "sha256:bb211f2b31f2b3bc60562b44cc1e3b712a16a98e9072968ba255beb04cefcfdf"
EXPECTED_QUERY_IDS = (
    "application-dashboards", "application-alerting", "application-core",
    "registration-secret", "app-project",
)


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
        raise D1Error(f"{path}: expected one YAML object")
    return value


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise D1Error(f"{path}: expected one JSON object")
    return value


def write_exclusive(path: Path, value: object) -> None:
    if path.parent != Path("/private/tmp") or path.exists() or path.is_symlink():
        raise D1Error(f"unsafe or existing private output: {path}")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump(value, stream, sort_keys=True, separators=(",", ":"))
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def bound_file(candidate_path: Path, relative: str, expected: str, semantic: bool = False) -> None:
    path = (candidate_path.parent / relative).resolve()
    if not path.is_file():
        raise D1Error(f"missing bound file: {path}")
    actual = canonical_digest(read_yaml(path)) if semantic else file_digest(path)
    if actual != expected:
        raise D1Error(f"bound file digest mismatch: {path.name}")


def verify_candidate(path: Path) -> dict[str, Any]:
    candidate = read_yaml(path)
    spec = candidate.get("spec", {})
    errors: list[str] = []
    if spec.get("version") != "ok141-delete-d1-execution/v1" or spec.get("state") != "OFFLINE-PREPARED-BLOCKED-NO-GO":
        errors.append("candidate identity mismatch")
    if spec.get("baseCommit") != EXPECTED_BASE:
        errors.append("base commit mismatch")
    bindings = spec.get("bindings", {})
    checks = (
        ("protocolPath", EXPECTED_PROTOCOL, True),
        ("d1PreflightCandidatePath", EXPECTED_PREFLIGHT_CANDIDATE, False),
        ("d1PreflightExecutorPath", EXPECTED_PREFLIGHT_EXECUTOR, False),
        ("d1PreflightClosurePath", EXPECTED_PREFLIGHT_CLOSURE, False),
    )
    for key, expected, semantic in checks:
        try:
            bound_file(path, bindings.get(key, ""), expected, semantic)
        except (D1Error, OSError, ValueError):
            errors.append(f"{key} binding mismatch")
    if bindings.get("protocolSemanticDigest") != EXPECTED_PROTOCOL:
        errors.append("declared protocol digest mismatch")
    if bindings.get("d1PreflightCandidateDigest") != EXPECTED_PREFLIGHT_CANDIDATE:
        errors.append("declared preflight candidate mismatch")
    if bindings.get("d1PreflightExecutorDigest") != EXPECTED_PREFLIGHT_EXECUTOR:
        errors.append("declared preflight executor mismatch")
    if bindings.get("d1PreflightClosureDigest") != EXPECTED_PREFLIGHT_CLOSURE:
        errors.append("declared preflight closure mismatch")

    records = spec.get("deleteOrder", [])
    if tuple(record.get("queryID") for record in records) != EXPECTED_QUERY_IDS:
        errors.append("delete order mismatch")
    if len(records) != 5 or len({record.get("rawURI") for record in records}) != 5:
        errors.append("delete target uniqueness mismatch")
    if any(record.get("namespace") != "argocd" or not record.get("rawURI", "").startswith(("/api/", "/apis/")) for record in records):
        errors.append("delete target boundary mismatch")

    operation = spec.get("operation", {})
    expected_operation = {
        "propagationPolicy": "Background",
        "preconditionFields": ["uid", "resourceVersion"],
        "exactGetImmediatelyBeforeDelete": True,
        "requireApplicationFinalizersAbsent": True,
        "requireDeletionTimestampAbsent": True,
        "absencePollIntervalSeconds": 2,
        "absencePollMaximumIterations": 30,
        "onFailure": "STOP-PRESERVE-NO-RETRY",
    }
    if operation != expected_operation:
        errors.append("operation boundary mismatch")
    input_spec = spec.get("input", {})
    if input_spec != {
        "bindingPath": "/private/tmp/ok141-delete-d1-runtime-binding-v2.json",
        "requiredFormat": "ok141-delete-d1-runtime-binding/v2",
        "requiredState": "PASS-D1-PREFLIGHT-PRIVATE-BOUND-NO-GO",
        "maximumAgeMinutes": 5,
        "mode": "0600",
    }:
        errors.append("private input boundary mismatch")
    output = spec.get("privateOutput", {})
    if output != {"evidencePath": "/private/tmp/ok141-delete-d1-execution-evidence-v1.json", "mode": "0600"}:
        errors.append("private output boundary mismatch")
    tool = spec.get("tool", {})
    if tool.get("digest") != file_digest(Path(__file__).resolve()) or tool.get("kubectlDigest") != EXPECTED_KUBECTL:
        errors.append("tool binding mismatch")
    authorization = spec.get("authorization", {})
    if authorization.get("decision") != "NO-GO" or any(value is not False for key, value in authorization.items() if key.endswith("Granted")):
        errors.append("candidate grants authority")
    if errors:
        raise D1Error("; ".join(errors))
    return candidate


def validate_binding(candidate: dict[str, Any], binding_path: Path, now: dt.datetime) -> tuple[dict[str, Any], list[dict[str, str]]]:
    if binding_path.is_symlink() or not binding_path.is_file() or stat.S_IMODE(binding_path.stat().st_mode) != 0o600:
        raise D1Error("unsafe private binding")
    binding = read_json(binding_path)
    input_spec = candidate["spec"]["input"]
    if binding.get("format") != input_spec["requiredFormat"] or binding.get("state") != input_spec["requiredState"]:
        raise D1Error("private binding identity mismatch")
    if binding.get("candidateDigest") != canonical_digest(read_yaml((HERE / "../delete-test-d1-preflight-v2/delete-d1-preflight-candidate-v2.yaml").resolve())):
        raise D1Error("private binding candidate mismatch")
    if now > parse_time(binding.get("expiresAt", "")):
        raise D1Error("private binding expired")
    if binding.get("mutationPerformed") is not False or binding.get("deletePerformed") is not False:
        raise D1Error("private binding execution boundary mismatch")
    records = binding.get("deleteOrder", [])
    if tuple(record.get("queryID") for record in records) != EXPECTED_QUERY_IDS:
        raise D1Error("private binding order mismatch")
    expected = {item["queryID"]: item for item in candidate["spec"]["deleteOrder"]}
    for record in records:
        item = expected[record["queryID"]]
        if record.get("name") != item["name"] or record.get("namespace") != item["namespace"]:
            raise D1Error("private binding target mismatch")
        if not record.get("uid") or not record.get("resourceVersion"):
            raise D1Error("private binding preconditions missing")
    return binding, records


def verify_grant(candidate_path: Path, grant_path: Path, binding_path: Path, now: dt.datetime | None = None) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, str]]]:
    candidate = verify_candidate(candidate_path)
    current = now or dt.datetime.now(dt.timezone.utc)
    binding, records = validate_binding(candidate, binding_path, current)
    grant = read_yaml(grant_path).get("spec", {})
    errors: list[str] = []
    if grant.get("state") != "GRANTED" or grant.get("candidateDigest") != file_digest(candidate_path):
        errors.append("grant candidate mismatch")
    if grant.get("d1BindingDigest") != file_digest(binding_path):
        errors.append("grant private binding mismatch")
    if grant.get("maximumRuns") != 1 or grant.get("consumed") is not False:
        errors.append("grant is not fresh and single-use")
    for key in ("credentialUseAuthorized", "mutationAuthorized", "deleteAuthorized", "partialStateAccepted"):
        if grant.get(key) is not True:
            errors.append(f"{key} is required")
    for key in ("retryAuthorized", "rollbackAuthorized", "cleanupAuthorized", "forceDeleteAuthorized", "finalizerMutationAuthorized", "d2Authorized", "d3Authorized", "outageAuthorized", "failureInjectionAuthorized"):
        if grant.get(key) is not False:
            errors.append(f"{key} must be false")
    start, end = parse_time(grant.get("notBefore", "")), parse_time(grant.get("notAfter", ""))
    if not start <= current <= end or (end - start).total_seconds() > 600:
        errors.append("grant window inactive or exceeds ten minutes")
    if grant.get("stopPolicy") != "STOP-PRESERVE-NO-RETRY":
        errors.append("grant stop policy mismatch")
    if errors:
        raise D1Error("; ".join(errors))
    return candidate, grant, records


def run_raw(kubectl: Path, kubeconfig: Path, verb: str, uri: str, payload: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    command = [str(kubectl), "--kubeconfig", str(kubeconfig), verb, "--raw", uri]
    if payload is not None:
        command += ["--filename", "-"]
    return subprocess.run(command, input=payload, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20, check=False)


def exact_get(kubectl: Path, kubeconfig: Path, uri: str) -> dict[str, Any]:
    result = run_raw(kubectl, kubeconfig, "get", uri)
    if result.returncode != 0 or len(result.stdout) > 5 * 1024 * 1024:
        raise D1Error("exact GET failed")
    value = json.loads(result.stdout)
    if not isinstance(value, dict):
        raise D1Error("exact GET returned invalid object")
    return value


def assert_current_identity(value: dict[str, Any], record: dict[str, str], application: bool) -> None:
    metadata = value.get("metadata", {})
    if any(str(metadata.get(key, "")) != str(record[key]) for key in ("name", "namespace", "uid", "resourceVersion")):
        raise D1Error("live identity differs from private binding")
    if metadata.get("deletionTimestamp") is not None:
        raise D1Error("target already deleting")
    if application and metadata.get("finalizers", []):
        raise D1Error("Application finalizer present")


def delete_payload(record: dict[str, str]) -> bytes:
    value = {
        "apiVersion": "v1",
        "kind": "DeleteOptions",
        "preconditions": {"uid": record["uid"], "resourceVersion": record["resourceVersion"]},
        "propagationPolicy": "Background",
    }
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def wait_absent(kubectl: Path, kubeconfig: Path, uri: str, maximum: int, interval: int) -> None:
    for index in range(maximum):
        result = run_raw(kubectl, kubeconfig, "get", uri)
        if result.returncode != 0 and b"not found" in result.stderr.lower():
            return
        if result.returncode != 0:
            raise D1Error("absence GET failed with non-NotFound error")
        if index + 1 < maximum:
            time.sleep(interval)
    raise D1Error("target did not become absent within bound")


def execute(candidate_path: Path, grant_path: Path, binding_path: Path, kubectl: Path) -> dict[str, Any]:
    candidate, grant, records = verify_grant(candidate_path, grant_path, binding_path)
    spec = candidate["spec"]
    if file_digest(kubectl) != EXPECTED_KUBECTL:
        raise D1Error("kubectl digest mismatch")
    kubeconfig = Path(spec["plane"]["kubeconfigPath"])
    if kubeconfig.is_symlink() or not kubeconfig.is_file() or stat.S_IMODE(kubeconfig.stat().st_mode) != 0o600:
        raise D1Error("unsafe kubeconfig")
    output = Path(spec["privateOutput"]["evidencePath"])
    deleted: list[str] = []
    stopped: D1Error | None = None
    targets = {item["queryID"]: item for item in spec["deleteOrder"]}
    try:
        for record in records:
            target = targets[record["queryID"]]
            current = exact_get(kubectl, kubeconfig, target["rawURI"])
            assert_current_identity(current, record, record["queryID"].startswith("application-"))
            result = run_raw(kubectl, kubeconfig, "delete", target["rawURI"], delete_payload(record))
            if result.returncode != 0:
                raise D1Error("preconditioned delete failed")
            wait_absent(
                kubectl, kubeconfig, target["rawURI"],
                spec["operation"]["absencePollMaximumIterations"],
                spec["operation"]["absencePollIntervalSeconds"],
            )
            deleted.append(record["queryID"])
    except D1Error as error:
        stopped = error

    evidence = {
        "format": "ok141-delete-d1-execution-private-evidence/v1",
        "state": "PASS-D1-GITOPS-QUIESCED-PRIVATE" if stopped is None else "STOP-D1-PARTIAL-PRESERVE-NO-RETRY",
        "candidateDigest": file_digest(candidate_path),
        "grantID": grant["grantID"],
        "bindingDigest": file_digest(binding_path),
        "plannedDeleteCount": 5,
        "completedDeleteCount": len(deleted),
        "completedQueryIDs": deleted,
        "allTargetsAbsent": stopped is None and len(deleted) == 5,
        "applicationFinalizersAbsentAtDelete": all(query_id in deleted for query_id in EXPECTED_QUERY_IDS[:3]),
        "optimisticConcurrencyUsed": True,
        "backgroundPropagationUsed": True,
        "targetResourceDeleteRequestedByRunner": False,
        "retryPerformed": False,
        "rollbackPerformed": False,
        "cleanupPerformed": False,
        "forceDeletePerformed": False,
        "finalizerMutationPerformed": False,
        "failureClass": None if stopped is None else "BOUND-DELETE-STOP",
        "credentialContentRetained": False,
        "rawObjectsRetained": False,
    }
    write_exclusive(output, evidence)
    if stopped is not None:
        raise D1Error(f"{stopped}; private partial-state evidence written")
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "verify-grant", "delete"))
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--grant", type=Path)
    parser.add_argument("--binding", type=Path)
    parser.add_argument("--kubectl", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    candidate_path = args.candidate.resolve()
    if args.command == "verify":
        candidate = verify_candidate(candidate_path)
        print(json.dumps({"candidateDigest": file_digest(candidate_path), "semanticDigest": canonical_digest(candidate), "state": "PASS-D1-EXECUTION-CANDIDATE-OFFLINE-NO-GO"}, sort_keys=True))
    elif args.command == "verify-grant":
        if args.grant is None or args.binding is None:
            raise D1Error("grant and binding are required")
        verify_grant(candidate_path, args.grant.resolve(), args.binding.resolve())
        print(file_digest(args.grant.resolve()))
    else:
        if not args.execute or args.grant is None or args.binding is None or args.kubectl is None:
            raise D1Error("delete requires --execute, grant, binding and kubectl")
        print(json.dumps(execute(candidate_path, args.grant.resolve(), args.binding.resolve(), args.kubectl.resolve()), sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (D1Error, OSError, ValueError, KeyError, json.JSONDecodeError, subprocess.TimeoutExpired) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
