#!/usr/bin/env python3
"""Fail-closed verifier for the selected OK-141 evidence destination."""

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


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


BUNDLE = _load("ok141_evidence_bundle_protocol", HERE / "evidence_bundle.py")
INPUTS = BUNDLE.INPUTS
V1 = BUNDLE.V1
SOURCE_DIGEST = "sha256:4b618081517eb96ef1896b40a7f9f5556054ab2d029fbbf706e8630bb6b42c5c"


def _expect(actual: Any, expected: Any, claim: str) -> None:
    if actual != expected:
        raise V1.HarnessError(f"evidence observer protocol {claim} mismatch")


def validate(document: dict[str, Any], protocol_path: Path) -> str:
    schema = json.loads((HERE / "evidence-observer-protocol-v1.schema.json").read_text())
    V1.normalize(document, schema)
    spec = document["spec"]
    _expect(spec["state"], "DESTINATION-SELECTED-OFFLINE-DEFINED-NO-GO", "state")

    source = spec["sourceAuthorityInputs"]
    source_path = (protocol_path.parent / source["path"]).resolve()
    if SPIKE.resolve() not in source_path.parents or not source_path.is_file():
        raise V1.HarnessError("evidence observer source is missing or outside spike")
    _expect(source["digest"], SOURCE_DIGEST, "source declared digest")
    _expect(V1.sha256_bytes(source_path.read_bytes()), SOURCE_DIGEST, "source raw digest")
    INPUTS.validate(V1.read_yaml_or_json(source_path), source_path)

    destination = spec["destination"]
    _expect(
        (destination["decision"], destination["acceptedBy"], destination["registry"], destination["repository"]),
        ("ACCEPTED", "github:arashkaffamanesh", "ghcr.io", "ghcr.io/openkubes/ok141-evidence"),
        "destination selection",
    )
    _expect(destination["artifactType"], "application/vnd.openkubes.ok141.evidence.v1", "artifact type")
    _expect((destination["authoritativeReference"], destination["tagAuthority"]), ("OCI-DIGEST-ONLY", "NON-AUTHORITATIVE"), "reference authority")
    _expect(
        (destination["externalToDevClusters"], destination["adminDeletionPossible"], destination["availabilityClaim"], destination["immutabilityClaim"], destination["retentionPolicy"], destination["accessProof"]),
        (True, True, "NOT-PROVEN", "CONTENT-INTEGRITY-BY-DIGEST-ONLY", "UNRESOLVED", "UNPROVEN"),
        "destination claim boundary",
    )

    bundle = spec["bundleContract"]
    _expect((bundle["schema"], bundle["implementation"]), ("evidence-bundle-v1.schema.json", "evidence_bundle.py"), "bundle artifacts")
    for name in (bundle["schema"], bundle["implementation"]):
        if not (HERE / name).is_file():
            raise V1.HarnessError(f"evidence observer bundle artifact missing: {name}")
    _expect((bundle["digestAlgorithm"], bundle["artifactOrdering"], bundle["symlinksAllowed"]), ("SHA-256", "LEXICOGRAPHIC-PATH", False), "bundle determinism")
    _expect((bundle["maximumFiles"], bundle["maximumArtifactBytes"], bundle["maximumBundleBytes"]), (BUNDLE.MAX_FILES, BUNDLE.MAX_ARTIFACT_BYTES, BUNDLE.MAX_BUNDLE_BYTES), "bundle limits")
    _expect(set(bundle["requiredBindings"]), {"protocolDigest", "fixtureDigest", "decisionInputDigest", "runId", "targetIdentities", "observedFrom", "observedUntil", "clockSource", "maximumClockSkewSeconds"}, "binding membership")
    publication = bundle["publication"]
    _expect((publication["status"], publication["authorized"], publication["credentialStatus"], publication["commandSurface"]), ("DISABLED", False, "NOT-AUTHORIZED", "NOT-IMPLEMENTED"), "publication boundary")

    redaction = spec["redactionPolicy"]
    _expect(redaction["mode"], "REJECT-NOT-AUTO-REDACT", "redaction mode")
    for field in ("kubernetesSecretObjectsAllowed", "kubeconfigsAllowed", "credentialsAllowed", "privateKeysAllowed", "bearerTokensAllowed", "rawAuthorizationHeadersAllowed"):
        _expect(redaction[field], False, f"redaction {field}")
    _expect(set(redaction["forbiddenPathFragments"]), set(BUNDLE.FORBIDDEN_PATH_FRAGMENTS), "forbidden path fragments")
    _expect({item.lower() for item in redaction["forbiddenStructuredKeys"]}, BUNDLE.FORBIDDEN_STRUCTURED_KEYS, "forbidden structured keys")

    observers = spec["observers"]
    _expect(set(observers), {"security", "evidence"}, "observer membership")
    _expect((observers["security"]["identity"], observers["security"]["status"]), ("ok-141-security-observer", "DEFINED-NOT-DEPLOYED"), "security observer")
    _expect((observers["evidence"]["identity"], observers["evidence"]["status"]), ("ok-141-evidence-observer", "DEFINED-NOT-DEPLOYED"), "evidence observer")
    if "not independent human" not in observers["security"]["claimBoundary"].lower():
        raise V1.HarnessError("evidence observer human-review boundary missing")
    if "does not prove ghcr" not in observers["evidence"]["claimBoundary"].lower():
        raise V1.HarnessError("evidence observer destination boundary missing")

    time_policy = spec["timePolicy"]
    _expect((time_policy["format"], time_policy["maximumClockSkewSeconds"], time_policy["source"], time_policy["currentSkewEvidence"]), ("RFC3339-UTC", 5, "UNPROVEN", "UNPROVEN"), "time policy")
    _expect(len(spec["unresolvedPrerequisites"]), 6, "unresolved prerequisites")

    authorization = spec["authorization"]
    _expect(authorization["decision"], "NO-GO", "authorization decision")
    for field in ("externalWriteAuthorized", "credentialMutationAuthorized", "infrastructureMutationAuthorized", "m0aInstallationGranted", "m0bInstallationGranted", "go1Granted"):
        _expect(authorization[field], False, f"authorization {field}")
    _expect(spec["summary"], {"destinationSelected": True, "offlineBundleMechanismDefined": True, "automatedObserversDeployed": False, "publicationProven": False, "installationGatesGranted": 0}, "summary")

    rules = " ".join(spec["rules"]).lower()
    for phrase in ("authorizes no push", "tags are never authoritative", "fail closed by rejection", "cannot claim independent human", "does not prove retention", "remain no-go"):
        if phrase not in rules:
            raise V1.HarnessError(f"evidence observer safety rule missing: {phrase}")
    return V1.sha256_bytes(protocol_path.read_bytes())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--digest-file", type=Path)
    args = parser.parse_args()
    try:
        path = args.protocol.resolve()
        digest = validate(V1.read_yaml_or_json(path), path)
        if args.digest_file:
            _expect(digest.removeprefix("sha256:"), args.digest_file.read_text().split()[0], "raw digest")
        print(digest)
        return 0
    except (V1.HarnessError, BUNDLE.EvidenceError, OSError, ValueError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
