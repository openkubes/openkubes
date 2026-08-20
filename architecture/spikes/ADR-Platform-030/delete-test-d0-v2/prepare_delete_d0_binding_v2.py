#!/usr/bin/env python3
"""Additive D0-v2 executor deriving DataVolume names from bound VMs."""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import importlib.util
import json
import stat
import subprocess
from pathlib import Path
from typing import Any

import yaml


HERE = Path(__file__).resolve().parent
V1_EXECUTOR = (HERE / "../delete-test-d0-v1/prepare_delete_d0_binding_v1.py").resolve()
_SPEC = importlib.util.spec_from_file_location("ok141_delete_d0_v1", V1_EXECUTOR)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError("cannot load D0-v1 executor")
V1 = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(V1)

BindingError = V1.BindingError
file_digest = V1.file_digest
canonical_digest = V1.canonical_digest
read_yaml = V1.read_yaml
safe_metadata = V1.safe_metadata
write_exclusive_json = V1.write_exclusive_json
parse_time = V1.parse_time

EXPECTED_V1_CANDIDATE_DIGEST = "sha256:4c705a7d56e1db6828b00f720ee7ab1baed1bdc901e7b3045265184f34468f56"
EXPECTED_V1_EXECUTOR_DIGEST = "sha256:c8856ee3c31c5dbcf03e12a73027fa20b243bbf7e42671a96960d5e28629f8b3"
DERIVED_RULE = "derived:virtual-machine-data-volume-template-names"


def amended_runtime_candidate(candidate: dict[str, Any], candidate_path: Path) -> dict[str, Any]:
    spec = candidate["spec"]
    bindings = spec["bindings"]
    base_path = (candidate_path.parent / bindings["v1CandidatePath"]).resolve()
    base = copy.deepcopy(read_yaml(base_path))
    amendment = spec["amendment"]
    queries = base["spec"]["planes"]["ok-infra"]["queries"]
    selected = [query for query in queries if query.get("id") == "data-volumes"]
    if len(selected) != 1:
        raise BindingError("base DataVolume query count mismatch")
    query = selected[0]
    if query.get("rawURI") != amendment["replacesRawURI"]:
        raise BindingError("base DataVolume query identity mismatch")
    query["rawURI"] = amendment["rawURI"]
    query["postFilter"] = amendment["postFilter"]
    query["expectedCount"] = amendment["expectedCount"]
    base["spec"]["privateOutputs"] = copy.deepcopy(spec["privateOutputs"])
    base["spec"]["tool"]["executorPath"] = "prepare_delete_d0_binding_v2.py"
    base["spec"]["tool"]["executorDigest"] = file_digest(Path(__file__).resolve())
    query_profile = {
        plane: plane_spec.get("queries", [])
        for plane, plane_spec in base["spec"]["planes"].items()
    }
    base["spec"]["tool"]["queryProfileDigest"] = canonical_digest(query_profile)
    return base


