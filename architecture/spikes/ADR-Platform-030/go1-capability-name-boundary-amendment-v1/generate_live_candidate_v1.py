#!/usr/bin/env python3
"""Generate the one-shot live v9 metadata/source binding candidate."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
AMENDMENT = HERE / "capability-name-boundary-amendment-v1.json"
VERIFIER = HERE / "verify_capability_name_boundary_amendment_v1.py"
TOOL = HERE / "bounded_live_capability_name_boundary_amendment_v1.py"
OUTPUT = HERE / "live-capability-name-boundary-amendment-candidate-v1.json"


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    identities = json.loads(AMENDMENT.read_text())["spec"]["identities"]
    candidate = {
        "apiVersion": "action.openkubes.io/v1alpha1",
        "kind": "OK141LiveCapabilityNameBoundaryAmendmentCandidate",
        "metadata": {"name": "ok141-live-capability-name-boundary-amendment-v1"},
        "spec": {
            "state": "LIVE-AUTHORIZED-ONCE",
            "standingGrantAcknowledged": True,
            "authorizationBasis": [
                "continuing OK-141 DEV execution grant",
                "user instruction: weiter",
            ],
            "failurePolicy": "STOP-PRESERVE-NO-RETRY",
            "amendmentPath": "go1-capability-name-boundary-amendment-v1/capability-name-boundary-amendment-v1.json",
            "amendmentDigest": digest(AMENDMENT),
            "verifierPath": "go1-capability-name-boundary-amendment-v1/verify_capability_name_boundary_amendment_v1.py",
            "toolPath": TOOL.name,
            "toolDigest": digest(TOOL),
            "clientPath": "/private/tmp/ok141-kubectl-v1.34.1-darwin-amd64",
            "clientDigest": "sha256:bb211f2b31f2b3bc60562b44cc1e3b712a16a98e9072968ba255beb04cefcfdf",
            "managementKubeconfigPath": "/Users/arash/.kube/ok-mgmt.yaml",
            "sharedKubeconfigPath": "/Users/arash/.kube/ok-shared.yaml",
            "outputPath": "/private/tmp/ok141-live-capability-name-boundary-amendment-v1-evidence.json",
            "identities": identities,
            "operation": {
                "replaceCount": 13,
                "optimisticConcurrency": "UID and resourceVersion checked for every replace",
                "ordering": "eight lifecycle objects, HCP, registration, two non-Core Applications, Core Application last",
                "exactApplicationDelta": "metadata identities and immutable targetRevision only",
                "automaticArgoReconciliationMayRun": True,
                "explicitArgoSyncSubmitted": False,
            },
            "observation": {"intervalSeconds": 15, "maxIterations": 80},
            "exclusions": [
                "manual Argo sync",
                "capability execution",
                "retry",
                "rollback",
                "general cleanup",
                "delete",
                "failure injection",
                "raw Secret retention",
                "raw kubeconfig retention",
                "raw API object publication",
            ],
        },
    }
    OUTPUT.write_text(json.dumps(candidate, indent=2, sort_keys=True) + "\n")
    print(digest(OUTPUT))


if __name__ == "__main__":
    main()
