#!/usr/bin/env python3
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parent
PROTOCOL = ROOT / "go1-l-recovery-protocol-v1.yaml"


class VerificationError(ValueError):
    pass


def expect(actual: Any, expected: Any, claim: str) -> None:
    if actual != expected:
        raise VerificationError(f"{claim}: expected {expected!r}, got {actual!r}")


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text())
    if not isinstance(value, dict):
        raise VerificationError(f"not a mapping: {path}")
    return value


def verify(protocol_path: Path = PROTOCOL) -> str:
    protocol = read(protocol_path)
    spec = protocol["spec"]
    expect(protocol["kind"], "GO1LRecoveryProtocol", "kind")
    expect(spec["state"], "OFFLINE-PREPARED-BLOCKED-NO-GO", "state")
    expect(spec["decision"]["strategy"], "uid-preconditioned-cleanup-then-fresh-recreate", "strategy")
    expect(spec["decision"]["patchInPlaceAllowed"], False, "patch-in-place")
    expect(spec["decision"]["automaticContinuationToRecreate"], False, "automatic recreate")

    for group in ("protocol", "submitter"):
        claim = spec["failedExecution"][group]
        expect(digest((ROOT / claim["path"]).resolve()), claim["digest"], f"{group} digest")
    for group in ("fixture", "amendment"):
        claim = spec["correctedBaseline"][group]
        expected = claim.get("fileDigest", claim.get("digest"))
        expect(digest((ROOT / claim["path"]).resolve()), expected, f"{group} digest")
    fixture = read((ROOT / spec["correctedBaseline"]["fixture"]["path"]).resolve())
    expect(fixture["fixtureDigest"], spec["correctedBaseline"]["fixture"]["fixtureDigest"], "FixtureDigest")
    expect(fixture["contract"]["R"], spec["correctedBaseline"]["fixture"]["R"], "R")

    binding = spec["privateRuntimeBinding"]
    expect(binding["required"], True, "private binding required")
    expect(binding["finalDigest"], None, "private binding remains unbound")
    expect(binding["state"], "BLOCKED-FRESH-READ-ONLY-PREFLIGHT", "private binding state")
    expect(binding["containsCredentials"], False, "credential boundary")
    expect(binding["publicUIDPublicationAllowed"], False, "UID publication boundary")

    stages = spec["stages"]
    expect([stage["id"] for stage in stages], ["R0", "R1", "R2", "R3", "R4"], "stage order")
    if any(stage["enabled"] for stage in stages):
        raise VerificationError("a recovery stage is enabled")
    for stage in (stages[1], stages[3]):
        expect(stage["transport"], "kubernetes-api-delete-with-deleteoptions-uid-precondition", f"{stage['id']} transport")
        expect(stage["force"], False, f"{stage['id']} force")
        expect(stage["removeFinalizers"], False, f"{stage['id']} finalizers")
        expect(stage["automaticRetry"], False, f"{stage['id']} retry")

    auth = spec["authorization"]
    expect(auth["decision"], "NO-GO", "authorization decision")
    if any(value is True for key, value in auth.items() if key != "decision"):
        raise VerificationError("an authorization flag is true")

    grant = read(ROOT / "recovery-grant-v1.template.yaml")["spec"]
    expect(grant["state"], "TEMPLATE-NOT-GRANTED", "grant state")
    expect(grant["maximumRuns"], 0, "grant maximum runs")
    if grant["authorizedStages"] or any(
        value is True for key, value in grant.items() if key.endswith("Authorized")
    ):
        raise VerificationError("grant template carries authority")

    runtime = read(ROOT / binding["templatePath"])["spec"]
    expect(runtime["state"], "TEMPLATE-NOT-EXECUTABLE", "runtime template state")
    expect(runtime["credentialsIncluded"], False, "runtime credential boundary")
    expect(runtime["executable"], False, "runtime executable flag")
    return digest(protocol_path)


if __name__ == "__main__":
    print(verify())
