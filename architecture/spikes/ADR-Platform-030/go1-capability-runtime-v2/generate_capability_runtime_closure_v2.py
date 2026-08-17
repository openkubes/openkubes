#!/usr/bin/env python3
"""Generate the public, redacted OK-141 happy-run closure."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "capability-runtime-closure-v2.json"


def semantic_digest(value) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def main() -> None:
    spec = {
        "observedAt": "2026-08-15T21:24:42Z",
        "identities": {
            "P": "sha256:2956184005f4860607e91672fce82164095dee6ebcbe57e5af883951a199c427",
            "R": "sha256:47bb651f6bc0bdb3a7a567efcd4ca4c776f872a63496fa55c2a6aed77d6fa995",
            "FixtureDigest": "sha256:11133538388c3562f135e814ba4560b76d9ffcb0dac6dab5019f7d75c5a71178",
            "sourceRevision": "c09c18759aeb7526d22106ccb001599f5f06bc4e",
            "capabilityScriptDigest": "sha256:98f41106b7ddc2f7ecffaca9bd9e3c3584d97ab41b169054d8be91ae9cdfb949",
        },
        "identityAmendment": {
            "offlineAmendmentDigest": "sha256:c10e1d59021da0ab9115b557c58d333e8af1e8abd1aa27d21fdb63824d8a9725",
            "initialLiveCandidateDigest": "sha256:c45f319da793d18598c6303a2f6c5a0d9651712371396d4cd979cc1a6c4aaaa1",
            "initialAttempt": "STOP-ZERO-WRITE-API-OMITTED-EXPLICIT-FALSE",
            "correctedLiveCandidateDigest": "sha256:87f6e826e731e76b2ff2ddd91f46828424f33ad39953ff8e91eac197275fb156",
            "privateEvidenceDigest": "sha256:252b26bf7a4342f510bc674b5a40ee996b95d628faa4da6d13cfaafb1c043691",
            "updatedObjectCount": 13,
            "applicationDelta": "identity annotations and immutable targetRevision only",
            "allApplicationsCurrentSyncedHealthy": True,
            "explicitSyncSubmitted": False,
            "retryCountAfterZeroWritePreflight": 1,
        },
        "capabilityExecution": {
            "candidateDigest": "sha256:9465dff1f1d9570b7973147b4e3dde4b4024ca5c233d2fa1b1a4d2b5c3b95e39",
            "privateEvidenceDigest": "sha256:b1cc4999d5720c8f72c15153bed7d8467f0973e3ce254b301af8332dbe1e79ac",
            "privateEvidenceSemanticDigest": "sha256:2160545a2979bf244aa455cb1c79931d622ca6711ea1a38891ee94801e8f1d66",
            "state": "PASS-CAPABILITY",
            "exitCode": 0,
            "applications": {
                "core": "Synced/Healthy/current-revision",
                "alerting": "Synced/Healthy/current-revision",
                "dashboards": "Synced/Healthy/current-revision",
            },
            "alertAcceptance": "firing-only",
            "historicalFailedRunReused": False,
            "retryPerformed": False,
            "rawOutputRetained": False,
            "secretBytesRetained": False,
        },
        "cleanupObservation": {
            "privateEvidenceDigest": "sha256:81aaa7f743097801a3ba671f8e6f2626fa0218f0f9bfcaf98b6ef4e2ec325d79",
            "exactResourceCount": 4,
            "deployment": "ABSENT",
            "service": "ABSENT",
            "serviceMonitor": "ABSENT",
            "logEmitterPod": "ABSENT",
            "ephemeralKubeconfigRemoved": True,
            "ephemeralToolDirectoryRemoved": True,
            "portForwardLogsRemoved": True,
        },
        "architectureResult": {
            "happyPathMutationProof": "PASS",
            "leadingHypothesis": "A",
            "requiresOpenKubesReconciler": "none proven",
            "broadOperatorJustified": False,
            "persistentStatusAdapterJustified": False,
            "overallOK141Classification": "still pending controlled failure-path evidence",
        },
        "remainingGates": {
            "failureInjection": "NO-GO",
            "managementOutage": "NOT-RUN",
            "executorRestart": "NOT-RUN",
            "deleteFinalizer": "NOT-RUN",
            "breakGlass": "NOT-RUN",
        },
        "retention": {
            "privateEvidencePublished": False,
            "rawCapabilityOutputPublished": False,
            "secretOrKubeconfigBytesPublished": False,
            "apiEndpointsPublished": False,
            "uidOrResourceVersionPublished": False,
        },
        "state": "PASS-HAPPY-RUN",
    }
    spec["closureDigest"] = semantic_digest(spec)
    document = {
        "apiVersion": "evidence.openkubes.io/v1alpha1",
        "kind": "OK141CapabilityRuntimeClosure",
        "metadata": {"name": "ok141-capability-runtime-closure-v2"},
        "spec": spec,
    }
    OUTPUT.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    print(spec["closureDigest"])


if __name__ == "__main__":
    main()
