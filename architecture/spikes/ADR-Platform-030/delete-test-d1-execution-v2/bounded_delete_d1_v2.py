#!/usr/bin/env python3
"""D1 execution v2 bound to the ordered v3 preflight."""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import stat
import sys
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V1 = load_module("ok141_delete_d1_execution_v1_for_v2", (HERE / "../delete-test-d1-execution-v1/bounded_delete_d1_v1.py").resolve())
D1Error = V1.D1Error
file_digest = V1.file_digest
canonical_digest = V1.canonical_digest
parse_time = V1.parse_time
read_yaml = V1.read_yaml
read_json = V1.read_json
write_exclusive = V1.write_exclusive

EXPECTED_BASE = "47238217e187e07e7b21f5b7231790c969a9d2db"
EXPECTED_V1_CANDIDATE = "sha256:2f8bfa6e6a622442381e57c56787a5c7804ddc40a64aefb219884ce3057848e3"
EXPECTED_V1_EXECUTOR = "sha256:8f941d5745bb7823c0ad5f449602606fe4b907a113acdae330df83b9e865c359"
EXPECTED_V3_PREFLIGHT_CANDIDATE = "sha256:7bcb68bdac1c8b17aaa3acf370ac7d4d9acc25b8d4395abd816ea6d7da0a4e9e"
EXPECTED_V3_PREFLIGHT_EXECUTOR = "sha256:92e2b9a7e923037e07e265cf59b4ae67b5aaa32cefdd043d8b594680c012ba9f"
EXPECTED_STOPPED = "sha256:a13be619262ab926550a992ac5535b7595fcdb1a05cc25510f22bed4f8776b44"
EXPECTED_KUBECTL = V1.EXPECTED_KUBECTL
EXPECTED_ORDER = V1.EXPECTED_QUERY_IDS