def verify_candidate(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    candidate = read_yaml(path)
    spec = candidate.get("spec", {})
    errors: list[str] = []
    if spec.get("version") != "ok141-delete-d0-binding/v2":
        errors.append("candidate version mismatch")
    if spec.get("state") != "READY-FOR-EXPLICIT-READ-ONLY-GRANT":
        errors.append("candidate state mismatch")
    bindings = spec.get("bindings", {})
    base_path = (path.parent / bindings.get("v1CandidatePath", "")).resolve()
    base_executor = (path.parent / bindings.get("v1ExecutorPath", "")).resolve()
    if not base_path.is_file() or file_digest(base_path) != EXPECTED_V1_CANDIDATE_DIGEST:
        errors.append("v1 candidate digest mismatch")
    if not base_executor.is_file() or file_digest(base_executor) != EXPECTED_V1_EXECUTOR_DIGEST:
        errors.append("v1 executor digest mismatch")
    if bindings.get("v1CandidateFileDigest") != EXPECTED_V1_CANDIDATE_DIGEST:
        errors.append("declared v1 candidate digest mismatch")
    if bindings.get("v1ExecutorDigest") != EXPECTED_V1_EXECUTOR_DIGEST:
        errors.append("declared v1 executor digest mismatch")
    tool = spec.get("tool", {})
    if tool.get("executorDigest") != file_digest(Path(__file__).resolve()):
        errors.append("v2 executor digest mismatch")
    amendment = spec.get("amendment", {})
    if amendment.get("queryID") != "data-volumes":
        errors.append("amended query mismatch")
    if amendment.get("sourceQueryID") != "virtual-machines":
        errors.append("derivation source mismatch")
    if amendment.get("rawURI") != "/apis/cdi.kubevirt.io/v1beta1/namespaces/disposable-ok141/datavolumes":
        errors.append("amended DataVolume URI mismatch")
    if amendment.get("postFilter") != DERIVED_RULE or amendment.get("expectedCount") != 2:
        errors.append("DataVolume filter boundary mismatch")
    outputs = spec.get("privateOutputs", {})
    if outputs.get("bindingPath") != "/private/tmp/ok141-delete-d0-runtime-binding-v2.json":
        errors.append("binding path mismatch")
    if outputs.get("evidencePath") != "/private/tmp/ok141-delete-d0-evidence-v2.json":
        errors.append("evidence path mismatch")
    if outputs.get("mode") != "0600" or outputs.get("maximumBindingAgeMinutes") != 10:
        errors.append("private output boundary mismatch")
    auth = spec.get("authorization", {})
    if auth.get("decision") != "NO-GO":
        errors.append("candidate authorization mismatch")
    if any(value is not False for key, value in auth.items() if key.endswith("Granted")):
        errors.append("candidate grants authority")
    if errors:
        raise BindingError("; ".join(errors))
    runtime = amended_runtime_candidate(candidate, path)
    if runtime["spec"]["tool"]["queryProfileDigest"] != tool.get("queryProfileDigest"):
        raise BindingError("amended query profile digest mismatch")
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
    for key in (
        "mutationAuthorized", "deleteAuthorized", "cleanupAuthorized", "retryAuthorized",
        "rollbackAuthorized", "outageAuthorized", "failureInjectionAuthorized", "publicationAuthorized",
    ):
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


def vm_data_volume_names(items: list[dict[str, Any]]) -> set[str]:
    names = {
        template.get("metadata", {}).get("name")
        for item in items
        for template in item.get("spec", {}).get("dataVolumeTemplates", [])
        if template.get("metadata", {}).get("name")
    }
    if len(names) != 2:
        raise BindingError(f"virtual-machines: expected exactly 2 derived DataVolume names, got {len(names)}")
    return names


def apply_post_filter(items: list[dict[str, Any]], query: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
    if query.get("postFilter") == DERIVED_RULE:
        names = context.get("vmDataVolumeTemplateNames", set())
        return [item for item in items if item.get("metadata", {}).get("name") in names]
    return V1.apply_post_filter(items, query, context)


def run_query(kubectl: Path, kubeconfig: Path, query: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
    command = [str(kubectl), "--kubeconfig", str(kubeconfig), "get", "--raw", query["rawURI"]]
    completed = subprocess.run(command, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
    if completed.returncode != 0:
        raise BindingError(f"{query['id']}: exact GET failed")
    if len(completed.stdout) > 5 * 1024 * 1024:
        raise BindingError(f"{query['id']}: response exceeds bound")
    value = json.loads(completed.stdout)
    items = value.get("items") if query.get("collection") else [value]
    if not isinstance(items, list):
        raise BindingError(f"{query['id']}: invalid response shape")
    if query["id"] == "virtual-machines":
        context["vmDataVolumeTemplateNames"] = vm_data_volume_names(items)
    items = apply_post_filter(items, query, context)
    if len(items) != query["expectedCount"]:
        raise BindingError(f"{query['id']}: expected {query['expectedCount']} objects, got {len(items)}")
    retained = [safe_metadata(item) for item in items]
    if query["id"] == "provider-pvs":
        context["providerVolumeHandles"] = {
            item.get("storage", {}).get("volumeHandle") for item in retained if item.get("storage", {}).get("volumeHandle")
        }
    return retained


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
        "format": "ok141-delete-d0-runtime-binding/v2",
        "state": "CURRENT-PRIVATE-BOUND-NO-GO",
        "candidateDigest": file_digest(candidate_path),
        "grantID": grant["spec"]["grantID"],
        "observedAt": completed.isoformat(),
        "expiresAt": (completed + dt.timedelta(minutes=10)).isoformat(),
        "planes": planes,
        "credentialContentRetained": False,
        "mutationPerformed": False,
        "deletePerformed": False,
    }
    outputs = candidate["spec"]["privateOutputs"]
    binding_path = Path(outputs["bindingPath"])
    write_exclusive_json(binding_path, binding)
    evidence = {
        "format": "ok141-delete-d0-private-evidence/v2",
        "state": "PASS-D0-PRIVATE-BOUND-NO-GO",
        "candidateDigest": file_digest(candidate_path),
        "grantID": grant["spec"]["grantID"],
        "startedAt": started.isoformat(),
        "completedAt": completed.isoformat(),
        "bindingDigest": file_digest(binding_path),
        "planeCounts": {plane: sum(len(items) for items in queries.values()) for plane, queries in planes.items()},
        "secretValuesRetained": False,
        "rawResponsesRetained": False,
        "mutationPerformed": False,
        "deletePerformed": False,
    }
    write_exclusive_json(Path(outputs["evidencePath"]), evidence)
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "profile-digest", "verify-grant", "snapshot"))
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--grant", type=Path)
    parser.add_argument("--kubectl", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if args.command == "verify":
        candidate, _ = verify_candidate(args.candidate.resolve())
        print(json.dumps({"candidateDigest": file_digest(args.candidate.resolve()), "semanticDigest": canonical_digest(candidate), "state": "PASS-D0-V2-CANDIDATE-OFFLINE-NO-GO"}, sort_keys=True))
    elif args.command == "profile-digest":
        _, runtime = verify_candidate(args.candidate.resolve())
        print(runtime["spec"]["tool"]["queryProfileDigest"])
    elif args.command == "verify-grant":
        if args.grant is None:
            raise BindingError("grant is required")
        print(file_digest(args.grant.resolve()) if verify_grant(args.candidate.resolve(), args.grant.resolve()) else "")
    elif args.command == "snapshot":
        if not args.execute or args.grant is None or args.kubectl is None:
            raise BindingError("snapshot requires --execute, --grant and --kubectl")
        print(json.dumps(snapshot(args.candidate.resolve(), args.grant.resolve(), args.kubectl.resolve()), sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (BindingError, OSError, ValueError, json.JSONDecodeError, subprocess.TimeoutExpired) as error:
        print(f"ERROR: {error}", file=__import__("sys").stderr)
        raise SystemExit(1)
