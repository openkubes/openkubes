#!/usr/bin/env python3
"""Bounded OK-141 installer prototype; current NO-GO protocols always refuse apply."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
import urllib.request
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import yaml


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
HARNESS = SPIKE / "harness"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


V4 = _load("ok141_phase_r_v4_bounded_installer", HARNESS / "ok141_phase_r_v4.py")
V1 = V4.V1

COMMANDS = {"materialize", "verify", "apply", "evidence"}
GATE_CONFIG = {
    "M0A-I": {
        "version": "ok141-m0a-i/v1",
        "grantField": "m0aInstallationGranted",
        "phase": "M0AI-G1",
        "fieldManager": "openkubes-ok141-m0ai",
    },
    "M0B-I": {
        "version": "ok141-m0b-i/v1",
        "grantField": "m0bInstallationGranted",
        "phase": "M0BI-G1",
        "fieldManager": "openkubes-ok141-m0bi",
    },
}


class InstallerError(ValueError):
    pass


@dataclass(frozen=True)
class ReviewedObjectSet:
    gate: str
    target_plane: str
    documents: list[dict[str, Any]]
    payload: bytes
    source_claims: list[dict[str, Any]]

    @property
    def semantic_digest(self) -> str:
        return V1.semantic_revision(self.documents)

    @property
    def raw_payload_digest(self) -> str:
        return V1.sha256_bytes(self.payload)

    @property
    def kind_inventory(self) -> dict[str, int]:
        return dict(sorted(Counter(item["kind"] for item in self.documents).items()))


def _resolve(protocol_path: Path, requested: str) -> Path:
    candidate = (protocol_path.parent / requested).resolve()
    if SPIKE.resolve() not in candidate.parents or not candidate.is_file():
        raise InstallerError(f"reference missing or outside spike root: {requested}")
    return candidate


def _documents(raw: bytes, source: str) -> list[dict[str, Any]]:
    try:
        return [item for item in yaml.load_all(raw.decode(), Loader=V1.UniqueKeyLoader) if item]
    except (UnicodeError, yaml.YAMLError) as exc:
        raise InstallerError(f"cannot parse reviewed source {source}: {exc}") from exc


def _expect(actual: Any, expected: Any, claim: str) -> None:
    if actual != expected:
        raise InstallerError(f"{claim} mismatch")


def _gate(protocol: dict[str, Any]) -> str:
    gate = protocol.get("spec", {}).get("authorityBoundary", {}).get("gate")
    if gate not in GATE_CONFIG:
        raise InstallerError("unsupported installation gate")
    _expect(protocol["spec"]["protocolVersion"], GATE_CONFIG[gate]["version"], "protocol version")
    return gate


def _materialized_file(directory: Path, item_id: str) -> Path:
    return directory / f"{item_id}.yaml"


def materialize_m0b(
    protocol: dict[str, Any],
    protocol_path: Path,
    output_dir: Path,
    fetch: Callable[[str], bytes] | None = None,
) -> dict[str, Any]:
    if _gate(protocol) != "M0B-I":
        raise InstallerError("materialize is only required by M0B-I")
    output_dir.mkdir(parents=True, exist_ok=True)
    source = protocol["spec"]["source"]
    lock_path = _resolve(protocol_path, source["lockPath"])
    _expect(V1.sha256_bytes(lock_path.read_bytes()), source["lockDigest"], "source lock digest")
    lock = V1.read_yaml_or_json(lock_path)["spec"]
    fetch_bytes = fetch or (lambda url: urllib.request.urlopen(url, timeout=30).read())
    evidence = []
    for item in lock["files"]:
        raw = fetch_bytes(item["url"])
        docs = _documents(raw, item["id"])
        actual = {
            "id": item["id"],
            "url": item["url"],
            "rawDigest": V1.sha256_bytes(raw),
            "semanticDigest": V1.semantic_revision(docs),
            "sizeBytes": len(raw),
            "objectCount": len(docs),
        }
        for field in ("rawDigest", "semanticDigest", "sizeBytes", "objectCount"):
            _expect(actual[field], item[field], f"{item['id']} {field}")
        _materialized_file(output_dir, item["id"]).write_bytes(raw)
        evidence.append(actual)
    return {
        "operation": "materialize",
        "gate": "M0B-I",
        "lockDigest": source["lockDigest"],
        "files": evidence,
        "mutationAuthorized": False,
        "clusterContacted": False,
    }


def _m0a_object_set(protocol: dict[str, Any], protocol_path: Path) -> ReviewedObjectSet:
    source = protocol["spec"]["source"]
    path = _resolve(protocol_path, source["manifestPath"])
    raw = path.read_bytes()
    docs = _documents(raw, str(path))
    _expect(V1.sha256_bytes(raw), source["rawDigest"], "M0a-I raw source")
    _expect(V1.semantic_revision(docs), source["semanticDigest"], "M0a-I semantic source")
    _expect(len(docs), source["objectCount"], "M0a-I object count")
    _expect(dict(sorted(Counter(item["kind"] for item in docs).items())), dict(sorted(source["objectKinds"].items())), "M0a-I kind inventory")
    return ReviewedObjectSet("M0A-I", protocol["spec"]["submission"]["targetPlane"], docs, raw, [{"path": source["manifestPath"], "rawDigest": source["rawDigest"]}])


def _m0b_object_set(protocol: dict[str, Any], protocol_path: Path, materialized_dir: Path | None) -> ReviewedObjectSet:
    if materialized_dir is None:
        raise InstallerError("M0B-I requires a materialized source directory")
    source = protocol["spec"]["source"]
    lock_path = _resolve(protocol_path, source["lockPath"])
    _expect(V1.sha256_bytes(lock_path.read_bytes()), source["lockDigest"], "M0b-I source lock")
    lock = V1.read_yaml_or_json(lock_path)["spec"]
    namespace_path = _resolve(protocol_path, source["namespacePath"])
    namespace_raw = namespace_path.read_bytes()
    _expect(V1.sha256_bytes(namespace_raw), source["namespaceRawDigest"], "M0b-I Namespace")
    chunks = [namespace_raw]
    documents = _documents(namespace_raw, "argocd Namespace")
    claims = [{"id": "namespace", "rawDigest": source["namespaceRawDigest"]}]
    for item in lock["files"]:
        path = _materialized_file(materialized_dir, item["id"])
        if not path.is_file():
            raise InstallerError(f"materialized source missing: {item['id']}")
        raw = path.read_bytes()
        docs = _documents(raw, item["id"])
        _expect(V1.sha256_bytes(raw), item["rawDigest"], f"{item['id']} raw digest")
        _expect(V1.semantic_revision(docs), item["semanticDigest"], f"{item['id']} semantic digest")
        _expect(len(raw), item["sizeBytes"], f"{item['id']} size")
        _expect(len(docs), item["objectCount"], f"{item['id']} object count")
        chunks.append(raw)
        documents.extend(docs)
        claims.append({"id": item["id"], "rawDigest": item["rawDigest"], "semanticDigest": item["semanticDigest"]})
    _expect(len(documents), source["combinedObjectCount"], "M0b-I combined object count")
    _expect(V1.semantic_revision(documents), source["combinedSemanticDigest"], "M0b-I combined semantic digest")
    _expect(dict(sorted(Counter(item["kind"] for item in documents).items())), dict(sorted(source["objectKinds"].items())), "M0b-I kind inventory")
    payload = b"\n---\n".join(chunk.rstrip() for chunk in chunks) + b"\n"
    return ReviewedObjectSet("M0B-I", protocol["spec"]["submission"]["targetPlane"], documents, payload, claims)


def verify_reviewed_object_set(
    protocol: dict[str, Any], protocol_path: Path, materialized_dir: Path | None = None
) -> ReviewedObjectSet:
    gate = _gate(protocol)
    reviewed = _m0a_object_set(protocol, protocol_path) if gate == "M0A-I" else _m0b_object_set(protocol, protocol_path, materialized_dir)
    submission = protocol["spec"]["submission"]
    _expect(reviewed.target_plane, protocol["spec"].get("target", protocol["spec"].get("placement"))["plane" if gate == "M0A-I" else "candidatePlane"], "target-plane authority")
    expected_semantic = submission.get("expectedSemanticDigest")
    _expect(reviewed.semantic_digest, expected_semantic, "submission semantic digest")
    expected_count = submission.get("expectedObjectCount", protocol["spec"]["source"].get("objectCount"))
    _expect(len(reviewed.documents), expected_count, "submission object count")
    return reviewed


def _authorization_plan(protocol: dict[str, Any], protocol_path: Path, reviewed: ReviewedObjectSet) -> dict[str, Any]:
    spec = protocol["spec"]
    gate = reviewed.gate
    config = GATE_CONFIG[gate]
    authorization = spec["authorization"]
    protocol_digest = V1.sha256_bytes(protocol_path.read_bytes())
    required = {
        "decision": "GO",
        "mutationAuthorized": True,
        config["grantField"]: True,
        "authorizedProtocolDigest": protocol_digest,
    }
    for field, expected in required.items():
        _expect(authorization.get(field), expected, f"authorization {field}")
    for field in ("grantID", "authority", "decidedAt"):
        if authorization.get(field) in (None, "UNASSIGNED", "UNRESOLVED", ""):
            raise InstallerError(f"authorization {field} is unresolved")
    if spec["submission"].get("enabled") is not True:
        raise InstallerError("submission is not enabled")
    requirements = spec["preInstallationRequirements"]
    if not requirements or any(item.get("status") != "CLOSED" for item in requirements):
        raise InstallerError("pre-installation requirements are not all CLOSED")
    phases = {item["id"]: item for item in spec["phases"]}
    if phases[config["phase"]].get("enabled") is not True:
        raise InstallerError("installation phase is not enabled")
    target = spec.get("target", spec.get("placement"))
    context = target.get("kubeContextIdentity")
    if context in (None, "UNRESOLVED", ""):
        raise InstallerError("target kube-context identity is unresolved")
    return {
        "operation": spec["submission"]["operation"],
        "gate": gate,
        "protocolDigest": protocol_digest,
        "grantID": authorization["grantID"],
        "targetPlane": reviewed.target_plane,
        "kubeContextIdentity": context,
        "objectCount": len(reviewed.documents),
        "kindInventory": reviewed.kind_inventory,
        "semanticDigest": reviewed.semantic_digest,
        "rawPayloadDigest": reviewed.raw_payload_digest,
        "fieldManager": config["fieldManager"],
        "command": ["kubectl", "--context", context, "apply", "--server-side", "--field-manager", config["fieldManager"], "--filename", "-"],
    }


def execute_apply(plan: dict[str, Any], payload: bytes, runner: Callable[..., Any] = subprocess.run) -> Any:
    command = plan.get("command")
    if not isinstance(command, list) or command[:1] != ["kubectl"] or "--filename" not in command or command[-1] != "-":
        raise InstallerError("apply plan does not contain the fixed kubectl stdin transport")
    return runner(command, input=payload, check=True, capture_output=True)


def evidence(reviewed: ReviewedObjectSet, protocol_path: Path) -> dict[str, Any]:
    return {
        "operation": "evidence",
        "gate": reviewed.gate,
        "protocolDigest": V1.sha256_bytes(protocol_path.read_bytes()),
        "targetPlane": reviewed.target_plane,
        "objectCount": len(reviewed.documents),
        "kindInventory": reviewed.kind_inventory,
        "semanticDigest": reviewed.semantic_digest,
        "rawPayloadDigest": reviewed.raw_payload_digest,
        "sourceClaims": reviewed.source_claims,
        "mutationAuthorized": False,
        "clusterContacted": False,
        "toolDigest": V1.sha256_bytes(Path(__file__).read_bytes()),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in sorted(COMMANDS):
        child = subparsers.add_parser(command)
        child.add_argument("--protocol", type=Path, required=True)
        if command in {"materialize", "verify", "apply", "evidence"}:
            child.add_argument("--materialized-dir", type=Path)
        if command == "materialize":
            child.add_argument("--output-dir", type=Path, required=True)
        if command == "apply":
            child.add_argument("--execute", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        protocol_path = args.protocol.resolve()
        protocol = V1.read_yaml_or_json(protocol_path)
        if args.command == "materialize":
            result = materialize_m0b(protocol, protocol_path, args.output_dir)
        else:
            reviewed = verify_reviewed_object_set(protocol, protocol_path, args.materialized_dir)
            if args.command in {"verify", "evidence"}:
                result = evidence(reviewed, protocol_path)
                result["operation"] = args.command
            else:
                result = _authorization_plan(protocol, protocol_path, reviewed)
                if args.execute:
                    completed = execute_apply(result, reviewed.payload)
                    result["transportExitCode"] = completed.returncode
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (InstallerError, OSError, ValueError, yaml.YAMLError, subprocess.SubprocessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
