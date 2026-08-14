#!/usr/bin/env python3
"""Validate the additive Cilium health JSON status-semantics amendment."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import yaml


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
CANDIDATE = HERE / "network-status-semantics-candidate-v1.yaml"
SOURCE_LOCK = HERE / "upstream-source-lock.yaml"
V1_CANDIDATE = SPIKE / "go1-l-network-observer-v1" / "go1-l-network-observer-candidate-v1.yaml"
V1_TOOL = SPIKE / "go1-l-network-observer-v1" / "bounded_go1_l_network_observer_v1.py"

V1_CANDIDATE_DIGEST = "sha256:15b24bd0d7247e0a05d4b1f291221cc52e4f1cefa498b8fe4c5d00b6347f3e04"
V1_TOOL_DIGEST = "sha256:801780456e5f4ec4381ad4fa58b28568bdf6ad655d642b114eb537f27feb28a5"
SOURCE_LOCK_DIGEST = "sha256:e1bac1e7bd7cba757e586acb1c7dd21707546fcd23acc6801a3e7d241dcf4037"
CILIUM_COMMIT = "9a8982433e18019e290b8199c0c4ad24f66befe8"


class StatusSemanticsError(ValueError):
    pass


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def read_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text())
    if not isinstance(value, dict):
        raise StatusSemanticsError(f"expected mapping: {path}")
    return value


def expect(actual: Any, expected: Any, context: str) -> None:
    if actual != expected:
        raise StatusSemanticsError(f"{context}: expected {expected!r}, got {actual!r}")


def parse_time(value: str) -> dt.datetime:
    if not isinstance(value, str) or not value:
        raise StatusSemanticsError("timestamp missing")
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise StatusSemanticsError("timestamp lacks timezone")
    return parsed.astimezone(dt.timezone.utc)


def successful_status(item: dict[str, Any]) -> bool:
    """Accept only Cilium's omitted/empty Go-string success representation."""

    if "status" not in item:
        return True
    return isinstance(item["status"], str) and item["status"] == ""


def path_ok(path: Any) -> tuple[bool, list[str]]:
    if not isinstance(path, dict):
        return False, []
    timestamps: list[str] = []
    for protocol in ("http", "icmp"):
        item = path.get(protocol)
        if not isinstance(item, dict) or not successful_status(item):
            return False, timestamps
        timestamp = item.get("lastProbed")
        if not isinstance(timestamp, str) or not timestamp:
            return False, timestamps
        timestamps.append(timestamp)
    return True, timestamps


def evaluate_probe(payload: dict[str, Any], expected_nodes: list[str], now: dt.datetime, maximum_age: int) -> tuple[str, dict[str, Any]]:
    try:
        timestamp = parse_time(payload.get("timestamp", ""))
    except (StatusSemanticsError, ValueError):
        return "FAIL-FUNCTIONAL-PROBE-TIMESTAMP", {}
    if abs((now - timestamp).total_seconds()) > maximum_age:
        return "FAIL-STALE-FUNCTIONAL-PROBE", {}
    nodes = payload.get("nodes", [])
    if not isinstance(nodes, list) or sorted(item.get("name") for item in nodes if isinstance(item, dict)) != sorted(expected_nodes):
        return "FAIL-PROBE-NODE-COVERAGE", {}
    last_probed: list[str] = []
    for node in nodes:
        for section in ("host", "health-endpoint"):
            ok, timestamps = path_ok(node.get(section, {}).get("primary-address"))
            if not ok:
                return "FAIL-FUNCTIONAL-CONNECTIVITY", {"node": node.get("name"), "section": section}
            last_probed.extend(timestamps)
    try:
        stale = any(abs((now - parse_time(value)).total_seconds()) > maximum_age for value in last_probed)
    except (StatusSemanticsError, ValueError):
        return "FAIL-FUNCTIONAL-PATH-TIMESTAMP", {}
    if stale:
        return "FAIL-STALE-FUNCTIONAL-PATH", {}
    return "PASS-FUNCTIONAL-NETWORK-PROBE", {
        "timestamp": timestamp.isoformat(),
        "nodeCount": len(nodes),
        "successfulPathCount": len(last_probed),
    }


def validate_source_lock(path: Path = SOURCE_LOCK) -> dict[str, Any]:
    value = read_yaml(path)
    expect(value.get("kind"), "UpstreamSourceSemanticsLock", "source-lock kind")
    spec = value["spec"]
    expect((spec["repository"], spec["commit"]), ("cilium/cilium", CILIUM_COMMIT), "source identity")
    files = {item["path"]: item for item in spec["files"]}
    expect(files["api/v1/health/models/connectivity_status.go"]["gitBlobSHA"], "ac4a6c6801d29b47f103cbee7ee03512dc5f4fcb", "model blob")
    expect(files["pkg/health/server/prober.go"]["gitBlobSHA"], "9ec1c6272be4d424d15a9a75935fdb208b85afd3", "prober blob")
    expect(spec["derivedSemantics"], {
        "omittedStatusIsSuccessfulZeroValue": True,
        "presentEmptyStatusIsSuccessfulZeroValue": True,
        "presentNonEmptyStatusIsFailure": True,
        "explicitNullStatusAccepted": False,
    }, "derived semantics")
    return value


def validate_candidate(path: Path = CANDIDATE) -> dict[str, Any]:
    value = read_yaml(path)
    expect(value.get("kind"), "GO1NetworkStatusSemanticsAmendmentCandidate", "kind")
    spec = value["spec"]
    expect(spec["version"], "ok141-network-status-semantics/v1", "version")
    expect(spec["state"], "OFFLINE-PROVEN-BLOCKED-NO-GO", "state")
    expect(digest(V1_CANDIDATE), V1_CANDIDATE_DIGEST, "historical candidate digest")
    expect(digest(V1_TOOL), V1_TOOL_DIGEST, "historical tool digest")
    expect(digest(SOURCE_LOCK), SOURCE_LOCK_DIGEST, "source-lock digest")
    validate_source_lock()
    expect(spec["supersedes"]["candidateDigest"], V1_CANDIDATE_DIGEST, "historical candidate binding")
    expect(spec["supersedes"]["toolDigest"], V1_TOOL_DIGEST, "historical tool binding")
    expect(spec["upstreamSource"]["lockDigest"], SOURCE_LOCK_DIGEST, "source-lock binding")
    expect(spec["statusSemantics"], {
        "omitted": "success-candidate",
        "presentEmptyString": "success-candidate",
        "presentNonEmptyString": "failure",
        "presentNullOrNonString": "failure",
    }, "status semantics")
    expect(digest(HERE / spec["tool"]["path"]), spec["tool"]["digest"], "tool digest")
    expect(spec["authorization"]["decision"], "NO-GO", "authorization")
    if any(item for key, item in spec["authorization"].items() if key.endswith("Granted")):
        raise StatusSemanticsError("candidate grants authority")
    return value


def plan(path: Path = CANDIDATE) -> dict[str, Any]:
    validate_candidate(path)
    return {
        "candidateDigest": digest(path),
        "ciliumCommit": CILIUM_COMMIT,
        "authorization": "NO-GO",
        "clusterContacted": False,
        "mutationPerformed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify",))
    parser.add_argument("--candidate", type=Path, default=CANDIDATE)
    args = parser.parse_args()
    try:
        print(json.dumps(plan(args.candidate.resolve()), indent=2, sort_keys=True))
        return 0
    except Exception as error:
        print(f"ERROR: {type(error).__name__}: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
