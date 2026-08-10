#!/usr/bin/env python3
"""Deterministic, local-only builder and verifier for redacted OK-141 evidence."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
MAX_FILES = 256
MAX_ARTIFACT_BYTES = 10 * 1024 * 1024
MAX_BUNDLE_BYTES = 50 * 1024 * 1024
DECISION_INPUT_DIGEST = "sha256:4b618081517eb96ef1896b40a7f9f5556054ab2d029fbbf706e8630bb6b42c5c"
FORBIDDEN_PATH_FRAGMENTS = (
    "kubeconfig",
    "credentials",
    "private-key",
    "id_rsa",
    "id_ed25519",
)
FORBIDDEN_STRUCTURED_KEYS = {
    "client-certificate-data",
    "client-key-data",
    "password",
    "bearertoken",
    "accesstoken",
    "refreshtoken",
    "privatekey",
}
FORBIDDEN_CONTENT = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)authorization\s*:\s*bearer\s+\S+"),
    re.compile(r"(?i)\b(client-key-data|client-certificate-data)\s*[:=]"),
)
MEDIA_TYPES = {
    ".json": "application/json",
    ".yaml": "application/yaml",
    ".yml": "application/yaml",
    ".log": "text/plain",
    ".txt": "text/plain",
    ".md": "text/markdown",
}


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


INPUTS = _load(
    "ok141_evidence_authority_inputs",
    SPIKE / "authority-decision-preflight" / "verify_authority_inputs.py",
)
V1 = INPUTS.V1


class EvidenceError(ValueError):
    pass


def _digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _timestamp(value: str, claim: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise EvidenceError(f"{claim} must be RFC3339 UTC")
    try:
        return datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as exc:
        raise EvidenceError(f"{claim} is not a valid timestamp") from exc


def _walk(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        kind = str(value.get("kind", "")).lower()
        if kind == "secret":
            raise EvidenceError(f"Kubernetes Secret object rejected at {path}")
        for key, child in value.items():
            lowered = str(key).replace("_", "").replace("-", "").lower()
            normalized_forbidden = {
                item.replace("_", "").replace("-", "").lower()
                for item in FORBIDDEN_STRUCTURED_KEYS
            }
            if lowered in normalized_forbidden:
                raise EvidenceError(f"forbidden structured key at {path}.{key}")
            if str(key) in {"data", "stringData"} and kind == "secret":
                raise EvidenceError(f"Secret payload rejected at {path}.{key}")
            _walk(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _walk(child, f"{path}[{index}]")


def _scan(path: Path, raw: bytes) -> str:
    relative = path.as_posix().lower()
    if any(fragment in relative for fragment in FORBIDDEN_PATH_FRAGMENTS) or path.suffix.lower() in {".key", ".pem", ".p12", ".pfx"}:
        raise EvidenceError(f"forbidden evidence path: {path.as_posix()}")
    media_type = MEDIA_TYPES.get(path.suffix.lower())
    if media_type is None:
        raise EvidenceError(f"unsupported evidence media type: {path.as_posix()}")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise EvidenceError(f"non-UTF-8 evidence rejected: {path.as_posix()}") from exc
    for pattern in FORBIDDEN_CONTENT:
        if pattern.search(text):
            raise EvidenceError(f"forbidden credential content: {path.as_posix()}")
    if path.suffix.lower() in {".json", ".yaml", ".yml"}:
        try:
            documents = (
                [json.loads(text)]
                if path.suffix.lower() == ".json"
                else list(yaml.load_all(text, Loader=V1.UniqueKeyLoader))
            )
        except (ValueError, yaml.YAMLError) as exc:
            raise EvidenceError(f"invalid structured evidence: {path.as_posix()}") from exc
        for document in documents:
            if document is not None:
                _walk(document)
    return media_type


def _files(root: Path) -> list[dict[str, Any]]:
    root = root.resolve()
    if not root.is_dir():
        raise EvidenceError("evidence root is not a directory")
    paths = sorted(item for item in root.rglob("*") if item.is_file() or item.is_symlink())
    if not paths or len(paths) > MAX_FILES:
        raise EvidenceError("evidence file count is outside the allowed range")
    result = []
    total = 0
    for path in paths:
        if path.is_symlink():
            raise EvidenceError(f"evidence symlink rejected: {path.relative_to(root)}")
        resolved = path.resolve()
        if root not in resolved.parents:
            raise EvidenceError("evidence path escapes root")
        raw = resolved.read_bytes()
        if len(raw) > MAX_ARTIFACT_BYTES:
            raise EvidenceError(f"evidence artifact too large: {path.relative_to(root)}")
        total += len(raw)
        if total > MAX_BUNDLE_BYTES:
            raise EvidenceError("evidence bundle exceeds maximum size")
        relative = path.relative_to(root)
        result.append({
            "path": relative.as_posix(),
            "digest": _digest(raw),
            "size": len(raw),
            "mediaType": _scan(relative, raw),
        })
    return result


def _sha(value: Any, claim: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
        raise EvidenceError(f"{claim} must be a SHA-256 digest")
    return value


def build(root: Path, context: dict[str, Any]) -> dict[str, Any]:
    required = {"runId", "createdAt", "protocolDigest", "fixtureDigest", "decisionInputDigest", "targetIdentities", "observedFrom", "observedUntil", "clockSource", "maximumClockSkewSeconds"}
    if set(context) != required:
        raise EvidenceError("evidence context membership mismatch")
    if not context["runId"] or not context["targetIdentities"]:
        raise EvidenceError("run ID and target identities are required")
    for field in ("protocolDigest", "fixtureDigest", "decisionInputDigest"):
        _sha(context[field], field)
    if context["decisionInputDigest"] != DECISION_INPUT_DIGEST:
        raise EvidenceError("decision input digest is not the accepted input record")
    created = _timestamp(context["createdAt"], "createdAt")
    observed_from = _timestamp(context["observedFrom"], "observedFrom")
    observed_until = _timestamp(context["observedUntil"], "observedUntil")
    if observed_from > observed_until or created < observed_until:
        raise EvidenceError("evidence timestamp order is invalid")
    if context["maximumClockSkewSeconds"] != 5 or not context["clockSource"]:
        raise EvidenceError("evidence clock contract mismatch")
    spec = {
        "version": "ok141-evidence-bundle/v1",
        "runId": context["runId"],
        "createdAt": context["createdAt"],
        "bindings": {
            "protocolDigest": context["protocolDigest"],
            "fixtureDigest": context["fixtureDigest"],
            "decisionInputDigest": context["decisionInputDigest"],
            "targetIdentities": context["targetIdentities"],
        },
        "clock": {
            "observedFrom": context["observedFrom"],
            "observedUntil": context["observedUntil"],
            "source": context["clockSource"],
            "maximumSkewSeconds": 5,
        },
        "artifacts": _files(root),
        "authorization": {"mutationAuthorized": False, "publicationAuthorized": False},
    }
    spec["bundleDigest"] = _digest(_canonical(spec))
    return {"apiVersion": "evidence.openkubes.io/v1alpha1", "kind": "EvidenceBundle", "spec": spec}


def verify(root: Path, manifest: dict[str, Any]) -> str:
    schema = json.loads((HERE / "evidence-bundle-v1.schema.json").read_text())
    V1.normalize(manifest, schema)
    spec = manifest["spec"]
    if spec["bindings"]["decisionInputDigest"] != DECISION_INPUT_DIGEST:
        raise EvidenceError("evidence bundle decision input binding mismatch")
    if spec["authorization"] != {"mutationAuthorized": False, "publicationAuthorized": False}:
        raise EvidenceError("evidence bundle contains authorization")
    _timestamp(spec["createdAt"], "createdAt")
    observed_from = _timestamp(spec["clock"]["observedFrom"], "observedFrom")
    observed_until = _timestamp(spec["clock"]["observedUntil"], "observedUntil")
    if observed_from > observed_until or _timestamp(spec["createdAt"], "createdAt") < observed_until:
        raise EvidenceError("evidence timestamp order is invalid")
    expected_artifacts = _files(root)
    if spec["artifacts"] != expected_artifacts:
        raise EvidenceError("evidence artifact inventory mismatch")
    without_digest = dict(spec)
    claimed = without_digest.pop("bundleDigest")
    computed = _digest(_canonical(without_digest))
    if claimed != computed:
        raise EvidenceError("evidence bundle digest mismatch")
    return claimed


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="operation", required=True)
    build_parser = sub.add_parser("build")
    build_parser.add_argument("--root", type=Path, required=True)
    build_parser.add_argument("--context", type=Path, required=True)
    verify_parser = sub.add_parser("verify")
    verify_parser.add_argument("--root", type=Path, required=True)
    verify_parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.operation == "build":
            context = V1.read_yaml_or_json(args.context)
            print(json.dumps(build(args.root, context), indent=2, sort_keys=True))
        else:
            manifest = V1.read_yaml_or_json(args.manifest)
            print(verify(args.root, manifest))
        return 0
    except (EvidenceError, OSError, ValueError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
