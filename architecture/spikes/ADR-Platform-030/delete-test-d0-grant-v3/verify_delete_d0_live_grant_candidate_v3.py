#!/usr/bin/env python3
"""Fail-closed offline verifier for the OK-141 D0-v3 live-grant candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml


class CandidateError(ValueError):
    pass


HERE = Path(__file__).resolve().parent
EXPECTED_BASE = "0d34f3c1f71f110bf4e17b73c1772df300c5fe60"
EXPECTED_PROTOCOL_DIGEST = "sha256:4cd457c5f40bdf3ae871cbe56ba7c151f7ac3242bd73129557f25cf620a2d0bc"
EXPECTED_D0_CANDIDATE_DIGEST = "sha256:771c09a760940afa8c04a26a79e3e921c11d87d96ae949c1781f4fd7c846074b"
EXPECTED_D0_SEMANTIC_DIGEST = "sha256:fc3c68828f87cfecb2f12bbcb18188cc16f6c386993f7b2e15406c84e47baa77"
EXPECTED_EXECUTOR_DIGEST = "sha256:66f45942bfe28d52860cb4a673bab39aa893e53952f942811ab94a41b5a4e8e5"
EXPECTED_QUERY_PROFILE_DIGEST = "sha256:f8dbcf6195712fdac4acfa5ff5bbc2eb8694f8c1f6436e6c400758cfa5888853"
EXPECTED_LONGHORN_CLOSURE_DIGEST = "sha256:8c11c9bf42d25f96817c43f3e4e0b11b3ed24f15e81f163038b41d29167ae634"
REQUIRED_TRUE = {"readOnlyAuthorized", "credentialUseAuthorized", "secretMetadataReadAuthorized"}
REQUIRED_FALSE = {
    "mutationAuthorized", "deleteAuthorized", "cleanupAuthorized", "retryAuthorized",
    "rollbackAuthorized", "outageAuthorized", "failureInjectionAuthorized", "publicationAuthorized",
}


def sha256_bytes(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def file_digest(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_digest(value: object) -> str:
    return sha256_bytes(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def read_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text())
    if not isinstance(value, dict):
        raise CandidateError(f"{path}: expected one YAML object")
    return value


def verify_candidate(path: Path) -> dict[str, Any]:
    candidate = read_yaml(path)
    spec = candidate.get("spec", {})
    errors: list[str] = []

    if spec.get("version") != "ok141-delete-d0-live-grant-candidate/v3":
        errors.append("version mismatch")
    if spec.get("state") != "READY-FOR-EXPLICIT-D0-V3-LIVE-READ-GRANT":
        errors.append("state mismatch")
    if spec.get("baseCommit") != EXPECTED_BASE:
        errors.append("base commit mismatch")

    bindings = spec.get("bindings", {})
    d0_candidate = (HERE / bindings.get("d0CandidatePath", "")).resolve()
    executor = (HERE / bindings.get("executorPath", "")).resolve()
    if bindings.get("protocolSemanticDigest") != EXPECTED_PROTOCOL_DIGEST:
        errors.append("protocol semantic digest mismatch")
    if bindings.get("d0CandidateFileDigest") != EXPECTED_D0_CANDIDATE_DIGEST:
        errors.append("declared D0 candidate digest mismatch")
    elif not d0_candidate.is_file() or file_digest(d0_candidate) != EXPECTED_D0_CANDIDATE_DIGEST:
        errors.append("D0 candidate content mismatch")
    if bindings.get("d0CandidateSemanticDigest") != EXPECTED_D0_SEMANTIC_DIGEST:
        errors.append("D0 semantic digest mismatch")
    elif d0_candidate.is_file() and canonical_digest(read_yaml(d0_candidate)) != EXPECTED_D0_SEMANTIC_DIGEST:
        errors.append("D0 candidate semantic content mismatch")
    if bindings.get("executorDigest") != EXPECTED_EXECUTOR_DIGEST:
        errors.append("declared executor digest mismatch")
    elif not executor.is_file() or file_digest(executor) != EXPECTED_EXECUTOR_DIGEST:
        errors.append("executor content mismatch")
    if bindings.get("queryProfileDigest") != EXPECTED_QUERY_PROFILE_DIGEST:
        errors.append("query profile mismatch")
    if bindings.get("longhornClosureDigest") != EXPECTED_LONGHORN_CLOSURE_DIGEST:
        errors.append("Longhorn closure mismatch")

    scope = spec.get("scope", {})
    if scope.get("planes") != ["ok-shared", "ok-mgmt", "ok-infra", "workload"]:
        errors.append("plane order mismatch")
    if scope.get("sealedGetCount") != 36:
        errors.append("sealed GET count mismatch")
    if any(scope.get(key) is not False for key in (
        "discoveryAllowed", "listOutsideBoundQueriesAllowed", "watchAllowed", "mutationAllowed"
    )):
        errors.append("scope permits forbidden behavior")

    outputs = spec.get("privateOutputs", {})
    if outputs.get("bindingPath") != "/private/tmp/ok141-delete-d0-runtime-binding-v3.json":
        errors.append("binding path mismatch")
    if outputs.get("evidencePath") != "/private/tmp/ok141-delete-d0-evidence-v3.json":
        errors.append("evidence path mismatch")
    if outputs.get("mustBeAbsentBeforeRun") is not True or outputs.get("mode") != "0600":
        errors.append("private output boundary mismatch")
    if outputs.get("maximumBindingAgeMinutes") != 10 or outputs.get("publishable") is not False:
        errors.append("binding lifetime or publication boundary mismatch")

    grant = spec.get("requiredGrant", {})
    if grant.get("kind") != "OK141DeleteD0BindingGrant" or grant.get("state") != "GRANTED":
        errors.append("required grant identity mismatch")
    if grant.get("grantIDBoundAtGrantTime") is not True or grant.get("windowBoundAtGrantTime") is not True:
        errors.append("grant is not just-in-time bound")
    if grant.get("maximumWindowMinutes") != 20 or grant.get("maximumRuns") != 1 or grant.get("consumed") is not False:
        errors.append("grant freshness boundary mismatch")
    if set(grant.get("requiredTrue", [])) != REQUIRED_TRUE:
        errors.append("required true authority set mismatch")
    if set(grant.get("requiredFalse", [])) != REQUIRED_FALSE:
        errors.append("required false authority set mismatch")
    if any(key in grant for key in ("notBefore", "notAfter", "grantID")):
        errors.append("candidate contains live grant values")

    auth = spec.get("authorization", {})
    if auth.get("decision") != "NO-GO":
        errors.append("candidate authorization is not NO-GO")
    if any(value is not False for key, value in auth.items() if key.endswith("Granted")):
        errors.append("candidate grants authority")

    if errors:
        raise CandidateError("; ".join(errors))
    return candidate


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify",))
    parser.add_argument("--candidate", type=Path, required=True)
    args = parser.parse_args()
    candidate = verify_candidate(args.candidate.resolve())
    print(json.dumps({
        "candidateDigest": file_digest(args.candidate.resolve()),
        "semanticDigest": canonical_digest(candidate),
        "state": "PASS-D0-V3-LIVE-GRANT-CANDIDATE-OFFLINE-NO-GO",
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
