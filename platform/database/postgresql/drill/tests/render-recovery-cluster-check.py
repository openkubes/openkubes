#!/usr/bin/env python3
"""Render the drill template and assert exact identity derivation and no secrets."""

from __future__ import annotations

import argparse
import copy
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
RUNNER = ROOT / "run-restore-drill.sh"
SOURCE = "ok-robotics"
RUN_ID = "20260817t120000z"
BACKUP_ID = "20260817T115500"


def render() -> tuple[str, list[dict]]:
    command = [
        str(RUNNER), "--render-only",
        "--source-cluster", SOURCE,
        "--run-id", RUN_ID,
        "--namespace", "database-ok-robotics",
        "--minio-endpoint", "https://minio.minio.svc:9000",
        "--minio-ca-secret", "minio-backup-store-ca",
        "--source-credentials-secret", "ok-db-backups-ok-robotics-reader",
        "--drill-credentials-secret", f"ok-db-drill-{RUN_ID}-writer",
        "--backup-id", BACKUP_ID,
        "--database-api-version", "platform.openkubes.ai/v1alpha1",
        "--database-kind", "Database",
        "--database-name", "ok-robotics",
        "--database-uid", "00000000-0000-0000-0000-000000000145",
        "--postgres-image", "ghcr.io/cloudnative-pg/postgresql:18@sha256:" + "a" * 64,
        "--storage-class", "local-path",
    ]
    result = subprocess.run(["bash", *command], check=True, text=True, capture_output=True)
    return result.stdout, list(yaml.safe_load_all(result.stdout))


def validate(text: str, documents: list[dict]) -> None:
    assert len(documents) == 3, f"expected 3 documents, got {len(documents)}"
    source_store, destination_store, cluster = documents
    assert [doc["kind"] for doc in documents] == ["ObjectStore", "ObjectStore", "Cluster"]
    recovery = cluster["spec"]["bootstrap"]["recovery"]["source"]
    assert cluster["spec"]["bootstrap"]["recovery"]["recoveryTarget"]["backupID"] == BACKUP_ID
    external = cluster["spec"]["externalClusters"]
    assert len(external) == 1
    external_name = external[0]["name"]
    server_name = external[0]["plugin"]["parameters"]["serverName"]
    assert recovery == external_name == server_name == SOURCE, (
        "source derivation mismatch: bootstrap source, external name, plugin serverName, "
        f"and folder must all equal {SOURCE!r}; got {(recovery, external_name, server_name)!r}"
    )
    assert source_store["spec"]["configuration"]["destinationPath"] == "s3://ok-db-backups"
    assert destination_store["spec"]["configuration"]["destinationPath"] == f"s3://ok-db-drill/{RUN_ID}"
    source_secret = source_store["spec"]["configuration"]["s3Credentials"]["accessKeyId"]["name"]
    destination_secret = destination_store["spec"]["configuration"]["s3Credentials"]["accessKeyId"]["name"]
    assert source_secret == "ok-db-backups-ok-robotics-reader"
    assert destination_secret == f"ok-db-drill-{RUN_ID}-writer"
    assert source_secret != destination_secret, "source and destination credentials must be distinct"
    for store, expected_secret in ((source_store, source_secret), (destination_store, destination_secret)):
        credentials = store["spec"]["configuration"]["s3Credentials"]
        assert credentials == {
            "accessKeyId": {"name": expected_secret, "key": "ACCESS_KEY_ID"},
            "secretAccessKey": {"name": expected_secret, "key": "ACCESS_SECRET_KEY"},
        }, "S3 credentials must contain only exact Kubernetes SecretKeySelector references"
    assert all(doc["kind"] != "Secret" for doc in documents), "render must never contain a Secret object"
    assert "${" not in text, "render contains unresolved template input"
    lowered = text.lower()
    for forbidden in ("secretaccesskey:", "accesskeyid:"):
        # Key selector field names are expected; values must only be Secret refs.
        assert lowered.count(forbidden) == 2
    assert "example-secret-value" not in lowered


def validate_runner(runner: str) -> None:
    assert '[[ "$LAST_SUCCESSFUL" == "$BACKUP_STOPPED"' not in runner, (
        "drill must use recovery-window containment, not latest-backup equality"
    )
    for comparison in ("first > last", "first > stopped", "stopped > last"):
        assert comparison in runner, f"drill containment is missing {comparison!r}"
    assert 'DENIAL_OBJECT="${RESOLVED_PATH_PREFIX}ok145-write-denial-${RUN_ID}"' in runner, (
        "denial key must be a sibling directly under the canonical server directory"
    )
    assert 'DENIAL_OBJECT="${KNOWN_OBJECT%/*}' not in runner, (
        "denial key must not be derived inside a real base-backup directory"
    )


