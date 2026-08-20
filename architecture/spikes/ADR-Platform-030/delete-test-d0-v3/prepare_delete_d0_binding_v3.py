#!/usr/bin/env python3
"""D0-v3 executor with raw-in-memory PV/Longhorn equality binding."""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import importlib.util
import json
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
V2_EXECUTOR = (HERE / "../delete-test-d0-v2/prepare_delete_d0_binding_v2.py").resolve()
_SPEC = importlib.util.spec_from_file_location("ok141_delete_d0_v2", V2_EXECUTOR)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError("cannot load D0-v2 executor")
V2 = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(V2)

BindingError = V2.BindingError
file_digest = V2.file_digest
canonical_digest = V2.canonical_digest
read_yaml = V2.read_yaml
write_exclusive_json = V2.write_exclusive_json
parse_time = V2.parse_time

EXPECTED_V2_CANDIDATE_DIGEST = "sha256:6064e19d7af591a4e32835b5b4f08afccc16217beaedb3e27a9f3457238170e5"
EXPECTED_V2_EXECUTOR_DIGEST = "sha256:d7e75599bf369b06d8a7dd5acb28af3a850fa8a756833c541804d9a329c9467f"
EXPECTED_CLOSURE_DIGEST = "sha256:8c11c9bf42d25f96817c43f3e4e0b11b3ed24f15e81f163038b41d29167ae634"
LONGHORN_RULE = "derived:provider-pv-longhorn-exact-equality"


def amended_runtime_candidate(candidate: dict[str, Any], candidate_path: Path) -> dict[str, Any]:
    spec = candidate["spec"]
    bindings = spec["bindings"]
    v2_path = (candidate_path.parent / bindings["v2CandidatePath"]).resolve()
    v2_candidate = read_yaml(v2_path)
    runtime = V2.amended_runtime_candidate(v2_candidate, v2_path)
    queries = runtime["spec"]["planes"]["ok-infra"]["queries"]
    selected = [query for query in queries if query.get("id") == "provider-longhorn-volumes"]
    if len(selected) != 1 or selected[0].get("postFilter") != "derived:provider-pv-volume-handles":
        raise BindingError("base Longhorn query identity mismatch")
    selected[0]["postFilter"] = LONGHORN_RULE
    runtime["spec"]["privateOutputs"] = copy.deepcopy(spec["privateOutputs"])
    runtime["spec"]["tool"]["executorPath"] = "prepare_delete_d0_binding_v3.py"
    runtime["spec"]["tool"]["executorDigest"] = file_digest(Path(__file__).resolve())
    query_profile = {plane: plane_spec.get("queries", []) for plane, plane_spec in runtime["spec"]["planes"].items()}
    runtime["spec"]["tool"]["queryProfileDigest"] = canonical_digest(query_profile)
    return runtime


