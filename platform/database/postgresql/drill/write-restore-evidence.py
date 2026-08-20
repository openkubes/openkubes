#!/usr/bin/env python3
"""Derive one RestoreVerified artifact from a complete JSONL observation stream."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


class ObservationError(ValueError):
    pass


SINGLETON_EVENTS = {
    "run",
    "profile",
    "database",
    "backup",
    "source",
    "recovery",
    "runtime",
    "psql",
    "effective-policy",
    "isolation",
}
ALLOWED_EVENTS = SINGLETON_EVENTS | {"check"}
SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
LSN = re.compile(r"^[0-9A-F]+/[0-9A-F]+$", re.IGNORECASE)


def require_text(mapping: dict[str, Any], key: str, label: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ObservationError(f"{label}.{key} must be an observed non-empty string")
    if value.strip().lower() in {"unknown", "<unknown>", "null", "none", "<missing>"}:
        raise ObservationError(f"{label}.{key} contains an unknown observed value")
    return value


def observed(event: dict[str, Any], label: str) -> dict[str, Any]:
    value = event.get("observed")
    if not isinstance(value, dict) or not value:
        raise ObservationError(f"{label} must carry non-empty observed values")
    for key, item in value.items():
        if item is None or (isinstance(item, str) and not item.strip()):
            raise ObservationError(f"{label}.observed.{key} is missing")
        if isinstance(item, str) and item.strip().lower() in {
            "unknown", "<unknown>", "null", "none", "<missing>"
        }:
            raise ObservationError(f"{label}.observed.{key} is unknown")
    return value


def load_stream(path: Path) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    singletons: dict[str, dict[str, Any]] = {}
    checks: list[dict[str, Any]] = []
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            raise ObservationError(f"JSONL line {number} is empty")
        try:
            event = json.loads(raw)
        except json.JSONDecodeError as error:
            raise ObservationError(f"JSONL line {number} is not valid JSON: {error}") from error
        if not isinstance(event, dict):
            raise ObservationError(f"JSONL line {number} must be an object")
        kind = event.get("event")
        if kind not in ALLOWED_EVENTS:
            raise ObservationError(f"JSONL line {number} has unknown event {kind!r}")
        observed(event, f"line {number} {kind}")
        if kind == "check":
            checks.append(event)
        elif kind in singletons:
            raise ObservationError(f"duplicate singleton event {kind!r}")
        else:
            singletons[kind] = event
    missing = sorted(SINGLETON_EVENTS - singletons.keys())
    if missing:
        raise ObservationError("observation stream is partial; missing event(s): " + ", ".join(missing))
    return singletons, checks


def profile_contract(path: Path) -> tuple[list[str], str]:
    data = path.read_bytes()
    names = re.findall(rb"^-- check: ([a-z0-9-]+)\s*$", data, re.MULTILINE)
    decoded = [name.decode("ascii") for name in names]
    if not decoded or len(decoded) != len(set(decoded)):
        raise ObservationError("check profile must declare a unique -- check: name for every SQL check")
    return decoded, "sha256:" + hashlib.sha256(data).hexdigest()


def parse_time(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ObservationError(f"{label} is not an ISO-8601 timestamp") from error
    if parsed.tzinfo is None:
        raise ObservationError(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc)


def validate_and_build(
    singletons: dict[str, dict[str, Any]],
    checks: list[dict[str, Any]],
    profile_path: Path,
    evidence_ref: str,
) -> dict[str, Any]:
    expected_checks, computed_profile_digest = profile_contract(profile_path)
    profile = singletons["profile"]
    profile_observed = observed(profile, "profile")
    if require_text(profile_observed, "digest", "profile.observed") != computed_profile_digest:
        raise ObservationError("observed check-profile digest does not match the supplied profile")
    if profile_observed.get("expectedChecks") != len(expected_checks):
        raise ObservationError("observed dynamic profile count does not match profile declarations")

    by_name: dict[str, dict[str, Any]] = {}
    for check in checks:
        name = require_text(check, "name", "check")
        if name in by_name:
            raise ObservationError(f"duplicate check observation {name!r}")
        result = require_text(check, "result", f"check {name}")
        if result not in {"PASS", "FAIL"}:
            raise ObservationError(f"check {name!r} has unknown result {result!r}")
        if result != "PASS":
            raise ObservationError(f"check {name!r} did not pass")
        by_name[name] = check
    expected_all = expected_checks + ["selected-backup-object-readable"]
    if set(by_name) != set(expected_all) or len(by_name) != len(expected_all):
        raise ObservationError(
            "check stream is partial or unknown; expected exactly " + ", ".join(expected_all)
        )

    psql = observed(singletons["psql"], "psql")
    if psql.get("exitCode") != 0 or psql.get("result") != "PASS":
        raise ObservationError("psql execution did not succeed")
    if psql.get("jsonRecords") != len(expected_checks):
        raise ObservationError("psql record count does not match the dynamic profile count")

    run = observed(singletons["run"], "run")
    run_id = require_text(run, "runId", "run.observed")
    if require_text(run, "evidenceRef", "run.observed") != evidence_ref:
        raise ObservationError("stream evidenceRef does not match writer output reference")

    database = observed(singletons["database"], "database")
    backup = observed(singletons["backup"], "backup")
    source = observed(singletons["source"], "source")
    recovery = observed(singletons["recovery"], "recovery")
    runtime = observed(singletons["runtime"], "runtime")
    policy = singletons["effective-policy"]
    policy_observed = observed(policy, "effective-policy")
    isolation = singletons["isolation"]
    isolation_observed = observed(isolation, "isolation")

    for label, event in (("effective-policy", policy), ("isolation", isolation)):
        result = require_text(event, "result", label)
        if result not in {"PASS", "FAIL"}:
            raise ObservationError(f"{label} has unknown result {result!r}")
        if result != "PASS":
            raise ObservationError(f"{label} did not pass")
    if policy_observed.get("subject") != "source-reader":
        raise ObservationError("effective policy observation is not for the source reader")
    if not SHA256.fullmatch(require_text(policy_observed, "policySha256", "effective-policy.observed")):
        raise ObservationError("effective policy digest is not sha256")
    if isolation_observed.get("writeDenialObjectAbsent") is not True:
        raise ObservationError("isolation observation does not prove the sibling denial key absent")
    denial_raw = require_text(isolation_observed, "writeDenialRawResponse", "isolation.observed")
    inconclusive = (
        "NoSuchBucket", "NoSuchKey", "x509", "certificate", "TLS", "credential",
        "lookup", "dial", "connection refused", "timeout",
    )
    if any(marker.lower() in denial_raw.lower() for marker in inconclusive):
        raise ObservationError("write denial was inconclusive rather than an authenticated permission denial")
    if not any(marker.lower() in denial_raw.lower() for marker in (
        "AccessDenied", "Access Denied", "Insufficient permissions"
    )):
        raise ObservationError("write response was not an authenticated permission denial")

    endpoint = require_text(source, "endpoint", "source.observed")
    bucket = require_text(source, "bucket", "source.observed")
    path_prefix = require_text(source, "pathPrefix", "source.observed")
    server_name = require_text(source, "serverName", "source.observed")
    canonical = require_text(source, "canonicalServerDirectory", "source.observed")
    expected_canonical = f"s3://{bucket}/{path_prefix}"
    if (
        canonical != expected_canonical
        or not path_prefix.endswith(f"{server_name}/")
        or path_prefix.startswith("/")
        or ".." in path_prefix.split("/")
    ):
        raise ObservationError("resolved canonical server directory is inconsistent")
    if not endpoint.startswith("https://"):
        raise ObservationError("resolved source endpoint is not TLS")

    started_text = require_text(recovery, "startedAt", "recovery.observed")
    completed_text = require_text(recovery, "completedAt", "recovery.observed")
    started = parse_time(started_text, "recovery.startedAt")
    completed = parse_time(completed_text, "recovery.completedAt")
    duration = recovery.get("durationSeconds")
    if not isinstance(duration, int) or duration < 0 or int((completed - started).total_seconds()) != duration:
        raise ObservationError("durationSeconds does not match observed timestamps")
    timeline = require_text(recovery, "reachedTimeline", "recovery.observed")
    lsn = require_text(recovery, "reachedLsn", "recovery.observed")
    if not timeline.isdigit() or not LSN.fullmatch(lsn):
        raise ObservationError("reached recovery target is malformed")

    known = observed(by_name["selected-backup-object-readable"], "selected backup check")
    object_digest = require_text(known, "sha256", "selected backup check observed")
    if not SHA256.fullmatch(object_digest):
        raise ObservationError("selected backup object digest is not sha256")
    for label, value in (
        ("checkProfileDigest", computed_profile_digest),
        ("manifestDigest", require_text(recovery, "manifestDigest", "recovery.observed")),
        ("verifierVersion", require_text(runtime, "verifierVersion", "runtime.observed")),
    ):
        if not SHA256.fullmatch(value):
            raise ObservationError(f"{label} is not sha256")

    artifact_checks = []
    for name in expected_all:
        event = by_name[name]
        item = {"name": name, "result": event["result"], "observed": event["observed"]}
        artifact_checks.append(item)

    return {
        "apiVersion": "evidence.platform.openkubes.ai/v1alpha1",
        "kind": "RestoreVerified",
        "metadata": {
            "name": f"ok-145-{run_id}",
            "labels": {
                "platform.openkubes.ai/source-cluster": require_text(
                    source, "clusterName", "source.observed"
                )
            },
        },
        "spec": {
            "databaseRef": {
                "apiVersion": require_text(database, "apiVersion", "database.observed"),
                "kind": require_text(database, "kind", "database.observed"),
                "name": require_text(database, "name", "database.observed"),
                "uid": require_text(database, "uid", "database.observed"),
            },
            "backupId": require_text(backup, "backupId", "backup.observed"),
            "backupRef": {
                "apiVersion": require_text(backup, "apiVersion", "backup.observed"),
                "kind": require_text(backup, "kind", "backup.observed"),
                "namespace": require_text(backup, "namespace", "backup.observed"),
                "name": require_text(backup, "name", "backup.observed"),
                "uid": require_text(backup, "uid", "backup.observed"),
            },
            "sourceSystemIdentifier": require_text(source, "systemIdentifier", "source.observed"),
            "sourceClusterRef": {
                "apiVersion": require_text(source, "clusterApiVersion", "source.observed"),
                "kind": require_text(source, "clusterKind", "source.observed"),
                "namespace": require_text(source, "clusterNamespace", "source.observed"),
                "name": require_text(source, "clusterName", "source.observed"),
                "uid": require_text(source, "clusterUid", "source.observed"),
            },
            "source": {
                "endpoint": endpoint,
                "bucket": bucket,
                "pathPrefix": path_prefix,
                "serverName": server_name,
                "canonicalServerDirectory": canonical,
            },
            "recoveryTarget": {
                "requested": require_text(recovery, "requestedTarget", "recovery.observed"),
                "reached": {"timelineId": timeline, "lsn": lsn},
            },
            "timing": {
                "startedAt": started_text,
                "completedAt": completed_text,
                "duration": f"PT{duration}S",
            },
            "checks": artifact_checks,
            "checkProfileDigest": computed_profile_digest,
            "manifestDigest": recovery["manifestDigest"],
            "isolation": {
                "effectivePolicyResult": policy["result"],
                "effectivePolicyName": require_text(policy_observed, "policyName", "effective-policy.observed"),
                "effectivePolicyDigest": policy_observed["policySha256"],
                "writeDenialProbeResult": isolation["result"],
                "writeDenialRawResponse": denial_raw,
                "writeDenialObject": require_text(isolation_observed, "writeDenialObject", "isolation.observed"),
                "writeDenialObjectAbsent": True,
            },
            "verifierVersion": runtime["verifierVersion"],
            "cnpgVersion": require_text(runtime, "cnpgVersion", "runtime.observed"),
            "pluginIdentity": require_text(runtime, "pluginIdentity", "runtime.observed"),
            "pluginVersion": require_text(runtime, "pluginVersion", "runtime.observed"),
            "evidenceRef": evidence_ref,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--stream", required=True)
    parser.add_argument("--check-profile", required=True)
    parser.add_argument("--evidence-ref", required=True)
    args = parser.parse_args()

    output = Path(args.output)
    if output.exists():
        raise FileExistsError(f"refusing to overwrite evidence artifact {output}")
    stream = Path(args.stream)
    profile = Path(args.check_profile)
    singletons, checks = load_stream(stream)
    artifact = validate_and_build(singletons, checks, profile, args.evidence_ref)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(yaml.safe_dump(artifact, sort_keys=False), encoding="utf-8")


if __name__ == "__main__":
    main()
