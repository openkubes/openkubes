#!/usr/bin/env python3
"""Two-stage, fail-closed runtime package for the reviewed GO1-L sequence."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable

import yaml


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
CANDIDATE = HERE / "go1-l-runtime-package-candidate-v1.yaml"
RUN_ID = re.compile(r"ok141-go1-l-[a-z0-9-]{8,80}")


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


EXEC = load_module("ok141_go1_l_executor_v2_for_runtime", SPIKE / "go1-l-executor-v2" / "bounded_go1_l_executor_v2.py")


class RuntimePackageError(ValueError):
    pass


def sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text())
    if not isinstance(value, dict):
        raise RuntimePackageError(f"expected mapping: {path}")
    return value


def expect(actual: Any, expected: Any, context: str) -> None:
    if actual != expected:
        raise RuntimePackageError(f"{context}: expected {expected!r}, got {actual!r}")


def resolve(candidate_path: Path, requested: str) -> Path:
    path = (candidate_path.parent / requested).resolve()
    if SPIKE.resolve() not in path.parents or not path.is_file():
        raise RuntimePackageError(f"reference missing or outside spike root: {requested}")
    return path


def parse_time(value: str) -> dt.datetime:
    return EXEC.V1.V3.V2.parse_time(value)


def iso(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def validate_candidate(candidate_path: Path = CANDIDATE) -> tuple[dict[str, Any], Path]:
    candidate = read(candidate_path)
    expect(candidate.get("apiVersion"), "execution.openkubes.io/v1alpha1", "apiVersion")
    expect(candidate.get("kind"), "GO1LRuntimePackageCandidate", "kind")
    spec = candidate["spec"]
    expect(spec["version"], "ok141-go1-l-runtime-package/v1", "version")
    expect(spec["state"], "OFFLINE-PROVEN-BLOCKED-NO-GO", "state")
    expected = {
        "protocol": "sha256:e45e5f6b8254e666226aa874810bf2ca51f76f2411e0316adb52a7ce51254885",
        "executor": "sha256:0f9693df9b89bc96278f69134517fb2777a60373a61fadc40612cdaacdc2115c",
        "preflight": "sha256:ef4b09a8835f187605a0120bdd19616d6d078b9ed19a3796a47b9cbbfc7a4fb2",
    }
    for name, digest in expected.items():
        expect(spec[name]["digest"], digest, f"{name} digest")
        expect(sha(resolve(candidate_path, spec[name]["path"])), digest, f"{name} source")
    executor_path = resolve(candidate_path, spec["executor"]["path"])
    EXEC.validate_candidate(executor_path)
    decisions = spec["operationalDecisions"]
    expected_decisions = {
        "authorityInputs": "sha256:4b618081517eb96ef1896b40a7f9f5556054ab2d029fbbf706e8630bb6b42c5c",
        "adminRiskAcceptance": "sha256:1bedab96f582b3ca31f67c81b948263560c36fd0a113ec317442cb9c65d25fed",
        "recoveryBaseline": "sha256:797a61fb61cc3ed0e4e57efb07cc5654ae2162b4e7b0c445029ae8e6f0b21674",
        "evidencePublicationProof": "sha256:3b86a78a7a8f3baf7e8e335d7716061d20623c8761eed601755139bbda8c3a3a",
        "retentionDecision": "sha256:b314ee48ad88337b7340f20daef606305b3bc16d70db7b6367e30e3d9477e40b",
    }
    resolved_decisions = {}
    for name, digest in expected_decisions.items():
        binding = decisions[name]
        expect(binding["digest"], digest, f"{name} digest")
        path = resolve(candidate_path, binding["path"])
        expect(sha(path), digest, f"{name} source")
        resolved_decisions[name] = read(path)
    expect(resolved_decisions["authorityInputs"]["spec"]["authorityPrincipal"]["principal"], "github:arashkaffamanesh", "authority principal")
    expect(resolved_decisions["authorityInputs"]["spec"]["governanceException"]["decision"], "ACCEPTED", "DEV-SOLO decision")
    expect(resolved_decisions["adminRiskAcceptance"]["spec"]["acceptance"]["accepted"], True, "admin risk")
    expect(resolved_decisions["recoveryBaseline"]["spec"]["observation"]["execution"]["closureState"], "PASS-R4-CLEAN-BASELINE", "recovery baseline")
    expect(resolved_decisions["evidencePublicationProof"]["spec"]["outcome"]["publicationObjectiveVerified"], True, "publication proof")
    expect(resolved_decisions["retentionDecision"]["spec"]["decision"]["outcome"], "ACCEPTED", "retention decision")
    execution = spec["execution"]
    expect((execution["outerWindowMinutes"], execution["maximumStageGrantMinutes"], execution["authority"]), (120, 20, "github:arashkaffamanesh"), "execution boundary")
    expect(execution["runtimeDirectory"], "/private/tmp/ok141-go1-l-runtime-v1", "runtime directory")
    expect(execution["stages"][0]["operations"], ["provider-prerequisites", "management-namespace", "provider-access-secret", "capi-lifecycle"], "G1 operations")
    expect(execution["stages"][1]["operations"], ["helmchartproxy"], "G3 operations")
    expect(execution["receipts"]["total"], 6, "receipt count")
    expect(sha(resolve(candidate_path, spec["tool"]["path"])), spec["tool"]["digest"], "tool binding")
    if any(spec["tool"][key] for key in ("arbitraryOperationAllowed", "arbitraryCredentialPathAllowed", "retryAllowed", "rollbackOrCleanupAllowed")):
        raise RuntimePackageError("tool expands the reviewed runtime surface")
    authorization = spec["authorization"]
    expect(authorization["decision"], "NO-GO", "authorization")
    expect(authorization["grantIDs"], [], "grant IDs")
    if any(value for key, value in authorization.items() if key.endswith("Granted")):
        raise RuntimePackageError("candidate grants authority")
    return candidate, executor_path


def write_exclusive(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if (path.parent.stat().st_mode & 0o777) != 0o700:
        raise RuntimePackageError("runtime directory mode must be 0700")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, json.dumps(value, indent=2, sort_keys=True).encode() + b"\n")
    finally:
        os.close(fd)


def validate_outer_grant(candidate_path: Path, grant_path: Path, stage: str, now: dt.datetime) -> tuple[dict[str, Any], dt.datetime]:
    candidate, _ = validate_candidate(candidate_path)
    grant = read(grant_path)
    expect(grant.get("apiVersion"), "authorization.openkubes.io/v1alpha1", "grant apiVersion")
    expect(grant.get("kind"), "GO1LStageGrant", "grant kind")
    spec = grant["spec"]
    expect((spec["decision"], spec["authority"], spec["stage"], spec["singleRun"]), ("GO", "github:arashkaffamanesh", stage, True), "stage authority")
    expect(spec["candidateDigest"], sha(candidate_path), "runtime candidate")
    expect(spec["executorDigest"], candidate["spec"]["executor"]["digest"], "executor")
    expect(spec["protocolDigest"], candidate["spec"]["protocol"]["digest"], "protocol")
    expect(spec["preflightCandidateDigest"], candidate["spec"]["preflight"]["digest"], "preflight")
    expect((spec["credentialUseGranted"], spec["go1LGranted"]), (True, True), "GO1-L authority")
    expect((spec["go1Granted"], spec["retryGranted"], spec["rollbackOrCleanupGranted"], spec["evidencePublicationGranted"], spec["failureInjectionGranted"]), (False, False, False, False, False), "excluded authority")
    if EXEC.V1.V3.V2.contains_secret_field(grant):
        raise RuntimePackageError("outer grant contains secret-bearing content")
    if not spec.get("grantID") or not RUN_ID.fullmatch(spec.get("runID", "")):
        raise RuntimePackageError("grant ID or run ID is invalid")
    issued, expires = parse_time(spec["issuedAt"]), parse_time(spec["expiresAt"])
    if not issued <= now <= expires or expires - issued > dt.timedelta(minutes=20):
        raise RuntimePackageError("stage grant is outside its maximum 20-minute window")
    if stage == "G1":
        expect((spec["g1Granted"], spec["g3Granted"]), (True, False), "G1 boundary")
    else:
        expect((spec["g1Granted"], spec["g3Granted"]), (False, True), "G3 boundary")
        if not spec.get("lifecycleEvidenceDigest", "").startswith("sha256:"):
            raise RuntimePackageError("G3 lifecycle evidence digest is missing")
    return grant, expires


def receipt(operation: str, plane: str, path: str, identity: str, now: dt.datetime, expires: dt.datetime) -> dict[str, Any]:
    return {"apiVersion": "evidence.openkubes.io/v1alpha1", "kind": "CredentialReceipt", "spec": {"operation": operation, "targetPlane": plane, "credentialPath": path, "credentialIdentityDigest": identity, "issuedAt": iso(now), "expiresAt": iso(expires), "tokenBytesPersisted": False, "tokenBytesEmitted": False}}


def inner_grant(candidate_path: Path, operation: str, outer: dict[str, Any], preflight_digest: str, receipt_paths: dict[str, Path], predecessor_paths: list[Path], now: dt.datetime, expires: dt.datetime, provider: bool = False) -> dict[str, Any]:
    candidate, _ = validate_candidate(candidate_path)
    return {"apiVersion": "authorization.openkubes.io/v1alpha1", "kind": "SingleOperationGrantV2", "spec": {"decision": "GO", "authority": outer["spec"]["authority"], "mutationAuthorized": True, "credentialUseGranted": True, "go1LGranted": True, "go1Granted": False, "retryGranted": False, "rollbackOrCleanupGranted": False, "evidencePublicationGranted": False, "failureInjectionGranted": False, "operationGranted": operation, "candidateDigest": candidate["spec"]["executor"]["digest"], "executorV1Digest": "sha256:206b62b955d7709f69601989d91b7b5938afba03b2235a4909c64fcecd4fac70", "protocolDigest": candidate["spec"]["protocol"]["digest"], "fixtureDigest": EXEC.V1.FIXTURE_DIGEST, "preflightCandidateDigest": candidate["spec"]["preflight"]["digest"], "preflightEvidenceDigest": preflight_digest, "clientDigest": EXEC.V1.CLIENT_DIGEST, "credentialIdentityClosureDigest": "sha256:26c840ac3e1c5eb879f107801740edb0db73a717fea9c00123ad1e36b3fdc008", "grantID": f"{outer['spec']['grantID']}/{operation}", "singleRun": True, "issuedAt": iso(now), "expiresAt": iso(expires), "credentialReceiptDigests": {name: sha(path) for name, path in receipt_paths.items()}, "predecessorEvidenceDigests": [sha(path) for path in predecessor_paths], "sourceCredentialReadGranted": provider, "destinationCredentialUseGranted": provider, "secretMaterializationGranted": provider}}


def run_directory(candidate: dict[str, Any], run_id: str, create: bool) -> Path:
    base = Path(candidate["spec"]["execution"]["runtimeDirectory"])
    base.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(base, 0o700)
    target = base / run_id
    if create:
        target.mkdir(mode=0o700, exist_ok=False)
    elif not target.is_dir():
        raise RuntimePackageError("G1 runtime directory is absent")
    return target


def make_receipt_file(run_dir: Path, operation: str, plane: str, credential_path: str, identity: str, now: dt.datetime, expires: dt.datetime) -> Path:
    safe = operation.replace("/", "-")
    path = run_dir / f"receipt-{safe}.json"
    write_exclusive(path, receipt(operation, plane, credential_path, identity, now, expires))
    return path


def execute_g1(candidate_path: Path, grant_path: Path, preflight_path: Path, now: dt.datetime, clock: Callable[[], dt.datetime] | None = None) -> dict[str, Any]:
    candidate, executor_path = validate_candidate(candidate_path)
    outer, expires = validate_outer_grant(candidate_path, grant_path, "G1", now)
    expect(sha(preflight_path), outer["spec"]["preflightEvidenceDigest"], "preflight evidence")
    EXEC.V1.validate_preflight(preflight_path, sha(preflight_path), now, True)
    run_dir = run_directory(candidate, outer["spec"]["runID"], True)
    identities = EXEC.validate_candidate(executor_path)[0]["spec"]["credentialIdentityClosure"]["expectedIdentityDigests"]
    credential_paths = EXEC.V1.read_yaml(resolve(executor_path, EXEC.V1.read_yaml(executor_path)["spec"]["supersedes"]["path"]))["spec"]["credentialPaths"]
    evidence: dict[str, Path] = {}
    time_now = clock or (lambda: dt.datetime.now(dt.timezone.utc))

    def do_static(operation: str, plane: str, predecessors: list[Path]) -> None:
        current = time_now()
        receipt_path = make_receipt_file(run_dir, operation, plane, credential_paths[plane], identities[plane], current, expires)
        grant = inner_grant(candidate_path, operation, outer, sha(preflight_path), {operation: receipt_path}, predecessors, current, expires)
        inner_path = run_dir / f"grant-{operation}.json"
        write_exclusive(inner_path, grant)
        result = EXEC.execute_static(executor_path, operation, inner_path, receipt_path, preflight_path, predecessors, current)
        output = run_dir / f"evidence-{operation}.json"
        write_exclusive(output, {"apiVersion": "evidence.openkubes.io/v1alpha1", "kind": "GO1LOperationEvidence", "spec": {**result, "runID": outer["spec"]["runID"], "outerGrantID": outer["spec"]["grantID"], "innerGrantDigest": sha(inner_path), "receiptDigests": [sha(receipt_path)], "predecessorEvidenceDigests": [sha(path) for path in predecessors], "observedAt": iso(time_now())}})
        evidence[operation] = output

    do_static("provider-prerequisites", "ok-infra", [])
    do_static("management-namespace", "ok-mgmt", [evidence["provider-prerequisites"]])
    current = time_now()
    source_receipt = make_receipt_file(run_dir, "provider-access-source", "ok-infra", credential_paths["ok-infra"], identities["ok-infra"], current, expires)
    destination_receipt = make_receipt_file(run_dir, "provider-access-secret", "ok-mgmt", credential_paths["ok-mgmt"], identities["ok-mgmt"], current, expires)
    provider_predecessors = [evidence["provider-prerequisites"], evidence["management-namespace"]]
    provider_grant = inner_grant(candidate_path, "provider-access-secret", outer, sha(preflight_path), {"provider-access-source": source_receipt, "provider-access-secret": destination_receipt}, provider_predecessors, current, expires, provider=True)
    provider_grant_path = run_dir / "grant-provider-access-secret.json"
    write_exclusive(provider_grant_path, provider_grant)
    result = EXEC.execute_provider(executor_path, provider_grant_path, source_receipt, destination_receipt, preflight_path, provider_predecessors, current)
    provider_evidence = run_dir / "evidence-provider-access-secret.json"
    write_exclusive(provider_evidence, {"apiVersion": "evidence.openkubes.io/v1alpha1", "kind": "GO1LOperationEvidence", "spec": {**result, "runID": outer["spec"]["runID"], "outerGrantID": outer["spec"]["grantID"], "innerGrantDigest": sha(provider_grant_path), "receiptDigests": [sha(source_receipt), sha(destination_receipt)], "predecessorEvidenceDigests": [sha(path) for path in provider_predecessors], "observedAt": iso(time_now())}})
    evidence["provider-access-secret"] = provider_evidence
    do_static("capi-lifecycle", "ok-mgmt", [evidence["management-namespace"], evidence["provider-access-secret"]])
    summary_path = run_dir / "g1-summary.json"
    summary = {"apiVersion": "evidence.openkubes.io/v1alpha1", "kind": "GO1LStageEvidence", "spec": {"stage": "G1", "result": "SUBMITTED-STOP-PRESERVE", "runID": outer["spec"]["runID"], "operationEvidenceDigests": {name: sha(path) for name, path in evidence.items()}, "mutationCount": 12, "retryPerformed": False, "rollbackOrCleanupPerformed": False, "completedAt": iso(time_now())}}
    write_exclusive(summary_path, summary)
    return {**summary["spec"], "evidencePath": str(summary_path), "evidenceDigest": sha(summary_path)}


def execute_g3(candidate_path: Path, grant_path: Path, preflight_path: Path, lifecycle_evidence_path: Path, now: dt.datetime) -> dict[str, Any]:
    candidate, executor_path = validate_candidate(candidate_path)
    outer, expires = validate_outer_grant(candidate_path, grant_path, "G3", now)
    expect(sha(preflight_path), outer["spec"]["preflightEvidenceDigest"], "preflight evidence")
    expect(sha(lifecycle_evidence_path), outer["spec"]["lifecycleEvidenceDigest"], "lifecycle evidence")
    run_dir = run_directory(candidate, outer["spec"]["runID"], False)
    identities = EXEC.validate_candidate(executor_path)[0]["spec"]["credentialIdentityClosure"]["expectedIdentityDigests"]
    predecessor = EXEC.V1.read_yaml(resolve(executor_path, EXEC.V1.read_yaml(executor_path)["spec"]["supersedes"]["path"]))
    credential = predecessor["spec"]["credentialPaths"]["ok-mgmt"]
    receipt_path = make_receipt_file(run_dir, "helmchartproxy", "ok-mgmt", credential, identities["ok-mgmt"], now, expires)
    grant = inner_grant(candidate_path, "helmchartproxy", outer, sha(preflight_path), {"helmchartproxy": receipt_path}, [lifecycle_evidence_path], now, expires)
    inner_path = run_dir / "grant-helmchartproxy.json"
    write_exclusive(inner_path, grant)
    result = EXEC.execute_static(executor_path, "helmchartproxy", inner_path, receipt_path, preflight_path, [lifecycle_evidence_path], now)
    evidence_path = run_dir / "evidence-helmchartproxy.json"
    evidence = {"apiVersion": "evidence.openkubes.io/v1alpha1", "kind": "GO1LOperationEvidence", "spec": {**result, "runID": outer["spec"]["runID"], "outerGrantID": outer["spec"]["grantID"], "innerGrantDigest": sha(inner_path), "receiptDigests": [sha(receipt_path)], "predecessorEvidenceDigests": [sha(lifecycle_evidence_path)], "observedAt": iso(now)}}
    write_exclusive(evidence_path, evidence)
    return {**evidence["spec"], "evidencePath": str(evidence_path), "evidenceDigest": sha(evidence_path)}


def plan(candidate_path: Path = CANDIDATE) -> dict[str, Any]:
    candidate, _ = validate_candidate(candidate_path)
    return {"candidateDigest": sha(candidate_path), "protocolDigest": candidate["spec"]["protocol"]["digest"], "executorDigest": candidate["spec"]["executor"]["digest"], "stages": candidate["spec"]["execution"]["stages"], "receiptCount": 6, "credentialUseGranted": False, "mutationAuthorized": False, "clusterContacted": False}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "plan", "run-g1", "run-g3"))
    parser.add_argument("--candidate", type=Path, default=CANDIDATE)
    parser.add_argument("--grant", type=Path)
    parser.add_argument("--preflight", type=Path)
    parser.add_argument("--lifecycle-evidence", type=Path)
    args = parser.parse_args()
    try:
        if args.command in ("verify", "plan"):
            result = plan(args.candidate.resolve())
            result["state"] = validate_candidate(args.candidate.resolve())[0]["spec"]["state"]
        elif args.command == "run-g1":
            if args.grant is None or args.preflight is None:
                raise RuntimePackageError("run-g1 requires grant and preflight")
            result = execute_g1(args.candidate.resolve(), args.grant.resolve(), args.preflight.resolve(), dt.datetime.now(dt.timezone.utc))
        else:
            if args.grant is None or args.preflight is None or args.lifecycle_evidence is None:
                raise RuntimePackageError("run-g3 requires grant preflight and lifecycle evidence")
            result = execute_g3(args.candidate.resolve(), args.grant.resolve(), args.preflight.resolve(), args.lifecycle_evidence.resolve(), dt.datetime.now(dt.timezone.utc))
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (RuntimePackageError, EXEC.ExecutorV2Error, EXEC.V1.ExecutorError, OSError, KeyError, TypeError, ValueError, yaml.YAMLError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
