#!/usr/bin/env python3
"""Fail-closed verifier for the non-authorizing OK-141 M0a credential gate."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import yaml


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
ALLOWED_VERBS = {"get", "patch"}
EXPECTED_OBJECTS = {
    ("ServiceAccount", "openkubes-system", "ok141-m0a-installer"),
    ("ClusterRole", None, "ok141-m0a-installer"),
    ("ClusterRoleBinding", None, "ok141-m0a-installer"),
}


class VerificationError(ValueError):
    pass


def sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def expect(actual, expected, claim: str) -> None:
    if actual != expected:
        raise VerificationError(f"{claim}: expected {expected!r}, got {actual!r}")


def resolve(reference: dict) -> Path:
    path = (HERE / reference["path"]).resolve()
    if SPIKE not in path.parents or not path.is_file():
        raise VerificationError(f"reference missing or outside spike root: {path}")
    expect(sha(path), reference["digest"], f"digest for {reference['path']}")
    return path


def load_documents(path: Path) -> list[dict]:
    return [item for item in yaml.safe_load_all(path.read_text()) if item]


def verify(path: Path) -> str:
    document = yaml.safe_load(path.read_text())
    spec = document["spec"]
    expect(spec["protocolState"], "BLOCKED", "protocol state")
    for reference in spec["references"].values():
        resolve(reference)

    manifest = HERE / spec["credentialObjects"]["manifestPath"]
    expect(sha(manifest), spec["credentialObjects"]["rawDigest"], "credential manifest digest")
    documents = load_documents(manifest)
    expect(len(documents), 3, "credential object count")
    actual = {
        (item["kind"], item["metadata"].get("namespace"), item["metadata"]["name"])
        for item in documents
    }
    expect(actual, EXPECTED_OBJECTS, "credential object inventory")

    role = next(item for item in documents if item["kind"] == "ClusterRole")
    named_targets = 0
    for rule in role["rules"]:
        verbs = set(rule.get("verbs", []))
        if verbs - ALLOWED_VERBS or not verbs:
            raise VerificationError("credential role contains an unapproved verb")
        resource_names = rule.get("resourceNames", [])
        if not resource_names:
            raise VerificationError("credential role contains an unbounded resource rule")
        named_targets += len(resource_names)
        if "secrets" in rule.get("resources", []):
            raise VerificationError("credential role grants Secret access")
    expect(named_targets, spec["permissionModel"]["allowedObjectNames"], "allowed object-name count")

    binding = next(item for item in documents if item["kind"] == "ClusterRoleBinding")
    expect(binding["roleRef"]["name"], "ok141-m0a-installer", "binding role")
    expect(binding["subjects"], [{
        "kind": "ServiceAccount",
        "name": "ok141-m0a-installer",
        "namespace": "openkubes-system",
    }], "binding subject")

    credential = spec["installerCredential"]
    expect(credential["maximumDuration"], "60m", "maximum token duration")
    for claim in ("persisted", "emittedToLogs", "emittedToEvidence"):
        expect(credential[claim], False, claim)

    auth = spec["authorization"]
    expect(auth["decision"], "NO-GO", "authorization decision")
    for claim in ("mutationAuthorized", "credentialBootstrapGranted", "tokenIssuanceGranted", "m0aInstallationGranted"):
        expect(auth[claim], False, claim)
    expect(auth["authorizedProtocolDigest"], None, "authorized protocol digest")

    phases = spec["phases"]
    if any(item["enabled"] for item in phases):
        raise VerificationError("a credential phase is enabled without authority")
    expect([item["mutating"] for item in phases], [False, True, True, False, True, False], "phase mutation model")

    rules = " ".join(spec["rules"])
    for phrase in ("grants no authority", "requiring one exact separately authorized digest", "does not grant M0a-I", "remain NO-GO"):
        if phrase not in rules:
            raise VerificationError(f"required fail-closed rule missing: {phrase}")
    return sha(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--digest-file", type=Path)
    args = parser.parse_args()
    try:
        result = verify(args.protocol.resolve())
        if args.digest_file:
            expect(args.digest_file.read_text().strip(), result, "protocol digest file")
        print(result)
        return 0
    except (OSError, KeyError, TypeError, VerificationError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
