#!/usr/bin/env python3
"""Fail-closed offline verifier for the OK-141 artifact provenance locks."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parent
SPIKE = ROOT.parent
ENABLEMENT_LOCK = ROOT / "enablement-artifact-lock.json"
PLATFORM_LOCK = ROOT / "platform-artifact-lock-candidate.json"
CHECKPOINT = ROOT / "artifact-provenance-checkpoint.json"
CHECKPOINT_DIGEST = ROOT / "artifact-provenance-checkpoint.sha256"
FIXTURE = SPIKE / "harness/fixtures/execution/phase-r-v3.json"
APPLICATIONS = SPIKE / "harness/profiles/platform/minimal-observability-v3/applications.yaml"
SOURCE_COMMIT = "fe394da8875adecc3b497137e546cecabd710d1d"
EXPECTED_PLATFORM_RENDER = "sha256:2adb637ca1b4bfd528abc660c102019057cdad5389b989ea1a2d7a5e9c5b7ecf"
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
TOP_LEVEL_KEYS = {"format", "subject", "roots", "integrity", "consumer", "closure", "authorization"}
ROOT_KEYS = {"id", "transport", "coordinate", "resolvedIdentity", "contentDigest", "inImmutableRoot"}


class VerificationError(ValueError):
    pass


def sha256_bytes(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def validate_lock(lock: dict[str, Any]) -> None:
    if set(lock) != TOP_LEVEL_KEYS:
        raise VerificationError("Artifact Lock has missing or unknown top-level fields")
    if lock["format"] != "openkubes-artifact-lock/v1":
        raise VerificationError("unsupported Artifact Lock format")
    subject = lock["subject"]
    if subject.get("kind") not in {"Enablement", "Platform"}:
        raise VerificationError("invalid subject kind")
    for key in ("semanticRevision", "executionFixture"):
        if not DIGEST_RE.fullmatch(subject.get(key, "")):
            raise VerificationError(f"invalid subject {key}")
    if not lock["roots"]:
        raise VerificationError("Artifact Lock requires at least one root")
    for root in lock["roots"]:
        if set(root) != ROOT_KEYS:
            raise VerificationError("artifact root has missing or unknown fields")
        if root["transport"] not in {"oci", "git-vendored-helm"}:
            raise VerificationError("unsupported artifact transport")
        if not DIGEST_RE.fullmatch(root["contentDigest"]):
            raise VerificationError("invalid artifact content digest")
    if lock["authorization"] != {"decision": "NO-GO", "executionGranted": False}:
        raise VerificationError("Artifact Lock must remain NO-GO")


def authorization_ready(lock: dict[str, Any]) -> bool:
    return all(
        (
            lock["integrity"]["content"] == "PROVEN",
            lock["integrity"]["authenticity"] == "PROVEN",
            lock["closure"]["contentGraph"] == "CLOSED",
            lock["closure"]["authoritative"] is True,
            lock["consumer"]["digestEnforced"] is True,
            all(root["inImmutableRoot"] for root in lock["roots"]),
        )
    )


def verify_fixture_correlation(enablement: dict[str, Any], platform: dict[str, Any]) -> None:
    fixture = load(FIXTURE)
    if enablement["subject"]["semanticRevision"] != fixture["enablement"]["E"]:
        raise VerificationError("Enablement lock is not bound to current E")
    if platform["subject"]["semanticRevision"] != fixture["platform"]["P"]:
        raise VerificationError("Platform lock is not bound to current P")
    for lock in (enablement, platform):
        if lock["subject"]["executionFixture"] != fixture["fixtureDigest"]:
            raise VerificationError("Artifact Lock is not bound to current FixtureDigest")


def verify_checkpoint() -> None:
    checkpoint = load(CHECKPOINT)
    if checkpoint.get("format") != "ok141-artifact-provenance-checkpoint/v1":
        raise VerificationError("unsupported checkpoint format")
    authorization = checkpoint.get("authorization", {})
    if set(authorization.values()) != {"NO-GO", "NOT-GRANTED"}:
        raise VerificationError("checkpoint must remain fail-closed")
    for item in checkpoint.get("files", []):
        path = ROOT / item["path"]
        if not path.is_file() or sha256_bytes(path.read_bytes()) != item["sha256"]:
            raise VerificationError(f"checkpoint file digest mismatch: {item['path']}")
    expected = CHECKPOINT_DIGEST.read_text().strip() if CHECKPOINT_DIGEST.exists() else ""
    actual = sha256_bytes(CHECKPOINT.read_bytes())
    if expected != actual:
        raise VerificationError(f"checkpoint digest mismatch: expected {expected!r}, got {actual!r}")


def verify_enablement_local(lock: dict[str, Any], ok_cluster: Path) -> None:
    root = lock["roots"][0]
    artifact = ok_cluster / ".tools/cilium-1.19.6.tgz"
    if not artifact.is_file():
        raise VerificationError(f"missing local Cilium evidence artifact: {artifact}")
    if sha256_bytes(artifact.read_bytes()) != root["contentDigest"]:
        raise VerificationError("local Cilium chart content differs from Artifact Lock")


def prove_platform_vendor_candidate(lock: dict[str, Any], source_repo: Path) -> str:
    subprocess.run(
        ["git", "-C", str(source_repo), "cat-file", "-e", f"{SOURCE_COMMIT}^{{commit}}"],
        check=True,
    )
    archive = subprocess.run(
        ["git", "-C", str(source_repo), "archive", SOURCE_COMMIT],
        check=True,
        capture_output=True,
    ).stdout
    with tempfile.TemporaryDirectory(prefix="ok141-artifact-proof-") as directory:
        extracted = Path(directory)
        with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
            bundle.extractall(extracted, filter="data")
        target_charts = extracted / "profiles/ok-observability-standard/charts"
        target_charts.mkdir(parents=True, exist_ok=True)
        for root in lock["roots"]:
            source = source_repo / root["coordinate"]
            if not source.is_file():
                raise VerificationError(f"missing local vendor candidate: {source}")
            if sha256_bytes(source.read_bytes()) != root["contentDigest"]:
                raise VerificationError(f"vendor candidate digest mismatch: {root['id']}")
            tracked = subprocess.run(
                ["git", "-C", str(source_repo), "cat-file", "-e", f"{SOURCE_COMMIT}:{root['coordinate']}"],
                capture_output=True,
            ).returncode == 0
            if tracked or root["inImmutableRoot"]:
                raise VerificationError("candidate must remain absent from the historical immutable root")
            shutil.copyfile(source, target_charts / source.name)

        applications = {
            item["metadata"]["name"]: item
            for item in yaml.safe_load_all(APPLICATIONS.read_text())
            if item
        }
        values = applications["disposable-ok141-observability-core"]["spec"]["source"]["helm"]["valuesObject"]
        values_path = extracted / "provider-values.yaml"
        values_path.write_text(yaml.safe_dump(values, sort_keys=True))
        rendered = subprocess.run(
            [
                "helm", "template", "disposable-ok141-observability-core",
                str(extracted / "profiles/ok-observability-standard"),
                "--namespace", "ok-observability", "--kube-version", "1.36.2",
                "--include-crds", "--values", str(values_path),
            ],
            check=True,
            capture_output=True,
        ).stdout
    digest = sha256_bytes(rendered)
    if digest != EXPECTED_PLATFORM_RENDER:
        raise VerificationError(f"vendor candidate render mismatch: {digest}")
    return digest


def verify(ok_cluster: Path | None = None, ok_observability: Path | None = None) -> list[str]:
    enablement = load(ENABLEMENT_LOCK)
    platform = load(PLATFORM_LOCK)
    validate_lock(enablement)
    validate_lock(platform)
    verify_fixture_correlation(enablement, platform)
    verify_checkpoint()
    if authorization_ready(enablement) or authorization_ready(platform):
        raise VerificationError("current Artifact Locks must not be authorization-ready")
    evidence = []
    if ok_cluster:
        verify_enablement_local(enablement, ok_cluster)
        evidence.append("E-content")
    if ok_observability:
        evidence.append("P-vendor=" + prove_platform_vendor_candidate(platform, ok_observability))
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ok-cluster", type=Path)
    parser.add_argument("--ok-observability", type=Path)
    args = parser.parse_args()
    try:
        evidence = verify(args.ok_cluster, args.ok_observability)
        print("PASS: artifact provenance locks are fail-closed" + (" (" + ", ".join(evidence) + ")" if evidence else ""))
        return 0
    except (VerificationError, OSError, ValueError, subprocess.CalledProcessError, tarfile.TarError) as exc:
        print(f"FAIL: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
