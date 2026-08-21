#!/usr/bin/env python3
"""Derive the non-authorizing Stage-1 signing candidate from fresh-run-v2."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
PACKAGE = HERE.parent / "fresh-run-v2"
OUTPUT = HERE / "stage-1-authorization-candidate.json"


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def main() -> None:
    manifest_raw = (PACKAGE / "package-manifest.json").read_bytes()
    manifest = json.loads(manifest_raw)
    plan = json.loads((PACKAGE / manifest["planPath"]).read_text())
    if manifest["authorizationState"] != "NO-GO" or plan["authorizationState"] != "NO-GO":
        raise SystemExit("fresh-run package is not fail-closed")
    stage = plan["stages"][0]
    if stage["id"] != "provider-prerequisites" or stage["requires"] != []:
        raise SystemExit("first stage identity is not accepted")
    stage_digest = digest(canonical(stage))
    request_payload = {
        "format": "ok147-stage-authorization-request/v1",
        "audience": "ok-cluster-staged-executor",
        "planDigest": manifest["planDigest"],
        "contractIdentity": plan["contractIdentity"],
        "contractRevision": manifest["intentRevision"],
        "enablementRevision": manifest["enablementRevision"],
        "platformRevision": manifest["platformRevision"],
        "executionFixture": manifest["phaseRFixture"],
        "stageId": stage["id"],
        "stageOrder": stage["order"],
        "stageDigest": stage_digest,
        "operation": stage["grantOperation"],
        "authority": stage["authority"],
        "predecessors": [],
        "maxUses": 1,
    }
    request = {"requestDigest": digest(canonical(request_payload)), **request_payload}
    grant_payload = {
        "audience": request["audience"],
        "grantId": "RUNTIME-LOWERCASE-GRANT-ID-REQUIRED",
        "decision": "ALLOW",
        "planDigest": request["planDigest"],
        "contractIdentity": request["contractIdentity"],
        "contractRevision": request["contractRevision"],
        "enablementRevision": request["enablementRevision"],
        "platformRevision": request["platformRevision"],
        "executionFixture": request["executionFixture"],
        "stageId": request["stageId"],
        "stageOrder": request["stageOrder"],
        "stageDigest": request["stageDigest"],
        "operation": request["operation"],
        "authority": request["authority"],
        "predecessors": [],
        "notBefore": "RUNTIME-RFC3339-NOT-BEFORE-REQUIRED",
        "notAfter": "RUNTIME-RFC3339-NOT-AFTER-REQUIRED",
        "maxUses": 1,
    }
    candidate = {
        "format": "ok141-fresh-stage-authorization-candidate/v2",
        "state": "READY-FOR-PRIVATE-SIGNING-DECISION-NO-GO",
        "package": {
            "manifestDigest": digest(manifest_raw),
            "planDigest": manifest["planDigest"],
            "runnerImage": manifest["runnerImage"],
            "runnerPublicationReceiptDigest": manifest["runnerProvenance"]["receiptDigest"],
        },
        "request": request,
        "unsignedGrantTemplate": {
            "format": "ok147-stage-authorization/v1",
            "payload": grant_payload,
            "signature": {
                "algorithm": "Ed25519",
                "keyId": "RUNTIME-SHA256-PUBLIC-KEY-ID-REQUIRED",
                "value": "RUNTIME-BASE64-SIGNATURE-REQUIRED",
            },
        },
        "privateSigningBoundary": {
            "privateKeyRequiredAtRuntime": True,
            "privateKeyPublicRepositoryAllowed": False,
            "maximumWindowSeconds": 1800,
            "maximumUses": 1,
            "laterMutationStagesRequireNewGrant": True,
            "predecessorReceiptsRequiredAfterStage1": True,
        },
        "authorization": {
            "privateKeyMaterialized": False,
            "grantSigned": False,
            "stage1Granted": False,
            "clusterContactGranted": False,
            "mutationGranted": False,
            "retryGranted": False,
            "cleanupGranted": False,
            "failureInjectionGranted": False,
        },
    }
    OUTPUT.write_text(json.dumps(candidate, indent=2) + "\n")
    print(digest(canonical(candidate)))


if __name__ == "__main__":
    main()
