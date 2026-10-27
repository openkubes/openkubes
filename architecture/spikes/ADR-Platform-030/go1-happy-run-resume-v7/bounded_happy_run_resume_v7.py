#!/usr/bin/env python3
"""Resume the OK-141 Happy Run strictly after the private Runtime Binding."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

import yaml


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
CANDIDATE = HERE / "happy-run-resume-candidate-v7.yaml"
RUNTIME_BINDING = Path("/private/tmp/ok141-go1-runtime-binding-v2.json")
HAPPY_TOOL = SPIKE / "go1-happy-run-v1" / "bounded_happy_run_v1.py"
HAPPY_CANDIDATE = SPIKE / "go1-happy-run-v1" / "happy-run-candidate-v1.yaml"
RUNTIME_RESUME_CANDIDATE = SPIKE / "go1-runtime-binding-resume-v1" / "runtime-binding-resume-candidate-v1.yaml"
PROJECTION_CANDIDATE = SPIKE / "go1-platform-projection-v1" / "platform-projection-candidate-v1.yaml"
PLATFORM_CANDIDATE = SPIKE / "go1-platform-observer-v1" / "platform-observer-candidate-v1.yaml"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(value)
    return value


HAPPY = load_module("ok141_happy_for_runtime_bound_resume", HAPPY_TOOL)
PROJECTION = HAPPY.PROJECTION
PLATFORM = HAPPY.PLATFORM


class ResumeV7Error(ValueError):
    pass


def sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text())
    if not isinstance(value, dict):
        raise ResumeV7Error(f"expected mapping: {path}")
    return value


def expect(actual: Any, expected: Any, context: str) -> None:
    if actual != expected:
        raise ResumeV7Error(f"{context}: expected {expected!r}, got {actual!r}")


def parse_time(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ResumeV7Error("timestamp lacks timezone")
    return parsed.astimezone(dt.timezone.utc)


def safe_private(path: Path, expected_digest: str, context: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or (path.stat().st_mode & 0o777) != 0o600:
        raise ResumeV7Error(f"unsafe {context}")
    expect(sha(path), expected_digest, f"{context} digest")
    return read(path)


def validate_candidate(path: Path = CANDIDATE) -> dict[str, Any]:
    value = read(path)
    expect(value.get("kind"), "GO1HappyRunResumeCandidateV7", "kind")
    spec = value["spec"]
    expect((spec["version"], spec["state"]), ("ok141-go1-happy-run-resume/v7", "OFFLINE-PROVEN-BLOCKED-NO-GO"), "candidate state")
    bound = spec["predecessors"]
    for key, expected_path in (
        ("happyRunCandidate", HAPPY_CANDIDATE),
        ("runtimeBindingResumeCandidate", RUNTIME_RESUME_CANDIDATE),
        ("platformProjectionCandidate", PROJECTION_CANDIDATE),
        ("platformObserverCandidate", PLATFORM_CANDIDATE),
    ):
        expect(sha(expected_path), bound[key]["digest"], f"{key} digest")
    HAPPY.validate_candidate(HAPPY_CANDIDATE)
    projection = PROJECTION.validate_candidate(PROJECTION_CANDIDATE)
    platform = PLATFORM.validate_candidate(PLATFORM_CANDIDATE)
    expect(projection["spec"]["fixture"], platform["spec"]["fixture"], "projection/observer fixture")
    expect(spec["privateRuntimeBinding"]["path"], str(RUNTIME_BINDING), "Runtime Binding path")
    expect(spec["resumeBoundary"]["earlierStagesReexecutionAllowed"], False, "earlier-stage boundary")
    expect(spec["sequence"], ["ABSENCE-PREFLIGHT", "TARGET-ACCESS", "PLATFORM-CREDENTIALS", "TOKEN-REGISTRATION", "APPLICATIONS", "PLATFORM-READY"], "sequence")
    expect(len(spec["absencePreflight"]["workload"]), 9, "workload preflight count")
    expect(len(spec["absencePreflight"]["shared"]), 5, "shared preflight count")
    if len(set(spec["absencePreflight"]["workload"] + spec["absencePreflight"]["shared"])) != 14:
        raise ResumeV7Error("absence preflight identities are not unique")
    expect(sha(Path(spec["capabilityScript"])), spec["capabilityScriptDigest"], "capability script")
    expect(sha(HERE / spec["tool"]["path"]), spec["tool"]["digest"], "tool digest")
    expect(spec["authorization"]["decision"], "NO-GO", "authorization")
    if any(item for key, item in spec["authorization"].items() if key.endswith("Granted")):
        raise ResumeV7Error("candidate grants authority")
    return value


TRUE = (
    "credentialUseGranted", "runtimeBindingReuseGranted", "exactAbsencePreflightGranted",
    "targetAccessGranted", "tokenRequestGranted", "registrationGranted",
    "credentialSecretGranted", "applicationSubmissionGranted", "platformObserverGranted",
    "capabilityTestGranted", "capabilityTestCleanupGranted", "happyRunResumeGranted", "go1Granted",
)
FALSE = (
    "earlierStageReexecutionGranted", "retryGranted", "rollbackOrBroadCleanupGranted",
    "evidencePublicationGranted", "outageGranted", "failureInjectionGranted",
)


def validate_runtime_binding(candidate: dict[str, Any], grant_spec: dict[str, Any]) -> dict[str, Any]:
    expect(Path(grant_spec["runtimeBindingPath"]), RUNTIME_BINDING, "Runtime Binding grant path")
    binding = safe_private(RUNTIME_BINDING, grant_spec["runtimeBindingDigest"], "Runtime Binding")
    spec = binding.get("spec", {})
    expect((binding.get("kind"), spec.get("state")), ("GO1RuntimeBinding", candidate["spec"]["privateRuntimeBinding"]["requiredState"]), "Runtime Binding state")
    projection_fixture = PROJECTION.validate_candidate(PROJECTION_CANDIDATE)["spec"]["fixture"]
    for key in ("fixtureDigest", "R", "E", "P"):
        expect(spec.get(key), projection_fixture[key], f"Runtime Binding {key}")
    expect(spec.get("semanticDigest"), grant_spec["runtimeBindingSemanticDigest"], "Runtime Binding semantic digest")
    expect(spec.get("evidence", {}).get("NetworkReady"), True, "Runtime Binding NetworkReady")
    expect(spec.get("evidence", {}).get("localPathProvisioner"), "rancher.io/local-path", "Runtime Binding storage")
    expect(spec.get("authorization"), {"registrationGranted": False, "platformSubmissionGranted": False, "go1Granted": False}, "Runtime Binding authority")
    return binding


def validate_grant(candidate_path: Path, grant_path: Path, now: dt.datetime | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    candidate = validate_candidate(candidate_path)
    grant = read(grant_path)
    expect(grant.get("kind"), "GO1HappyRunResumeGrantV7", "grant kind")
    spec = grant["spec"]
    expect((spec.get("decision"), spec.get("authority"), spec.get("singleRun"), spec.get("consumed")), ("GO", "github:arashkaffamanesh", True, False), "grant identity")
    expect(spec.get("candidateDigest"), sha(candidate_path), "candidate digest")
    if any(spec.get(key) is not True for key in TRUE) or any(spec.get(key) is not False for key in FALSE):
        raise ResumeV7Error("grant authority is incomplete or overbroad")
    if not spec.get("grantID") or not spec.get("runID", "").startswith("ok141-happy-resume-runtime-bound-"):
        raise ResumeV7Error("grant is not an exact named run")
    current = now or dt.datetime.now(dt.timezone.utc)
    issued, expires = parse_time(spec["issuedAt"]), parse_time(spec["expiresAt"])
    if not issued <= current <= expires or expires - issued > dt.timedelta(hours=2):
        raise ResumeV7Error("grant inactive or exceeds two hours")
    return grant, validate_runtime_binding(candidate, spec)


def raw_get_absent(client: Path, kubeconfig: Path, uri: str, runner: Callable[..., Any] = subprocess.run) -> dict[str, Any]:
    completed = runner([str(client), "--kubeconfig", str(kubeconfig), "get", "--raw", uri], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if completed.returncode == 0:
        raise ResumeV7Error(f"preflight object already exists: {uri}")
    stdout = completed.stdout.decode(errors="replace")
    stderr = completed.stderr.decode(errors="replace")
    reason = ""
    try:
        value = json.loads(stdout)
        reason = value.get("reason", "") if isinstance(value, dict) else ""
    except json.JSONDecodeError:
        pass
    if reason != "NotFound" and "NotFound" not in stderr and "not found" not in stderr.lower():
        raise ResumeV7Error(f"preflight did not prove NotFound: {uri}")
    return {"uri": uri, "state": "ABSENT", "responseDigest": HAPPY.sha_bytes(completed.stdout + completed.stderr)}


def registration_secret(binding: dict[str, Any], fixture: dict[str, str], token: str, expiration: str) -> dict[str, Any]:
    target = binding["spec"]["target"]
    return {
        "apiVersion": "v1", "kind": "Secret",
        "metadata": {
            "name": "disposable-ok141-cluster", "namespace": "argocd",
            "labels": {"argocd.argoproj.io/secret-type": "cluster"},
            "annotations": {
                "openkubes.io/intent-revision": fixture["R"],
                "openkubes.io/platform-revision": fixture["P"],
                "openkubes.io/execution-fixture": fixture["fixtureDigest"],
                "openkubes.io/capi-cluster-uid": target["capiClusterUID"],
                "openkubes.io/workload-kube-system-uid": target["workloadKubeSystemUID"],
                "openkubes.io/workload-api-ca-sha256": target["workloadAPICAFingerprint"],
                "openkubes.io/token-expiration": expiration,
            },
        },
        "type": "Opaque",
        "stringData": {
            "name": "disposable-ok141", "server": target["workloadAPIServer"],
            "namespaces": "ok-observability,kube-system", "clusterResources": "true",
            "project": "openkubes-disposable",
            "config": json.dumps({"bearerToken": token, "tlsClientConfig": {"insecure": False, "caData": target["caData"]}}, sort_keys=True, separators=(",", ":")),
        },
    }


def validate_admin_tools() -> dict[str, Any]:
    observer = PLATFORM.validate_candidate(PLATFORM_CANDIDATE)["spec"]
    for client, expected in ((HAPPY.MGMT_CLIENT, observer["argo"]["clientDigest"]), (HAPPY.WORKLOAD_CLIENT, observer["workload"]["clientDigest"])):
        expect(sha(client), expected, "kubectl digest")
    for kubeconfig, expected in ((Path(observer["argo"]["credentialPath"]), observer["argo"]["credentialIdentityDigest"]), (Path(observer["management"]["credentialPath"]), observer["management"]["credentialIdentityDigest"])):
        if kubeconfig.is_symlink() or not kubeconfig.is_file() or (kubeconfig.stat().st_mode & 0o777) != 0o600:
            raise ResumeV7Error("unsafe administrator kubeconfig")
        expect(PLATFORM.EXECUTOR.inspect_identity(kubeconfig)["identityDigest"], expected, "administrator identity")
    return observer


def validate_workload_identity(binding: dict[str, Any], workload_kubeconfig: Path) -> None:
    identity = PLATFORM.EXECUTOR.inspect_identity(workload_kubeconfig)
    expect(identity["server"], binding["spec"]["target"]["workloadAPIServer"], "workload server")
    expect(identity["caFingerprint"], binding["spec"]["target"]["workloadAPICAFingerprint"], "workload CA")


def execute(candidate_path: Path, grant_path: Path, capability_script: Path) -> dict[str, Any]:
    candidate = validate_candidate(candidate_path)
    grant, binding = validate_grant(candidate_path, grant_path)
    spec, grant_spec = candidate["spec"], grant["spec"]
    observer_spec = validate_admin_tools()
    observer_output = Path(observer_spec["outputPath"])
    if observer_output.exists() or observer_output.is_symlink():
        raise ResumeV7Error("exclusive Platform observer output already exists")
    if sha(capability_script) != spec["capabilityScriptDigest"]:
        raise ResumeV7Error("capability script identity mismatch")
    run_dir = Path(spec["runtimeDirectory"]) / grant_spec["runID"]
    run_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    os.chmod(run_dir, 0o700)
    HAPPY.write_exclusive(run_dir / "outer-grant-consumption.json", {
        "grantID": grant_spec["grantID"], "candidateDigest": sha(candidate_path),
        "runtimeBindingDigest": sha(RUNTIME_BINDING), "consumedAt": HAPPY.iso(dt.datetime.now(dt.timezone.utc)),
        "state": "CONSUMED-BEFORE-FIRST-CLUSTER-CONTACT",
    })
    workload_kubeconfig = HAPPY.ephemeral_workload_kubeconfig(run_dir)
    platform_credentials = run_dir / "platform-credentials.json"
    token = ""
    try:
        validate_workload_identity(binding, workload_kubeconfig)
        shared_kubeconfig = Path(observer_spec["argo"]["credentialPath"])
        absent = [raw_get_absent(HAPPY.WORKLOAD_CLIENT, workload_kubeconfig, uri) for uri in spec["absencePreflight"]["workload"]]
        absent += [raw_get_absent(HAPPY.MGMT_CLIENT, shared_kubeconfig, uri) for uri in spec["absencePreflight"]["shared"]]
        HAPPY.write_exclusive(run_dir / "absence-preflight-evidence.json", {"state": "PASS-14-ABSENT", "objects": absent})

        values = PROJECTION.generate_credentials(PROJECTION_CANDIDATE)
        HAPPY.write_exclusive(platform_credentials, values)
        target_result = HAPPY.create_documents(HAPPY.WORKLOAD_CLIENT, workload_kubeconfig, PROJECTION.target_access(PROJECTION_CANDIDATE))
        target_evidence = run_dir / "target-access-evidence.json"
        HAPPY.write_exclusive(target_evidence, {"state": "TARGET-ACCESS-CREATED", **target_result})
        credential_result = HAPPY.create_documents(HAPPY.WORKLOAD_CLIENT, workload_kubeconfig, [PROJECTION.credential_secret(PROJECTION_CANDIDATE, values)])
        credential_evidence = run_dir / "platform-credential-evidence.json"
        HAPPY.write_exclusive(credential_evidence, {"state": "PLATFORM-CREDENTIAL-SECRET-CREATED", **credential_result, "credentialBytesRetainedInEvidence": False})

        request = {"apiVersion": "authentication.k8s.io/v1", "kind": "TokenRequest", "spec": {"audiences": [binding["spec"]["target"]["tokenAudience"]], "expirationSeconds": 10800}}
        completed = subprocess.run([str(HAPPY.WORKLOAD_CLIENT), "--kubeconfig", str(workload_kubeconfig), "create", "--raw", "/api/v1/namespaces/kube-system/serviceaccounts/ok141-argocd-manager/token", "-f", "-"], input=json.dumps(request, sort_keys=True, separators=(",", ":")).encode(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        if completed.returncode != 0:
            raise ResumeV7Error("bounded TokenRequest failed; output suppressed")
        response = json.loads(completed.stdout)
        token, expiration = response["status"]["token"], response["status"]["expirationTimestamp"]

        control = PROJECTION.control_plane(PROJECTION_CANDIDATE)
        project, applications = control[0], control[1:]
        fixture = PROJECTION.validate_candidate(PROJECTION_CANDIDATE)["spec"]["fixture"]
        registration = registration_secret(binding, fixture, token, expiration)
        registration_result = HAPPY.create_documents(HAPPY.MGMT_CLIENT, shared_kubeconfig, [project, registration])
        token = ""
        registration_evidence = run_dir / "registration-evidence.json"
        HAPPY.write_exclusive(registration_evidence, {"state": "REGISTRATION-CREATED", **registration_result, "tokenExpiration": expiration, "credentialBytesRetained": False})
        application_result = HAPPY.create_documents(HAPPY.MGMT_CLIENT, shared_kubeconfig, applications)
        application_evidence = run_dir / "application-submission-evidence.json"
        HAPPY.write_exclusive(application_evidence, {"state": "APPLICATIONS-SUBMITTED", **application_result})

        current = dt.datetime.now(dt.timezone.utc)
        base = HAPPY.inner_base(grant, sha(PLATFORM_CANDIDATE), current, 80)
        platform_grant = {
            "apiVersion": "authorization.openkubes.io/v1alpha1", "kind": "GO1PlatformObserverGrant",
            "spec": {
                **base, "grantID": grant_spec["grantID"] + "/PLATFORM",
                "runtimeBindingDigest": sha(RUNTIME_BINDING),
                "registrationEvidenceDigest": sha(registration_evidence),
                "credentialMaterializationEvidenceDigest": sha(credential_evidence),
                "applicationSubmissionEvidenceDigest": sha(application_evidence),
                "credentialFileDigest": sha(platform_credentials),
                "clusterContactGranted": True, "credentialUseGranted": True, "secretReadGranted": True,
                "argoObservationGranted": True, "capabilityTestGranted": True, "capabilityTestCleanupGranted": True,
                "arbitraryMutationGranted": False, "applicationSubmissionGranted": False,
                "retryGranted": False, "go1Granted": False, "failureInjectionGranted": False,
            },
        }
        platform_grant_path = HAPPY.grant_file(run_dir, "platform", platform_grant)
        platform = PLATFORM.execute(PLATFORM_CANDIDATE, platform_grant_path, RUNTIME_BINDING, registration_evidence, credential_evidence, application_evidence, platform_credentials, capability_script, HAPPY.MGMT_CLIENT, HAPPY.MGMT_CLIENT, HAPPY.WORKLOAD_CLIENT)
        result = {
            "state": "PASS-HAPPY-RUN", "runID": grant_spec["runID"], "candidateDigest": sha(candidate_path),
            "fixtureDigest": fixture["fixtureDigest"], "NetworkReady": True, "PlatformReady": platform["PlatformReady"],
            "runtimeBindingReused": True, "earlierStagesReexecuted": False,
            "retryPerformed": False, "rollbackPerformed": False, "failureInjectionPerformed": False,
        }
        final_path = run_dir / "happy-run-result.json"
        HAPPY.write_exclusive(final_path, result)
        return {**result, "evidencePath": str(final_path), "evidenceDigest": sha(final_path)}
    except Exception:
        platform_credentials.unlink(missing_ok=True)
        raise
    finally:
        token = ""
        workload_kubeconfig.unlink(missing_ok=True)


def plan(path: Path = CANDIDATE) -> dict[str, Any]:
    candidate = validate_candidate(path)
    return {
        "candidateDigest": sha(path), "sequence": candidate["spec"]["sequence"],
        "runtimeBindingPath": candidate["spec"]["privateRuntimeBinding"]["path"],
        "authorization": "NO-GO", "clusterContacted": False, "mutationPerformed": False,
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
                raise ResumeV7Error("grant required")
            validate_grant(args.candidate.resolve(), args.grant.resolve())
            print(sha(args.grant.resolve()))
        else:
            if not args.execute or args.grant is None or args.capability_script is None:
                raise ResumeV7Error("run requires --execute, grant and capability script")
            print(json.dumps(execute(args.candidate.resolve(), args.grant.resolve(), args.capability_script.resolve()), indent=2, sort_keys=True))
        return 0
    except Exception as error:
        print(f"ERROR: {type(error).__name__}: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
