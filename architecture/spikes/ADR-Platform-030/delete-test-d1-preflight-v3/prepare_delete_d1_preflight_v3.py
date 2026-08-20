#!/usr/bin/env python3
"""D1 preflight v3: bind records in exact delete-protocol order."""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import stat
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V2 = load_module("ok141_delete_d1_v2_for_v3", (HERE / "../delete-test-d1-preflight-v2/prepare_delete_d1_preflight_v2.py").resolve())
PreflightError = V2.PreflightError
file_digest = V2.file_digest
canonical_digest = V2.canonical_digest
read_yaml = V2.read_yaml
read_json = V2.read_json
write_exclusive = V2.write_exclusive
parse_time = V2.parse_time

EXPECTED_BASE = "47238217e187e07e7b21f5b7231790c969a9d2db"
EXPECTED_V2_CANDIDATE = "sha256:c5c78e4d82b689f645c63be3ccbb3a3c4c2f890b01d7004daad7915da6fa7276"
EXPECTED_V2_EXECUTOR = "sha256:08970c4761d7a4265b900fdb1e98433cd02a5deeb1248f6975795e445b8eae99"
EXPECTED_STOPPED = "sha256:a13be619262ab926550a992ac5535b7595fcdb1a05cc25510f22bed4f8776b44"
EXPECTED_PROTOCOL = "sha256:4cd457c5f40bdf3ae871cbe56ba7c151f7ac3242bd73129557f25cf620a2d0bc"
EXPECTED_KUBECTL = V2.EXPECTED_KUBECTL
EXPECTED_ORDER = (
    "application-dashboards", "application-alerting", "application-core",
    "registration-secret", "app-project",
)


