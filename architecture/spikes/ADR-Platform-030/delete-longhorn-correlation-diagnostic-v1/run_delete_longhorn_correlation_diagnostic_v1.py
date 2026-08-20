#!/usr/bin/env python3
"""Bounded read-only diagnostic for OK-141 provider PV/Longhorn correlation."""

from __future__ import annotations

import argparse
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


class DiagnosticError(ValueError):
    pass


EXPECTED_D0_V2_CANDIDATE_DIGEST = "sha256:6064e19d7af591a4e32835b5b4f08afccc16217beaedb3e27a9f3457238170e5"
EXPECTED_D0_V2_EXECUTOR_DIGEST = "sha256:d7e75599bf369b06d8a7dd5acb28af3a850fa8a756833c541804d9a329c9467f"


def sha256_bytes(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def file_digest(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_digest(value: object) -> str:
    return sha256_bytes(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def read_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text())
    if not isinstance(value, dict):
        raise DiagnosticError(f"{path}: expected one YAML object")
    return value


def parse_time(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise DiagnosticError("timestamp lacks timezone")
    return parsed.astimezone(dt.timezone.utc)


def verify_candidate(path: Path) -> dict[str, Any]:
    candidate = read_yaml(path)
    spec = candidate.get("spec", {})
    errors: list[str] = []
    if spec.get("version") != "ok141-delete-longhorn-correlation-diagnostic/v1":
        errors.append("version mismatch")
    if spec.get("state") != "READY-FOR-EXPLICIT-READ-ONLY-GRANT":
        errors.append("state mismatch")
    bindings = spec.get("bindings", {})
    d0_candidate = (path.parent / bindings.get("d0V2CandidatePath", "")).resolve()
    d0_executor = (path.parent / bindings.get("d0V2ExecutorPath", "")).resolve()
    if not d0_candidate.is_file() or file_digest(d0_candidate) != EXPECTED_D0_V2_CANDIDATE_DIGEST:
        errors.append("D0-v2 candidate mismatch")
    if not d0_executor.is_file() or file_digest(d0_executor) != EXPECTED_D0_V2_EXECUTOR_DIGEST:
        errors.append("D0-v2 executor mismatch")
    if bindings.get("d0V2CandidateDigest") != EXPECTED_D0_V2_CANDIDATE_DIGEST:
        errors.append("declared D0-v2 candidate mismatch")
    if bindings.get("d0V2ExecutorDigest") != EXPECTED_D0_V2_EXECUTOR_DIGEST:
        errors.append("declared D0-v2 executor mismatch")
    tool = spec.get("tool", {})
    if tool.get("executorDigest") != file_digest(Path(__file__).resolve()):
        errors.append("diagnostic executor mismatch")
    queries = spec.get("queries", [])
    if [query.get("id") for query in queries] != ["provider-pvs", "longhorn-volumes"]:
        errors.append("query identity mismatch")
    if any(query.get("method") != "GET" or not query.get("collection") for query in queries):
        errors.append("query boundary mismatch")
    if queries and queries[0].get("postFilter") != "claim-namespace:disposable-ok141":
        errors.append("PV post-filter mismatch")
    if tool.get("queryProfileDigest") != canonical_digest(queries):
        errors.append("query profile digest mismatch")
    output = spec.get("privateOutput", {})
    if output.get("path") != "/private/tmp/ok141-delete-longhorn-correlation-diagnostic-v1-evidence.json":
        errors.append("output path mismatch")
    if output.get("mode") != "0600" or output.get("mustBeAbsent") is not True:
        errors.append("output boundary mismatch")
    auth = spec.get("authorization", {})
    if auth.get("decision") != "NO-GO":
        errors.append("authorization mismatch")
    if any(value is not False for key, value in auth.items() if key.endswith("Granted")):
        errors.append("candidate grants authority")
    if errors:
        raise DiagnosticError("; ".join(errors))
    return candidate


def verify_grant(candidate_path: Path, grant_path: Path, now: dt.datetime | None = None) -> dict[str, Any]:
    candidate = verify_candidate(candidate_path)
    grant = read_yaml(grant_path)
    spec = grant.get("spec", {})
    errors: list[str] = []
    if spec.get("state") != "GRANTED" or spec.get("candidateDigest") != file_digest(candidate_path):
        errors.append("grant identity mismatch")
    if spec.get("maximumRuns") != 1 or spec.get("consumed") is not False:
        errors.append("grant is not fresh and single-use")
    if spec.get("readOnlyAuthorized") is not True or spec.get("credentialUseAuthorized") is not True:
        errors.append("read authority is missing")
    for key in ("mutationAuthorized", "deleteAuthorized", "cleanupAuthorized", "retryAuthorized", "publicationAuthorized", "failureInjectionAuthorized"):
        if spec.get(key) is not False:
            errors.append(f"{key} must be false")
    current = now or dt.datetime.now(dt.timezone.utc)
    start = parse_time(spec.get("notBefore", ""))
    end = parse_time(spec.get("notAfter", ""))
    if not start <= current <= end or (end - start).total_seconds() > 900:
        errors.append("grant window is inactive or exceeds fifteen minutes")
    if spec.get("evidencePath") != candidate["spec"]["privateOutput"]["path"]:
        errors.append("grant output path differs")
    if errors:
        raise DiagnosticError("; ".join(errors))
    return grant


def get_collection(kubectl: Path, kubeconfig: Path, uri: str) -> list[dict[str, Any]]:
    completed = subprocess.run(
        [str(kubectl), "--kubeconfig", str(kubeconfig), "get", "--raw", uri],
        check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20,
    )
    if completed.returncode != 0:
        raise DiagnosticError("exact collection GET failed")
    if len(completed.stdout) > 5 * 1024 * 1024:
        raise DiagnosticError("response exceeds bound")
    value = json.loads(completed.stdout)
    items = value.get("items")
    if not isinstance(items, list):
        raise DiagnosticError("invalid collection response")
    return items


def correlate(pvs: list[dict[str, Any]], volumes: list[dict[str, Any]]) -> dict[str, Any]:
    owned_pvs = [pv for pv in pvs if pv.get("spec", {}).get("claimRef", {}).get("namespace") == "disposable-ok141"]
    if len(owned_pvs) != 2:
        raise DiagnosticError(f"expected 2 provider PVs, got {len(owned_pvs)}")
    pv_rows = [{
        "pv": pv.get("metadata", {}).get("name"),
        "handle": pv.get("spec", {}).get("csi", {}).get("volumeHandle"),
        "pvc": pv.get("spec", {}).get("claimRef", {}).get("name"),
    } for pv in owned_pvs]
    if any(not all(row.values()) for row in pv_rows):
        raise DiagnosticError("provider PV correlation fields are incomplete")
    volume_rows = [{
        "name": volume.get("metadata", {}).get("name"),
        "namespace": volume.get("status", {}).get("kubernetesStatus", {}).get("namespace"),
        "pv": volume.get("status", {}).get("kubernetesStatus", {}).get("pvName"),
        "pvc": volume.get("status", {}).get("kubernetesStatus", {}).get("pvcName"),
        "state": volume.get("status", {}).get("state"),
        "robustness": volume.get("status", {}).get("robustness"),
        "fromBackup": bool(volume.get("spec", {}).get("fromBackup")),
    } for volume in volumes]
    handles = {row["handle"] for row in pv_rows}
    pv_names = {row["pv"] for row in pv_rows}
    tuples = {("disposable-ok141", row["pv"], row["pvc"]) for row in pv_rows}
    handle_matches = [row for row in volume_rows if row["name"] in handles]
    name_matches = [row for row in volume_rows if row["name"] in pv_names]
    status_matches = [row for row in volume_rows if (row["namespace"], row["pv"], row["pvc"]) in tuples]
    strategies = {
        "volumeHandleToMetadataName": len(handle_matches),
        "pvNameToMetadataName": len(name_matches),
        "kubernetesStatusTuple": len(status_matches),
    }
    successful = sorted(name for name, count in strategies.items() if count == 2)
    if not successful:
        verdict = "NO-EXACT-TWO-WAY-CORRELATION"
    elif len(successful) == 1:
        verdict = "ONE-EXACT-CORRELATION"
    else:
        verdict = "MULTIPLE-EQUIVALENT-CORRELATIONS"
    selected = status_matches if len(status_matches) == 2 else (name_matches if len(name_matches) == 2 else handle_matches)
    identity = {
        "providerPVs": sorted(row["pv"] for row in pv_rows),
        "providerPVCs": sorted(row["pvc"] for row in pv_rows),
        "providerHandles": sorted(row["handle"] for row in pv_rows),
        "matchedLonghornNames": sorted(row["name"] for row in selected),
    }
    return {
        "providerPVCount": len(pv_rows),
        "longhornCollectionCount": len(volume_rows),
        "matchCounts": strategies,
        "successfulStrategies": successful,
        "verdict": verdict,
        "identityDigest": canonical_digest(identity),
        "selectedStateCategories": sorted({str(row["state"]) for row in selected}),
        "selectedRobustnessCategories": sorted({str(row["robustness"]) for row in selected}),
        "selectedFromBackupTrueCount": sum(1 for row in selected if row["fromBackup"]),
        "rawNamesRetained": False,
    }


def write_exclusive(path: Path, value: object) -> None:
    if path.parent != Path("/private/tmp") or path.exists():
        raise DiagnosticError("unsafe or existing output")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump(value, stream, sort_keys=True, separators=(",", ":"))
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    path.chmod(0o600)


def run(candidate_path: Path, grant_path: Path, kubectl: Path) -> dict[str, Any]:
    candidate = verify_candidate(candidate_path)
    grant = verify_grant(candidate_path, grant_path)
    spec = candidate["spec"]
    if file_digest(kubectl) != spec["tool"]["kubectlDigest"]:
        raise DiagnosticError("kubectl digest mismatch")
    kubeconfig = Path(spec["kubeconfigPath"])
    if kubeconfig.is_symlink() or not kubeconfig.is_file() or stat.S_IMODE(kubeconfig.stat().st_mode) != 0o600:
        raise DiagnosticError("unsafe kubeconfig")
    pvs = get_collection(kubectl, kubeconfig, spec["queries"][0]["rawURI"])
    volumes = get_collection(kubectl, kubeconfig, spec["queries"][1]["rawURI"])
    result = correlate(pvs, volumes)
    evidence = {
        "format": "ok141-delete-longhorn-correlation-diagnostic/v1",
        "state": "PASS-READ-ONLY-DIAGNOSTIC-NO-GO" if result["verdict"] != "NO-EXACT-TWO-WAY-CORRELATION" else "BLOCKED-NO-CORRELATION-NO-GO",
        "candidateDigest": file_digest(candidate_path),
        "grantID": grant["spec"]["grantID"],
        "observedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "result": result,
        "mutationPerformed": False,
        "deletePerformed": False,
        "rawObjectsRetained": False,
    }
    write_exclusive(Path(spec["privateOutput"]["path"]), evidence)
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "verify-grant", "run"))
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--grant", type=Path)
    parser.add_argument("--kubectl", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if args.command == "verify":
        candidate = verify_candidate(args.candidate.resolve())
        print(json.dumps({"candidateDigest": file_digest(args.candidate.resolve()), "semanticDigest": canonical_digest(candidate), "state": "PASS-LONGHORN-CORRELATION-DIAGNOSTIC-CANDIDATE-OFFLINE-NO-GO"}, sort_keys=True))
    elif args.command == "verify-grant":
        if args.grant is None:
            raise DiagnosticError("grant is required")
        verify_grant(args.candidate.resolve(), args.grant.resolve())
        print(file_digest(args.grant.resolve()))
    else:
        if not args.execute or args.grant is None or args.kubectl is None:
            raise DiagnosticError("run requires --execute, --grant and --kubectl")
        print(json.dumps(run(args.candidate.resolve(), args.grant.resolve(), args.kubectl.resolve()), sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (DiagnosticError, OSError, ValueError, json.JSONDecodeError, subprocess.TimeoutExpired) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
