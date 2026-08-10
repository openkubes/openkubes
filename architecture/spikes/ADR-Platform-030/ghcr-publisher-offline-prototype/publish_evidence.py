#!/usr/bin/env python3
"""Deterministic offline planner and pull-back verifier for OK-141 evidence."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
import re
import sys
import tarfile
from pathlib import Path, PurePosixPath
from typing import Any


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
REPOSITORY = "ghcr.io/openkubes/ok141-evidence"
ARTIFACT_TYPE = "application/vnd.openkubes.ok141.evidence.v1"
LAYER_MEDIA_TYPE = "application/vnd.openkubes.ok141.evidence.bundle.v1+tar"
DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
RUN_ID_RE = re.compile(r"[1-9][0-9]{0,19}\Z")
SIGNER_IDENTITY = "https://github.com/openkubes/openkubes/.github/workflows/ok141-evidence-publisher.yaml@refs/heads/main"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


BUNDLE = _load(
    "ok141_publisher_evidence_bundle",
    SPIKE / "evidence-observer-protocol" / "evidence_bundle.py",
)


class PublicationError(ValueError):
    """A fail-closed publication planning or receipt error."""


def _digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _run_id(value: str) -> str:
    if not isinstance(value, str) or not RUN_ID_RE.fullmatch(value):
        raise PublicationError("source run ID must be a positive decimal GitHub run ID")
    return value


def _tar_entry(archive: tarfile.TarFile, name: str, raw: bytes) -> None:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        raise PublicationError("transport entry path is unsafe")
    info = tarfile.TarInfo(path.as_posix())
    info.size = len(raw)
    info.mode = 0o644
    info.mtime = 0
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    archive.addfile(info, io.BytesIO(raw))


def build_transport(root: Path, manifest_path: Path, source_run_id: str) -> tuple[bytes, dict[str, Any]]:
    source_run_id = _run_id(source_run_id)
    manifest = BUNDLE.V1.read_yaml_or_json(manifest_path)
    internal_digest = BUNDLE.verify(root, manifest)
    if str(manifest["spec"]["runId"]) != source_run_id:
        raise PublicationError("source run ID does not match evidence bundle")

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as archive:
        _tar_entry(archive, "evidence-bundle.json", _canonical(manifest))
        for item in manifest["spec"]["artifacts"]:
            path = (root / item["path"]).resolve()
            if root.resolve() not in path.parents:
                raise PublicationError("artifact path escapes evidence root")
            _tar_entry(archive, f"evidence/{item['path']}", path.read_bytes())
    transport = buffer.getvalue()
    plan = {
        "version": "ok141-publication-plan/v1",
        "sourceRunId": source_run_id,
        "repository": REPOSITORY,
        "nonAuthoritativeTag": f"run-{source_run_id}",
        "artifactType": ARTIFACT_TYPE,
        "layerMediaType": LAYER_MEDIA_TYPE,
        "transportDigest": _digest(transport),
        "internalBundleDigest": internal_digest,
        "maximumTransportBytes": 60 * 1024 * 1024,
        "tagAuthoritative": False,
    }
    if len(transport) > plan["maximumTransportBytes"]:
        raise PublicationError("transport exceeds the reviewed size limit")
    return transport, plan


def validate_receipt(plan: dict[str, Any], receipt: dict[str, Any], pulled_transport: bytes) -> dict[str, Any]:
    expected_plan_keys = {"version", "sourceRunId", "repository", "nonAuthoritativeTag", "artifactType", "layerMediaType", "transportDigest", "internalBundleDigest", "maximumTransportBytes", "tagAuthoritative"}
    if not isinstance(plan, dict) or set(plan) != expected_plan_keys:
        raise PublicationError("publication plan membership mismatch")
    expected_receipt_keys = {"version", "sourceRunId", "repository", "ociManifestDigest", "transportDigest", "internalBundleDigest", "attestationSubjectDigest", "attestationSignerIdentity", "workflowRunURL", "pullReference"}
    if not isinstance(receipt, dict) or set(receipt) != expected_receipt_keys:
        raise PublicationError("publication receipt membership mismatch")
    if receipt["version"] != "ok141-publication-receipt/v1" or receipt["sourceRunId"] != plan["sourceRunId"] or receipt["repository"] != REPOSITORY:
        raise PublicationError("publication receipt identity mismatch")
    for field in ("ociManifestDigest", "transportDigest", "internalBundleDigest", "attestationSubjectDigest"):
        if not isinstance(receipt[field], str) or not DIGEST_RE.fullmatch(receipt[field]):
            raise PublicationError(f"publication receipt {field} is not a SHA-256 digest")
    if receipt["transportDigest"] != plan["transportDigest"] or receipt["transportDigest"] != _digest(pulled_transport):
        raise PublicationError("pull-back transport digest mismatch")
    if receipt["internalBundleDigest"] != plan["internalBundleDigest"]:
        raise PublicationError("pull-back internal bundle digest mismatch")
    if receipt["attestationSubjectDigest"] != receipt["ociManifestDigest"]:
        raise PublicationError("attestation subject is not the OCI manifest digest")
    expected_pull = f"{REPOSITORY}@{receipt['ociManifestDigest']}"
    if receipt["pullReference"] != expected_pull:
        raise PublicationError("pull-back did not use the authoritative digest reference")
    if not receipt["attestationSignerIdentity"].startswith("https://github.com/openkubes/openkubes/"):
        raise PublicationError("attestation signer identity is outside the repository")
    if not receipt["workflowRunURL"].startswith("https://github.com/openkubes/openkubes/actions/runs/"):
        raise PublicationError("workflow run URL is outside the repository")
    return {
        "version": "ok141-publication-verification/v1",
        "status": "VERIFIED-PULL-BACK",
        "sourceRunId": plan["sourceRunId"],
        "ociManifestDigest": receipt["ociManifestDigest"],
        "transportDigest": receipt["transportDigest"],
        "internalBundleDigest": receipt["internalBundleDigest"],
        "attestationSubjectDigest": receipt["attestationSubjectDigest"],
    }


def build_receipt(
    plan: dict[str, Any],
    oci_manifest_digest: str,
    attestation_subject_digest: str,
    workflow_run_url: str,
) -> dict[str, Any]:
    if not DIGEST_RE.fullmatch(oci_manifest_digest) or attestation_subject_digest != oci_manifest_digest:
        raise PublicationError("receipt subject must be the exact OCI manifest digest")
    if not workflow_run_url.startswith("https://github.com/openkubes/openkubes/actions/runs/"):
        raise PublicationError("workflow run URL is outside the repository")
    return {
        "version": "ok141-publication-receipt/v1",
        "sourceRunId": plan["sourceRunId"],
        "repository": REPOSITORY,
        "ociManifestDigest": oci_manifest_digest,
        "transportDigest": plan["transportDigest"],
        "internalBundleDigest": plan["internalBundleDigest"],
        "attestationSubjectDigest": attestation_subject_digest,
        "attestationSignerIdentity": SIGNER_IDENTITY,
        "workflowRunURL": workflow_run_url,
        "pullReference": f"{REPOSITORY}@{oci_manifest_digest}",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="operation", required=True)
    plan_parser = sub.add_parser("plan")
    plan_parser.add_argument("--root", type=Path, required=True)
    plan_parser.add_argument("--manifest", type=Path, required=True)
    plan_parser.add_argument("--source-run-id", required=True)
    plan_parser.add_argument("--transport", type=Path, required=True)
    plan_parser.add_argument("--plan", type=Path, required=True)
    verify_parser = sub.add_parser("verify-receipt")
    verify_parser.add_argument("--plan", type=Path, required=True)
    verify_parser.add_argument("--receipt", type=Path, required=True)
    verify_parser.add_argument("--pulled-transport", type=Path, required=True)
    receipt_parser = sub.add_parser("receipt")
    receipt_parser.add_argument("--plan", type=Path, required=True)
    receipt_parser.add_argument("--oci-manifest-digest", required=True)
    receipt_parser.add_argument("--attestation-subject-digest", required=True)
    receipt_parser.add_argument("--workflow-run-url", required=True)
    receipt_parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.operation == "plan":
            transport, plan = build_transport(args.root, args.manifest, args.source_run_id)
            args.transport.write_bytes(transport)
            args.plan.write_bytes(_canonical(plan) + b"\n")
            print(json.dumps(plan, sort_keys=True, separators=(",", ":")))
        elif args.operation == "verify-receipt":
            plan = json.loads(args.plan.read_text())
            receipt = json.loads(args.receipt.read_text())
            print(json.dumps(validate_receipt(plan, receipt, args.pulled_transport.read_bytes()), sort_keys=True, separators=(",", ":")))
        else:
            plan = json.loads(args.plan.read_text())
            receipt = build_receipt(plan, args.oci_manifest_digest, args.attestation_subject_digest, args.workflow_run_url)
            args.receipt.write_bytes(_canonical(receipt) + b"\n")
            print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
        return 0
    except (BUNDLE.EvidenceError, PublicationError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
