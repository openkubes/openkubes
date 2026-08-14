#!/usr/bin/env python3
"""Single-grant, stop-preserve OK-141 Happy Run orchestration candidate."""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
CANDIDATE = HERE / "happy-run-candidate-v1.yaml"
MGMT_CLIENT = Path("/private/tmp/ok141-kubectl-v1.34.1-darwin-amd64")
WORKLOAD_CLIENT = Path("/private/tmp/ok141-kubectl-v1.36.2-darwin-amd64")


def module(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, SPIKE / relative)
    value = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(value)
    return value


PREFLIGHT = module("ok141_happy_preflight", "go1-v6-preflight-v2/bounded_go1_v6_preflight_v2.py")
RUNTIME = module("ok141_happy_runtime", "go1-l-runtime-package-v1/bounded_go1_l_runtime_package_v1.py")
LIFECYCLE = module("ok141_happy_lifecycle", "go1-l-lifecycle-observer-v1/bounded_go1_l_lifecycle_observer_v1.py")
NETWORK = module("ok141_happy_network", "go1-l-network-observer-v1/bounded_go1_l_network_observer_v1.py")
BINDING = module("ok141_happy_binding", "go1-runtime-binding-v2/bounded_runtime_binding_v2.py")
PROJECTION = module("ok141_happy_projection", "go1-platform-projection-v1/bounded_platform_projection_v1.py")
PLATFORM = module("ok141_happy_platform", "go1-platform-observer-v1/bounded_platform_observer_v1.py")


class HappyRunError(ValueError):
    pass


def sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def sha_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def read(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text())
    if not isinstance(value, dict):
        raise HappyRunError(f"expected mapping: {path}")
    return value


def expect(actual: Any, expected: Any, context: str) -> None:
    if actual != expected:
        raise HappyRunError(f"{context}: expected {expected!r}, got {actual!r}")


def resolve(candidate_path: Path, requested: str) -> Path:
    path = (candidate_path.parent / requested).resolve()
    if SPIKE.resolve() not in path.parents or not path.is_file():
        raise HappyRunError(f"reference missing or outside spike root: {requested}")
    return path