def verify_candidate(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    candidate = read_yaml(path)
    spec = candidate.get("spec", {})
    errors: list[str] = []
    if spec.get("version") != "ok141-delete-d1-preflight/v3" or spec.get("state") != "READY-FOR-EXPLICIT-READ-ONLY-GRANT":
        errors.append("candidate identity mismatch")
    if spec.get("baseCommit") != EXPECTED_BASE:
        errors.append("base commit mismatch")
    bindings = spec.get("bindings", {})
    v2_candidate_path = (path.parent / bindings.get("v2CandidatePath", "")).resolve()
    v2_executor_path = (path.parent / bindings.get("v2ExecutorPath", "")).resolve()
    stopped_path = (path.parent / bindings.get("stoppedEvidencePath", "")).resolve()
    protocol_path = (path.parent / bindings.get("protocolPath", "")).resolve()
    checks = (
        (v2_candidate_path, bindings.get("v2CandidateDigest"), EXPECTED_V2_CANDIDATE, "v2 candidate", False),
        (v2_executor_path, bindings.get("v2ExecutorDigest"), EXPECTED_V2_EXECUTOR, "v2 executor", False),
        (stopped_path, bindings.get("stoppedEvidenceDigest"), EXPECTED_STOPPED, "stopped evidence", False),
        (protocol_path, bindings.get("protocolSemanticDigest"), EXPECTED_PROTOCOL, "protocol", True),
    )
    for target, declared, expected, label, semantic in checks:
        if not target.is_file():
            errors.append(f"{label} missing")
            continue
        actual = canonical_digest(read_yaml(target)) if semantic else file_digest(target)
        if declared != expected or actual != expected:
            errors.append(f"{label} binding mismatch")
    if tuple(spec.get("bindingOrder", [])) != EXPECTED_ORDER:
        errors.append("binding order mismatch")
    if spec.get("normalization") != {"profile": "argocd-application-c14n/v1", "defaults": {"spec.source.directory.recurse": False}}:
        errors.append("normalization mismatch")
    assertions = spec.get("assertions", {})
    if any(assertions.get(key) is not True for key in ("allV2SemanticAssertionsRetained", "bindingOrderMustEqualProtocol", "bindingRecordsMustMatchAsSet")):
        errors.append("assertion boundary mismatch")
    if assertions.get("oldV2DigestReinterpreted") is not False:
        errors.append("v2 reinterpretation boundary mismatch")
    outputs = spec.get("privateOutputs", {})
    if outputs != {
        "bindingPath": "/private/tmp/ok141-delete-d1-runtime-binding-v3.json",
        "evidencePath": "/private/tmp/ok141-delete-d1-preflight-evidence-v3.json",
        "mode": "0600", "maximumBindingAgeMinutes": 5,
    }:
        errors.append("private output mismatch")
    tool = spec.get("tool", {})
    if tool.get("executorDigest") != file_digest(Path(__file__).resolve()) or tool.get("kubectlDigest") != EXPECTED_KUBECTL:
        errors.append("tool binding mismatch")
    authorization = spec.get("authorization", {})
    if authorization.get("decision") != "NO-GO" or any(value is not False for key, value in authorization.items() if key.endswith("Granted")):
        errors.append("candidate grants authority")
    if errors:
        raise PreflightError("; ".join(errors))
    return candidate, V2.verify_candidate(v2_candidate_path)[1]


def verify_grant(candidate_path: Path, grant_path: Path, d0_path: Path, now: dt.datetime | None = None) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    candidate, v1_candidate = verify_candidate(candidate_path)
    grant = read_yaml(grant_path).get("spec", {})
    d0 = read_json(d0_path)
    errors: list[str] = []
    if grant.get("state") != "GRANTED" or grant.get("candidateDigest") != file_digest(candidate_path):
        errors.append("grant identity mismatch")
    if grant.get("d0BindingDigest") != file_digest(d0_path):
        errors.append("D0 runtime digest mismatch")
    if grant.get("maximumRuns") != 1 or grant.get("consumed") is not False:
        errors.append("grant is not fresh and single-use")
    for key in ("readOnlyAuthorized", "credentialUseAuthorized", "secretContentReadAuthorized"):
        if grant.get(key) is not True:
            errors.append(f"{key} is required")
    for key in ("mutationAuthorized", "deleteAuthorized", "cleanupAuthorized", "retryAuthorized", "rollbackAuthorized", "publicationAuthorized", "outageAuthorized", "failureInjectionAuthorized"):
        if grant.get(key) is not False:
            errors.append(f"{key} must be false")
    current = now or dt.datetime.now(dt.timezone.utc)
    start, end = parse_time(grant.get("notBefore", "")), parse_time(grant.get("notAfter", ""))
    if not start <= current <= end or (end - start).total_seconds() > 600:
        errors.append("grant window inactive or exceeds ten minutes")
    if d0.get("format") != "ok141-delete-d0-runtime-binding/v3" or d0.get("candidateDigest") != V2.V1.EXPECTED_D0_CANDIDATE:
        errors.append("D0 runtime identity mismatch")
    if current > parse_time(d0.get("expiresAt", "")):
        errors.append("D0 runtime binding expired")
    outputs = candidate["spec"]["privateOutputs"]
    if grant.get("bindingPath") != outputs["bindingPath"] or grant.get("evidencePath") != outputs["evidencePath"]:
        errors.append("grant output paths differ")
    if errors:
        raise PreflightError("; ".join(errors))
    return candidate, v1_candidate, d0


def build_binding(candidate: dict[str, Any], d0: dict[str, Any], live: dict[str, Any], now: dt.datetime) -> dict[str, Any]:
    binding = V2.build_binding(candidate, d0, live, now)
    records = {record["queryID"]: record for record in binding["deleteOrder"]}
    if set(records) != set(EXPECTED_ORDER):
        raise PreflightError("binding record membership mismatch")
    binding["format"] = "ok141-delete-d1-runtime-binding/v3"
    binding["candidateDigest"] = canonical_digest(candidate)
    binding["deleteOrder"] = [records[query_id] for query_id in EXPECTED_ORDER]
    binding["bindingOrderProfile"] = "ok141-delete-d1-order/v1"
    return binding


def snapshot(candidate_path: Path, grant_path: Path, d0_path: Path, kubectl: Path) -> dict[str, Any]:
    candidate, v1_candidate, d0 = verify_grant(candidate_path, grant_path, d0_path)
    if file_digest(kubectl) != EXPECTED_KUBECTL:
        raise PreflightError("kubectl digest mismatch")
    kubeconfig = Path(v1_candidate["spec"]["queries"]["kubeconfigPath"])
    if kubeconfig.is_symlink() or not kubeconfig.is_file() or stat.S_IMODE(kubeconfig.stat().st_mode) != 0o600:
        raise PreflightError("unsafe kubeconfig")
    live = {query["id"]: V2.V1.exact_get(kubectl, kubeconfig, query["rawURI"]) for query in v1_candidate["spec"]["queries"]["items"]}
    binding = build_binding(candidate, d0, live, dt.datetime.now(dt.timezone.utc))
    outputs = candidate["spec"]["privateOutputs"]
    binding_path = Path(outputs["bindingPath"])
    write_exclusive(binding_path, binding)
    evidence = {
        "format": "ok141-delete-d1-preflight-private-evidence/v3",
        "state": "PASS-D1-PREFLIGHT-PRIVATE-BOUND-NO-GO",
        "candidateDigest": file_digest(candidate_path),
        "grantID": read_yaml(grant_path)["spec"]["grantID"],
        "bindingDigest": file_digest(binding_path),
        "sealedGetCount": 6,
        "deleteTargetCount": 5,
        "bindingOrderProfile": "ok141-delete-d1-order/v1",
        "protocolOrderMatched": True,
        "semanticMatchCount": 3,
        "targetCorrelationPassed": True,
        "secretContentRetained": False,
        "endpointRetained": False,
        "mutationPerformed": False,
        "deletePerformed": False,
    }
    write_exclusive(Path(outputs["evidencePath"]), evidence)
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "verify-grant", "snapshot"))
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--grant", type=Path)
    parser.add_argument("--d0-binding", type=Path)
    parser.add_argument("--kubectl", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    candidate_path = args.candidate.resolve()
    if args.command == "verify":
        candidate, _ = verify_candidate(candidate_path)
        print(json.dumps({"candidateDigest": file_digest(candidate_path), "semanticDigest": canonical_digest(candidate), "state": "PASS-D1-PREFLIGHT-V3-CANDIDATE-OFFLINE-NO-GO"}, sort_keys=True))
    elif args.command == "verify-grant":
        if args.grant is None or args.d0_binding is None:
            raise PreflightError("grant and D0 binding are required")
        verify_grant(candidate_path, args.grant.resolve(), args.d0_binding.resolve())
        print(file_digest(args.grant.resolve()))
    else:
        if not args.execute or args.grant is None or args.d0_binding is None or args.kubectl is None:
            raise PreflightError("snapshot requires --execute, grant, D0 binding and kubectl")
        print(json.dumps(snapshot(candidate_path, args.grant.resolve(), args.d0_binding.resolve(), args.kubectl.resolve()), sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (PreflightError, OSError, ValueError, KeyError, json.JSONDecodeError):
        raise
