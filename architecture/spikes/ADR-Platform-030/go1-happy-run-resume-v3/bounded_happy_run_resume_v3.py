#!/usr/bin/env python3
"""Resume OK-141 after preserved lifecycle, G3 and failed NetworkReady evidence."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import os
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
CANDIDATE = HERE / "happy-run-resume-candidate-v3.yaml"
RESUME_V2_CANDIDATE = SPIKE / "go1-happy-run-resume-v2" / "happy-run-resume-candidate-v2.yaml"
RESUME_V2_DIGEST = "sha256:8a9522e51816cc9d8974f8791c678e3d5d86b76abc4e3935d4c4592be74c3487"
DEFAULTING_CANDIDATE = SPIKE / "go1-l-network-observer-defaulting-v1" / "network-observer-defaulting-candidate-v1.yaml"
DEFAULTING_DIGEST = "sha256:d7fb85331150dd2ee626d7d81a5f3f4e5114163a761d3d8e61869f3f72a207fe"
DEFAULTING_TOOL = SPIKE / "go1-l-network-observer-defaulting-v1" / "network_observer_defaulting_v1.py"
DEFAULTING_TOOL_DIGEST = "sha256:cfd2832dd08599c720c48c86830cda61b743945bb24a2c9b220fc21313790dc5"

LIFECYCLE_PATH = Path("/private/tmp/ok141-go1-l-lifecycle-api-observer-v1-evidence.json")
G3_PATH = Path("/private/tmp/ok141-go1-l-runtime-v1/ok141-go1-l-20260814-v2/evidence-helmchartproxy.json")
FAILED_NETWORK_PATH = Path("/private/tmp/ok141-go1-l-network-ready-observer-v1-evidence.json")
NETWORK_OUTPUT_PATH = Path("/private/tmp/ok141-go1-l-network-ready-observer-defaulting-v1-evidence.json")


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(value)
    return value


V2 = load_module("ok141_happy_resume_v2_for_v3", SPIKE / "go1-happy-run-resume-v2" / "bounded_happy_run_resume_v2.py")
DEFAULTING = load_module("ok141_network_defaulting_for_resume_v3", DEFAULTING_TOOL)
HAPPY = V2.V1.V2.V1


class ResumeV3Error(ValueError):
    pass


def sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text())
    if not isinstance(value, dict):
        raise ResumeV3Error(f"expected mapping: {path}")
    return value


def expect(actual: Any, expected: Any, context: str) -> None:
    if actual != expected:
        raise ResumeV3Error(f"{context}: expected {expected!r}, got {actual!r}")


def parse_time(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ResumeV3Error("timestamp lacks timezone")
    return parsed.astimezone(dt.timezone.utc)


def write_exclusive(path: Path, value: dict[str, Any]) -> None:
    raw = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)


def validate_candidate(path: Path = CANDIDATE) -> dict[str, Any]:
    value = read(path)
    expect(value.get("kind"), "GO1HappyRunResumeCandidateV3", "kind")
    spec = value["spec"]
    expect(spec["version"], "ok141-go1-happy-run-resume/v3", "version")
    expect(spec["state"], "OFFLINE-PROVEN-BLOCKED-NO-GO", "state")
    expect(sha(RESUME_V2_CANDIDATE), RESUME_V2_DIGEST, "resume v2 candidate")
    V2.validate_candidate(RESUME_V2_CANDIDATE)
    expect(spec["supersedes"]["digest"], RESUME_V2_DIGEST, "resume v2 binding")
    expect(sha(DEFAULTING_CANDIDATE), DEFAULTING_DIGEST, "defaulting candidate")
    expect(sha(DEFAULTING_TOOL), DEFAULTING_TOOL_DIGEST, "defaulting tool")
    DEFAULTING.validate_candidate(DEFAULTING_CANDIDATE)
    expect(spec["networkObserverAmendment"]["candidateDigest"], DEFAULTING_DIGEST, "defaulting binding")
    expect(spec["networkObserverAmendment"]["toolDigest"], DEFAULTING_TOOL_DIGEST, "defaulting tool binding")
    expected_paths = {
        "lifecycle": str(LIFECYCLE_PATH),
        "g3": str(G3_PATH),
        "failedNetwork": str(FAILED_NETWORK_PATH),
    }
    expect({key: item["path"] for key, item in spec["requiredPrivateEvidence"].items()}, expected_paths, "private evidence paths")
    expect(spec["resumeBoundary"]["startsAfter"], "G3-AND-FAILED-NETWORK-OBSERVATION", "resume boundary")
    for key in ("preflightReexecutionAllowed", "g1ReexecutionAllowed", "remediationReexecutionAllowed", "lifecycleReexecutionAllowed", "g3ReexecutionAllowed"):
        expect(spec["resumeBoundary"][key], False, key)
    expect(spec["networkObserverAmendment"]["outputPath"], str(NETWORK_OUTPUT_PATH), "new output path")
    expect(sha(HERE / spec["tool"]["path"]), spec["tool"]["digest"], "tool digest")
    expect(spec["authorization"]["decision"], "NO-GO", "authorization")
    if any(item for key, item in spec["authorization"].items() if key.endswith("Granted")):
        raise ResumeV3Error("candidate grants authority")
    return value


def safe_private(path: Path, expected_path: Path, expected_digest: str, context: str) -> dict[str, Any]:
    expect(path, expected_path, f"{context} path")
    if path.is_symlink() or not path.is_file() or (path.stat().st_mode & 0o777) != 0o600:
        raise ResumeV3Error(f"unsafe {context} evidence")
    expect(sha(path), expected_digest, f"{context} digest")
    return read(path)


def validate_prior_values(lifecycle: dict[str, Any], g3: dict[str, Any], failed: dict[str, Any]) -> None:
    expect((lifecycle.get("kind"), lifecycle.get("closureState")), ("GO1LLifecycleAPIEvidence", "PASS-CURRENT-LIFECYCLE-API-EVIDENCE"), "lifecycle result")
    g3_spec = g3.get("spec", {})
    expect((g3.get("kind"), g3_spec.get("operation"), g3_spec.get("semanticDigest")), ("GO1LOperationEvidence", "helmchartproxy", "sha256:cd1a21b0b611a3a928e6e7d63d7eb2c4b4657570152ac3c6ae6061a48d4b788e"), "G3 result")
    expect((g3_spec.get("retryPerformed"), g3_spec.get("rollbackOrCleanupPerformed")), (False, False), "G3 exclusions")
    expect(g3_spec.get("predecessorEvidenceDigests"), [failed.get("lifecycleEvidenceDigest")], "G3 lifecycle predecessor")
    expect((failed.get("kind"), failed.get("closureState"), failed.get("NetworkReady")), ("GO1LNetworkReadyEvidence", "FAIL-HCP-SPEC", False), "failed NetworkReady result")
    expect(failed.get("candidateDigest"), "sha256:15b24bd0d7247e0a05d4b1f291221cc52e4f1cefa498b8fe4c5d00b6347f3e04", "failed observer candidate")
    expect(failed.get("lifecycleEvidenceDigest"), "sha256:" + hashlib.sha256((json.dumps(lifecycle, sort_keys=True, separators=(",", ":")) + "\n").encode()).hexdigest(), "failed lifecycle binding")
    expect(failed.get("persistentMutationPerformed"), False, "failed observer mutation")


def validate_private_chain(spec: dict[str, Any]) -> dict[str, Any]:
    bindings = spec["priorEvidence"]
    lifecycle = safe_private(Path(bindings["lifecyclePath"]), LIFECYCLE_PATH, bindings["lifecycleDigest"], "lifecycle")
    g3 = safe_private(Path(bindings["g3Path"]), G3_PATH, bindings["g3Digest"], "G3")
    failed = safe_private(Path(bindings["failedNetworkPath"]), FAILED_NETWORK_PATH, bindings["failedNetworkDigest"], "failed NetworkReady")
    validate_prior_values(lifecycle, g3, failed)
    return {"lifecycle": lifecycle, "g3": g3, "failedNetwork": failed}


TRUE = (
    "resumeAfterG3Granted", "lifecycleEvidenceReuseGranted", "g3EvidenceReuseGranted",
    "networkObserverGranted", "runtimeBindingGranted", "targetAccessGranted", "tokenRequestGranted",
    "registrationGranted", "credentialSecretGranted", "applicationSubmissionGranted",
    "platformObserverGranted", "capabilityTestGranted", "capabilityTestCleanupGranted",
    "credentialUseGranted", "go1LGranted", "go1Granted",
)
FALSE = (
    "preflightGranted", "g1Granted", "remediationGranted", "lifecycleReexecutionGranted",
    "g3Granted", "retryGranted", "rollbackGranted", "broadCleanupGranted",
    "evidencePublicationGranted", "failureInjectionGranted", "outageGranted",
)


def validate_grant(candidate_path: Path, grant_path: Path, now: dt.datetime | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    validate_candidate(candidate_path)
    grant = read(grant_path)
    expect(grant.get("kind"), "GO1HappyRunResumeGrantV3", "grant kind")
    spec = grant["spec"]
    expect((spec.get("decision"), spec.get("authority"), spec.get("singleRun"), spec.get("consumed")), ("GO", "github:arashkaffamanesh", True, False), "grant identity")
    expect(spec.get("candidateDigest"), sha(candidate_path), "candidate digest")
    expect(spec.get("networkObserverDefaultingCandidateDigest"), DEFAULTING_DIGEST, "defaulting candidate")
    if any(spec.get(key) is not True for key in TRUE) or any(spec.get(key) is not False for key in FALSE):
        raise ResumeV3Error("resume authority is incomplete or overbroad")
    current = now or dt.datetime.now(dt.timezone.utc)
    issued, expires = parse_time(spec["issuedAt"]), parse_time(spec["expiresAt"])
    if not issued <= current <= expires or expires - issued > dt.timedelta(hours=2):
        raise ResumeV3Error("grant inactive or exceeds two hours")
    return grant, validate_private_chain(spec)


def adapt_grant(grant: dict[str, Any]) -> dict[str, Any]:
    adapted = deepcopy(grant)
    adapted["kind"] = "GO1HappyRunResumeGrantV2"
    spec = adapted["spec"]
    spec["candidateDigest"] = RESUME_V2_DIGEST
    spec["remediationEvidenceBindingGranted"] = True
    spec["resumeFromG1Granted"] = True
    spec["lifecycleObserverGranted"] = True
    spec["g3Granted"] = True
    return adapted


def amended_network_candidate(original: dict[str, Any]) -> dict[str, Any]:
    value = deepcopy(original)
    value["spec"]["observation"]["outputPath"] = str(NETWORK_OUTPUT_PATH)
    return value


def prior_g3_result(g3: dict[str, Any]) -> dict[str, Any]:
    return {**deepcopy(g3["spec"]), "evidencePath": str(G3_PATH), "evidenceDigest": sha(G3_PATH)}


def execute(candidate_path: Path, grant_path: Path, capability_script: Path) -> dict[str, Any]:
    outer, prior = validate_grant(candidate_path, grant_path)
    adapted = adapt_grant(outer)
    adapted_path = Path(f"/private/tmp/ok141-happy-resume-v3-adapted-{outer['spec']['runID']}.json")
    if adapted_path.exists() or adapted_path.is_symlink():
        raise ResumeV3Error("adapted grant already exists")
    write_exclusive(adapted_path, adapted)

    original_lifecycle_execute = HAPPY.LIFECYCLE.execute
    original_g3_execute = HAPPY.RUNTIME.execute_g3
    original_network_validate = HAPPY.NETWORK.validate_candidate
    original_semantic_hcp_spec = HAPPY.NETWORK.semantic_hcp_spec

    def reuse_lifecycle(candidate, stage_grant, kubectl, now=None, runner=None, sleeper=None):
        HAPPY.LIFECYCLE.validate_grant(candidate, stage_grant, now)
        return deepcopy(prior["lifecycle"])

    def reuse_g3(candidate, stage_grant, preflight, lifecycle, now):
        HAPPY.RUNTIME.validate_outer_grant(candidate, stage_grant, "G3", now)
        expect(sha(lifecycle), outer["spec"]["priorEvidence"]["lifecycleDigest"], "reused lifecycle path")
        return prior_g3_result(prior["g3"])

    def validate_amended_network(candidate=HAPPY.NETWORK.CANDIDATE):
        return amended_network_candidate(original_network_validate(candidate))

    HAPPY.LIFECYCLE.execute = reuse_lifecycle
    HAPPY.RUNTIME.execute_g3 = reuse_g3
    HAPPY.NETWORK.validate_candidate = validate_amended_network
    HAPPY.NETWORK.semantic_hcp_spec = DEFAULTING.semantic_hcp_spec
    try:
        result = V2.execute(RESUME_V2_CANDIDATE, adapted_path, capability_script)
    finally:
        HAPPY.LIFECYCLE.execute = original_lifecycle_execute
        HAPPY.RUNTIME.execute_g3 = original_g3_execute
        HAPPY.NETWORK.validate_candidate = original_network_validate
        HAPPY.NETWORK.semantic_hcp_spec = original_semantic_hcp_spec
        adapted_path.unlink(missing_ok=True)
    result["candidateDigest"] = sha(candidate_path)
    result["networkObserverDefaultingCandidateDigest"] = DEFAULTING_DIGEST
    result["failedNetworkEvidenceDigest"] = outer["spec"]["priorEvidence"]["failedNetworkDigest"]
    result["lifecycleReexecuted"] = False
    result["g3Reexecuted"] = False
    return result


def plan(path: Path = CANDIDATE) -> dict[str, Any]:
    value = validate_candidate(path)
    return {
        "candidateDigest": sha(path),
        "supersedes": RESUME_V2_DIGEST,
        "resumeBoundary": value["spec"]["resumeBoundary"],
        "networkObserverAmendment": DEFAULTING_DIGEST,
        "authorization": "NO-GO",
        "clusterContacted": False,
        "mutationPerformed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "verify-grant", "run"))
    parser.add_argument("--candidate", type=Path, default=CANDIDATE)
    parser.add_argument("--grant", type=Path)
    parser.add_argument("--capability-script", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "verify":
            print(json.dumps(plan(args.candidate.resolve()), indent=2, sort_keys=True))
        elif args.command == "verify-grant":
            if args.grant is None:
                raise ResumeV3Error("grant required")
            validate_grant(args.candidate.resolve(), args.grant.resolve())
            print(sha(args.grant.resolve()))
        else:
            if not args.execute or args.grant is None or args.capability_script is None:
                raise ResumeV3Error("run requires --execute, grant and capability script")
            print(json.dumps(execute(args.candidate.resolve(), args.grant.resolve(), args.capability_script.resolve()), indent=2, sort_keys=True))
        return 0
    except Exception as error:
        print(f"ERROR: {type(error).__name__}: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
