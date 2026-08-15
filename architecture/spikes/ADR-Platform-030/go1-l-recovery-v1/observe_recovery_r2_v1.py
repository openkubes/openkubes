#!/usr/bin/env python3
"""Bounded read-only R2 observer for management cleanup closure."""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import sys
import time
from pathlib import Path
from typing import Any, Callable


HERE = Path(__file__).resolve().parent
MODULE_SPEC = importlib.util.spec_from_file_location(
    "observe_recovery_snapshot_attempt_for_r2", HERE / "observe_recovery_snapshot_attempt_v1.py"
)
BASE = importlib.util.module_from_spec(MODULE_SPEC)
assert MODULE_SPEC.loader is not None
MODULE_SPEC.loader.exec_module(BASE)
V2 = BASE.V2
V1 = BASE.V1
ObservationError = BASE.SnapshotError
TOOL_DIGEST = BASE.TOOL_DIGEST
QUERY_PROFILE = HERE / "recovery-snapshot-candidate-v3.yaml"
QUERY_PROFILE_DIGEST = "sha256:cc16cd21ae73948b1db83d1fa3490d545fd1b0616ecf81776281b36aa21df435"
R1_CLEANUP_CANDIDATE_DIGEST = "sha256:71a81d3609de890727a08bb5f7680b0c188aa080361de98a3f5aa4d0dab7b1e1"
MGMT_ABSENT = {
    "mgmt-namespace", "cluster", "kubevirt-cluster", "talos-control-plane",
    "talos-worker-template", "machine-deployment", "control-plane-machine-template",
    "worker-machine-template", "misrouted-load-balancer", "machines", "machine-sets",
    "kubevirt-machines",
}
MGMT_API_NOT_SERVED = {"local-provider-vms", "local-provider-vmis"}
INFRA_PRESENT = {"infra-namespace", "golden-image-cloner-role", "golden-image-cloner-binding"}
INFRA_ABSENT = {"intended-provider-load-balancer", "provider-vms", "provider-vmis"}


def verify_candidate(path: Path) -> dict[str, Any]:
    candidate = V1.read(path)
    spec = candidate["spec"]
    if spec["version"] != "ok141-go1-l-recovery-r2/v1" or spec["state"] != "READY-FOR-EXPLICIT-READ-ONLY-GRANT":
        raise ObservationError("candidate identity or state mismatch")
    if spec["protocolDigest"] != V1.sha256(HERE / "go1-l-recovery-protocol-v1.yaml"):
        raise ObservationError("protocol digest mismatch")
    if V1.sha256(QUERY_PROFILE) != QUERY_PROFILE_DIGEST or spec["queryProfileDigest"] != QUERY_PROFILE_DIGEST:
        raise ObservationError("query profile digest mismatch")
    if spec["planes"] != V1.read(QUERY_PROFILE)["spec"]["planes"]:
        raise ObservationError("query set differs from reviewed profile")
    predecessor = spec["predecessor"]
    if predecessor["cleanupCandidateDigest"] != R1_CLEANUP_CANDIDATE_DIGEST:
        raise ObservationError("R1 cleanup candidate mismatch")
    for claim in ("r1EvidenceDigest", "privateRuntimeBindingDigest"):
        value = predecessor.get(claim)
        if not isinstance(value, str) or not value.startswith("sha256:") or len(value) != 71:
            raise ObservationError(f"R1 predecessor lacks {claim}")
    if not predecessor.get("r1GrantID") or predecessor["r1State"] != "ALL-DELETES-ACCEPTED":
        raise ObservationError("R1 was not accepted")
    if spec["tool"]["executorDigest"] != V1.sha256(Path(__file__).resolve()):
        raise ObservationError("executor digest mismatch")
    if spec["tool"]["kubectlDigest"] != TOOL_DIGEST:
        raise ObservationError("kubectl digest mismatch")
    polling = spec["polling"]
    if polling != {
        "targetQueryID": "mgmt-namespace",
        "intervalSeconds": 10,
        "maximumIterations": 60,
        "maximumDurationSeconds": 600,
    }:
        raise ObservationError("polling boundary mismatch")
    if spec["evidence"]["outputPath"] != "/private/tmp/ok141-go1-l-recovery-r2-v1-evidence.json":
        raise ObservationError("evidence output mismatch")
    if any(spec["authorization"].values()):
        raise ObservationError("candidate grants authority")
    return candidate


def verify_grant(candidate_path: Path, grant_path: Path, now: dt.datetime | None = None) -> dict[str, Any]:
    candidate = verify_candidate(candidate_path)
    grant = V1.read(grant_path)
    spec = grant["spec"]
    if spec["state"] != "GRANTED" or not spec["readOnlyAuthorized"] or not spec["credentialUseAuthorized"]:
        raise ObservationError("R2 is not granted")
    if spec["candidateDigest"] != V1.sha256(candidate_path):
        raise ObservationError("grant candidate digest mismatch")
    if spec["maximumRuns"] != 1 or spec["consumed"]:
        raise ObservationError("grant is reused or not single-run")
    for claim in (
        "mutationAuthorized", "cleanupAuthorized", "retryAuthorized", "secretReadAuthorized",
        "r3Authorized", "recreateAuthorized", "go1LAuthorized", "go1Authorized",
        "failureInjectionAuthorized",
    ):
        if spec[claim]:
            raise ObservationError("grant carries excluded authority")
    current = now or dt.datetime.now(dt.timezone.utc)
    start, end = V1.parse_time(spec["notBefore"]), V1.parse_time(spec["notAfter"])
    if not start <= current <= end or end - start > dt.timedelta(minutes=20):
        raise ObservationError("grant window is inactive or exceeds 20 minutes")
    if spec["outputPath"] != candidate["spec"]["evidence"]["outputPath"]:
        raise ObservationError("evidence output mismatch")
    return grant


