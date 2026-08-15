#!/usr/bin/env python3
"""Generate the one-shot corrected OK-141 capability candidate."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil


HERE = Path(__file__).resolve().parent
TOOL = HERE / "bounded_capability_runtime_v2.py"
OUTPUT = HERE / "capability-runtime-candidate-v2.json"


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def executable(name: str, fallback: str | None = None) -> Path:
    value = shutil.which(name) or fallback
    if not value:
        raise RuntimeError(f"required executable unavailable: {name}")
    return Path(value).resolve()


def main() -> None:
    shared = Path("/Users/arash/.kube/ok-shared.yaml")
    management = Path("/Users/arash/.kube/ok-mgmt.yaml")
    script = Path("/Users/arash/temp/kubernauts/ok/ok-observability/tests/contract-test.sh")
    live_evidence = Path("/private/tmp/ok141-live-capability-name-boundary-amendment-v1-evidence.json")
    clients = {
        "sharedAndManagementKubectl": Path("/private/tmp/ok141-kubectl-v1.34.1-darwin-amd64"),
        "workloadKubectl": executable("kubectl"),
        "bash": Path("/bin/bash"),
        "curl": Path("/usr/bin/curl"),
        "jq": executable("jq"),
    }
    candidate = {
        "apiVersion": "execution.openkubes.io/v1alpha1",
        "kind": "OK141CapabilityRuntimeCandidate",
        "metadata": {"name": "ok141-capability-runtime-v2", "ticket": "OK-141"},
        "spec": {
            "version": "ok141-capability-runtime/v2",
            "state": "AUTHORIZED-BY-CONTINUOUS-DEV-GRANT",
            "stopSemantics": "STOP-PRESERVE-NO-RETRY",
            "identities": {
                "P": "sha256:2956184005f4860607e91672fce82164095dee6ebcbe57e5af883951a199c427",
                "R": "sha256:47bb651f6bc0bdb3a7a567efcd4ca4c776f872a63496fa55c2a6aed77d6fa995",
                "FixtureDigest": "sha256:11133538388c3562f135e814ba4560b76d9ffcb0dac6dab5019f7d75c5a71178",
            },
            "sourceRevision": "c09c18759aeb7526d22106ccb001599f5f06bc4e",
            "predecessor": {
                "liveAmendmentCandidateDigest": "sha256:87f6e826e731e76b2ff2ddd91f46828424f33ad39953ff8e91eac197275fb156",
                "liveAmendmentEvidencePath": str(live_evidence),
                "liveAmendmentEvidenceDigest": digest(live_evidence),
                "historicalV1RunReused": False,
            },
            "applications": [
                "disposable-ok141-observability-core",
                "disposable-ok141-observability-alerting",
                "disposable-ok141-observability-dashboards",
            ],
            "credentials": {
                "sharedKubeconfig": str(shared),
                "sharedKubeconfigDigest": digest(shared),
                "managementKubeconfig": str(management),
                "managementKubeconfigDigest": digest(management),
            },
            "workload": {
                "kubeconfigSecretURI": "/api/v1/namespaces/disposable-ok141/secrets/disposable-ok141-kubeconfig",
                "credentialSecretURI": "/api/v1/namespaces/ok-observability/secrets/ok-observability-credentials",
                "credentialKeys": ["grafana-admin-user", "grafana-admin-password", "opensearch-admin-password"],
            },
            "capability": {
                "contractDigest": "sha256:b6ef10a8ecf6daf42e6d44018d51e2263f380ed649445e5a70ff5c550c73415e",
                "scriptPath": str(script),
                "scriptDigest": digest(script),
                "namespace": "ok-observability",
                "runID": "ok141-cap-v9-20260815-01",
                "asyncTimeoutSeconds": 240,
                "overallTimeoutSeconds": 1800,
                "alertAcceptance": "firing-only",
                "syntheticMutationAndCleanupOwnedByScript": True,
            },
            "tools": {key: {"path": str(path), "digest": digest(path)} for key, path in clients.items()},
            "runtime": {
                "ephemeralKubeconfigPath": "/private/tmp/ok141-capability-runtime-v2-workload-kubeconfig.yaml",
                "ephemeralToolDirectory": "/private/tmp/ok141-capability-runtime-v2-tools",
            },
            "outputPath": "/private/tmp/ok141-capability-runtime-v2-evidence.json",
            "evidenceBoundary": {
                "retains": ["application-state", "identity-digests", "capability-exit-code", "stdout-digest", "stderr-digest", "cleanup-state"],
                "forbids": ["secret-bytes", "kubeconfig-bytes", "raw-capability-output", "api-endpoints", "tokens", "private-keys"],
            },
            "tool": {"path": TOOL.name, "digest": digest(TOOL)},
            "authorization": {
                "source": "user-continuous-dev-execution-grant-until-happy-run-or-stop-condition",
                "exactApplicationReads": True,
                "exactSecretReads": True,
                "temporary0600Kubeconfig": True,
                "exactCapabilityTest": True,
                "syntheticCapabilityCleanup": True,
                "retry": False,
                "forbidden": ["arbitraryMutation", "failureInjection", "broadCleanup", "rawEvidencePublication", "forceDelete", "finalizerMutation"],
            },
        },
    }
    OUTPUT.write_text(json.dumps(candidate, indent=2, sort_keys=True) + "\n")
    print(digest(OUTPUT))


if __name__ == "__main__":
    main()
