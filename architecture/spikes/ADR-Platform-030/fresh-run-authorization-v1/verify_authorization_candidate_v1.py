#!/usr/bin/env python3
"""Fail-closed verification of the public Stage-1 authorization candidate."""

from __future__ import annotations

import json
import sys

import generate_authorization_candidate_v1 as generator


class VerificationError(ValueError):
    pass


def expect(actual: object, expected: object, claim: str) -> None:
    if actual != expected:
        raise VerificationError(f"{claim} mismatch")


def verify() -> str:
    candidate = json.loads(generator.OUTPUT.read_text())
    manifest_raw = (generator.PACKAGE / "package-manifest.json").read_bytes()
    manifest = json.loads(manifest_raw)
    plan = json.loads((generator.PACKAGE / manifest["planPath"]).read_text())
    stage = plan["stages"][0]
    stage_digest = generator.digest(generator.canonical(stage))
    expect(candidate["format"], "ok141-fresh-stage-authorization-candidate/v1", "format")
    expect(candidate["state"], "READY-FOR-PRIVATE-SIGNING-DECISION-NO-GO", "state")
    expect(candidate["package"]["manifestDigest"], generator.digest(manifest_raw), "manifest digest")
    expect(candidate["package"]["planDigest"], manifest["planDigest"], "plan digest")
    expect(candidate["package"]["runnerImage"], manifest["runnerImage"], "runner image")
    expect(candidate["package"]["runnerPublicationReceiptDigest"], manifest["runnerProvenance"]["receiptDigest"], "runner receipt")
    request = candidate["request"]
    request_payload = {key: value for key, value in request.items() if key != "requestDigest"}
    expect(request["requestDigest"], generator.digest(generator.canonical(request_payload)), "request digest")
    expect(request["stageId"], "provider-prerequisites", "stage")
    expect(request["stageOrder"], 1, "stage order")
    expect(request["stageDigest"], stage_digest, "stage digest")
    expect(request["operation"], "CreateProviderPrerequisites", "operation")
    expect(request["authority"], "infrastructure", "authority")
    expect(request["predecessors"], [], "predecessors")
    expect(request["maxUses"], 1, "max uses")
    payload = candidate["unsignedGrantTemplate"]["payload"]
    for key in (
        "audience", "planDigest", "contractIdentity", "contractRevision",
        "enablementRevision", "platformRevision", "executionFixture", "stageId",
        "stageOrder", "stageDigest", "operation", "authority", "predecessors", "maxUses",
    ):
        expect(payload[key], request[key], f"grant binding {key}")
    expect(payload["grantId"], "RUNTIME-LOWERCASE-GRANT-ID-REQUIRED", "grant ID placeholder")
    expect(payload["notBefore"], "RUNTIME-RFC3339-NOT-BEFORE-REQUIRED", "notBefore placeholder")
    expect(payload["notAfter"], "RUNTIME-RFC3339-NOT-AFTER-REQUIRED", "notAfter placeholder")
    signature = candidate["unsignedGrantTemplate"]["signature"]
    expect(signature, {
        "algorithm": "Ed25519",
        "keyId": "RUNTIME-SHA256-PUBLIC-KEY-ID-REQUIRED",
        "value": "RUNTIME-BASE64-SIGNATURE-REQUIRED",
    }, "signature placeholder")
    expect(candidate["privateSigningBoundary"]["maximumWindowSeconds"], 1800, "maximum window")
    expect(candidate["authorization"], {
        "privateKeyMaterialized": False,
        "grantSigned": False,
        "stage1Granted": False,
        "clusterContactGranted": False,
        "mutationGranted": False,
        "retryGranted": False,
        "cleanupGranted": False,
        "failureInjectionGranted": False,
    }, "authorization boundary")
    return generator.digest(generator.canonical(candidate))


if __name__ == "__main__":
    try:
        print(verify())
    except (OSError, KeyError, TypeError, json.JSONDecodeError, VerificationError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(2)