def verify_candidate(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    candidate = read_yaml(path)
    spec = candidate.get("spec", {})
    errors: list[str] = []
    if spec.get("version") != "ok141-delete-d0-binding/v3" or spec.get("state") != "READY-FOR-EXPLICIT-READ-ONLY-GRANT":
        errors.append("candidate identity mismatch")
    bindings = spec.get("bindings", {})
    v2_candidate = (path.parent / bindings.get("v2CandidatePath", "")).resolve()
    v2_executor = (path.parent / bindings.get("v2ExecutorPath", "")).resolve()
    closure = (path.parent / bindings.get("longhornClosurePath", "")).resolve()
    if not v2_candidate.is_file() or file_digest(v2_candidate) != EXPECTED_V2_CANDIDATE_DIGEST:
        errors.append("v2 candidate mismatch")
    if not v2_executor.is_file() or file_digest(v2_executor) != EXPECTED_V2_EXECUTOR_DIGEST:
        errors.append("v2 executor mismatch")
    if not closure.is_file() or file_digest(closure) != EXPECTED_CLOSURE_DIGEST:
        errors.append("Longhorn closure mismatch")
    if bindings.get("v2CandidateDigest") != EXPECTED_V2_CANDIDATE_DIGEST or bindings.get("v2ExecutorDigest") != EXPECTED_V2_EXECUTOR_DIGEST:
        errors.append("declared v2 binding mismatch")
    if bindings.get("longhornClosureDigest") != EXPECTED_CLOSURE_DIGEST:
        errors.append("declared closure binding mismatch")
    tool = spec.get("tool", {})
    if tool.get("executorDigest") != file_digest(Path(__file__).resolve()):
        errors.append("v3 executor mismatch")
    amendment = spec.get("amendment", {})
    if amendment.get("queryID") != "provider-longhorn-volumes" or amendment.get("postFilter") != LONGHORN_RULE:
        errors.append("Longhorn amendment mismatch")
    if amendment.get("deriveBeforeRedaction") is not True or amendment.get("requiredEqualityCount") != 2:
        errors.append("Longhorn equality boundary mismatch")
    outputs = spec.get("privateOutputs", {})
    if outputs.get("bindingPath") != "/private/tmp/ok141-delete-d0-runtime-binding-v3.json" or outputs.get("evidencePath") != "/private/tmp/ok141-delete-d0-evidence-v3.json":
        errors.append("private output path mismatch")
    if outputs.get("mode") != "0600" or outputs.get("maximumBindingAgeMinutes") != 10:
        errors.append("private output boundary mismatch")
    auth = spec.get("authorization", {})
    if auth.get("decision") != "NO-GO" or any(value is not False for key, value in auth.items() if key.endswith("Granted")):
        errors.append("candidate grants authority")
    if errors:
        raise BindingError("; ".join(errors))
    runtime = amended_runtime_candidate(candidate, path)
    if runtime["spec"]["tool"]["queryProfileDigest"] != tool.get("queryProfileDigest"):
        raise BindingError("v3 query profile mismatch")
    return candidate, runtime


def verify_grant(candidate_path: Path, grant_path: Path, now: dt.datetime | None = None) -> dict[str, Any]:
    candidate, _ = verify_candidate(candidate_path)
    grant = read_yaml(grant_path)
    spec = grant.get("spec", {})
    errors: list[str] = []
    if spec.get("state") != "GRANTED" or spec.get("candidateDigest") != file_digest(candidate_path):
        errors.append("grant identity mismatch")
    if spec.get("maximumRuns") != 1 or spec.get("consumed") is not False:
        errors.append("grant is not fresh and single-use")
    for key in ("readOnlyAuthorized", "credentialUseAuthorized", "secretMetadataReadAuthorized"):
        if spec.get(key) is not True:
            errors.append(f"{key} is required")
    for key in ("mutationAuthorized", "deleteAuthorized", "cleanupAuthorized", "retryAuthorized", "rollbackAuthorized", "outageAuthorized", "failureInjectionAuthorized", "publicationAuthorized"):
        if spec.get(key) is not False:
            errors.append(f"{key} must be false")
    current = now or dt.datetime.now(dt.timezone.utc)
    start = parse_time(spec.get("notBefore", ""))
    end = parse_time(spec.get("notAfter", ""))
    if not start <= current <= end or (end - start).total_seconds() > 1200:
        errors.append("grant window is inactive or exceeds twenty minutes")
    outputs = candidate["spec"]["privateOutputs"]
    if spec.get("bindingPath") != outputs["bindingPath"] or spec.get("evidencePath") != outputs["evidencePath"]:
        errors.append("grant output paths differ")
    if errors:
        raise BindingError("; ".join(errors))
    return grant


def derive_provider_pv_rows(items: list[dict[str, Any]]) -> list[dict[str, str]]:
    rows = [{
        "pv": item.get("metadata", {}).get("name"),
        "handle": item.get("spec", {}).get("csi", {}).get("volumeHandle"),
        "namespace": item.get("spec", {}).get("claimRef", {}).get("namespace"),
        "pvc": item.get("spec", {}).get("claimRef", {}).get("name"),
    } for item in items]
    if len(rows) != 2 or any(not all(row.values()) for row in rows):
        raise BindingError("provider-pvs: exact raw correlation fields are incomplete")
    if len({row["pv"] for row in rows}) != 2 or len({row["handle"] for row in rows}) != 2:
        raise BindingError("provider-pvs: correlation identities are not unique")
    return rows


def safe_item(item: dict[str, Any], query_id: str) -> dict[str, Any]:
    retained = V2.safe_metadata(item)
    if query_id in ("provider-pvs", "platform-pvs"):
        spec = item.get("spec", {})
        retained["storage"] = {
            "claimRef": {key: spec.get("claimRef", {}).get(key) for key in ("namespace", "name", "uid")},
            "reclaimPolicy": spec.get("persistentVolumeReclaimPolicy"),
            "storageClassName": spec.get("storageClassName"),
            "volumeHandle": spec.get("csi", {}).get("volumeHandle"),
            "phase": item.get("status", {}).get("phase"),
        }
    if query_id == "provider-longhorn-volumes":
        status = item.get("status", {})
        kubernetes = status.get("kubernetesStatus", {})
        retained["longhorn"] = {
            "state": status.get("state"),
            "robustness": status.get("robustness"),
            "fromBackup": item.get("spec", {}).get("fromBackup"),
            "kubernetesStatus": {key: kubernetes.get(key) for key in ("namespace", "pvName", "pvcName")},
        }
    return retained


def apply_post_filter(items: list[dict[str, Any]], query: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
    if query.get("postFilter") != LONGHORN_RULE:
        return V2.apply_post_filter(items, query, context)
    rows = context.get("providerPVRows", [])
    retained = []
    for item in items:
        name = item.get("metadata", {}).get("name")
        status = item.get("status", {}).get("kubernetesStatus", {})
        matches = [row for row in rows if (
            name == row["pv"] == row["handle"]
            and status.get("namespace") == row["namespace"]
            and status.get("pvName") == row["pv"]
            and status.get("pvcName") == row["pvc"]
        )]
        if len(matches) == 1:
            retained.append(item)
    return retained


def run_query(kubectl: Path, kubeconfig: Path, query: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
    completed = subprocess.run([str(kubectl), "--kubeconfig", str(kubeconfig), "get", "--raw", query["rawURI"]], check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
    if completed.returncode != 0:
        raise BindingError(f"{query['id']}: exact GET failed")
    if len(completed.stdout) > 5 * 1024 * 1024:
        raise BindingError(f"{query['id']}: response exceeds bound")
    value = json.loads(completed.stdout)
    items = value.get("items") if query.get("collection") else [value]
    if not isinstance(items, list):
        raise BindingError(f"{query['id']}: invalid response shape")
    if query["id"] == "virtual-machines":
        context["vmDataVolumeTemplateNames"] = V2.vm_data_volume_names(items)
    items = apply_post_filter(items, query, context)
    if query["id"] == "provider-pvs":
        context["providerPVRows"] = derive_provider_pv_rows(items)
    if len(items) != query["expectedCount"]:
        raise BindingError(f"{query['id']}: expected {query['expectedCount']} objects, got {len(items)}")
    return [safe_item(item, query["id"]) for item in items]


def snapshot(candidate_path: Path, grant_path: Path, kubectl: Path) -> dict[str, Any]:
    candidate, runtime = verify_candidate(candidate_path)
    grant = verify_grant(candidate_path, grant_path)
    if file_digest(kubectl) != runtime["spec"]["tool"]["kubectlDigest"]:
        raise BindingError("kubectl binary digest mismatch")
    context: dict[str, Any] = {}
    started = dt.datetime.now(dt.timezone.utc)
    planes: dict[str, Any] = {}
    for plane, plane_spec in runtime["spec"]["planes"].items():
        kubeconfig = Path(plane_spec["kubeconfigPath"])
        if kubeconfig.is_symlink() or not kubeconfig.is_file() or stat.S_IMODE(kubeconfig.stat().st_mode) != 0o600:
            raise BindingError(f"{plane}: unsafe kubeconfig")
        planes[plane] = {query["id"]: run_query(kubectl, kubeconfig, query, context) for query in plane_spec["queries"]}
    completed = dt.datetime.now(dt.timezone.utc)
    binding = {
        "format": "ok141-delete-d0-runtime-binding/v3", "state": "CURRENT-PRIVATE-BOUND-NO-GO",
        "candidateDigest": file_digest(candidate_path), "grantID": grant["spec"]["grantID"],
        "observedAt": completed.isoformat(), "expiresAt": (completed + dt.timedelta(minutes=10)).isoformat(),
        "planes": planes, "credentialContentRetained": False, "mutationPerformed": False, "deletePerformed": False,
    }
    outputs = candidate["spec"]["privateOutputs"]
    binding_path = Path(outputs["bindingPath"])
    write_exclusive_json(binding_path, binding)
    evidence = {
        "format": "ok141-delete-d0-private-evidence/v3", "state": "PASS-D0-PRIVATE-BOUND-NO-GO",
        "candidateDigest": file_digest(candidate_path), "grantID": grant["spec"]["grantID"],
        "startedAt": started.isoformat(), "completedAt": completed.isoformat(), "bindingDigest": file_digest(binding_path),
        "planeCounts": {plane: sum(len(items) for items in queries.values()) for plane, queries in planes.items()},
        "secretValuesRetained": False, "rawResponsesRetained": False, "mutationPerformed": False, "deletePerformed": False,
    }
    write_exclusive_json(Path(outputs["evidencePath"]), evidence)
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "verify-grant", "snapshot"))
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--grant", type=Path)
    parser.add_argument("--kubectl", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if args.command == "verify":
        candidate, _ = verify_candidate(args.candidate.resolve())
        print(json.dumps({"candidateDigest": file_digest(args.candidate.resolve()), "semanticDigest": canonical_digest(candidate), "state": "PASS-D0-V3-CANDIDATE-OFFLINE-NO-GO"}, sort_keys=True))
    elif args.command == "verify-grant":
        if args.grant is None:
            raise BindingError("grant is required")
        verify_grant(args.candidate.resolve(), args.grant.resolve())
        print(file_digest(args.grant.resolve()))
    else:
        if not args.execute or args.grant is None or args.kubectl is None:
            raise BindingError("snapshot requires --execute, --grant and --kubectl")
        print(json.dumps(snapshot(args.candidate.resolve(), args.grant.resolve(), args.kubectl.resolve()), sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (BindingError, OSError, ValueError, json.JSONDecodeError, subprocess.TimeoutExpired) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
