#!/usr/bin/env python3
"""Deterministic OK-141 transport with durable source-run correlation."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
import re
import sys
import tarfile
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


V1 = _load("ok141_publisher_durable_v1", SPIKE / "ghcr-publisher-offline-prototype" / "publish_evidence.py")
BUNDLE = V1.BUNDLE
SHA_RE = re.compile(r"[0-9a-f]{40}\Z")
WORKFLOW_ID_RE = re.compile(r"[1-9][0-9]{0,19}\Z")


class CorrelationError(ValueError):
    """A fail-closed source-correlation or transport error."""


def _digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _expect(actual: Any, expected: Any, claim: str) -> None:
    if actual != expected:
        raise CorrelationError(f"source-run {claim} mismatch")


def build_correlation(
    source: dict[str, Any], manifest: dict[str, Any], source_run_id: str,
    source_workflow_id: str, source_head_sha: str, protocol_digest: str,
    internal_bundle_digest: str,
) -> dict[str, Any]:
    V1._run_id(source_run_id)
    if not WORKFLOW_ID_RE.fullmatch(source_workflow_id):
        raise CorrelationError("workflow ID must be a positive decimal GitHub workflow ID")
    if not SHA_RE.fullmatch(source_head_sha):
        raise CorrelationError("source head SHA must be lowercase hexadecimal")
    if not V1.DIGEST_RE.fullmatch(protocol_digest):
        raise CorrelationError("protocol digest must be SHA-256")
    _expect(source["repository"]["full_name"], "openkubes/openkubes", "repository")
    _expect(str(source["id"]), source_run_id, "run ID")
    _expect(str(source["workflow_id"]), source_workflow_id, "workflow ID")
    _expect(source["event"], "workflow_dispatch", "event")
    _expect(source["head_branch"], "main", "head branch")
    _expect(source["head_sha"], source_head_sha, "head SHA")
    _expect(source["status"], "completed", "status")
    _expect(source["conclusion"], "success", "conclusion")
    _expect(str(manifest["spec"]["runId"]), source_run_id, "evidence run ID")
    _expect(manifest["spec"]["bindings"]["protocolDigest"], protocol_digest, "evidence protocol digest")
    return {
        "version": "ok141-source-run-correlation/v1",
        "repository": "openkubes/openkubes",
        "runId": source_run_id,
        "workflowId": source_workflow_id,
        "event": "workflow_dispatch",
        "headBranch": "main",
        "headSHA": source_head_sha,
        "status": "completed",
        "conclusion": "success",
        "protocolDigest": protocol_digest,
        "internalBundleDigest": internal_bundle_digest,
    }


def build_transport(
    root: Path, manifest_path: Path, source_run_path: Path, source_run_id: str,
    source_workflow_id: str, source_head_sha: str, protocol_digest: str,
) -> tuple[bytes, dict[str, Any], dict[str, Any]]:
    manifest = BUNDLE.V1.read_yaml_or_json(manifest_path)
    internal_digest = BUNDLE.verify(root, manifest)
    source = json.loads(source_run_path.read_text())
    correlation = build_correlation(
        source, manifest, source_run_id, source_workflow_id, source_head_sha,
        protocol_digest, internal_digest,
    )
    correlation_raw = _canonical(correlation)
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as archive:
        V1._tar_entry(archive, "evidence-bundle.json", _canonical(manifest))
        V1._tar_entry(archive, "source-run-correlation.json", correlation_raw)
        for item in manifest["spec"]["artifacts"]:
            artifact = (root / item["path"]).resolve()
            if root.resolve() not in artifact.parents:
                raise CorrelationError("artifact path escapes evidence root")
            V1._tar_entry(archive, f"evidence/{item['path']}", artifact.read_bytes())
    transport = buffer.getvalue()
    plan = {
        "version": "ok141-publication-plan/v2",
        "sourceRunId": source_run_id,
        "sourceWorkflowId": source_workflow_id,
        "sourceHeadSHA": source_head_sha,
        "protocolDigest": protocol_digest,
        "sourceCorrelationDigest": _digest(correlation_raw),
        "repository": V1.REPOSITORY,
        "nonAuthoritativeTag": f"run-{source_run_id}",
        "artifactType": V1.ARTIFACT_TYPE,
        "layerMediaType": V1.LAYER_MEDIA_TYPE,
        "transportDigest": _digest(transport),
        "internalBundleDigest": internal_digest,
        "maximumTransportBytes": 60 * 1024 * 1024,
        "tagAuthoritative": False,
    }
    if len(transport) > plan["maximumTransportBytes"]:
        raise CorrelationError("transport exceeds the reviewed size limit")
    return transport, plan, correlation


PLAN_KEYS = {
    "version", "sourceRunId", "sourceWorkflowId", "sourceHeadSHA",
    "protocolDigest", "sourceCorrelationDigest", "repository",
    "nonAuthoritativeTag", "artifactType", "layerMediaType",
    "transportDigest", "internalBundleDigest", "maximumTransportBytes",
    "tagAuthoritative",
}
RECEIPT_KEYS = {
    "version", "sourceRunId", "sourceWorkflowId", "sourceHeadSHA",
    "protocolDigest", "sourceCorrelationDigest", "repository",
    "ociManifestDigest", "transportDigest", "internalBundleDigest",
    "attestationSubjectDigest", "attestationSignerIdentity",
    "workflowRunURL", "pullReference",
}


def _validate_plan(plan: dict[str, Any]) -> None:
    if not isinstance(plan, dict) or set(plan) != PLAN_KEYS:
        raise CorrelationError("publication plan membership mismatch")
    if plan["version"] != "ok141-publication-plan/v2":
        raise CorrelationError("publication plan version mismatch")
    for field in ("protocolDigest", "sourceCorrelationDigest", "transportDigest", "internalBundleDigest"):
        if not isinstance(plan[field], str) or not V1.DIGEST_RE.fullmatch(plan[field]):
            raise CorrelationError(f"publication plan {field} is not SHA-256")


def build_receipt(plan: dict[str, Any], oci_digest: str, attestation_digest: str, workflow_url: str) -> dict[str, Any]:
    _validate_plan(plan)
    if not V1.DIGEST_RE.fullmatch(oci_digest) or attestation_digest != oci_digest:
        raise CorrelationError("receipt subject must be the exact OCI manifest digest")
    if not workflow_url.startswith("https://github.com/openkubes/openkubes/actions/runs/"):
        raise CorrelationError("workflow run URL is outside the repository")
    return {
        "version": "ok141-publication-receipt/v2",
        "sourceRunId": plan["sourceRunId"],
        "sourceWorkflowId": plan["sourceWorkflowId"],
        "sourceHeadSHA": plan["sourceHeadSHA"],
        "protocolDigest": plan["protocolDigest"],
        "sourceCorrelationDigest": plan["sourceCorrelationDigest"],
        "repository": V1.REPOSITORY,
        "ociManifestDigest": oci_digest,
        "transportDigest": plan["transportDigest"],
        "internalBundleDigest": plan["internalBundleDigest"],
        "attestationSubjectDigest": attestation_digest,
        "attestationSignerIdentity": V1.SIGNER_IDENTITY,
        "workflowRunURL": workflow_url,
        "pullReference": f"{V1.REPOSITORY}@{oci_digest}",
    }


def validate_receipt(plan: dict[str, Any], receipt: dict[str, Any], pulled_transport: bytes) -> dict[str, Any]:
    _validate_plan(plan)
    if not isinstance(receipt, dict) or set(receipt) != RECEIPT_KEYS:
        raise CorrelationError("publication receipt membership mismatch")
    _expect(receipt["version"], "ok141-publication-receipt/v2", "receipt version")
    for field in ("sourceRunId", "sourceWorkflowId", "sourceHeadSHA", "protocolDigest", "sourceCorrelationDigest", "transportDigest", "internalBundleDigest"):
        _expect(receipt[field], plan[field], f"receipt {field}")
    _expect(receipt["repository"], V1.REPOSITORY, "receipt repository")
    for field in ("ociManifestDigest", "transportDigest", "internalBundleDigest", "attestationSubjectDigest"):
        if not isinstance(receipt[field], str) or not V1.DIGEST_RE.fullmatch(receipt[field]):
            raise CorrelationError(f"publication receipt {field} is not SHA-256")
    _expect(receipt["transportDigest"], _digest(pulled_transport), "pull-back transport digest")
    _expect(receipt["attestationSubjectDigest"], receipt["ociManifestDigest"], "attestation subject")
    _expect(receipt["pullReference"], f"{V1.REPOSITORY}@{receipt['ociManifestDigest']}", "pull reference")
    _expect(receipt["attestationSignerIdentity"], V1.SIGNER_IDENTITY, "signer identity")
    if not receipt["workflowRunURL"].startswith("https://github.com/openkubes/openkubes/actions/runs/"):
        raise CorrelationError("workflow run URL is outside the repository")
    return {
        "version": "ok141-publication-verification/v2",
        "status": "VERIFIED-PULL-BACK-WITH-SOURCE-CORRELATION",
        "sourceRunId": plan["sourceRunId"],
        "sourceCorrelationDigest": plan["sourceCorrelationDigest"],
        "ociManifestDigest": receipt["ociManifestDigest"],
        "transportDigest": receipt["transportDigest"],
        "internalBundleDigest": receipt["internalBundleDigest"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="operation", required=True)
    plan_parser = sub.add_parser("plan")
    plan_parser.add_argument("--root", type=Path, required=True)
    plan_parser.add_argument("--manifest", type=Path, required=True)
    plan_parser.add_argument("--source-run", type=Path, required=True)
    plan_parser.add_argument("--source-run-id", required=True)
    plan_parser.add_argument("--source-workflow-id", required=True)
    plan_parser.add_argument("--source-head-sha", required=True)
    plan_parser.add_argument("--protocol-digest", required=True)
    plan_parser.add_argument("--transport", type=Path, required=True)
    plan_parser.add_argument("--plan", type=Path, required=True)
    plan_parser.add_argument("--correlation", type=Path, required=True)
    receipt_parser = sub.add_parser("receipt")
    receipt_parser.add_argument("--plan", type=Path, required=True)
    receipt_parser.add_argument("--oci-manifest-digest", required=True)
    receipt_parser.add_argument("--attestation-subject-digest", required=True)
    receipt_parser.add_argument("--workflow-run-url", required=True)
    receipt_parser.add_argument("--receipt", type=Path, required=True)
    verify_parser = sub.add_parser("verify-receipt")
    verify_parser.add_argument("--plan", type=Path, required=True)
    verify_parser.add_argument("--receipt", type=Path, required=True)
    verify_parser.add_argument("--pulled-transport", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.operation == "plan":
            transport, plan, correlation = build_transport(
                args.root, args.manifest, args.source_run, args.source_run_id,
                args.source_workflow_id, args.source_head_sha, args.protocol_digest,
            )
            args.transport.write_bytes(transport)
            args.plan.write_bytes(_canonical(plan) + b"\n")
            args.correlation.write_bytes(_canonical(correlation) + b"\n")
            print(json.dumps(plan, sort_keys=True, separators=(",", ":")))
        elif args.operation == "receipt":
            plan = json.loads(args.plan.read_text())
            receipt = build_receipt(plan, args.oci_manifest_digest, args.attestation_subject_digest, args.workflow_run_url)
            args.receipt.write_bytes(_canonical(receipt) + b"\n")
            print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
        else:
            plan = json.loads(args.plan.read_text())
            receipt = json.loads(args.receipt.read_text())
            print(json.dumps(validate_receipt(plan, receipt, args.pulled_transport.read_bytes()), sort_keys=True, separators=(",", ":")))
        return 0
    except (BUNDLE.EvidenceError, V1.PublicationError, CorrelationError, OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
