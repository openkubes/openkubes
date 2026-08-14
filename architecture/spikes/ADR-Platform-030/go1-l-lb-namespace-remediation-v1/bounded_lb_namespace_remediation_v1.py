#!/usr/bin/env python3
"""Bounded one-shot repair for the OK-141 misplaced CAPK load balancer."""

from __future__ import annotations

import argparse
import base64
import copy
import datetime as dt
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

import yaml


HERE = Path(__file__).resolve().parent
CANDIDATE = HERE / "lb-namespace-remediation-candidate-v1.yaml"
CLIENT = Path("/private/tmp/ok141-kubectl-v1.34.1-darwin-amd64")
CLIENT_DIGEST = "sha256:bb211f2b31f2b3bc60562b44cc1e3b712a16a98e9072968ba255beb04cefcfdf"
MGMT_KUBECONFIG = Path("/Users/arash/.kube/ok-mgmt.yaml")
INFRA_KUBECONFIG = Path("/Users/arash/.kube/ok-infra.yaml")
RUN_ID = re.compile(r"ok141-lb-namespace-remediation-[a-z0-9-]+")


class RemediationError(ValueError):
    pass


def sha_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def sha(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def load(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text())
    if not isinstance(value, dict):
        raise RemediationError(f"expected mapping: {path}")
    return value


def expect(actual: Any, expected: Any, context: str) -> None:
    if actual != expected:
        raise RemediationError(f"{context}: expected {expected!r}, got {actual!r}")


def parse_time(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def safe_credential(path: Path) -> None:
    if path.is_symlink() or not path.is_file() or stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise RemediationError(f"unsafe credential file: {path}")


def validate_candidate(path: Path = CANDIDATE) -> dict[str, Any]:
    value = load(path)
    expect(value.get("apiVersion"), "execution.openkubes.io/v1alpha1", "apiVersion")
    expect(value.get("kind"), "LBNamespaceRemediationCandidate", "kind")
    spec = value["spec"]
    expect(spec["version"], "ok141-lb-namespace-remediation/v1", "version")
    expect(spec["state"], "OFFLINE-PROVEN-BLOCKED-NO-GO", "state")
    expect(spec["failureSemantics"], "STOP-PRESERVE-NO-RETRY", "failure semantics")
    expect(spec["sourceFix"]["repository"], "openkubes/ok-cluster", "source repository")
    expect(spec["sourceFix"]["commit"], "38cfe626b328e99f07194ee254ec69b19fca1064", "source fix")
    expect(spec["credentialIdentities"], {
        "ok-infra": "sha256:0cab42fab537845afb82ef510169bf9402e314e0fcb3ebce972499e0a1cd8f13",
        "ok-mgmt": "sha256:32a164332776f37129e46415af79945745134fefe80c5237d43fe13fa0511ffe",
    }, "credential identities")
    expect(spec["runtime"]["preflightEvidenceDigest"], "sha256:221cf748c7ae4d8698e8ad0b9033987d8cb04856aa3eb8c42fab832e62438c24", "preflight evidence")
    expect(spec["runtime"]["g1SummaryDigest"], "sha256:c3aef1a58e85ef4b9b2348f10cf8bd4dfdd344f4e89f6170ea132663aa544c86", "G1 evidence")
    expect(spec["runtime"]["endpoint"], {"host": "192.168.100.213", "port": 6443}, "endpoint")
    expect(spec["namespaceTransition"], {"from": "ok-obs-verify", "to": "disposable-ok141"}, "namespace transition")
    expect(spec["objects"]["secret"]["rawURI"], "/api/v1/namespaces/disposable-ok141/secrets/external-infra-kubeconfig-disposable-ok141", "Secret URI")
    expect(spec["objects"]["misplacedService"]["rawURI"], "/api/v1/namespaces/ok-obs-verify/services/disposable-ok141-lb", "old Service URI")
    expect(spec["objects"]["targetService"]["rawURI"], "/api/v1/namespaces/disposable-ok141/services/disposable-ok141-lb", "target Service URI")
    expect(spec["objects"]["targetService"]["requestedIP"], "192.168.100.213", "requested IP")
    expect(spec["objects"]["targetService"]["addressPool"], "ok-pool", "address pool")
    expect(spec["objects"]["kubevirtCluster"]["rawURI"], "/apis/infrastructure.cluster.x-k8s.io/v1alpha1/namespaces/disposable-ok141/kubevirtclusters/disposable-ok141", "KubevirtCluster URI")
    expect(spec["objects"]["cluster"]["rawURI"], "/apis/cluster.x-k8s.io/v1beta2/namespaces/disposable-ok141/clusters/disposable-ok141", "Cluster URI")
    expect(spec["tool"]["path"], "bounded_lb_namespace_remediation_v1.py", "tool path")
    expect(sha(HERE / spec["tool"]["path"]), spec["tool"]["digest"], "tool digest")
    auth = spec["authorization"]
    expect(auth["decision"], "NO-GO", "authorization")
    if any(value for key, value in auth.items() if key.endswith("Granted")):
        raise RemediationError("candidate grants authority")
    expect(spec["exclusions"]["deleteMisplacedService"], "single-exact-delete-after-target-create", "delete boundary")
    expect(spec["exclusions"]["generalCleanupGranted"], False, "cleanup boundary")
    return value


def validate_grant(candidate_path: Path, grant_path: Path, now: dt.datetime | None = None) -> dict[str, Any]:
    candidate = validate_candidate(candidate_path)
    grant = load(grant_path)
    expect(grant.get("kind"), "LBNamespaceRemediationGrant", "grant kind")
    spec = grant["spec"]
    expect((spec["decision"], spec["authority"], spec["singleRun"], spec["consumed"]), ("GO", "github:arashkaffamanesh", True, False), "grant identity")
    expect(spec["candidateDigest"], sha(candidate_path), "grant candidate")
    expect(spec["riskAcceptance"], "DEV-REBUILD-ON-FAILURE-ACCEPTED", "risk acceptance")
    required_true = (
        "credentialUseGranted", "secretReadGranted", "secretReplaceGranted",
        "targetServiceCreateGranted", "misplacedServiceDeleteGranted",
        "kubevirtClusterEndpointResetGranted", "observationGranted",
    )
    required_false = (
        "retryGranted", "rollbackGranted", "generalCleanupGranted", "happyRunResumeGranted",
        "g3Granted", "platformConvergenceGranted", "evidencePublicationGranted", "failureInjectionGranted",
    )
    if any(spec.get(key) is not True for key in required_true) or any(spec.get(key) is not False for key in required_false):
        raise RemediationError("grant is incomplete or overbroad")
    if not spec.get("grantID") or not RUN_ID.fullmatch(spec.get("runID", "")):
        raise RemediationError("invalid grant or run ID")
    current = now or dt.datetime.now(dt.timezone.utc)
    issued, expires = parse_time(spec["issuedAt"]), parse_time(spec["expiresAt"])
    if not issued <= current <= expires or expires - issued > dt.timedelta(minutes=30):
        raise RemediationError("grant inactive or exceeds 30 minutes")
    expect(spec["rawEvidencePath"], "/private/tmp/ok141-lb-namespace-remediation-v1-evidence.json", "evidence path")
    expect(spec["credentialIdentityDigests"], candidate["spec"]["credentialIdentities"], "credential identities")
    return grant


def normalize_kubeconfig(raw: bytes, old_namespace: str, target_namespace: str) -> bytes:
    try:
        original = yaml.safe_load(raw.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as error:
        raise RemediationError("Secret kubeconfig is not valid UTF-8 YAML") from error
    if not isinstance(original, dict) or original.get("apiVersion") != "v1" or original.get("kind") != "Config":
        raise RemediationError("Secret payload is not a Kubernetes Config")
    current = original.get("current-context")
    contexts = [entry for entry in original.get("contexts", []) if isinstance(entry, dict) and entry.get("name") == current]
    if len(contexts) != 1 or not isinstance(contexts[0].get("context"), dict):
        raise RemediationError("kubeconfig current-context is ambiguous")
    expect(contexts[0]["context"].get("namespace"), old_namespace, "current-context namespace")
    normalized = copy.deepcopy(original)
    normalized_context = next(entry for entry in normalized["contexts"] if entry.get("name") == current)
    normalized_context["context"]["namespace"] = target_namespace
    proof = copy.deepcopy(normalized)
    next(entry for entry in proof["contexts"] if entry.get("name") == current)["context"]["namespace"] = old_namespace
    expect(proof, original, "semantic kubeconfig delta")
    return yaml.safe_dump(normalized, sort_keys=False).encode("utf-8")


def build_secret_replacement(secret: dict[str, Any], spec: dict[str, Any]) -> tuple[bytes, dict[str, Any]]:
    metadata = secret.get("metadata", {})
    expect((secret.get("apiVersion"), secret.get("kind")), ("v1", "Secret"), "Secret identity")
    expect((metadata.get("namespace"), metadata.get("name")), ("disposable-ok141", "external-infra-kubeconfig-disposable-ok141"), "Secret name")
    if not metadata.get("uid") or not metadata.get("resourceVersion"):
        raise RemediationError("Secret lacks UID/resourceVersion")
    data = secret.get("data", {})
    expect(set(data), {"kubeconfig"}, "Secret data keys")
    try:
        raw = base64.b64decode(data["kubeconfig"], validate=True)
    except Exception as error:
        raise RemediationError("invalid Secret kubeconfig encoding") from error
    transition = spec["namespaceTransition"]
    normalized = normalize_kubeconfig(raw, transition["from"], transition["to"])
    updated = copy.deepcopy(secret)
    updated["data"]["kubeconfig"] = base64.b64encode(normalized).decode("ascii")
    return json.dumps(updated, sort_keys=True, separators=(",", ":")).encode(), {
        "identity": "v1|Secret|disposable-ok141|external-infra-kubeconfig-disposable-ok141",
        "uid": metadata["uid"],
        "resourceVersion": metadata["resourceVersion"],
        "dataKeys": ["kubeconfig"],
        "semanticChange": "current-context.namespace:ok-obs-verify->disposable-ok141",
        "secretBytesEmitted": False,
        "secretDigestEmitted": False,
    }


def validate_misplaced_service(service: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    metadata = service.get("metadata", {})
    expect((service.get("apiVersion"), service.get("kind")), ("v1", "Service"), "Service identity")
    expect((metadata.get("namespace"), metadata.get("name")), ("ok-obs-verify", "disposable-ok141-lb"), "misplaced Service")
    if not metadata.get("uid") or not metadata.get("resourceVersion"):
        raise RemediationError("misplaced Service lacks UID/resourceVersion")
    expect(service.get("spec", {}).get("selector"), spec["objects"]["targetService"]["selector"], "Service selector")
    ingress = service.get("status", {}).get("loadBalancer", {}).get("ingress", [])
    expect([item.get("ip") for item in ingress], [spec["runtime"]["endpoint"]["host"]], "Service VIP")
    expect(metadata.get("annotations", {}).get("metallb.io/ip-allocated-from-pool"), spec["objects"]["targetService"]["addressPool"], "allocated pool")
    return {"uid": metadata["uid"], "resourceVersion": metadata["resourceVersion"]}


def build_target_service(spec: dict[str, Any]) -> bytes:
    target = spec["objects"]["targetService"]
    value = {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {
            "name": "disposable-ok141-lb",
            "namespace": "disposable-ok141",
            "labels": {"cluster.x-k8s.io/cluster-name": "disposable-ok141"},
            "annotations": {
                "metallb.io/address-pool": target["addressPool"],
                "metallb.io/loadBalancerIPs": target["requestedIP"],
                "openkubes.io/remediation": "OK-141-lb-namespace-v1",
            },
        },
        "spec": {
            "type": "LoadBalancer",
            "ports": [{"protocol": "TCP", "port": 6443, "targetPort": 6443}],
            "selector": target["selector"],
        },
    }
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def kubevirt_cluster_patch(value: dict[str, Any], spec: dict[str, Any]) -> bytes:
    metadata = value.get("metadata", {})
    expect((value.get("kind"), metadata.get("namespace"), metadata.get("name")), ("KubevirtCluster", "disposable-ok141", "disposable-ok141"), "KubevirtCluster identity")
    endpoint = value.get("spec", {}).get("controlPlaneEndpoint", {})
    expect(endpoint, spec["runtime"]["endpoint"], "current endpoint")
    if not metadata.get("uid") or not metadata.get("resourceVersion"):
        raise RemediationError("KubevirtCluster lacks UID/resourceVersion")
    patch = [
        {"op": "test", "path": "/metadata/uid", "value": metadata["uid"]},
        {"op": "test", "path": "/metadata/resourceVersion", "value": metadata["resourceVersion"]},
        {"op": "test", "path": "/spec/controlPlaneEndpoint/host", "value": endpoint["host"]},
        {"op": "replace", "path": "/spec/controlPlaneEndpoint/host", "value": ""},
    ]
    return json.dumps(patch, separators=(",", ":")).encode()


def default_runner(command: list[str], *, input: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(command, input=input, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


def kubectl(runner: Callable[..., subprocess.CompletedProcess[bytes]], kubeconfig: Path, arguments: list[str], payload: bytes | None = None, allow_not_found: bool = False) -> dict[str, Any] | None:
    completed = runner([str(CLIENT), "--kubeconfig", str(kubeconfig), *arguments], input=payload)
    if completed.returncode != 0:
        message = completed.stderr.decode("utf-8", errors="replace")
        if allow_not_found and "NotFound" in message:
            return None
        raise RemediationError(f"bounded kubectl operation failed ({completed.returncode})")
    if not completed.stdout:
        return {}
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise RemediationError("bounded kubectl returned non-JSON") from error
    return value


def exact_get(runner: Callable[..., subprocess.CompletedProcess[bytes]], kubeconfig: Path, uri: str, allow_not_found: bool = False) -> dict[str, Any] | None:
    return kubectl(runner, kubeconfig, ["get", "--raw", uri], allow_not_found=allow_not_found)


def validate_runtime_files() -> None:
    if not CLIENT.is_file() or CLIENT.is_symlink() or sha(CLIENT) != CLIENT_DIGEST:
        raise RemediationError("untrusted kubectl client")
    safe_credential(MGMT_KUBECONFIG)
    safe_credential(INFRA_KUBECONFIG)


def poll_target(runner: Callable[..., subprocess.CompletedProcess[bytes]], spec: dict[str, Any], attempts: int = 60, delay: float = 5.0) -> dict[str, Any]:
    target_uri = spec["objects"]["targetService"]["rawURI"]
    endpoints_uri = spec["objects"]["targetEndpoints"]["rawURI"]
    for _ in range(attempts):
        service = exact_get(runner, INFRA_KUBECONFIG, target_uri)
        endpoints = exact_get(runner, INFRA_KUBECONFIG, endpoints_uri, allow_not_found=True)
        ingress = (service or {}).get("status", {}).get("loadBalancer", {}).get("ingress", [])
        addresses = []
        for subset in (endpoints or {}).get("subsets", []):
            addresses.extend(item.get("ip") for item in subset.get("addresses", []) if item.get("ip"))
        if [item.get("ip") for item in ingress] == [spec["runtime"]["endpoint"]["host"]] and addresses:
            return {"serviceUID": service["metadata"]["uid"], "vip": ingress[0]["ip"], "endpointAddressCount": len(addresses)}
        time.sleep(delay)
    raise RemediationError("target Service did not acquire the bound VIP and endpoints")


def poll_control_plane(runner: Callable[..., subprocess.CompletedProcess[bytes]], spec: dict[str, Any], attempts: int = 60, delay: float = 5.0) -> dict[str, Any]:
    expected = spec["runtime"]["endpoint"]
    for _ in range(attempts):
        kubevirt_cluster = exact_get(runner, MGMT_KUBECONFIG, spec["objects"]["kubevirtCluster"]["rawURI"])
        cluster = exact_get(runner, MGMT_KUBECONFIG, spec["objects"]["cluster"]["rawURI"])
        kvc_endpoint = (kubevirt_cluster or {}).get("spec", {}).get("controlPlaneEndpoint")
        cluster_endpoint = (cluster or {}).get("spec", {}).get("controlPlaneEndpoint")
        if kvc_endpoint == expected and cluster_endpoint == expected:
            return {"kubevirtCluster": kvc_endpoint, "cluster": cluster_endpoint}
        time.sleep(delay)
    raise RemediationError("management objects did not return to the bound control-plane endpoint")


def write_evidence(path: Path, value: dict[str, Any]) -> None:
    raw = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)


def execute(candidate_path: Path, grant_path: Path, runner: Callable[..., subprocess.CompletedProcess[bytes]] = default_runner, now: dt.datetime | None = None, poll_attempts: int = 60, poll_delay: float = 5.0) -> dict[str, Any]:
    candidate = validate_candidate(candidate_path)
    grant = validate_grant(candidate_path, grant_path, now)
    validate_runtime_files()
    spec = candidate["spec"]
    evidence_path = Path(grant["spec"]["rawEvidencePath"])
    if evidence_path.exists() or evidence_path.is_symlink():
        raise RemediationError("raw evidence path already exists")
    completed_stages: list[str] = []

    try:
        secret = exact_get(runner, MGMT_KUBECONFIG, spec["objects"]["secret"]["rawURI"])
        old_service = exact_get(runner, INFRA_KUBECONFIG, spec["objects"]["misplacedService"]["rawURI"])
        target = exact_get(runner, INFRA_KUBECONFIG, spec["objects"]["targetService"]["rawURI"], allow_not_found=True)
        kubevirt_cluster = exact_get(runner, MGMT_KUBECONFIG, spec["objects"]["kubevirtCluster"]["rawURI"])
        if target is not None:
            raise RemediationError("target Service already exists")
        secret_payload, secret_evidence = build_secret_replacement(secret or {}, spec)
        old_binding = validate_misplaced_service(old_service or {}, spec)
        kvc_patch = kubevirt_cluster_patch(kubevirt_cluster or {}, spec)
        completed_stages.append("validated-current-state")

        kubectl(runner, MGMT_KUBECONFIG, ["replace", "--raw", spec["objects"]["secret"]["rawURI"], "--filename", "-"], secret_payload)
        completed_stages.append("normalized-provider-secret")
        kubectl(runner, INFRA_KUBECONFIG, ["create", "--raw", "/api/v1/namespaces/disposable-ok141/services", "--filename", "-"], build_target_service(spec))
        completed_stages.append("created-target-service")

        current_old = exact_get(runner, INFRA_KUBECONFIG, spec["objects"]["misplacedService"]["rawURI"])
        current_binding = validate_misplaced_service(current_old or {}, spec)
        expect(current_binding["uid"], old_binding["uid"], "old Service UID before delete")
        kubectl(runner, INFRA_KUBECONFIG, ["delete", "--raw", spec["objects"]["misplacedService"]["rawURI"]])
        completed_stages.append("deleted-misplaced-service")

        target_result = poll_target(runner, spec, poll_attempts, poll_delay)
        completed_stages.append("target-vip-and-endpoints-ready")
        kubectl(runner, MGMT_KUBECONFIG, [
            "patch", "kubevirtcluster.infrastructure.cluster.x-k8s.io", "disposable-ok141",
            "--namespace", "disposable-ok141", "--type", "json", "--patch", kvc_patch.decode("utf-8"), "--output", "json",
        ])
        completed_stages.append("reset-provider-derived-endpoint")
        endpoint_result = poll_control_plane(runner, spec, poll_attempts, poll_delay)
        completed_stages.append("bound-endpoint-restored")

        result = {
            "apiVersion": "evidence.openkubes.io/v1alpha1",
            "kind": "LBNamespaceRemediationEvidence",
            "spec": {
                "candidateDigest": sha(candidate_path),
                "grantID": grant["spec"]["grantID"],
                "runID": grant["spec"]["runID"],
                "result": "REMEDIATED-PRESERVE-HAPPY-RUN",
                "completedStages": completed_stages,
                "secret": secret_evidence,
                "misplacedService": {"identity": "v1|Service|ok-obs-verify|disposable-ok141-lb", "deletedUID": current_binding["uid"], "resourceVersionReadBeforeDelete": current_binding["resourceVersion"], "deletePrecondition": "exact-read-immediately-before-delete; kubectl-raw-delete-has-no-server-side-UID-precondition"},
                "targetService": target_result,
                "endpointsAfterTrigger": endpoint_result,
                "secretBytesEmitted": False,
                "secretDigestEmitted": False,
                "retryPerformed": False,
                "rollbackOrGeneralCleanupPerformed": False,
                "happyRunResumed": False,
                "evidencePublished": False,
            },
        }
        write_evidence(evidence_path, result)
        return {"result": result["spec"]["result"], "evidencePath": str(evidence_path), "targetVIP": target_result["vip"], "happyRunResumed": False}
    except Exception as error:
        if not evidence_path.exists():
            write_evidence(evidence_path, {
                "apiVersion": "evidence.openkubes.io/v1alpha1",
                "kind": "LBNamespaceRemediationEvidence",
                "spec": {
                    "candidateDigest": sha(candidate_path), "grantID": grant["spec"]["grantID"], "runID": grant["spec"]["runID"],
                    "result": "STOP-PRESERVE-NO-RETRY", "completedStages": completed_stages,
                    "errorClass": type(error).__name__, "secretBytesEmitted": False, "secretDigestEmitted": False,
                    "retryPerformed": False, "rollbackOrGeneralCleanupPerformed": False, "happyRunResumed": False, "evidencePublished": False,
                },
            })
        raise


def plan(candidate_path: Path = CANDIDATE) -> dict[str, Any]:
    candidate = validate_candidate(candidate_path)
    return {
        "candidateDigest": sha(candidate_path),
        "state": candidate["spec"]["state"],
        "sequence": candidate["spec"]["sequence"],
        "authorization": "NO-GO",
        "clusterContacted": False,
        "mutationPerformed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "verify-grant", "run"))
    parser.add_argument("--candidate", type=Path, default=CANDIDATE)
    parser.add_argument("--grant", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        candidate = args.candidate.resolve()
        if args.command == "verify":
            print(json.dumps(plan(candidate), indent=2, sort_keys=True))
        elif args.command == "verify-grant":
            if args.grant is None:
                raise RemediationError("grant required")
            validate_grant(candidate, args.grant.resolve())
            print(sha(args.grant.resolve()))
        else:
            if not args.execute or args.grant is None:
                raise RemediationError("run requires --execute and --grant")
            print(json.dumps(execute(candidate, args.grant.resolve()), indent=2, sort_keys=True))
        return 0
    except Exception as error:
        print(f"ERROR: {type(error).__name__}: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
