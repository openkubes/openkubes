#!/usr/bin/env python3
"""Reusable, immutable-attempt R0 observer for OK-141 recovery."""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
MODULE_SPEC = importlib.util.spec_from_file_location(
    "observe_recovery_snapshot_v3_for_attempt", HERE / "observe_recovery_snapshot_v3.py"
)
V3 = importlib.util.module_from_spec(MODULE_SPEC)
assert MODULE_SPEC.loader is not None
MODULE_SPEC.loader.exec_module(V3)
V2 = V3.V2
V1 = V3.V1
SnapshotError = V3.SnapshotError
TOOL_DIGEST = V3.TOOL_DIGEST
QUERY_PROFILE = HERE / "recovery-snapshot-candidate-v3.yaml"
QUERY_PROFILE_DIGEST = "sha256:cc16cd21ae73948b1db83d1fa3490d545fd1b0616ecf81776281b36aa21df435"
ATTEMPT_ID = re.compile(r"^r0-v[4-9][0-9]*-[0-9]{8}-[0-9]{2}$")


def verify_candidate(path: Path) -> dict[str, Any]:
    candidate = V1.read(path)
    spec = candidate["spec"]
    if spec["version"] != "ok141-go1-l-recovery-snapshot-attempt/v1":
        raise SnapshotError("candidate version mismatch")
    if spec["state"] != "READY-FOR-EXPLICIT-READ-ONLY-GRANT":
        raise SnapshotError("candidate state mismatch")
    if spec["protocolDigest"] != V1.sha256(HERE / "go1-l-recovery-protocol-v1.yaml"):
        raise SnapshotError("protocol digest mismatch")
    if V1.sha256(QUERY_PROFILE) != QUERY_PROFILE_DIGEST:
        raise SnapshotError("historical query profile digest mismatch")
    if spec["queryProfileDigest"] != QUERY_PROFILE_DIGEST:
        raise SnapshotError("candidate query profile mismatch")
    if spec["planes"] != V1.read(QUERY_PROFILE)["spec"]["planes"]:
        raise SnapshotError("candidate query set differs from reviewed profile")
    if spec["tool"]["executorDigest"] != V1.sha256(Path(__file__).resolve()):
        raise SnapshotError("executor digest mismatch")
    if spec["tool"]["kubectlDigest"] != TOOL_DIGEST:
        raise SnapshotError("kubectl digest mismatch")

    attempt = spec["attempt"]
    if not ATTEMPT_ID.fullmatch(attempt["id"]) or attempt["sequence"] < 4:
        raise SnapshotError("invalid immutable attempt identity")
    history = attempt["predecessor"]
    for field in ("candidateDigest", "privateEvidenceDigest", "privateBindingDigest"):
        if not isinstance(history.get(field), str) or not history[field].startswith("sha256:"):
            raise SnapshotError("attempt lacks predecessor evidence identity")
    if history["disposition"] != "valid-historical-expired-no-cleanup":
        raise SnapshotError("predecessor disposition mismatch")

    output = spec["evidence"]["outputPath"]
    expected_output = f"/private/tmp/ok141-go1-l-recovery-snapshot-{attempt['id']}-evidence.json"
    if output != expected_output or not spec["evidence"]["outputMustBeAbsent"]:
        raise SnapshotError("attempt output identity mismatch")
    if spec["runtimeBinding"]["name"] != f"ok141-go1-l-recovery-runtime-binding-{attempt['id']}":
        raise SnapshotError("runtime binding identity mismatch")
    if spec["runtimeBinding"]["freshnessMaximumMinutes"] != 10:
        raise SnapshotError("runtime binding freshness changed")
    authorization = spec["authorization"]
    if any(authorization.values()):
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
    if not start <= current <= end or end - start > dt.timedelta(minutes=20):
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
        "attemptID": candidate["spec"]["attempt"]["id"],
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
            verify_grant(args.candidate.resolve(), args.grant.resolve())
            print(V1.sha256(args.grant.resolve()))
        else:
            if not args.execute or args.grant is None or args.kubectl is None:
                raise SnapshotError("snapshot requires --execute, grant and kubectl")
            execute(args.candidate.resolve(), args.grant.resolve(), args.kubectl.resolve())
        return 0
    except (SnapshotError, KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
