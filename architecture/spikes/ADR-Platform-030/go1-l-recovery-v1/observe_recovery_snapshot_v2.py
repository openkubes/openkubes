#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode


ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "observe_recovery_snapshot_v1_for_v2", ROOT / "observe_recovery_snapshot_v1.py"
)
V1 = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(V1)
SnapshotError = V1.SnapshotError
TOOL_DIGEST = V1.TOOL_DIGEST
API_ABSENCE_IDS = {"local-provider-vms", "local-provider-vmis"}


def verify_candidate(path: Path) -> dict[str, Any]:
    candidate = V1.read(path)
    spec = candidate["spec"]
    if spec["version"] != "ok141-go1-l-recovery-snapshot/v2":
        raise SnapshotError("candidate version mismatch")
    if spec["state"] != "READY-FOR-EXPLICIT-READ-ONLY-GRANT":
        raise SnapshotError("candidate is not in the expected state")
    if spec["protocolDigest"] != V1.sha256(ROOT / "go1-l-recovery-protocol-v1.yaml"):
        raise SnapshotError("protocol digest mismatch")
    if spec["tool"]["executorDigest"] != V1.sha256(Path(__file__).resolve()):
        raise SnapshotError("snapshot executor digest mismatch")
    if spec["tool"]["kubectlDigest"] != TOOL_DIGEST:
        raise SnapshotError("kubectl digest mismatch")
    if set(spec["planes"]) != {"ok-mgmt", "ok-infra"}:
        raise SnapshotError("plane set mismatch")
    allowed_absence = set()
    for plane, plane_spec in spec["planes"].items():
        if not plane_spec["kubeconfigPath"].startswith("/Users/arash/.kube/"):
            raise SnapshotError(f"unexpected kubeconfig path for {plane}")
        queries = plane_spec["queries"]
        if not queries or len({query["id"] for query in queries}) != len(queries):
            raise SnapshotError(f"invalid query identities for {plane}")
        for query in queries:
            uri = query["rawURI"]
            if not uri.startswith(("/api/", "/apis/")):
                raise SnapshotError(f"invalid raw URI: {uri}")
            lowered = uri.lower()
            if any(forbidden in lowered for forbidden in ("secret", "/pods", "/logs", "tokenrequest")):
                raise SnapshotError(f"forbidden query: {uri}")
            if query["mode"] == "collection" and not query.get("labelSelector"):
                raise SnapshotError(f"unbounded collection: {query['id']}")
            if query.get("allowAPIResourceAbsent"):
                if plane != "ok-mgmt" or query["mode"] != "collection" or query["id"] not in API_ABSENCE_IDS:
                    raise SnapshotError(f"unapproved API-absence allowance: {query['id']}")
                allowed_absence.add(query["id"])
    if allowed_absence != API_ABSENCE_IDS:
        raise SnapshotError("API-absence allowances are incomplete")
    if spec["authorization"]["readOnlyGranted"]:
        raise SnapshotError("candidate itself grants authority")
    if any(spec["authorization"][key] for key in spec["authorization"] if key != "readOnlyGranted"):
        raise SnapshotError("candidate carries forbidden authority")
    return candidate


def verify_grant(candidate_path: Path, grant_path: Path, now: datetime | None = None) -> dict[str, Any]:
    candidate = verify_candidate(candidate_path)
    grant = V1.read(grant_path)
    spec = grant["spec"]
    if spec["state"] != "GRANTED" or not spec["readOnlyAuthorized"] or not spec["credentialUseAuthorized"]:
        raise SnapshotError("read-only snapshot is not granted")
    if spec["candidateDigest"] != V1.sha256(candidate_path):
        raise SnapshotError("grant candidate digest mismatch")
    if spec["maximumRuns"] != 1 or spec["consumed"]:
        raise SnapshotError("grant is reused or not single-run")
    if any(spec[key] for key in (
        "mutationAuthorized", "cleanupAuthorized", "retryAuthorized",
        "secretReadAuthorized", "go1LAuthorized", "go1Authorized",
        "failureInjectionAuthorized",
    )):
        raise SnapshotError("grant carries excluded authority")
    current = now or datetime.now(timezone.utc)
    start, end = V1.parse_time(spec["notBefore"]), V1.parse_time(spec["notAfter"])
    if not (start <= current <= end) or (end - start).total_seconds() > 1200:
        raise SnapshotError("grant window is inactive or exceeds 20 minutes")
    if spec["outputPath"] != candidate["spec"]["evidence"]["outputPath"]:
        raise SnapshotError("evidence output mismatch")
    return grant


def run_query(
    kubectl: Path,
    kubeconfig: Path,
    query: dict[str, Any],
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> dict[str, Any]:
    uri = query["rawURI"]
    if query["mode"] == "collection":
        uri += "?" + urlencode({"labelSelector": query["labelSelector"]})
    completed = runner(
        [str(kubectl), "--kubeconfig", str(kubeconfig), "get", f"--raw={uri}"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        lowered = completed.stderr.lower()
        if query["mode"] == "exact" and "not found" in lowered:
            return {"id": query["id"], "outcome": "ABSENT", "objects": []}
        api_missing = any(text in lowered for text in (
            "server could not find the requested resource",
            "the requested resource was not found",
        ))
        if query.get("allowAPIResourceAbsent") and api_missing:
            return {"id": query["id"], "outcome": "API_NOT_SERVED", "objects": []}
        raise SnapshotError(f"query failed without retaining raw output: {query['id']}")
    value = json.loads(completed.stdout)
    items = value.get("items") if query["mode"] == "collection" else [value]
    if not isinstance(items, list):
        raise SnapshotError(f"invalid response shape: {query['id']}")
    return {
        "id": query["id"],
        "outcome": "PRESENT" if items else "ABSENT",
        "objects": [V1.retained_metadata(item) for item in items],
    }


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
        "startedAt": datetime.now(timezone.utc).isoformat(),
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
        evidence["planes"][plane] = [
            run_query(kubectl, kubeconfig, query) for query in plane_spec["queries"]
        ]
    evidence["completedAt"] = datetime.now(timezone.utc).isoformat()
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
                raise SnapshotError("snapshot requires --execute, --grant and --kubectl")
            execute(args.candidate.resolve(), args.grant.resolve(), args.kubectl.resolve())
        return 0
    except (SnapshotError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
