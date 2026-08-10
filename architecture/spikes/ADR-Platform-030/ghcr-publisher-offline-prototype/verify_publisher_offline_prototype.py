#!/usr/bin/env python3
"""Fail-closed verifier for the inert, write-capable OK-141 publisher prototype."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import yaml


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
REPO = SPIKE.parents[2]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


OBSERVER = _load(
    "ok141_publisher_source_observer",
    SPIKE / "ghcr-observer-offline-prototype" / "verify_observer_offline_prototype.py",
)
V1 = OBSERVER.V1
SOURCE_DIGEST = "sha256:c41b191ffa930e8c0fbf9a0906fb0cc8a6935c31d663c3abe2b63e557aaa77d4"
COMPONENT_DIGESTS = {
    "candidateWorkflow": ("candidate/ok141-evidence-publisher.workflow.yaml", "sha256:ae6514766cdba993f3480d6445494d8134eefad447c7320c4b720ed57633de4e"),
    "plannerAndVerifier": ("publish_evidence.py", "sha256:95eff6c7fd5f3bb3bbd152ed782ae4052236b9759d204d1353f95e6444880f1d"),
}


def _expect(actual: Any, expected: Any, claim: str) -> None:
    if actual != expected:
        raise V1.HarnessError(f"GHCR publisher offline prototype {claim} mismatch")


def validate(document: dict[str, Any], manifest_path: Path) -> str:
    schema = json.loads((HERE / "publisher-offline-prototype-v1.schema.json").read_text())
    V1.normalize(document, schema)
    spec = document["spec"]
    _expect(spec["state"], "IMPLEMENTED-OFFLINE-INERT-WRITE-CAPABLE-NOT-DEPLOYED-NO-GO", "state")

    source = spec["sourceObserverPrototype"]
    source_path = (manifest_path.parent / source["path"]).resolve()
    if SPIKE.resolve() not in source_path.parents or not source_path.is_file():
        raise V1.HarnessError("GHCR publisher source is missing or outside spike")
    _expect(source, {"path": "../ghcr-observer-offline-prototype/observer-offline-prototype-v1.yaml", "digest": SOURCE_DIGEST, "state": "IMPLEMENTED-OFFLINE-INERT-NOT-DEPLOYED-NO-GO"}, "source")
    _expect(V1.sha256_bytes(source_path.read_bytes()), SOURCE_DIGEST, "source raw digest")
    OBSERVER.validate(V1.read_yaml_or_json(source_path), source_path)

    for name, (path, digest) in COMPONENT_DIGESTS.items():
        _expect(spec["components"][name], {"path": path, "digest": digest}, f"component {name}")
        component_path = (HERE / path).resolve()
        if HERE.resolve() not in component_path.parents or not component_path.is_file():
            raise V1.HarnessError(f"GHCR publisher component missing or outside prototype: {name}")
        _expect(V1.sha256_bytes(component_path.read_bytes()), digest, f"component raw digest {name}")

    supply = spec["supplyChain"]
    _expect(supply["checkout"]["fullCommitSHA"], "11d5960a326750d5838078e36cf38b85af677262", "checkout pin")
    _expect(supply["attestation"], {"repository": "actions/attest", "version": "v4.2.2", "fullCommitSHA": "1e69f48acb82d1966a394da916b4c1698aa569d6"}, "attestation pin")
    _expect(supply["oras"], {"repository": "oras-project/oras", "version": "v1.3.3", "asset": "oras_1.3.3_linux_amd64.tar.gz", "assetDigest": "sha256:9ce999f8d2de03fc03968b29d743077a58783e545e5eaa53917ca177352d0e59"}, "ORAS pin")

    workflow_path = HERE / COMPONENT_DIGESTS["candidateWorkflow"][0]
    workflow = yaml.safe_load(workflow_path.read_text())
    _expect(set(workflow["on"]), {"workflow_dispatch"}, "candidate trigger")
    _expect(workflow["permissions"], {"actions": "read", "artifact-metadata": "write", "attestations": "write", "contents": "read", "id-token": "write", "packages": "write"}, "candidate permissions")
    _expect(workflow["jobs"]["publish"]["environment"], "ok-141-evidence-publish", "candidate environment")
    _expect(len(workflow["jobs"]["publish"]["steps"]), 8, "candidate step count")
    action_uses = [step["uses"] for step in workflow["jobs"]["publish"]["steps"] if "uses" in step]
    _expect(action_uses, ["actions/checkout@11d5960a326750d5838078e36cf38b85af677262", "actions/attest@1e69f48acb82d1966a394da916b4c1698aa569d6"], "candidate action pins")
    text = workflow_path.read_text()
    for phrase in ("9ce999f8d2de03fc03968b29d743077a58783e545e5eaa53917ca177352d0e59", "--source-ref refs/heads/main", "@${{ steps.publish.outputs.digest }}", "--password-stdin"):
        if phrase not in text:
            raise V1.HarnessError(f"GHCR publisher candidate boundary missing: {phrase}")
    for forbidden in ("packages: delete", "issues: write", "pull-requests: write", ":latest"):
        if forbidden in text.lower():
            raise V1.HarnessError(f"GHCR publisher candidate exposes forbidden scope: {forbidden}")

    contract = spec["workflowContract"]
    _expect((contract["futureDeploymentPathPresent"], contract["environmentPresent"], contract["packageDeletePermissionPresent"], contract["issueOrWebhookPermissionPresent"], contract["checkoutCredentialsPersisted"]), (False, False, False, False, False), "inert workflow boundary")
    if (REPO / contract["futureDeploymentPath"]).exists():
        raise V1.HarnessError("GHCR publisher candidate is unexpectedly deployed")

    publication = spec["publicationContract"]
    _expect((publication["repository"], publication["tagAuthority"], publication["attestationSubject"], publication["signerSourceRef"], publication["pullBackReference"]), ("ghcr.io/openkubes/ok141-evidence", "NON-AUTHORITATIVE", "OCI-MANIFEST-DIGEST", "refs/heads/main", "OCI-DIGEST-ONLY"), "publication boundary")
    proof = spec["proof"]
    _expect((proof["offlineTestsPassed"], proof["deterministicTransportProven"], proof["changedEvidenceRejected"], proof["pullBackTamperingRejected"], proof["wrongAttestationSubjectRejected"]), (9, True, True, True, True), "offline proof")
    for field in ("livePackageWritePerformed", "liveAttestationPerformed", "livePullBackPerformed", "workflowDeployed", "environmentCreated", "credentialAuthorized"):
        _expect(proof[field], False, f"proof {field}")
    _expect(len(spec["remainingBlockers"]), 8, "remaining blocker count")

    authorization = spec["authorization"]
    _expect(authorization["decision"], "NO-GO", "authorization decision")
    for field in authorization:
        if field != "decision":
            _expect(authorization[field], False, f"authorization {field}")
    _expect(spec["summary"], {"plannerImplementedOffline": True, "pullBackVerifierImplementedOffline": True, "inertWorkflowCandidatePresent": True, "activeWorkflowPresent": False, "livePublicationProven": False, "installationGatesGranted": 0}, "summary")

    rules = " ".join(spec["rules"]).lower()
    for phrase in ("inert but write capable", "separately authorized exact source run", "tag is non-authoritative", "bind repository signer workflow", "requires a separate mutation gate", "remain no-go"):
        if phrase not in rules:
            raise V1.HarnessError(f"GHCR publisher safety rule missing: {phrase}")
    return V1.sha256_bytes(manifest_path.read_bytes())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--digest-file", type=Path)
    args = parser.parse_args()
    try:
        path = args.manifest.resolve()
        digest = validate(V1.read_yaml_or_json(path), path)
        if args.digest_file:
            _expect(digest.removeprefix("sha256:"), args.digest_file.read_text().split()[0], "raw digest")
        print(digest)
        return 0
    except (V1.HarnessError, OSError, ValueError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
