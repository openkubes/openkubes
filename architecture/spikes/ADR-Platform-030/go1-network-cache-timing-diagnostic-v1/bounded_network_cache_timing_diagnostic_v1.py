#!/usr/bin/env python3
"""One-shot redacted timing diagnostic for Cilium's cached health response."""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

import yaml


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
CANDIDATE = HERE / "network-cache-timing-diagnostic-candidate-v1.yaml"
SOURCE_LOCK = HERE / "upstream-cache-source-lock.yaml"
OLD_DIAGNOSTIC = SPIKE / "go1-network-functional-diagnostic-v1" / "bounded_network_functional_diagnostic_v1.py"
RESUME_CANDIDATE = SPIKE / "go1-happy-run-resume-v5" / "happy-run-resume-candidate-v5.yaml"
STATUS_TOOL = SPIKE / "go1-network-status-semantics-v1" / "network_status_semantics_v1.py"
FAILED_PATH = Path("/private/tmp/ok141-go1-l-network-ready-observer-status-v1-evidence.json")
OUTPUT_PATH = Path("/private/tmp/ok141-network-cache-timing-diagnostic-v1-evidence.json")
EPHEMERAL_PATH = Path("/private/tmp/ok141-network-cache-timing-diagnostic-v1-kubeconfig.yaml")
MGMT_CLIENT = Path("/private/tmp/ok141-kubectl-v1.34.1-darwin-amd64")
WORKLOAD_CLIENT = Path("/private/tmp/ok141-kubectl-v1.36.2-darwin-amd64")
MGMT_KUBECONFIG = Path("/Users/arash/.kube/ok-mgmt.yaml")
PROBE = ("cilium-health", "status", "--probe", "--output", "json")
SOURCE_LOCK_DIGEST = "sha256:563ed197391196c7bbfd526f9f88eff0fcac73e1f4ade7113aca767e326e550f"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(value)
    return value


OLD = load_module("ok141_old_functional_diagnostic_for_timing", OLD_DIAGNOSTIC)
STATUS = load_module("ok141_status_semantics_for_timing", STATUS_TOOL)


class TimingDiagnosticError(ValueError):
    pass


