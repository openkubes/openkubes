#!/usr/bin/env python3
"""D1 preflight v2 with normalized authoritative Application semantics."""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import importlib.util
import json
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
V1_PATH = (HERE / "../delete-test-d1-preflight-v1/prepare_delete_d1_preflight_v1.py").resolve()
HARNESS_PATH = (HERE / "../harness/ok141_harness.py").resolve()

def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

V1 = load_module("ok141_delete_d1_v1", V1_PATH)
HARNESS = load_module("ok141_harness", HARNESS_PATH)
PreflightError = V1.PreflightError
file_digest = V1.file_digest
canonical_digest = V1.canonical_digest
read_yaml = V1.read_yaml
read_json = V1.read_json
write_exclusive = V1.write_exclusive
parse_time = V1.parse_time

EXPECTED_BASE = "9482ed60fd537feb4017fb5741671ed91d55787b"
EXPECTED_V1_CANDIDATE = "sha256:b654def485a39594424e8bc6c10d74bb7f5f7a14b3ecae1052617d6d9d6a6de5"
EXPECTED_V1_EXECUTOR = "sha256:05efc4724fe710e5e23b9d1fa857c2fb924151d92be779fcb36dcd31da1be1e0"
EXPECTED_STOPPED = "sha256:153cb08e3ef45ddba17aea2c59913f1b60fc38f322ab58b834a906319a79cb40"
EXPECTED_PROFILE = "sha256:5570d309696d0ba6541a998e6eee82880159ec13c4d933ef2c570a179d5fdfa1"
EXPECTED_APPLICATIONS = "sha256:5ab84ce73198b95e3ebd0947ce2ca896b40eb5e7b91a13bdf827bf0e7421a1ea"
EXPECTED_KUBECTL = V1.EXPECTED_KUBECTL
EXPECTED_DIGESTS = {
    "disposable-ok141-observability-core": "sha256:e48724fdfb54db0b4fe6942fc4eb15e97e63c0ac987c9a70781222d35a4cd8c5",
    "disposable-ok141-observability-alerting": "sha256:45d34b49ea65fdb2576ea5de6d34681048d88d17aef95ddf2190208bbdbdf98c",
    "disposable-ok141-observability-dashboards": "sha256:9b27a1106631f0fe40d444b7227e0065910bc6c4cb963e1279afc5b923e3807e",
}


def bound_v1_candidate(candidate_path: Path, candidate: dict[str, Any]) -> tuple[dict[str, Any], Path]:
    bindings = candidate["spec"]["bindings"]
    path = (candidate_path.parent / bindings["v1CandidatePath"]).resolve()
    return read_yaml(path), path