def parse_time(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise HappyRunError("timestamp lacks timezone")
    return parsed.astimezone(dt.timezone.utc)


def iso(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def write_exclusive(path: Path, value: Any) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    raw = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)


def validate_candidate(candidate_path: Path = CANDIDATE) -> dict[str, Any]:
    candidate = read(candidate_path)
    expect(candidate.get("kind"), "GO1HappyRunCandidate", "kind")
    spec = candidate["spec"]
    expect(spec["version"], "ok141-go1-happy-run/v1", "version")
    expect(spec["state"], "OFFLINE-PROVEN-BLOCKED-NO-GO", "state")
    validators = {"preflight": PREFLIGHT.validate_candidate, "runtimePackage": RUNTIME.validate_candidate, "lifecycleObserver": LIFECYCLE.validate_candidate, "networkObserver": NETWORK.validate_candidate, "runtimeBinding": BINDING.validate_candidate, "platformProjection": PROJECTION.validate_candidate, "platformObserver": PLATFORM.validate_candidate}
    for key, validator in validators.items():
        path = resolve(candidate_path, spec["components"][key]["path"])
        expect(sha(path), spec["components"][key]["digest"], f"{key} digest")
        validator(path)
    expect(sha(resolve(candidate_path, spec["tool"]["path"])), spec["tool"]["digest"], "tool digest")
    expected = ["PF", "G1", "LIFECYCLE", "G3", "NETWORK", "BIND", "TARGET-ACCESS", "PLATFORM-CREDENTIALS", "TOKEN-REGISTRATION", "APPLICATIONS", "PLATFORM-READY"]
    expect([item["id"] for item in spec["sequence"]], expected, "sequence")
    if any(spec["authorization"].get(key) for key in spec["authorization"] if key.endswith("Granted")):
        raise HappyRunError("candidate grants authority")
    return candidate


GRANTED = ("preflightGranted", "credentialUseGranted", "g1Granted", "lifecycleObserverGranted", "g3Granted", "networkObserverGranted", "runtimeBindingGranted", "targetAccessGranted", "tokenRequestGranted", "registrationGranted", "credentialSecretGranted", "applicationSubmissionGranted", "platformObserverGranted", "capabilityTestGranted", "capabilityTestCleanupGranted", "go1LGranted", "go1Granted")
DENIED = ("retryGranted", "rollbackGranted", "broadCleanupGranted", "evidencePublicationGranted", "failureInjectionGranted", "outageGranted")


def validate_grant(candidate_path: Path, grant_path: Path, now: dt.datetime | None = None) -> dict[str, Any]:
    candidate = validate_candidate(candidate_path)
    grant = read(grant_path)
    expect(grant.get("kind"), "GO1HappyRunGrant", "grant kind")
    spec = grant["spec"]
    expect((spec["decision"], spec["authority"], spec["singleRun"]), ("GO", "github:arashkaffamanesh", True), "grant identity")
    expect(spec["candidateDigest"], sha(candidate_path), "candidate digest")
    expect(spec["protocolDigest"], candidate["spec"]["protocolDigest"], "protocol digest")
    expect(spec["fixtureDigest"], candidate["spec"]["fixture"]["fixtureDigest"], "fixture digest")
    if any(spec.get(key) is not True for key in GRANTED) or any(spec.get(key) is not False for key in DENIED):
        raise HappyRunError("grant authority is incomplete or overbroad")
    if spec.get("consumed") is not False or not spec.get("grantID") or not spec.get("runID", "").startswith("ok141-happy-"):
        raise HappyRunError("grant is not an unused named single run")
    current = now or dt.datetime.now(dt.timezone.utc)
    issued, expires = parse_time(spec["issuedAt"]), parse_time(spec["expiresAt"])
    if not issued <= current <= expires or expires - issued > dt.timedelta(hours=2):
        raise HappyRunError("grant inactive or exceeds two hours")
    return grant


def grant_file(run_dir: Path, name: str, value: dict[str, Any]) -> Path:
    path = run_dir / f"grant-{name}.json"; write_exclusive(path, value); return path


def inner_base(outer: dict[str, Any], candidate_digest: str, now: dt.datetime, minutes: int) -> dict[str, Any]:
    end = min(parse_time(outer["spec"]["expiresAt"]), now + dt.timedelta(minutes=minutes))
    return {"decision": "GO", "authority": outer["spec"]["authority"], "candidateDigest": candidate_digest, "singleRun": True, "consumed": False, "issuedAt": iso(now), "expiresAt": iso(end)}


def raw_get(client: Path, kubeconfig: Path, uri: str) -> dict[str, Any]:
    completed = subprocess.run([str(client), "--kubeconfig", str(kubeconfig), "get", "--raw", uri], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if completed.returncode != 0: raise HappyRunError("bounded raw GET failed")
    value = json.loads(completed.stdout)
    if not isinstance(value, dict): raise HappyRunError("bounded raw GET returned non-object")
    return value


def create_documents(client: Path, kubeconfig: Path, documents: list[dict[str, Any]]) -> dict[str, Any]:
    payload = yaml.safe_dump_all(documents, explicit_start=True, sort_keys=False).encode()
    completed = subprocess.run([str(client), "--kubeconfig", str(kubeconfig), "create", "--filename", "-"], input=payload, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if completed.returncode != 0: raise HappyRunError("exact create-only submission failed; output suppressed")
    return {"objectCount": len(documents), "payloadDigest": sha_bytes(payload), "stdoutDigest": sha_bytes(completed.stdout), "stderrDigest": sha_bytes(completed.stderr)}


def ephemeral_workload_kubeconfig(run_dir: Path) -> Path:
    secret = raw_get(MGMT_CLIENT, Path("/Users/arash/.kube/ok-mgmt.yaml"), "/api/v1/namespaces/disposable-ok141/secrets/disposable-ok141-kubeconfig")
    path = run_dir / "workload-admin-kubeconfig.yaml"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream: stream.write(base64.b64decode(secret["data"]["value"], validate=True))
    return path


def execute(candidate_path: Path, grant_path: Path, capability_script: Path) -> dict[str, Any]:
    candidate, outer = validate_candidate(candidate_path), validate_grant(candidate_path, grant_path)
    now = dt.datetime.now(dt.timezone.utc)
    run_dir = Path(candidate["spec"]["runtimeDirectory"]) / outer["spec"]["runID"]
    run_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    receipt = run_dir / "outer-grant-consumption.json"
    write_exclusive(receipt, {"grantID": outer["spec"]["grantID"], "candidateDigest": sha(candidate_path), "consumedAt": iso(now), "state": "CONSUMED-BEFORE-FIRST-CLUSTER-CONTACT"})
    components = {key: resolve(candidate_path, value["path"]) for key, value in candidate["spec"]["components"].items()}

    _, _, closure = PREFLIGHT.validate_candidate(components["preflight"])
    preflight_spec = {**inner_base(outer, sha(components["preflight"]), now, 15), "protocolDigest": candidate["spec"]["protocolDigest"], "clientDigest": PREFLIGHT.CLIENT_DIGEST, "expectedCredentialIdentities": closure["spec"]["identities"], "readOnly": True, "mutationAuthorized": False, "grantID": outer["spec"]["grantID"] + "/PF"}
    preflight_grant = grant_file(run_dir, "preflight", {"apiVersion": "authorization.openkubes.io/v1alpha1", "kind": "GO1V6PreflightGrantV2", "spec": preflight_spec})
    preflight = PREFLIGHT.run_preflight(components["preflight"], preflight_grant, dt.datetime.now(dt.timezone.utc))
    preflight_path = Path(PREFLIGHT.validate_candidate(components["preflight"])[0]["spec"]["evidence"]["rawLocalPath"])

    runtime_candidate = RUNTIME.validate_candidate(components["runtimePackage"])[0]
    def stage_grant(stage: str, extra: dict[str, Any] | None = None) -> Path:
        current = dt.datetime.now(dt.timezone.utc); end = min(parse_time(outer["spec"]["expiresAt"]), current + dt.timedelta(minutes=20))
        spec = {"decision": "GO", "authority": outer["spec"]["authority"], "stage": stage, "singleRun": True, "candidateDigest": sha(components["runtimePackage"]), "executorDigest": runtime_candidate["spec"]["executor"]["digest"], "protocolDigest": candidate["spec"]["protocolDigest"], "preflightCandidateDigest": runtime_candidate["spec"]["preflight"]["digest"], "credentialUseGranted": True, "go1LGranted": True, "go1Granted": False, "retryGranted": False, "rollbackOrCleanupGranted": False, "evidencePublicationGranted": False, "failureInjectionGranted": False, "grantID": outer["spec"]["grantID"] + "/" + stage, "runID": outer["spec"]["runID"].replace("ok141-happy-", "ok141-go1-l-"), "issuedAt": iso(current), "expiresAt": iso(end), "preflightEvidenceDigest": sha(preflight_path), "g1Granted": stage == "G1", "g3Granted": stage == "G3"}
        spec.update(extra or {}); return grant_file(run_dir, stage.lower(), {"apiVersion": "authorization.openkubes.io/v1alpha1", "kind": "GO1LStageGrant", "spec": spec})
    g1 = RUNTIME.execute_g1(components["runtimePackage"], stage_grant("G1"), preflight_path, dt.datetime.now(dt.timezone.utc))

    current = dt.datetime.now(dt.timezone.utc)
    life_base = inner_base(outer, sha(components["lifecycleObserver"]), current, 50)
    life_spec = {**life_base, "protocolDigest": candidate["spec"]["protocolDigest"], "fixtureDigest": candidate["spec"]["fixture"]["fixtureDigest"], "grantID": outer["spec"]["grantID"] + "/LIFECYCLE", "g1OperationEvidenceDigests": g1["operationEvidenceDigests"], "clusterContactGranted": True, "credentialUseGranted": True, "readOnlyObserverGranted": True, "mutationGranted": False, "g3Granted": False, "go1Granted": False, "retryGranted": False, "rollbackOrCleanupGranted": False, "evidencePublicationGranted": False, "failureInjectionGranted": False, "outputPath": LIFECYCLE.validate_candidate(components["lifecycleObserver"])["spec"]["observation"]["outputPath"]}
    life_grant = grant_file(run_dir, "lifecycle", {"apiVersion": "authorization.openkubes.io/v1alpha1", "kind": "GO1LLifecycleAPIObserverGrant", "spec": life_spec})
    LIFECYCLE.execute(components["lifecycleObserver"], life_grant, MGMT_CLIENT)
    life_path = Path(life_spec["outputPath"])

    g3 = RUNTIME.execute_g3(components["runtimePackage"], stage_grant("G3", {"lifecycleEvidenceDigest": sha(life_path)}), preflight_path, life_path, dt.datetime.now(dt.timezone.utc))
    hcp_flat = run_dir / "hcp-submission-flat.json"; write_exclusive(hcp_flat, g3)

    current = dt.datetime.now(dt.timezone.utc); net_base = inner_base(outer, sha(components["networkObserver"]), current, 40)
    net_output = NETWORK.validate_candidate(components["networkObserver"])["spec"]["observation"]["outputPath"]
    net_spec = {**net_base, "protocolDigest": candidate["spec"]["protocolDigest"], "fixtureDigest": candidate["spec"]["fixture"]["fixtureDigest"], "grantID": outer["spec"]["grantID"] + "/NETWORK", "lifecycleEvidenceDigest": sha(life_path), "hcpSubmissionEvidenceDigest": sha(hcp_flat), "clusterContactGranted": True, "managementCredentialUseGranted": True, "workloadKubeconfigSecretReadGranted": True, "ephemeralCredentialMaterializationGranted": True, "workloadCredentialUseGranted": True, "readOnlyQueriesGranted": True, "fixedPodExecProbeGranted": True, "persistentMutationGranted": False, "retryGranted": False, "rollbackOrCleanupGranted": False, "go1Granted": False, "evidencePublicationGranted": False, "failureInjectionGranted": False, "outputPath": net_output}
    net_grant = grant_file(run_dir, "network", {"apiVersion": "authorization.openkubes.io/v1alpha1", "kind": "GO1LNetworkReadyObserverGrant", "spec": net_spec})
    NETWORK.execute(components["networkObserver"], net_grant, life_path, hcp_flat, MGMT_CLIENT, WORKLOAD_CLIENT)
    net_path = Path(net_output)

    current = dt.datetime.now(dt.timezone.utc); bind_base = inner_base(outer, sha(components["runtimeBinding"]), current, 15)
    bind_spec = {**bind_base, "protocolDigest": candidate["spec"]["protocolDigest"], "grantID": outer["spec"]["grantID"] + "/BIND", "lifecycleEvidenceDigest": sha(life_path), "networkEvidenceDigest": sha(net_path), "clusterContactGranted": True, "credentialUseGranted": True, "secretReadGranted": True, "ephemeralMaterializationGranted": True, "readOnlyQueriesGranted": True, "persistentMutationGranted": False, "registrationGranted": False, "platformSubmissionGranted": False, "go1Granted": False, "retryGranted": False, "cleanupGranted": False}
    bind_grant = grant_file(run_dir, "binding", {"apiVersion": "authorization.openkubes.io/v1alpha1", "kind": "GO1RuntimeBindingGrant", "spec": bind_spec})
    BINDING.execute(components["runtimeBinding"], bind_grant, life_path, net_path, MGMT_CLIENT, WORKLOAD_CLIENT)
    binding_path = Path(BINDING.validate_candidate(components["runtimeBinding"])["spec"]["outputPath"]); binding = json.loads(binding_path.read_text())

    workload_kubeconfig = ephemeral_workload_kubeconfig(run_dir)
    platform_credentials = run_dir / "platform-credentials.json"
    values = PROJECTION.generate_credentials(components["platformProjection"]); write_exclusive(platform_credentials, values)
    try:
        target_result = create_documents(WORKLOAD_CLIENT, workload_kubeconfig, PROJECTION.target_access(components["platformProjection"]))
        target_evidence = run_dir / "target-access-evidence.json"; write_exclusive(target_evidence, {"state": "TARGET-ACCESS-CREATED", **target_result})
        credential_result = create_documents(WORKLOAD_CLIENT, workload_kubeconfig, [PROJECTION.credential_secret(components["platformProjection"], values)])
        credential_evidence = run_dir / "platform-credential-evidence.json"; write_exclusive(credential_evidence, {"state": "PLATFORM-CREDENTIAL-SECRET-CREATED", **credential_result, "credentialBytesRetainedInEvidence": False})
        token_request = {"apiVersion": "authentication.k8s.io/v1", "kind": "TokenRequest", "spec": {"audiences": [binding["spec"]["target"]["tokenAudience"]], "expirationSeconds": 10800}}
        completed = subprocess.run([str(WORKLOAD_CLIENT), "--kubeconfig", str(workload_kubeconfig), "create", "--raw", "/api/v1/namespaces/kube-system/serviceaccounts/ok141-argocd-manager/token", "-f", "-"], input=json.dumps(token_request, sort_keys=True, separators=(",", ":")).encode(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        if completed.returncode != 0: raise HappyRunError("bounded TokenRequest failed; output suppressed")
        token_response = json.loads(completed.stdout); token = token_response["status"]["token"]; expiration = token_response["status"]["expirationTimestamp"]
        control = PROJECTION.control_plane(components["platformProjection"]); project, applications = control[0], control[1:]
        target = binding["spec"]["target"]
        registration = {"apiVersion": "v1", "kind": "Secret", "metadata": {"name": "disposable-ok141-cluster", "namespace": "argocd", "labels": {"argocd.argoproj.io/secret-type": "cluster"}, "annotations": {"openkubes.io/intent-revision": candidate["spec"]["fixture"]["R"], "openkubes.io/platform-revision": candidate["spec"]["fixture"]["P"], "openkubes.io/execution-fixture": candidate["spec"]["fixture"]["fixtureDigest"], "openkubes.io/capi-cluster-uid": target["capiClusterUID"], "openkubes.io/workload-kube-system-uid": target["workloadKubeSystemUID"], "openkubes.io/workload-api-ca-sha256": target["workloadAPICAFingerprint"], "openkubes.io/token-expiration": expiration}}, "type": "Opaque", "stringData": {"name": "disposable-ok141", "server": target["workloadAPIServer"], "namespaces": "ok-observability,kube-system", "clusterResources": "true", "project": "openkubes-disposable", "config": json.dumps({"bearerToken": token, "tlsClientConfig": {"insecure": False, "caData": target["caData"]}}, sort_keys=True, separators=(",", ":"))}}
        registration_result = create_documents(MGMT_CLIENT, Path("/Users/arash/.kube/ok-shared.yaml"), [project, registration]); token = ""
        registration_evidence = run_dir / "registration-evidence.json"; write_exclusive(registration_evidence, {"state": "REGISTRATION-CREATED", **registration_result, "tokenExpiration": expiration, "credentialBytesRetained": False})
        application_result = create_documents(MGMT_CLIENT, Path("/Users/arash/.kube/ok-shared.yaml"), applications)
        application_evidence = run_dir / "application-submission-evidence.json"; write_exclusive(application_evidence, {"state": "APPLICATIONS-SUBMITTED", **application_result})
    finally:
        workload_kubeconfig.unlink(missing_ok=True)

    current = dt.datetime.now(dt.timezone.utc); platform_base = inner_base(outer, sha(components["platformObserver"]), current, 80)
    platform_spec = {**platform_base, "grantID": outer["spec"]["grantID"] + "/PLATFORM", "runtimeBindingDigest": sha(binding_path), "registrationEvidenceDigest": sha(registration_evidence), "credentialMaterializationEvidenceDigest": sha(credential_evidence), "applicationSubmissionEvidenceDigest": sha(application_evidence), "credentialFileDigest": sha(platform_credentials), "clusterContactGranted": True, "credentialUseGranted": True, "secretReadGranted": True, "argoObservationGranted": True, "capabilityTestGranted": True, "capabilityTestCleanupGranted": True, "arbitraryMutationGranted": False, "applicationSubmissionGranted": False, "retryGranted": False, "go1Granted": False, "failureInjectionGranted": False}
    platform_grant = grant_file(run_dir, "platform", {"apiVersion": "authorization.openkubes.io/v1alpha1", "kind": "GO1PlatformObserverGrant", "spec": platform_spec})
    platform = PLATFORM.execute(components["platformObserver"], platform_grant, binding_path, registration_evidence, credential_evidence, application_evidence, platform_credentials, capability_script, MGMT_CLIENT, MGMT_CLIENT, WORKLOAD_CLIENT)
    result = {"state": "PASS-HAPPY-RUN", "runID": outer["spec"]["runID"], "candidateDigest": sha(candidate_path), "fixtureDigest": candidate["spec"]["fixture"]["fixtureDigest"], "NetworkReady": True, "PlatformReady": platform["PlatformReady"], "retryPerformed": False, "rollbackPerformed": False, "failureInjectionPerformed": False}
    final_path = run_dir / "happy-run-result.json"; write_exclusive(final_path, result); return {**result, "evidencePath": str(final_path), "evidenceDigest": sha(final_path)}


def plan(candidate_path: Path = CANDIDATE) -> dict[str, Any]:
    candidate = validate_candidate(candidate_path)
    return {"candidateDigest": sha(candidate_path), "fixtureDigest": candidate["spec"]["fixture"]["fixtureDigest"], "sequence": [item["id"] for item in candidate["spec"]["sequence"]], "authorization": "NO-GO", "clusterContacted": False}


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("command", choices=("verify", "verify-grant", "run")); parser.add_argument("--candidate", type=Path, default=CANDIDATE); parser.add_argument("--grant", type=Path); parser.add_argument("--capability-script", type=Path); parser.add_argument("--execute", action="store_true"); args = parser.parse_args()
    try:
        if args.command == "verify": print(json.dumps(plan(args.candidate.resolve()), indent=2, sort_keys=True))
        elif args.command == "verify-grant":
            if args.grant is None: raise HappyRunError("grant required")
            validate_grant(args.candidate.resolve(), args.grant.resolve()); print(sha(args.grant.resolve()))
        else:
            if not args.execute or args.grant is None or args.capability_script is None: raise HappyRunError("run requires --execute, grant and capability script")
            print(json.dumps(execute(args.candidate.resolve(), args.grant.resolve(), args.capability_script.resolve()), indent=2, sort_keys=True))
        return 0
    except Exception as error:
        print(f"ERROR: {type(error).__name__}: {error}", file=sys.stderr); return 2


if __name__ == "__main__": raise SystemExit(main())