def negative_controls(documents: list[dict]) -> None:
    mismatch = copy.deepcopy(documents)
    mismatch[2]["spec"]["externalClusters"][0]["plugin"]["parameters"]["serverName"] = "other-db"
    try:
        validate(yaml.safe_dump_all(mismatch), mismatch)
    except AssertionError as exc:
        assert "source derivation mismatch" in str(exc)
        print(f"NEGATIVE CONTROL PASS: mismatched server folder: {exc}")
    else:
        raise AssertionError("negative control accepted mismatched recovery source folder")
    inline_secret = copy.deepcopy(documents)
    inline_secret[0]["spec"]["configuration"]["s3Credentials"]["secretAccessKey"] = "example-secret-value"
    try:
        validate(yaml.safe_dump_all(inline_secret), inline_secret)
    except AssertionError as exc:
        assert "SecretKeySelector" in str(exc)
        print(f"NEGATIVE CONTROL PASS: inline credential value: {exc}")
    else:
        raise AssertionError("negative control accepted an inline credential value")

    runner = RUNNER.read_text(encoding="utf-8")
    reverted = runner.replace(
        'DENIAL_OBJECT="${RESOLVED_PATH_PREFIX}ok145-write-denial-${RUN_ID}"',
        'DENIAL_OBJECT="${KNOWN_OBJECT%/*}/ok145-write-denial-${RUN_ID}"',
    )
    try:
        validate_runner(reverted)
    except AssertionError as exc:
        assert "canonical server directory" in str(exc)
        print(f"NEGATIVE CONTROL PASS: denial key inside backup directory: {exc}")
    else:
        raise AssertionError("negative control accepted denial key inside a real backup directory")

    reverted = runner + '\n[[ "$LAST_SUCCESSFUL" == "$BACKUP_STOPPED" ]]\n'
    try:
        validate_runner(reverted)
    except AssertionError as exc:
        assert "latest-backup equality" in str(exc)
        print(f"NEGATIVE CONTROL PASS: latest-backup equality restored: {exc}")
    else:
        raise AssertionError("negative control accepted latest-backup equality")

    common = [
        "bash", str(RUNNER), "--source-cluster", SOURCE, "--run-id", RUN_ID,
        "--namespace", "database-ok-robotics", "--minio-endpoint", "https://minio.minio.svc:9000",
        "--minio-ca-secret", "minio-backup-store-ca",
        "--source-credentials-secret", "ok-db-backups-ok-robotics-reader",
        "--drill-credentials-secret", f"ok-db-drill-{RUN_ID}-writer",
        "--backup-id", BACKUP_ID,
        "--database-api-version", "platform.openkubes.ai/v1alpha1",
        "--database-kind", "Database",
        "--database-name", "ok-robotics",
        "--database-uid", "00000000-0000-0000-0000-000000000145",
        "--postgres-image", "ghcr.io/cloudnative-pg/postgresql:18@sha256:" + "a" * 64,
        "--storage-class", "local-path",
    ]

    attacker = common.copy()
    attacker[attacker.index(SOURCE)] = "keycloak-db"
    attacker_result = subprocess.run(attacker, text=True, capture_output=True)
    assert attacker_result.returncode != 0 and "authorized only for source cluster" in attacker_result.stderr
    print("NEGATIVE CONTROL PASS: unauthorized source cluster/endpoint tuple rejected")

    shared = common.copy()
    shared[shared.index(f"ok-db-drill-{RUN_ID}-writer")] = "ok-db-backups-ok-robotics-reader"
    shared_result = subprocess.run(shared, text=True, capture_output=True)
    assert shared_result.returncode != 0 and "credential Secrets must be distinct" in shared_result.stderr
    print("NEGATIVE CONTROL PASS: shared source/destination credentials rejected")

    no_approval_result = subprocess.run([*common, "--execute"], text=True, capture_output=True)
    assert no_approval_result.returncode != 0 and "requires --approve-isolated-restore" in no_approval_result.stderr
    print("NEGATIVE CONTROL PASS: execution without explicit approval rejected")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--negative-controls", action="store_true")
    args = parser.parse_args()
    text, documents = render()
    if args.negative_controls:
        negative_controls(documents)
        return
    validate(text, documents)
    validate_runner(RUNNER.read_text(encoding="utf-8"))
    print("PASS: rendered recovery identity is exact; containment and sibling denial-key guards are present")


if __name__ == "__main__":
    main()