def verify_candidate(path: Path) -> dict[str, Any]:
    candidate = read_yaml(path)
    spec = candidate.get("spec", {})
    errors: list[str] = []
    if spec.get("version") != "ok141-delete-d1-execution/v2" or spec.get("state") != "OFFLINE-PREPARED-BLOCKED-NO-GO":
        errors.append("candidate identity mismatch")
    if spec.get("baseCommit") != EXPECTED_BASE:
        errors.append("base commit mismatch")
    bindings = spec.get("bindings", {})
    checks = (
        ("v1CandidatePath", "v1CandidateDigest", EXPECTED_V1_CANDIDATE),
        ("v1ExecutorPath", "v1ExecutorDigest", EXPECTED_V1_EXECUTOR),
        ("v3PreflightCandidatePath", "v3PreflightCandidateDigest", EXPECTED_V3_PREFLIGHT_CANDIDATE),
        ("v3PreflightExecutorPath", "v3PreflightExecutorDigest", EXPECTED_V3_PREFLIGHT_EXECUTOR),
        ("stoppedEvidencePath", "stoppedEvidenceDigest", EXPECTED_STOPPED),
    )
    for path_key, digest_key, expected in checks:
        target = (path.parent / bindings.get(path_key, "")).resolve()
        if bindings.get(digest_key) != expected or not target.is_file() or file_digest(target) != expected:
            errors.append(f"{path_key} binding mismatch")
    records = spec.get("deleteOrder", [])
    if tuple(item.get("queryID") for item in records) != EXPECTED_ORDER:
        errors.append("delete order mismatch")
    if len(records) != 5 or len({item.get("rawURI") for item in records}) != 5:
        errors.append("delete target uniqueness mismatch")
    if spec.get("operation") != {
        "propagationPolicy": "Background",
        "preconditionFields": ["uid", "resourceVersion"],
        "exactGetImmediatelyBeforeDelete": True,
        "requireApplicationFinalizersAbsent": True,
        "requireDeletionTimestampAbsent": True,
        "absencePollIntervalSeconds": 2,
        "absencePollMaximumIterations": 30,
        "onFailure": "STOP-PRESERVE-NO-RETRY",
    }:
        errors.append("operation boundary mismatch")
    if spec.get("input") != {
        "bindingPath": "/private/tmp/ok141-delete-d1-runtime-binding-v3.json",
        "requiredFormat": "ok141-delete-d1-runtime-binding/v3",
        "requiredState": "PASS-D1-PREFLIGHT-PRIVATE-BOUND-NO-GO",
        "requiredOrderProfile": "ok141-delete-d1-order/v1",
        "maximumAgeMinutes": 5, "mode": "0600",
    }:
        errors.append("input boundary mismatch")
    if spec.get("privateOutput") != {"evidencePath": "/private/tmp/ok141-delete-d1-execution-evidence-v2.json", "mode": "0600"}:
        errors.append("output boundary mismatch")
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
    v3_candidate = read_yaml((HERE / "../delete-test-d1-preflight-v3/delete-d1-preflight-candidate-v3.yaml").resolve())
    if binding.get("candidateDigest") != canonical_digest(v3_candidate):
        raise D1Error("private binding candidate mismatch")
    if binding.get("bindingOrderProfile") != input_spec["requiredOrderProfile"]:
        raise D1Error("private binding order profile mismatch")
    if now > parse_time(binding.get("expiresAt", "")):
        raise D1Error("private binding expired")
    if binding.get("mutationPerformed") is not False or binding.get("deletePerformed") is not False:
        raise D1Error("private binding execution boundary mismatch")
    records = binding.get("deleteOrder", [])
    if tuple(record.get("queryID") for record in records) != EXPECTED_ORDER:
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
    _, records = validate_binding(candidate, binding_path, current)
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
            current = V1.exact_get(kubectl, kubeconfig, target["rawURI"])
            V1.assert_current_identity(current, record, record["queryID"].startswith("application-"))
            result = V1.run_raw(kubectl, kubeconfig, "delete", target["rawURI"], V1.delete_payload(record))
            if result.returncode != 0:
                raise D1Error("preconditioned delete failed")
            V1.wait_absent(kubectl, kubeconfig, target["rawURI"], spec["operation"]["absencePollMaximumIterations"], spec["operation"]["absencePollIntervalSeconds"])
            deleted.append(record["queryID"])
    except D1Error as error:
        stopped = error
    evidence = {
        "format": "ok141-delete-d1-execution-private-evidence/v2",
        "state": "PASS-D1-GITOPS-QUIESCED-PRIVATE" if stopped is None else "STOP-D1-PARTIAL-PRESERVE-NO-RETRY",
        "candidateDigest": file_digest(candidate_path), "grantID": grant["grantID"],
        "bindingDigest": file_digest(binding_path), "bindingOrderProfile": "ok141-delete-d1-order/v1",
        "plannedDeleteCount": 5, "completedDeleteCount": len(deleted), "completedQueryIDs": deleted,
        "allTargetsAbsent": stopped is None and len(deleted) == 5,
        "applicationFinalizersAbsentAtDelete": all(query_id in deleted for query_id in EXPECTED_ORDER[:3]),
        "optimisticConcurrencyUsed": True, "backgroundPropagationUsed": True,
        "targetResourceDeleteRequestedByRunner": False, "retryPerformed": False,
        "rollbackPerformed": False, "cleanupPerformed": False, "forceDeletePerformed": False,
        "finalizerMutationPerformed": False, "failureClass": None if stopped is None else "BOUND-DELETE-STOP",
        "credentialContentRetained": False, "rawObjectsRetained": False,
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
        print(json.dumps({"candidateDigest": file_digest(candidate_path), "semanticDigest": canonical_digest(candidate), "state": "PASS-D1-EXECUTION-V2-CANDIDATE-OFFLINE-NO-GO"}, sort_keys=True))
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
    except (D1Error, OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