def outcomes(items: list[dict[str, Any]]) -> dict[str, str]:
    return {item["id"]: item["outcome"] for item in items}


def evaluate(planes: dict[str, list[dict[str, Any]]]) -> str:
    mgmt, infra = outcomes(planes["ok-mgmt"]), outcomes(planes["ok-infra"])
    if set(mgmt) != MGMT_ABSENT | MGMT_API_NOT_SERVED or set(infra) != INFRA_PRESENT | INFRA_ABSENT:
        return "FAIL-QUERY-SET"
    if any(mgmt[item] != "ABSENT" for item in MGMT_ABSENT):
        return "BLOCKED-MANAGEMENT-STATE-REMAINS"
    if any(mgmt[item] != "API_NOT_SERVED" for item in MGMT_API_NOT_SERVED):
        return "FAIL-API-BOUNDARY"
    if any(infra[item] != "PRESENT" for item in INFRA_PRESENT):
        return "FAIL-INFRA-PREREQUISITE-STATE"
    if any(infra[item] != "ABSENT" for item in INFRA_ABSENT):
        return "FAIL-PROVIDER-RUNTIME-STATE"
    return "PASS-R2-CLEAN"


def execute(
    candidate_path: Path,
    grant_path: Path,
    kubectl: Path,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    candidate = verify_candidate(candidate_path)
    grant = verify_grant(candidate_path, grant_path)
    if V1.sha256(kubectl) != TOOL_DIGEST:
        raise ObservationError("local kubectl digest mismatch")
    output = Path(candidate["spec"]["evidence"]["outputPath"])
    if output.exists():
        raise ObservationError("evidence output already exists")
    kubeconfigs = {}
    for plane, plane_spec in candidate["spec"]["planes"].items():
        path = Path(plane_spec["kubeconfigPath"])
        if path.is_symlink() or not path.is_file() or (path.stat().st_mode & 0o777) != 0o600:
            raise ObservationError(f"unsafe kubeconfig for {plane}")
        kubeconfigs[plane] = path

    mgmt_queries = candidate["spec"]["planes"]["ok-mgmt"]["queries"]
    namespace_query = next(query for query in mgmt_queries if query["id"] == "mgmt-namespace")
    polling = candidate["spec"]["polling"]
    started_at = dt.datetime.now(dt.timezone.utc).isoformat()
    poll_results = []
    namespace_result = None
    for iteration in range(1, polling["maximumIterations"] + 1):
        namespace_result = V2.run_query(kubectl, kubeconfigs["ok-mgmt"], namespace_query)
        poll_results.append({"iteration": iteration, "outcome": namespace_result["outcome"]})
        if namespace_result["outcome"] == "ABSENT":
            break
        if iteration < polling["maximumIterations"]:
            sleeper(polling["intervalSeconds"])

    evidence = {
        "candidateDigest": V1.sha256(candidate_path),
        "grantID": grant["spec"]["grantID"],
        "startedAt": started_at,
        "completedAt": None,
        "pollResults": poll_results,
        "credentialBytesEmitted": False,
        "secretReadsPerformed": False,
        "mutationPerformed": False,
        "planes": {},
        "closureState": "BLOCKED-NAMESPACE-STILL-PRESENT",
    }
    if namespace_result is not None and namespace_result["outcome"] == "ABSENT":
        evidence["planes"]["ok-mgmt"] = [namespace_result] + [
            V2.run_query(kubectl, kubeconfigs["ok-mgmt"], query)
            for query in mgmt_queries if query["id"] != "mgmt-namespace"
        ]
        evidence["planes"]["ok-infra"] = [
            V2.run_query(kubectl, kubeconfigs["ok-infra"], query)
            for query in candidate["spec"]["planes"]["ok-infra"]["queries"]
        ]
        evidence["closureState"] = evaluate(evidence["planes"])
    evidence["completedAt"] = dt.datetime.now(dt.timezone.utc).isoformat()
    output.write_text(json.dumps(evidence, sort_keys=True, separators=(",", ":")) + "\n")
    output.chmod(0o600)
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "verify-grant", "observe"))
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--grant", type=Path)
    parser.add_argument("--kubectl", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "verify":
            verify_candidate(args.candidate.resolve())
            print(V1.sha256(args.candidate.resolve()))
        elif args.command == "verify-grant":
            if args.grant is None:
                raise ObservationError("grant is required")
            verify_grant(args.candidate.resolve(), args.grant.resolve())
            print(V1.sha256(args.grant.resolve()))
        else:
            if not args.execute or args.grant is None or args.kubectl is None:
                raise ObservationError("observe requires --execute, grant and kubectl")
            result = execute(args.candidate.resolve(), args.grant.resolve(), args.kubectl.resolve())
            print(json.dumps({"closureState": result["closureState"]}, sort_keys=True))
        return 0
    except (ObservationError, KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
