#!/usr/bin/env python3
"""Exercise the JSONL evidence writer and validate generated RestoreVerified artifacts."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
WRITER = ROOT / "write-restore-evidence.py"
PROFILE = ROOT / "check-profile.sql"
EVIDENCE_REF = "platform/database/postgresql/drill/evidence/restoreverified-test-run.yaml"
PROFILE_NAMES = [
    "outside-recovery",
    "known-row-readable",
    "restore-probe-heap-readable",
    "primary-key-index-readable",
]


class EvidenceError(ValueError):
    pass


def fixture() -> list[dict]:
    digest = "sha256:" + hashlib.sha256(PROFILE.read_bytes()).hexdigest()
    return [
        {"event": "profile", "observed": {"digest": digest, "expectedChecks": 4}},
        {"event": "database", "observed": {
            "apiVersion": "platform.openkubes.ai/v1alpha1", "kind": "Database",
            "name": "fixture-database", "uid": "database-uid-observed",
        }},
        {"event": "backup", "observed": {
            "backupId": "20260817T104456", "apiVersion": "postgresql.cnpg.io/v1",
            "kind": "Backup", "namespace": "fixture-namespace", "name": "observed-backup",
            "uid": "backup-uid-observed", "stoppedAt": "2026-08-17T10:45:56Z",
        }},
        {"event": "source", "observed": {
            "systemIdentifier": "7674943119728799765", "clusterApiVersion": "postgresql.cnpg.io/v1",
            "clusterKind": "Cluster", "clusterNamespace": "fixture-namespace",
            "clusterName": "fixture-source", "clusterUid": "source-uid-observed",
            "endpoint": "https://resolved.example:9000", "bucket": "resolved-backups",
            "pathPrefix": "base-prefix/fixture-server/", "serverName": "fixture-server",
            "canonicalServerDirectory": "s3://resolved-backups/base-prefix/fixture-server/",
        }},
        {"event": "recovery", "observed": {
            "requestedTarget": "backupID=20260817T104456", "reachedTimeline": "2",
            "reachedLsn": "0/80001D0", "startedAt": "2026-08-17T11:48:25Z",
            "completedAt": "2026-08-17T11:49:40Z", "durationSeconds": 75,
            "manifestDigest": "sha256:" + "a" * 64,
        }},
        {"event": "runtime", "observed": {
            "verifierVersion": "sha256:" + "b" * 64, "cnpgVersion": "discovered-cnpg-version",
            "pluginIdentity": "discovered.plugin.identity", "pluginVersion": "discovered-plugin-version",
        }},
        {"event": "psql", "observed": {
            "result": "PASS", "exitCode": 0, "jsonRecords": 4, "stderrBytes": 0,
        }},
        {"event": "effective-policy", "result": "PASS", "observed": {
            "subject": "source-reader", "policyName": "resolved-reader-policy",
            "policySha256": "sha256:" + "c" * 64,
        }},
        {"event": "isolation", "result": "PASS", "observed": {
            "writeDenialRawResponse": "Insufficient permissions to access this path",
            "writeDenialObject": "base-prefix/fixture-server/base/backup/sibling-denial-key",
            "writeDenialObjectAbsent": True,
        }},
        {"event": "run", "observed": {"runId": "test-run", "evidenceRef": EVIDENCE_REF}},
        {"event": "check", "name": "outside-recovery", "result": "PASS",
         "observed": {"pgIsInRecovery": False}},
        {"event": "check", "name": "known-row-readable", "result": "PASS",
         "observed": {"matchingRows": 1, "marker": "ok-145-real-backup"}},
        {"event": "check", "name": "restore-probe-heap-readable", "result": "PASS",
         "observed": {"rowCount": 1, "minimumId": 145, "maximumId": 145}},
        {"event": "check", "name": "primary-key-index-readable", "result": "PASS",
         "observed": {"matchingRows": 1, "indexName": "restore_probe_pkey",
                      "indexValid": True, "indexReady": True}},
        {"event": "check", "name": "selected-backup-object-readable", "result": "PASS",
         "observed": {"object": "base-prefix/fixture-server/base/backup/backup.info",
                      "sha256": "sha256:" + "d" * 64}},
    ]


def write_stream(path: Path, events: list[dict]) -> None:
    path.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")


def invoke(events: list[dict], work: Path) -> subprocess.CompletedProcess[str]:
    stream = work / "observations.jsonl"
    output = work / "artifact.yaml"
    write_stream(stream, events)
    return subprocess.run(
        ["python3", str(WRITER), "--output", str(output), "--stream", str(stream),
         "--check-profile", str(PROFILE), "--evidence-ref", EVIDENCE_REF],
        text=True, capture_output=True,
    )


def need(mapping: dict, path: str):
    value = mapping
    for component in path.split("."):
        if not isinstance(value, dict) or component not in value:
            raise EvidenceError(f"missing required field spec.{path}")
        value = value[component]
    if value in (None, "", []):
        raise EvidenceError(f"required field spec.{path} is empty")
    return value


def validate(document: dict) -> None:
    if document.get("kind") != "RestoreVerified":
        raise EvidenceError("kind must be RestoreVerified")
    spec = document.get("spec", {})
    for field in (
        "databaseRef.apiVersion", "databaseRef.kind", "databaseRef.name", "databaseRef.uid",
        "backupId", "backupRef.uid", "sourceSystemIdentifier", "sourceClusterRef.uid",
        "source.endpoint", "source.bucket", "source.pathPrefix", "source.serverName",
        "source.canonicalServerDirectory", "recoveryTarget.requested",
        "recoveryTarget.reached.timelineId", "recoveryTarget.reached.lsn",
        "timing.startedAt", "timing.completedAt", "timing.duration", "checks",
        "checkProfileDigest", "manifestDigest", "isolation.effectivePolicyResult",
        "isolation.effectivePolicyDigest", "isolation.writeDenialProbeResult",
        "verifierVersion", "cnpgVersion", "pluginIdentity", "pluginVersion", "evidenceRef",
    ):
        need(spec, field)
    if document["metadata"]["labels"]["platform.openkubes.ai/source-cluster"] != spec["sourceClusterRef"]["name"]:
        raise EvidenceError("source-cluster selector label must equal the resolved source Cluster name")
    checks = spec["checks"]
    if [check["name"] for check in checks] != PROFILE_NAMES + ["selected-backup-object-readable"]:
        raise EvidenceError("generated check set/order does not match the profile plus object observation")
    if any(check.get("result") != "PASS" or not check.get("observed") for check in checks):
        raise EvidenceError("every generated check must PASS and carry typed observed values")


def positive_control() -> None:
    with tempfile.TemporaryDirectory(prefix="restore-evidence-check-") as directory:
        work = Path(directory)
        result = invoke(fixture(), work)
        if result.returncode != 0:
            raise EvidenceError(f"valid writer fixture failed: {result.stderr}")
        document = yaml.safe_load((work / "artifact.yaml").read_text(encoding="utf-8"))
        validate(document)
        print("PASS: JSONL writer derived a complete RestoreVerified artifact from observed values")


def expect_rejected(label: str, events: list[dict], expected: str) -> None:
    with tempfile.TemporaryDirectory(prefix="restore-evidence-reject-") as directory:
        work = Path(directory)
        result = invoke(events, work)
        if result.returncode == 0:
            raise EvidenceError(f"negative control unexpectedly accepted: {label}")
        if expected not in result.stderr:
            raise EvidenceError(f"{label} rejected for the wrong reason: {result.stderr}")
        if (work / "artifact.yaml").exists():
            raise EvidenceError(f"{label} wrote an artifact before rejection")
        print(f"NEGATIVE CONTROL PASS: {label}: {expected}")


def negative_controls() -> None:
    base = fixture()
    expect_rejected("partial stream", [event for event in base if event["event"] != "isolation"], "stream is partial")

    failed = copy.deepcopy(base)
    next(event for event in failed if event.get("name") == "known-row-readable")["result"] = "FAIL"
    expect_rejected("failed check", failed, "did not pass")

    duplicate = copy.deepcopy(base)
    duplicate.append(copy.deepcopy(next(event for event in duplicate if event["event"] == "source")))
    expect_rejected("duplicate singleton", duplicate, "duplicate singleton event")

    duplicate_check = copy.deepcopy(base)
    duplicate_check.append(copy.deepcopy(next(event for event in duplicate_check if event.get("name") == "outside-recovery")))
    expect_rejected("duplicate check", duplicate_check, "duplicate check observation")

    unknown = copy.deepcopy(base)
    unknown.append({"event": "invented", "observed": {"value": "present"}})
    expect_rejected("unknown event", unknown, "unknown event")

    missing = copy.deepcopy(base)
    next(event for event in missing if event["event"] == "source")["observed"]["endpoint"] = ""
    expect_rejected("missing observed value", missing, "is missing")

    psql_failed = copy.deepcopy(base)
    process = next(event for event in psql_failed if event["event"] == "psql")
    process["observed"].update(result="FAIL", exitCode=2, stderrBytes=41)
    expect_rejected("psql failure", psql_failed, "psql execution did not succeed")

    digest_mismatch = copy.deepcopy(base)
    next(event for event in digest_mismatch if event["event"] == "profile")["observed"]["digest"] = "sha256:" + "0" * 64
    expect_rejected("profile digest mismatch", digest_mismatch, "digest does not match")

    unknown_check = copy.deepcopy(base)
    next(event for event in unknown_check if event.get("name") == "outside-recovery")["name"] = "invented-check"
    expect_rejected("unknown check", unknown_check, "check stream is partial or unknown")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact", nargs="?")
    parser.add_argument("--negative-controls", action="store_true")
    args = parser.parse_args()
    if args.artifact:
        validate(yaml.safe_load(Path(args.artifact).read_text(encoding="utf-8")))
        print("PASS: RestoreVerified carries the complete observed ADR-Platform-032 section 11.2 field set")
    elif args.negative_controls:
        negative_controls()
    else:
        positive_control()


if __name__ == "__main__":
    main()
