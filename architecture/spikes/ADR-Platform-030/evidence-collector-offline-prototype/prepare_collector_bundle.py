#!/usr/bin/env python3
"""Prepare a verified OK-141 bundle from reviewed, already-redacted intake."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
from datetime import datetime, timezone
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


BUNDLE = _load("ok141_collector_bundle", SPIKE / "evidence-observer-protocol" / "evidence_bundle.py")
DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
RUN_RE = re.compile(r"[1-9][0-9]{0,19}\Z")
COMMIT_RE = re.compile(r"[0-9a-f]{40}\Z")
PATH_RE = re.compile(r"architecture/spikes/ADR-Platform-030/evidence/intake/[a-z0-9][a-z0-9-]{0,62}\Z")
CONTEXT_KEYS = {
    "protocolDigest", "fixtureDigest", "decisionInputDigest",
    "targetIdentities", "observedFrom", "observedUntil", "clockSource",
    "maximumClockSkewSeconds",
}


class CollectorError(ValueError):
    """A fail-closed collector intake error."""


def _digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def prepare(
    evidence_root: Path, context_path: Path, expected_context_digest: str,
    expected_protocol_digest: str, expected_fixture_digest: str,
    run_id: str, created_at: str, intake_commit: str, intake_path: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not RUN_RE.fullmatch(run_id):
        raise CollectorError("run ID must be a positive decimal GitHub run ID")
    if not COMMIT_RE.fullmatch(intake_commit):
        raise CollectorError("intake commit must be a lowercase full Git commit SHA")
    if not PATH_RE.fullmatch(intake_path):
        raise CollectorError("intake path is outside the reviewed evidence prefix")
    for value, claim in (
        (expected_context_digest, "context digest"),
        (expected_protocol_digest, "protocol digest"),
        (expected_fixture_digest, "fixture digest"),
    ):
        if not DIGEST_RE.fullmatch(value):
            raise CollectorError(f"{claim} must be SHA-256")
    if context_path.is_symlink():
        raise CollectorError("intake context symlink rejected")
    raw_context = context_path.read_bytes()
    if _digest(raw_context) != expected_context_digest:
        raise CollectorError("intake context raw digest mismatch")
    context = json.loads(raw_context)
    if not isinstance(context, dict) or set(context) != CONTEXT_KEYS:
        raise CollectorError("intake context membership mismatch")
    if context["protocolDigest"] != expected_protocol_digest:
        raise CollectorError("intake protocol digest mismatch")
    if context["fixtureDigest"] != expected_fixture_digest:
        raise CollectorError("intake fixture digest mismatch")
    created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    if created.tzinfo != timezone.utc:
        raise CollectorError("createdAt must be UTC")
    bound = dict(context)
    bound["runId"] = run_id
    bound["createdAt"] = created_at
    source_path = evidence_root / "collector-source.json"
    if source_path.exists() or source_path.is_symlink():
        raise CollectorError("collector-source.json is reserved")
    source = {
        "version": "ok141-collector-source/v1",
        "repository": "openkubes/openkubes",
        "intakeCommit": intake_commit,
        "intakePath": intake_path,
        "contextDigest": expected_context_digest,
    }
    source_path.write_bytes(_canonical(source))
    manifest = BUNDLE.build(evidence_root, bound)
    if BUNDLE.verify(evidence_root, manifest) != manifest["spec"]["bundleDigest"]:
        raise CollectorError("built evidence bundle did not re-verify")
    receipt = {
        "version": "ok141-collector-receipt/v1",
        "runId": run_id,
        "contextDigest": expected_context_digest,
        "intakeCommit": intake_commit,
        "intakePath": intake_path,
        "protocolDigest": expected_protocol_digest,
        "fixtureDigest": expected_fixture_digest,
        "bundleDigest": manifest["spec"]["bundleDigest"],
        "artifactName": "ok141-evidence-bundle",
        "publicationAuthorized": False,
    }
    return manifest, receipt


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode() + b"\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--context", type=Path, required=True)
    parser.add_argument("--context-digest", required=True)
    parser.add_argument("--protocol-digest", required=True)
    parser.add_argument("--fixture-digest", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--created-at", required=True)
    parser.add_argument("--intake-commit", required=True)
    parser.add_argument("--intake-path", required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    try:
        manifest, receipt = prepare(
            args.evidence_root, args.context, args.context_digest,
            args.protocol_digest, args.fixture_digest, args.run_id,
            args.created_at, args.intake_commit, args.intake_path,
        )
        args.manifest.write_bytes(_canonical(manifest))
        args.receipt.write_bytes(_canonical(receipt))
        print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
        return 0
    except (BUNDLE.EvidenceError, CollectorError, OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
