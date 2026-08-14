#!/usr/bin/env python3
"""Additive fresh R0-v3 observation instance for UID-bound cleanup planning."""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("observe_recovery_snapshot_v2_for_v3", HERE / "observe_recovery_snapshot_v2.py")
V2 = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(V2)
V1 = V2.V1
SnapshotError = V2.SnapshotError
TOOL_DIGEST = V2.TOOL_DIGEST
API_ABSENCE_IDS = V2.API_ABSENCE_IDS
V2_CANDIDATE_DIGEST = "sha256:4cc18693b948844a0516492395e7943cd1f1925d66b35f25d35977c989bac71f"
V2_EVIDENCE_DIGEST = "sha256:33c617b54d6de4e31fd15335487102a229150d9210a7cd4ee1fd0f302b8c10c3"
V2_REDACTED_CLOSURE_DIGEST = "sha256:42e9da5225e02f551c12ea4a14a85eeef73de2b6462b4e9bd9b9855b367e439d"


def verify_candidate(path: Path) -> dict[str, Any]:
    candidate = V1.read(path)
    spec = candidate["spec"]
    if spec["version"] != "ok141-go1-l-recovery-snapshot/v3":
        raise SnapshotError("candidate version mismatch")
    if spec["state"] != "READY-FOR-EXPLICIT-READ-ONLY-GRANT":
        raise SnapshotError("candidate state mismatch")
    if spec["protocolDigest"] != V1.sha256(HERE / "go1-l-recovery-protocol-v1.yaml"):
        raise SnapshotError("protocol digest mismatch")
    supersedes = spec["supersedes"]
    if supersedes != {
        "candidateDigest": V2_CANDIDATE_DIGEST,
        "privateEvidenceDigest": V2_EVIDENCE_DIGEST,
        "publicRedactedClosureDigest": V2_REDACTED_CLOSURE_DIGEST,
        "disposition": "valid-historical-consumed-successful-read-only",
        "reason": "A fresh ten-minute runtime binding requires a new immutable evidence output; v2 remains preserved.",
    }:
        raise SnapshotError("v2 history binding mismatch")
    if spec["tool"]["executorDigest"] != V1.sha256(Path(__file__).resolve()):
        raise SnapshotError("executor digest mismatch")
    if spec["tool"]["kubectlDigest"] != TOOL_DIGEST:
        raise SnapshotError("kubectl digest mismatch")
    if set(spec["planes"]) != {"ok-mgmt", "ok-infra"}:
        raise SnapshotError("plane set mismatch")
    allowed_absence = set()
    query_count = 0
    for plane, plane_spec in spec["planes"].items():
        if not plane_spec["kubeconfigPath"].startswith("/Users/arash/.kube/"):
            raise SnapshotError("unexpected kubeconfig path")
        queries = plane_spec["queries"]
        query_count += len(queries)
        if len({query["id"] for query in queries}) != len(queries):
            raise SnapshotError("duplicate query identity")
        for query in queries:
            if not query["rawURI"].startswith(("/api/", "/apis/")):
                raise SnapshotError("invalid raw URI")
            if query["mode"] == "collection" and not query.get("labelSelector"):
                raise SnapshotError("unbounded collection")
            if query.get("allowAPIResourceAbsent"):
                if plane != "ok-mgmt" or query["mode"] != "collection" or query["id"] not in API_ABSENCE_IDS:
                    raise SnapshotError("unapproved API-absence allowance")
                allowed_absence.add(query["id"])
    if query_count != 20 or allowed_absence != API_ABSENCE_IDS:
        raise SnapshotError("query profile mismatch")
    if spec["evidence"]["outputPath"] != "/private/tmp/ok141-go1-l-recovery-snapshot-v3-evidence.json":
        raise SnapshotError("v3 output mismatch")
    if spec["authorization"]["readOnlyGranted"] or any(
        value for key, value in spec["authorization"].items() if key != "readOnlyGranted"
    ):
        raise SnapshotError("candidate grants authority")
    return candidate


def verify_grant(candidate_path: Path, grant_path: Path, now: dt.datetime | None = None) -> dict[str, Any]:
    candidate = verify_candidate(candidate_path)
    grant = V1.read(grant_path)
    spec = grant["spec"]
    if spec["state"] != "GRANTED" or not spec["readOnlyAuthorized"] or not spec["credentialUseAuthorized"]:
        raise SnapshotError("read-only snapshot is not granted")
    if spec["candidateDigest"] != V1.sha256(candidate_path):
        raise SnapshotError("grant candidate digest mismatch")
    if spec["maximumRuns"] != 1 or spec["consumed"]:
        raise SnapshotError("grant is reused or not single-run")
    for claim in (
        "mutationAuthorized", "cleanupAuthorized", "retryAuthorized", "secretReadAuthorized",
        "go1LAuthorized", "go1Authorized", "failureInjectionAuthorized",
    ):
        if spec[claim]:
            raise SnapshotError("grant carries excluded authority")
    current = now or dt.datetime.now(dt.timezone.utc)
    start, end = V1.parse_time(spec["notBefore"]), V1.parse_time(spec["notAfter"])
    if not start <= current <= end or (end - start).total_seconds() > 1200:
        raise SnapshotError("grant window is inactive or exceeds 20 minutes")
    if spec["outputPath"] != candidate["spec"]["evidence"]["outputPath"]:
        raise SnapshotError("evidence output mismatch")
    return grant


def execute(candidate_path: Path, grant_path: Path, kubectl: Path) -> dict[str, Any]:
    candidate = verify_candidate(candidate_path)
    grant = verify_grant(candidate_path, grant_path)
    if V1.sha256(kubectl) != TOOL_DIGEST:
        raise SnapshotError("local kubectl digest mismatch")
    output = Path(candidate["spec"]["evidence"]["outputPath"])
    if output.exists():
        raise SnapshotError("evidence output already exists")
    evidence = {
        "candidateDigest": V1.sha256(candidate_path),
        "grantID": grant["spec"]["grantID"],
        "startedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "credentialBytesEmitted": False,
        "credentialUseAuthorized": True,
        "secretReadsPerformed": False,
        "mutationPerformed": False,
        "planes": {},
    }
    for plane, plane_spec in candidate["spec"]["planes"].items():
        kubeconfig = Path(plane_spec["kubeconfigPath"])
        if kubeconfig.is_symlink() or not kubeconfig.is_file() or (kubeconfig.stat().st_mode & 0o777) != 0o600:
            raise SnapshotError(f"unsafe kubeconfig for {plane}")
        evidence["planes"][plane] = [V2.run_query(kubectl, kubeconfig, query) for query in plane_spec["queries"]]
    evidence["completedAt"] = dt.datetime.now(dt.timezone.utc).isoformat()
    output.write_text(json.dumps(evidence, sort_keys=True, separators=(",", ":")) + "\n")
    output.chmod(0o600)
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "verify-grant", "snapshot"))
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
                raise SnapshotError("grant is required")
            print(V1.sha256(args.grant.resolve()) if verify_grant(args.candidate.resolve(), args.grant.resolve()) else "")
        else:
            if not args.execute or args.grant is None or args.kubectl is None:
                raise SnapshotError("snapshot requires --execute, grant and kubectl")
            execute(args.candidate.resolve(), args.grant.resolve(), args.kubectl.resolve())
        return 0
    except (SnapshotError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
