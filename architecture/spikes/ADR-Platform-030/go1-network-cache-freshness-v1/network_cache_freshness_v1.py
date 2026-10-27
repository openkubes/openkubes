#!/usr/bin/env python3
"""Validate source-bound dynamic freshness for Cilium cached health."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import yaml


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
CANDIDATE = HERE / "network-cache-freshness-candidate-v1.yaml"
SOURCE_LOCK = SPIKE / "go1-network-cache-timing-diagnostic-v1" / "upstream-cache-source-lock.yaml"
STATUS_CANDIDATE = SPIKE / "go1-network-status-semantics-v1" / "network-status-semantics-candidate-v1.yaml"
STATUS_TOOL = SPIKE / "go1-network-status-semantics-v1" / "network_status_semantics_v1.py"
TIMING_TOOL = SPIKE / "go1-network-cache-timing-diagnostic-v1" / "bounded_network_cache_timing_diagnostic_v1.py"
SOURCE_LOCK_DIGEST = "sha256:563ed197391196c7bbfd526f9f88eff0fcac73e1f4ade7113aca767e326e550f"
STATUS_CANDIDATE_DIGEST = "sha256:d2ef66ab787d93fb486b170a7010ab221251b696e0a855e4a3a546764f5b797b"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(value)
    return value


STATUS = load_module("ok141_status_semantics_for_cache_freshness", STATUS_TOOL)
TIMING = load_module("ok141_timing_parser_for_cache_freshness", TIMING_TOOL)


class CacheFreshnessError(ValueError):
    pass


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text())
    if not isinstance(value, dict):
        raise CacheFreshnessError(f"expected mapping: {path}")
    return value


def expect(actual: Any, expected: Any, context: str) -> None:
    if actual != expected:
        raise CacheFreshnessError(f"{context}: expected {expected!r}, got {actual!r}")


def validate_candidate(path: Path = CANDIDATE) -> dict[str, Any]:
    value = read(path)
    expect(value.get("kind"), "GO1NetworkCacheFreshnessAmendmentCandidate", "kind")
    spec = value["spec"]
    expect(spec["version"], "ok141-network-cache-freshness/v1", "version")
    expect(spec["state"], "OFFLINE-PROVEN-BLOCKED-NO-GO", "state")
    expect(digest(SOURCE_LOCK), SOURCE_LOCK_DIGEST, "source lock")
    expect(digest(STATUS_CANDIDATE), STATUS_CANDIDATE_DIGEST, "status candidate")
    expect(spec["upstreamSource"]["lockDigest"], SOURCE_LOCK_DIGEST, "source binding")
    expect(spec["statusSemantics"]["candidateDigest"], STATUS_CANDIDATE_DIGEST, "status binding")
    rule = spec["timingRule"]
    expect((rule["publicationIntervalSeconds"], rule["schedulingAndClockToleranceSeconds"], rule["maximumProbeIntervalInclusiveSeconds"]), (60, 10, 300), "timing bounds")
    expect(digest(HERE / spec["tool"]["path"]), spec["tool"]["digest"], "tool digest")
    expect(spec["authorization"]["decision"], "NO-GO", "authorization")
    if any(item for key, item in spec["authorization"].items() if key.endswith("Granted")):
        raise CacheFreshnessError("candidate grants authority")
    return value


def evaluate_probe(payload: dict[str, Any], expected_nodes: list[str], now: dt.datetime, _historical_maximum_age: int = 120) -> tuple[str, dict[str, Any]]:
    candidate = validate_candidate()
    rule = candidate["spec"]["timingRule"]
    try:
        interval = TIMING.parse_duration(payload.get("probeInterval", ""))
        timestamp = STATUS.parse_time(payload.get("timestamp", ""))
    except (ValueError, STATUS.StatusSemanticsError, TIMING.TimingDiagnosticError):
        return "FAIL-CACHED-HEALTH-TIMING-METADATA", {}
    if not 0 < interval <= rule["maximumProbeIntervalInclusiveSeconds"]:
        return "FAIL-CACHED-HEALTH-PROBE-INTERVAL", {}
    maximum_age = interval + rule["publicationIntervalSeconds"] + rule["schedulingAndClockToleranceSeconds"]
    response_age = (now - timestamp).total_seconds()
    if response_age < -rule["maximumFutureTimestampSeconds"] or response_age > maximum_age:
        return "FAIL-STALE-CACHED-HEALTH-RESPONSE", {"maximumAcceptedAgeSeconds": round(maximum_age, 3)}
    nodes = payload.get("nodes", [])
    if not isinstance(nodes, list) or sorted(item.get("name") for item in nodes if isinstance(item, dict)) != sorted(expected_nodes):
        return "FAIL-PROBE-NODE-COVERAGE", {}
    ages: list[float] = []
    for node in nodes:
        for section in ("host", "health-endpoint"):
            path = node.get(section, {}).get("primary-address")
            if not isinstance(path, dict):
                return "FAIL-FUNCTIONAL-CONNECTIVITY", {"section": section}
            for protocol in ("http", "icmp"):
                item = path.get(protocol)
                if not isinstance(item, dict) or not STATUS.successful_status(item) or not item.get("lastProbed"):
                    return "FAIL-FUNCTIONAL-CONNECTIVITY", {"section": section, "protocol": protocol}
                try:
                    age = (now - STATUS.parse_time(item["lastProbed"])).total_seconds()
                except (ValueError, STATUS.StatusSemanticsError):
                    return "FAIL-FUNCTIONAL-PATH-TIMESTAMP", {}
                if age < -rule["maximumFutureTimestampSeconds"] or age > maximum_age:
                    return "FAIL-STALE-CACHED-FUNCTIONAL-PATH", {"maximumAcceptedAgeSeconds": round(maximum_age, 3)}
                ages.append(age)
    if len(ages) != len(expected_nodes) * 4:
        return "FAIL-PROBE-PATH-COVERAGE", {}
    return "PASS-FUNCTIONAL-NETWORK-PROBE", {
        "nodeCount": len(nodes),
        "successfulPathCount": len(ages),
        "probeIntervalSeconds": round(interval, 3),
        "maximumAcceptedAgeSeconds": round(maximum_age, 3),
        "maximumObservedPathAgeSeconds": round(max(ages), 3),
    }


def plan(path: Path = CANDIDATE) -> dict[str, Any]:
    value = validate_candidate(path)
    return {"candidateDigest": digest(path), "timingRule": value["spec"]["timingRule"], "authorization": "NO-GO", "clusterContacted": False, "mutationPerformed": False}


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

