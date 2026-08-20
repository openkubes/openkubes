#!/usr/bin/env python3
"""D1 execution v3 with fresh resourceVersion delete preconditions."""

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


V2 = load_module("ok141_delete_d1_execution_v2_for_v3", (HERE / "../delete-test-d1-execution-v2/bounded_delete_d1_v2.py").resolve())
V1 = V2.V1
D1Error = V1.D1Error
file_digest = V1.file_digest
canonical_digest = V1.canonical_digest
parse_time = V1.parse_time
read_yaml = V1.read_yaml
write_exclusive = V1.write_exclusive

EXPECTED_BASE = "72aa66192fef31be13868ccdd5db751ee32b099a"
EXPECTED_V2_CANDIDATE = "sha256:b6c7ff18498be0e06fa3753e6b4f673f20befffab13bb807cb81505a6e1eecf9"
EXPECTED_V2_EXECUTOR = "sha256:2ef548871d225291c24a57148d10889c437ab1fbaa4ed36be01319295cb91a6a"
EXPECTED_STOPPED = "sha256:75321aeeb7ab5f86f0e9b7dc38b838faff520bfeea6c85054e245266b0e1e141"
EXPECTED_KUBECTL = V1.EXPECTED_KUBECTL
EXPECTED_ORDER = V1.EXPECTED_QUERY_IDS


def verify_candidate(path: Path) -> dict[str, Any]:
    candidate = read_yaml(path)
    spec = candidate.get("spec", {})
    errors: list[str] = []
    if spec.get("version") != "ok141-delete-d1-execution/v3" or spec.get("state") != "OFFLINE-PREPARED-BLOCKED-NO-GO":
        errors.append("candidate identity mismatch")
    if spec.get("baseCommit") != EXPECTED_BASE:
        errors.append("base commit mismatch")
    bindings = spec.get("bindings", {})
    checks = (
        ("v2CandidatePath", "v2CandidateDigest", EXPECTED_V2_CANDIDATE),
        ("v2ExecutorPath", "v2ExecutorDigest", EXPECTED_V2_EXECUTOR),
        ("stoppedEvidencePath", "stoppedEvidenceDigest", EXPECTED_STOPPED),
    )
    for path_key, digest_key, expected in checks:
        target = (path.parent / bindings.get(path_key, "")).resolve()
        if bindings.get(digest_key) != expected or not target.is_file() or file_digest(target) != expected:
            errors.append(f"{path_key} binding mismatch")
    v2_candidate = read_yaml((HERE / "../delete-test-d1-execution-v2/delete-d1-execution-candidate-v2.yaml").resolve())
    if spec.get("deleteOrder") != v2_candidate.get("spec", {}).get("deleteOrder"):
        errors.append("v2 delete targets reinterpreted")
    if spec.get("plane") != v2_candidate.get("spec", {}).get("plane"):
        errors.append("v2 plane reinterpreted")
    if tuple(item.get("queryID") for item in spec.get("deleteOrder", [])) != EXPECTED_ORDER:
        errors.append("delete order mismatch")
    if spec.get("operation") != {
        "propagationPolicy": "Background",
        "immutableIdentityFields": ["name", "namespace", "uid"],
        "preflightResourceVersionIsObservationOnly": True,
        "exactGetImmediatelyBeforeDelete": True,
        "deletePreconditionFields": ["uid", "resourceVersion"],
        "useLiveResourceVersionForDelete": True,
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
        "maximumAgeMinutes": 5,
        "mode": "0600",
    }:
        errors.append("input boundary mismatch")
    if spec.get("privateOutput") != {"evidencePath": "/private/tmp/ok141-delete-d1-execution-evidence-v3.json", "mode": "0600"}:
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
    return V2.validate_binding(candidate, binding_path, now)


def verify_grant(candidate_path: Path, grant_path: Path, binding_path: Path, now: dt.datetime | None = None):
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


def live_delete_record(current: dict[str, Any], record: dict[str, str], application: bool) -> tuple[dict[str, str], bool]:
    metadata = current.get("metadata", {})
    for key in ("name", "namespace", "uid"):
        if str(metadata.get(key, "")) != str(record[key]):
            raise D1Error("live immutable identity differs from private binding")
    if metadata.get("deletionTimestamp") is not None:
        raise D1Error("target already deleting")
    if application and metadata.get("finalizers", []):
        raise D1Error("Application finalizer present")
    live_rv = str(metadata.get("resourceVersion", ""))
    if not live_rv:
        raise D1Error("live resourceVersion missing")
    delete_record = dict(record)
    delete_record["resourceVersion"] = live_rv
    return delete_record, live_rv != str(record["resourceVersion"])


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
    advanced = 0
    stopped: D1Error | None = None
    targets = {item["queryID"]: item for item in spec["deleteOrder"]}
    try:
        for record in records:
            target = targets[record["queryID"]]
            current = V1.exact_get(kubectl, kubeconfig, target["rawURI"])
            live_record, changed = live_delete_record(current, record, record["queryID"].startswith("application-"))
            advanced += int(changed)
            result = V1.run_raw(kubectl, kubeconfig, "delete", target["rawURI"], V1.delete_payload(live_record))
            if result.returncode != 0:
                raise D1Error("preconditioned delete failed")
            V1.wait_absent(kubectl, kubeconfig, target["rawURI"], spec["operation"]["absencePollMaximumIterations"], spec["operation"]["absencePollIntervalSeconds"])
            deleted.append(record["queryID"])
    except D1Error as error:
        stopped = error
    evidence = {
        "format": "ok141-delete-d1-execution-private-evidence/v3",
        "state": "PASS-D1-GITOPS-QUIESCED-PRIVATE" if stopped is None else "STOP-D1-PARTIAL-PRESERVE-NO-RETRY",
        "candidateDigest": file_digest(candidate_path), "grantID": grant["grantID"],
        "bindingDigest": file_digest(binding_path), "bindingOrderProfile": "ok141-delete-d1-order/v1",
        "plannedDeleteCount": 5, "completedDeleteCount": len(deleted), "completedQueryIDs": deleted,
        "allTargetsAbsent": stopped is None and len(deleted) == 5,
        "applicationFinalizersAbsentAtDelete": all(query_id in deleted for query_id in EXPECTED_ORDER[:3]),
        "immutableUIDBindingUsed": True, "liveResourceVersionPreconditionUsedCount": len(deleted),
        "preflightResourceVersionAdvancedCount": advanced,
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
        print(json.dumps({"candidateDigest": file_digest(candidate_path), "semanticDigest": canonical_digest(candidate), "state": "PASS-D1-EXECUTION-V3-CANDIDATE-OFFLINE-NO-GO"}, sort_keys=True))
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
