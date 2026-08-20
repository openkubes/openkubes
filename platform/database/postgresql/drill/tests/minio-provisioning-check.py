#!/usr/bin/env python3
"""Validate the static OK-145 MinIO provisioning and its credential boundary."""

from __future__ import annotations

import argparse
import copy
import hashlib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "minio.yaml"
SCRIPT = ROOT / "provision-minio.sh"
READER_POLICY = ROOT / "minio-policy-backups-readonly.json"
DRILL_POLICY = ROOT / "minio-policy-drill-write.json"
PRODUCER_POLICY = ROOT / "minio-policy-backups-ok-robotics-writer.json"
MINIO_IMAGE = (
    "quay.io/minio/minio:RELEASE.2025-09-07T16-13-09Z@"
    "sha256:a1a8bd4ac40ad7881a245bab97323e18f971e4d4cba2c2007ec1bedd21cbaba2"
)


def validate(documents: list[dict], script: str, reader_bytes: bytes, drill_bytes: bytes) -> None:
    by_kind_name = {(doc["kind"], doc["metadata"]["name"]): doc for doc in documents}
    deployment = by_kind_name[("Deployment", "minio")]
    container = deployment["spec"]["template"]["spec"]["containers"][0]
    assert container["image"] == MINIO_IMAGE, "MinIO image must retain the reviewed tag and digest"
    assert "--certs-dir=/certs" in container["args"], "MinIO must load its TLS keypair"
    service = by_kind_name[("Service", "minio")]
    assert service["spec"]["ports"] == [
        {"name": "https-s3", "port": 9000, "targetPort": "https-s3"}
    ], "Service must expose only the TLS S3 port"
    ca = by_kind_name[("Certificate", "minio-backup-store-ca")]
    assert ca["spec"]["isCA"] is True and ca["spec"]["secretName"] == "minio-backup-store-ca"
    server = by_kind_name[("Certificate", "minio-server")]
    assert "minio.minio.svc" in server["spec"]["dnsNames"]
    pvc = by_kind_name[("PersistentVolumeClaim", "minio-data")]
    assert pvc["spec"]["storageClassName"] == "local-path"
    assert all(doc["kind"] != "Secret" for doc in documents), "credential values must not be declarative"
    assert all(
        doc["metadata"]["labels"]["platform.openkubes.ai/managed-by"] == "ok-145-minio-provisioner"
        for doc in documents
    ), "every persistent resource must carry the ownership label"

    assert hashlib.sha256(reader_bytes).hexdigest() == "3171361cdc3706c0641bd67dd6a3b180f102eaef4606b35948eebf6ea39b2246", (
        "reviewed reader policy changed"
    )
    assert hashlib.sha256(drill_bytes).hexdigest() == "411fe6f0da806326526dfcf2404d4dc5c7205fb1ca1e0a478a30166310911408", (
        "reviewed drill policy changed"
    )
    producer = yaml.safe_load(PRODUCER_POLICY.read_text())
    reader = yaml.safe_load(reader_bytes)
    reader_list = next(statement for statement in reader["Statement"] if "s3:ListBucket" in statement["Action"])
    assert set(reader_list) == {"Sid", "Effect", "Action", "Resource"}, (
        "Barman HeadBucket requires bucket-level ListBucket without an s3:prefix condition"
    )
    reader_object_actions = [
        statement for statement in reader["Statement"]
        if any(action in {"s3:GetObject", "s3:PutObject", "s3:DeleteObject"} for action in statement["Action"])
    ]
    assert len(reader_object_actions) == 1 and reader_object_actions[0]["Action"] == ["s3:GetObject"], (
        "reader object access must remain read-only"
    )
    resources = [r for statement in producer["Statement"] for r in ([statement["Resource"]] if isinstance(statement["Resource"], str) else statement["Resource"])]
    assert any(r == "arn:aws:s3:::ok-db-backups/ok-robotics/*" for r in resources)
    assert all("ok-db-drill" not in r for r in resources), "producer policy must not reach the drill bucket"

    assert "set -Eeuo pipefail" in script
    assert "--from-env-file=/dev/stdin" in script, "Kubernetes credentials must enter through stdin"
    assert "mc admin user add" not in script and "mc admin group add" not in script and "mc admin policy attach" not in script, (
        "mc must not receive access-key identities in argv"
    )
    assert "SetUserReq" in (ROOT / "minio-admin-helper/main.go").read_text()
    helper = (ROOT / "minio-admin-helper/main.go").read_text()
    assert "InfoCannedPolicyV2" in helper and "bytes.Equal(actual, expected)" in helper, (
        "effective policy verification must compare the server document with the reviewed JSON"
    )
    assert "io.ReadAll(os.Stdin)" in helper, (
        "reviewed policy content must reach the helper over stdin, not argv"
    )
    assert "ok-db-drill-${RUN_ID}-writer" not in script, "provisioner must not own per-run writers"


def expect_rejected(label: str, documents: list[dict], script: str, reader_bytes: bytes, drill_bytes: bytes, text: str) -> None:
    try:
        validate(documents, script, reader_bytes, drill_bytes)
    except AssertionError as exc:
        assert text in str(exc), f"{label}: unhelpful rejection: {exc}"
        print(f"NEGATIVE CONTROL PASS: {label}: {exc}")
        return
    raise AssertionError(f"negative control was accepted: {label}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--negative-controls", action="store_true")
    args = parser.parse_args()
    documents = list(yaml.safe_load_all(MANIFEST.read_text()))
    script = SCRIPT.read_text()
    reader_bytes = READER_POLICY.read_bytes()
    drill_bytes = DRILL_POLICY.read_bytes()
    if args.negative_controls:
        unpinned = copy.deepcopy(documents)
        unpinned[-1]["spec"]["template"]["spec"]["containers"][0]["image"] = "quay.io/minio/minio:latest"
        expect_rejected("unpinned MinIO", unpinned, script, reader_bytes, drill_bytes, "reviewed tag and digest")
        changed_reader = reader_bytes.replace(b'"s3:GetObject"', b'"s3:GetObject", "s3:PutObject"')
        expect_rejected("modified reviewed reader policy", documents, script, changed_reader, drill_bytes, "reader policy changed")
        unsafe_script = script + "\nmc admin user add ok145 access secret\n"
        expect_rejected("credential-bearing mc argv", documents, unsafe_script, reader_bytes, drill_bytes, "access-key identities in argv")
        return
    validate(documents, script, reader_bytes, drill_bytes)
    print("PASS: MinIO provisioning is TLS-only, pinned, owned, scoped, and credential-safe by construction")


if __name__ == "__main__":
    main()