def verify_candidate(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    candidate = read_yaml(path)
    spec = candidate.get("spec", {})
    errors: list[str] = []
    if spec.get("version") != "ok141-delete-d1-preflight/v2" or spec.get("state") != "READY-FOR-EXPLICIT-READ-ONLY-GRANT":
        errors.append("candidate identity mismatch")
    if spec.get("baseCommit") != EXPECTED_BASE:
        errors.append("base commit mismatch")
    bindings = spec.get("bindings", {})
    v1_candidate_path = (path.parent / bindings.get("v1CandidatePath", "")).resolve()
    v1_executor_path = (path.parent / bindings.get("v1ExecutorPath", "")).resolve()
    stopped_path = (path.parent / bindings.get("stoppedEvidencePath", "")).resolve()
    profile_path = (path.parent / bindings.get("platformProfilePath", "")).resolve()
    applications_path = (path.parent / bindings.get("platformApplicationsPath", "")).resolve()
    checks = (
        (v1_candidate_path, bindings.get("v1CandidateDigest"), EXPECTED_V1_CANDIDATE, "v1 candidate"),
        (v1_executor_path, bindings.get("v1ExecutorDigest"), EXPECTED_V1_EXECUTOR, "v1 executor"),
        (stopped_path, bindings.get("stoppedEvidenceDigest"), EXPECTED_STOPPED, "stopped evidence"),
        (profile_path, bindings.get("platformProfileDigest"), EXPECTED_PROFILE, "platform profile"),
        (applications_path, bindings.get("platformApplicationsDigest"), EXPECTED_APPLICATIONS, "platform Applications"),
    )
    for target, declared, expected, label in checks:
        if declared != expected or not target.is_file() or file_digest(target) != expected:
            errors.append(f"{label} binding mismatch")
    normalization = spec.get("normalization", {})
    if normalization.get("profile") != "argocd-application-c14n/v1" or normalization.get("defaults") != {"spec.source.directory.recurse": False}:
        errors.append("normalization profile mismatch")
    if normalization.get("expectedApplicationDigests") != EXPECTED_DIGESTS:
        errors.append("Application digest set mismatch")
    assertions = spec.get("assertions", {})
    required_true = (
        "applicationUIDMustEqualD0", "applicationResourceVersionMayAdvance",
        "applicationGenerationMayAdvance", "normalizedApplicationDigestMustMatchProfile",
        "appProjectMetadataMustEqualD0", "registrationSecretMetadataMustEqualD0",
        "allV1TargetCorrelationAssertionsRetained",
    )
    if any(assertions.get(key) is not True for key in required_true):
        errors.append("assertion boundary mismatch")
    tool = spec.get("tool", {})
    if tool.get("executorDigest") != file_digest(Path(__file__).resolve()) or tool.get("kubectlDigest") != EXPECTED_KUBECTL:
        errors.append("tool binding mismatch")
    outputs = spec.get("privateOutputs", {})
    if outputs.get("bindingPath") != "/private/tmp/ok141-delete-d1-runtime-binding-v2.json" or outputs.get("evidencePath") != "/private/tmp/ok141-delete-d1-preflight-evidence-v2.json":
        errors.append("private output path mismatch")
    if outputs.get("mode") != "0600" or outputs.get("maximumBindingAgeMinutes") != 5:
        errors.append("private output boundary mismatch")
    auth = spec.get("authorization", {})
    if auth.get("decision") != "NO-GO" or any(value is not False for key, value in auth.items() if key.endswith("Granted")):
        errors.append("candidate grants authority")
    if errors:
        raise PreflightError("; ".join(errors))
    v1_candidate = V1.verify_candidate(v1_candidate_path)
    return candidate, v1_candidate


def normalize_application(application: dict[str, Any]) -> dict[str, Any]:
    projected = {
        "apiVersion": application.get("apiVersion"),
        "kind": application.get("kind"),
        "metadata": {
            "name": application.get("metadata", {}).get("name"),
            "namespace": application.get("metadata", {}).get("namespace"),
        },
        "spec": copy.deepcopy(application.get("spec", {})),
    }
    directory = projected["spec"].get("source", {}).get("directory")
    if isinstance(directory, dict) and "recurse" not in directory:
        directory["recurse"] = False
    return projected


def normalized_digest(application: dict[str, Any]) -> str:
    return HARNESS.semantic_revision(normalize_application(application))


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
    if d0.get("format") != "ok141-delete-d0-runtime-binding/v3" or d0.get("candidateDigest") != V1.EXPECTED_D0_CANDIDATE:
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
    d0_shared = d0["planes"]["ok-shared"]
    applications = [live[query_id] for query_id in V1.APP_IDS]
    project_items = [item for item in live["project-applications"].get("items", []) if item.get("spec", {}).get("project") == "openkubes-disposable"]
    if len(project_items) != 3 or {item.get("metadata", {}).get("name") for item in project_items} != set(V1.APP_NAMES.values()):
        raise PreflightError("project Application membership mismatch")
    secret = live["registration-secret"]
    if secret.get("metadata", {}).get("labels", {}).get("argocd.argoproj.io/secret-type") != "cluster":
        raise PreflightError("registration Secret type mismatch")
    server, registration_name = V1.decode_field(secret, "server"), V1.decode_field(secret, "name")
    if not server or not registration_name:
        raise PreflightError("registration identity empty")
    target_digest = canonical_digest({"server": server, "name": registration_name})

    records = []
    semantics = {}
    for query_id, application in zip(V1.APP_IDS, applications, strict=True):
        spec = application.get("spec", {})
        status = application.get("status", {})
        if spec.get("project") != "openkubes-disposable" or status.get("sync", {}).get("status") != "Synced" or status.get("health", {}).get("status") != "Healthy":
            raise PreflightError("Application baseline mismatch")
        destination = spec.get("destination", {})
        if destination.get("server"):
            if destination["server"] != server:
                raise PreflightError("Application server target mismatch")
        elif destination.get("name") != registration_name:
            raise PreflightError("Application named target mismatch")
        current = V1.metadata_identity(application)
        previous = d0_shared[query_id][0]
        if current["uid"] != previous.get("uid") or current["name"] != previous.get("name") or current["namespace"] != previous.get("namespace"):
            raise PreflightError("Application immutable identity differs from D0")
        digest = normalized_digest(application)
        if digest != EXPECTED_DIGESTS[current["name"]]:
            raise PreflightError("normalized Application semantics mismatch")
        semantics[current["name"]] = digest
        records.append({"queryID": query_id, **current})

    for query_id in ("app-project", "registration-secret"):
        current = V1.metadata_identity(live[query_id])
        previous = d0_shared[query_id][0]
        if any(current[key] != previous.get(key) for key in ("name", "namespace", "uid", "resourceVersion")):
            raise PreflightError(f"{query_id} differs from D0 binding")
        records.append({"queryID": query_id, **current})

    return {
        "format": "ok141-delete-d1-runtime-binding/v2",
        "state": "PASS-D1-PREFLIGHT-PRIVATE-BOUND-NO-GO",
        "candidateDigest": canonical_digest(candidate),
        "d0BindingDigest": canonical_digest(d0),
        "observedAt": now.isoformat(),
        "expiresAt": (now + dt.timedelta(minutes=5)).isoformat(),
        "normalizationProfile": "argocd-application-c14n/v1",
        "targetIdentityDigest": target_digest,
        "applicationSemanticDigests": semantics,
        "deleteOrder": records,
        "secretContentRetained": False,
        "endpointRetained": False,
        "mutationPerformed": False,
        "deletePerformed": False,
    }


def snapshot(candidate_path: Path, grant_path: Path, d0_path: Path, kubectl: Path) -> dict[str, Any]:
    candidate, v1_candidate, d0 = verify_grant(candidate_path, grant_path, d0_path)
    if file_digest(kubectl) != EXPECTED_KUBECTL:
        raise PreflightError("kubectl digest mismatch")
    kubeconfig = Path(v1_candidate["spec"]["queries"]["kubeconfigPath"])
    if kubeconfig.is_symlink() or not kubeconfig.is_file() or stat.S_IMODE(kubeconfig.stat().st_mode) != 0o600:
        raise PreflightError("unsafe kubeconfig")
    live = {query["id"]: V1.exact_get(kubectl, kubeconfig, query["rawURI"]) for query in v1_candidate["spec"]["queries"]["items"]}
    binding = build_binding(candidate, d0, live, dt.datetime.now(dt.timezone.utc))
    outputs = candidate["spec"]["privateOutputs"]
    binding_path = Path(outputs["bindingPath"])
    write_exclusive(binding_path, binding)
    evidence = {
        "format": "ok141-delete-d1-preflight-private-evidence/v2",
        "state": "PASS-D1-PREFLIGHT-PRIVATE-BOUND-NO-GO",
        "candidateDigest": file_digest(candidate_path),
        "grantID": read_yaml(grant_path)["spec"]["grantID"],
        "bindingDigest": file_digest(binding_path),
        "sealedGetCount": 6,
        "deleteTargetCount": 5,
        "normalizationProfile": "argocd-application-c14n/v1",
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
        print(json.dumps({"candidateDigest": file_digest(candidate_path), "semanticDigest": canonical_digest(candidate), "state": "PASS-D1-PREFLIGHT-V2-CANDIDATE-OFFLINE-NO-GO"}, sort_keys=True))
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
    except (PreflightError, OSError, ValueError, KeyError, json.JSONDecodeError, subprocess.TimeoutExpired) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