def sha_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def sha(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def read(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text())
    if not isinstance(value, dict):
        raise TimingDiagnosticError(f"expected mapping: {path}")
    return value


def expect(actual: Any, expected: Any, context: str) -> None:
    if actual != expected:
        raise TimingDiagnosticError(f"{context}: expected {expected!r}, got {actual!r}")


def parse_time(value: str) -> dt.datetime:
    return STATUS.parse_time(value)


DURATION = re.compile(r"^(?:(?P<h>[0-9]+)h)?(?:(?P<m>[0-9]+)m)?(?P<s>[0-9]+(?:\.[0-9]+)?)s$")


def parse_duration(value: str) -> float:
    match = DURATION.fullmatch(value or "")
    if not match:
        raise TimingDiagnosticError("invalid Go duration")
    return int(match.group("h") or 0) * 3600 + int(match.group("m") or 0) * 60 + float(match.group("s"))


def validate_candidate(path: Path = CANDIDATE) -> dict[str, Any]:
    value = read(path)
    expect(value.get("kind"), "GO1NetworkCacheTimingDiagnosticCandidate", "kind")
    spec = value["spec"]
    expect(spec["version"], "ok141-network-cache-timing-diagnostic/v1", "version")
    expect(spec["state"], "OFFLINE-PROVEN-BLOCKED-NO-GO", "state")
    expect(sha(RESUME_CANDIDATE), "sha256:3e2ef69489668a6157867331ff11dced512b265162218b7a06c6d5d0008b01a2", "resume candidate")
    expect(sha(SOURCE_LOCK), SOURCE_LOCK_DIGEST, "source lock")
    lock = read(SOURCE_LOCK)["spec"]
    expect((lock["repository"], lock["commit"]), ("cilium/cilium", "9a8982433e18019e290b8199c0c4ad24f66befe8"), "source identity")
    expect(lock["derivedSemantics"], {"cliProbeForcesFreshCycle": False, "responseIsCached": True, "publicationIntervalSeconds": 60, "fixed120SecondFreshnessProven": False}, "source semantics")
    expect(spec["sourceSemantics"]["lockDigest"], SOURCE_LOCK_DIGEST, "source binding")
    expect(spec["probe"]["command"], list(PROBE), "probe command")
    expect(spec["output"]["path"], str(OUTPUT_PATH), "output path")
    expect(sha(HERE / spec["tool"]["path"]), spec["tool"]["digest"], "tool digest")
    expect(spec["authorization"]["decision"], "NO-GO", "authorization")
    if any(item for key, item in spec["authorization"].items() if key.endswith("Granted")):
        raise TimingDiagnosticError("candidate grants authority")
    return value


def safe_failed(spec: dict[str, Any]) -> dict[str, Any]:
    path = Path(spec["failedEvidencePath"])
    expect(path, FAILED_PATH, "failed evidence path")
    if path.is_symlink() or not path.is_file() or (path.stat().st_mode & 0o777) != 0o600:
        raise TimingDiagnosticError("unsafe failed evidence")
    expect(sha(path), spec["failedEvidenceDigest"], "failed evidence digest")
    value = read(path)
    expect((value.get("kind"), value.get("closureState"), value.get("NetworkReady")), ("GO1LNetworkReadyEvidence", "FAIL-STALE-FUNCTIONAL-PATH", False), "failed result")
    expect((value.get("fixedPodExecProbePerformed"), value.get("persistentMutationPerformed")), (True, False), "failed boundary")
    pod = value.get("details", {}).get("probePod", {})
    expect((spec["podName"], spec["podUID"]), (pod.get("name"), pod.get("uid")), "probe pod binding")
    expect(spec["workloadTargetIdentityDigest"], value.get("workloadTargetIdentityDigest"), "target binding")
    return value


TRUE = ("clusterContactGranted", "managementCredentialUseGranted", "exactSecretReadGranted", "ephemeralCredentialMaterializationGranted", "workloadCredentialUseGranted", "exactPodReadGranted", "fixedProbeExecGranted")
FALSE = ("persistentMutationGranted", "happyRunResumeGranted", "retryGranted", "rollbackOrCleanupGranted", "evidencePublicationGranted", "failureInjectionGranted")


def validate_grant(candidate_path: Path, grant_path: Path, now: dt.datetime | None = None):
    validate_candidate(candidate_path)
    grant = read(grant_path)
    expect(grant.get("kind"), "GO1NetworkCacheTimingDiagnosticGrant", "grant kind")
    spec = grant["spec"]
    expect((spec.get("decision"), spec.get("authority"), spec.get("singleRun"), spec.get("consumed")), ("GO", "github:arashkaffamanesh", True, False), "grant identity")
    expect(spec.get("candidateDigest"), sha(candidate_path), "candidate digest")
    if any(spec.get(key) is not True for key in TRUE) or any(spec.get(key) is not False for key in FALSE):
        raise TimingDiagnosticError("diagnostic authority incomplete or overbroad")
    current = now or dt.datetime.now(dt.timezone.utc)
    issued, expires = parse_time(spec["issuedAt"]), parse_time(spec["expiresAt"])
    if not issued <= current <= expires or expires - issued > dt.timedelta(minutes=20):
        raise TimingDiagnosticError("grant inactive or exceeds 20 minutes")
    return grant, safe_failed(spec)


def timing_summary(payload: dict[str, Any], expected_nodes: list[str], now: dt.datetime) -> tuple[str, dict[str, Any]]:
    nodes = payload.get("nodes")
    if not isinstance(nodes, list) or sorted(item.get("name") for item in nodes if isinstance(item, dict)) != sorted(expected_nodes):
        return "FAIL-NODE-COVERAGE", {}
    probe_interval = parse_duration(payload.get("probeInterval", ""))
    response_age = max(0.0, (now - parse_time(payload.get("timestamp", ""))).total_seconds())
    ages: list[float] = []
    counts = {"success": 0, "failure": 0, "invalid": 0}
    for node in nodes:
        for section in ("host", "health-endpoint"):
            primary = node.get(section, {}).get("primary-address", {})
            for protocol in ("http", "icmp"):
                item = primary.get(protocol)
                if not isinstance(item, dict) or not item.get("lastProbed"):
                    counts["invalid"] += 1
                    continue
                status = item.get("status", "__omitted__")
                if "status" not in item or status == "":
                    counts["success"] += 1
                elif isinstance(status, str):
                    counts["failure"] += 1
                else:
                    counts["invalid"] += 1
                ages.append(max(0.0, (now - parse_time(item["lastProbed"])).total_seconds()))
    if len(ages) != 8:
        return "FAIL-PATH-COVERAGE", {"pathCount": len(ages), "statusCategoryCounts": counts}
    rounded = sorted(round(value, 3) for value in ages)
    result = "PASS-CACHED-HEALTH-TIMING-OBSERVED" if counts == {"success": 8, "failure": 0, "invalid": 0} else "OBSERVED-NON-SUCCESS-STATUS"
    return result, {
        "probeIntervalSeconds": round(probe_interval, 3),
        "responseTimestampAgeSeconds": round(response_age, 3),
        "minimumPathAgeSeconds": rounded[0],
        "maximumPathAgeSeconds": rounded[-1],
        "sortedPathAgeSeconds": rounded,
        "statusCategoryCounts": counts,
        "pathCount": 8,
    }


def execute(candidate_path: Path, grant_path: Path, runner: Callable[..., Any] = subprocess.run) -> dict[str, Any]:
    candidate = validate_candidate(candidate_path)
    grant, failed = validate_grant(candidate_path, grant_path)
    old_spec = OLD.validate_candidate()["spec"]
    if OUTPUT_PATH.exists() or EPHEMERAL_PATH.exists():
        raise TimingDiagnosticError("exclusive output already exists")
    for path, expected in ((MGMT_CLIENT, old_spec["clients"]["managementDigest"]), (WORKLOAD_CLIENT, old_spec["clients"]["workloadDigest"])):
        expect(sha(path), expected, "client digest")
    if MGMT_KUBECONFIG.is_symlink() or not MGMT_KUBECONFIG.is_file() or (MGMT_KUBECONFIG.stat().st_mode & 0o777) != 0o600:
        raise TimingDiagnosticError("unsafe management kubeconfig")
    expect(OLD.NETWORK.EXECUTOR.inspect_identity(MGMT_KUBECONFIG)["identityDigest"], old_spec["managementCredentialIdentityDigest"], "management identity")
    secret = OLD.raw_get(MGMT_CLIENT, MGMT_KUBECONFIG, old_spec["secretRawURI"], runner)
    OLD.write_exclusive(EPHEMERAL_PATH, base64.b64decode(secret["data"]["value"], validate=True))
    pod_verified = False
    completed = None
    try:
        expect(OLD.NETWORK.EXECUTOR.inspect_identity(EPHEMERAL_PATH)["identityDigest"], grant["spec"]["workloadTargetIdentityDigest"], "workload identity")
        pod_name = grant["spec"]["podName"]
        pod = OLD.raw_get(WORKLOAD_CLIENT, EPHEMERAL_PATH, f"/api/v1/namespaces/kube-system/pods/{quote(pod_name, safe='')}", runner)
        expect(pod.get("metadata", {}).get("uid"), grant["spec"]["podUID"], "pod UID")
        if "cilium-agent" not in {item.get("name") for item in pod.get("spec", {}).get("containers", [])}:
            raise TimingDiagnosticError("bound pod lacks cilium-agent")
        pod_verified = True
        completed = runner([str(WORKLOAD_CLIENT), "--kubeconfig", str(EPHEMERAL_PATH), "exec", "--namespace", "kube-system", pod_name, "--container", "cilium-agent", "--", *PROBE], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        if completed.returncode == 0:
            result, details = timing_summary(json.loads(completed.stdout), failed["details"]["nodeNames"], dt.datetime.now(dt.timezone.utc))
        else:
            result, details = "PROBE-EXEC-FAILED", {"stdoutDigest": sha_bytes(completed.stdout), "stderrDigest": sha_bytes(completed.stderr)}
    finally:
        EPHEMERAL_PATH.unlink(missing_ok=True)
    evidence = {
        "apiVersion": "evidence.openkubes.io/v1alpha1",
        "kind": "GO1NetworkCacheTimingDiagnosticEvidence",
        "candidateDigest": sha(candidate_path),
        "grantID": grant["spec"]["grantID"],
        "failedEvidenceDigest": sha(FAILED_PATH),
        "result": result,
        "probeExitCode": completed.returncode if completed else None,
        "podIdentityVerified": pod_verified,
        "details": details,
        "persistentMutationPerformed": False,
        "happyRunResumed": False,
        "rawProbeOutputRetained": False,
        "nodeNamesRetained": False,
        "ipAddressesRetained": False,
        "rawStatusesRetained": False,
        "secretPayloadRetained": False,
        "workloadKubeconfigRemoved": not EPHEMERAL_PATH.exists(),
    }
    evidence["semanticDigest"] = sha_bytes(json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode())
    OLD.write_exclusive(OUTPUT_PATH, (json.dumps(evidence, sort_keys=True, separators=(",", ":")) + "\n").encode())
    return evidence


def plan(path: Path = CANDIDATE) -> dict[str, Any]:
    validate_candidate(path)
    return {"candidateDigest": sha(path), "authorization": "NO-GO", "clusterContacted": False, "mutationPerformed": False}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "verify-grant", "run"))
    parser.add_argument("--candidate", type=Path, default=CANDIDATE)
    parser.add_argument("--grant", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "verify":
            print(json.dumps(plan(args.candidate.resolve()), indent=2, sort_keys=True))
        elif args.command == "verify-grant":
            if args.grant is None:
                raise TimingDiagnosticError("grant required")
            validate_grant(args.candidate.resolve(), args.grant.resolve())
            print(sha(args.grant.resolve()))
        else:
            if not args.execute or args.grant is None:
                raise TimingDiagnosticError("run requires --execute and grant")
            print(json.dumps(execute(args.candidate.resolve(), args.grant.resolve()), indent=2, sort_keys=True))
        return 0
    except Exception as error:
        print(f"ERROR: {type(error).__name__}: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
