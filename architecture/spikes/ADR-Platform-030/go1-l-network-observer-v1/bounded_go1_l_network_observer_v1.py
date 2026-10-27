#!/usr/bin/env python3
"""Bounded enablement and functional NetworkReady observer for OK-141."""

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
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import yaml


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
CANDIDATE = HERE / "go1-l-network-observer-candidate-v1.yaml"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


EXECUTOR = load_module("ok141_executor_v2_for_network_observer", SPIKE / "go1-l-executor-v2" / "bounded_go1_l_executor_v2.py")


class NetworkObserverError(ValueError):
    pass


def read_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text())
    if not isinstance(value, dict):
        raise NetworkObserverError(f"expected mapping: {path}")
    return value


def sha_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def digest(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def canonical_digest(value: Any) -> str:
    return sha_bytes(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def parse_time(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise NetworkObserverError("timestamp lacks timezone")
    return parsed


def expect(actual: Any, expected: Any, context: str) -> None:
    if actual != expected:
        raise NetworkObserverError(f"{context}: expected {expected!r}, got {actual!r}")


def resolve(candidate_path: Path, requested: str) -> Path:
    path = (candidate_path.parent / requested).resolve()
    if SPIKE.resolve() not in path.parents or not path.is_file():
        raise NetworkObserverError(f"reference missing or outside spike root: {requested}")
    return path


def validate_candidate(candidate_path: Path = CANDIDATE) -> dict[str, Any]:
    candidate = read_yaml(candidate_path)
    expect(candidate.get("apiVersion"), "evidence.openkubes.io/v1alpha1", "apiVersion")
    expect(candidate.get("kind"), "GO1LNetworkReadyObserverCandidate", "kind")
    spec = candidate["spec"]
    expect(spec["version"], "ok141-go1-l-network-ready-observer/v1", "version")
    expect(spec["state"], "OFFLINE-PROVEN-BLOCKED-NO-GO", "state")
    expect(digest(resolve(candidate_path, spec["protocol"]["path"])), spec["protocol"]["digest"], "protocol digest")
    bindings = spec["predecessor"]
    expect(digest(resolve(candidate_path, bindings["lifecycleObserverPath"])), bindings["lifecycleObserverDigest"], "lifecycle observer")
    expect(digest(resolve(candidate_path, bindings["runtimePackagePath"])), bindings["runtimePackageDigest"], "runtime package")
    expect(digest(resolve(candidate_path, bindings["hcpPath"])), bindings["hcpPayloadDigest"], "HCP payload")
    expect(spec["sources"]["caaph"]["commit"], "825662962a26dc339f3871184c91ed4bd2f83a4f", "CAAPH source")
    expect(spec["sources"]["cilium"]["commit"], "9a8982433e18019e290b8199c0c4ad24f66befe8", "Cilium source")
    expect(spec["sources"]["cilium"]["functionalProbe"], ["cilium-health", "status", "--probe", "--output", "json"], "fixed probe")
    management = spec["management"]["queries"]
    expect([(item["id"], item["mode"]) for item in management], [("cluster", "exact"), ("hcp", "exact"), ("hrp", "exact-bounded-collection"), ("workload-kubeconfig", "exact-secret")], "management query boundary")
    expect(management[-1]["rawURI"], "/api/v1/namespaces/disposable-ok141/secrets/disposable-ok141-kubeconfig", "Secret identity")
    workload = spec["workload"]
    expect(workload["clientDigest"], "sha256:ce6c5e55cd17559e87e4fb5e73ebbbc2511bcf2b695d7a40c1b1461a9817d4b3", "workload client")
    expect(workload["expectedNodeCount"], 2, "Node count")
    expect([item["id"] for item in workload["queries"]], ["nodes", "cilium-daemonset", "envoy-daemonset", "cilium-operator", "cilium-pods"], "workload query boundary")
    observation = spec["observation"]
    expect((observation["intervalSeconds"], observation["maximumIterations"], observation["maximumDurationSeconds"]), (15, 120, 1800), "poll boundary")
    expect(digest(resolve(candidate_path, spec["tool"]["path"])), spec["tool"]["digest"], "tool digest")
    tool = spec["tool"]
    if tool["arbitraryCommandAllowed"] or tool["arbitraryQueryAllowed"] or tool["persistentMutationAllowed"] or not tool["fixedPodExecSubresourceOnly"]:
        raise NetworkObserverError("tool expands the bounded observer")
    authorization = spec["authorization"]
    expect(authorization["decision"], "NO-GO", "authorization")
    expect(authorization["grantIDs"], [], "grant inventory")
    if any(value for key, value in authorization.items() if key.endswith("Granted")):
        raise NetworkObserverError("candidate grants live authority")
    return candidate


def validate_grant(candidate_path: Path, grant_path: Path, now: dt.datetime | None = None) -> dict[str, Any]:
    candidate = validate_candidate(candidate_path)
    grant = read_yaml(grant_path)
    expect(grant.get("apiVersion"), "authorization.openkubes.io/v1alpha1", "grant apiVersion")
    expect(grant.get("kind"), "GO1LNetworkReadyObserverGrant", "grant kind")
    spec = grant["spec"]
    expect(spec["decision"], "GO", "decision")
    expect(spec["candidateDigest"], digest(candidate_path), "candidate")
    expect(spec["protocolDigest"], candidate["spec"]["protocol"]["digest"], "protocol")
    expect(spec["fixtureDigest"], candidate["spec"]["protocol"]["fixtureDigest"], "fixture")
    expect(spec["authority"], "github:arashkaffamanesh", "authority")
    if not spec.get("grantID") or spec.get("singleRun") is not True or spec.get("consumed") is not False:
        raise NetworkObserverError("grant is not unused single-run authority")
    required_digests = ("lifecycleEvidenceDigest", "hcpSubmissionEvidenceDigest")
    for key in required_digests:
        value = spec.get(key)
        if not isinstance(value, str) or not value.startswith("sha256:") or len(value) != 71:
            raise NetworkObserverError(f"invalid predecessor: {key}")
    true_claims = ("clusterContactGranted", "managementCredentialUseGranted", "workloadKubeconfigSecretReadGranted", "ephemeralCredentialMaterializationGranted", "workloadCredentialUseGranted", "readOnlyQueriesGranted", "fixedPodExecProbeGranted")
    false_claims = ("persistentMutationGranted", "retryGranted", "rollbackOrCleanupGranted", "go1Granted", "evidencePublicationGranted", "failureInjectionGranted")
    if any(spec.get(key) is not True for key in true_claims) or any(spec.get(key) is not False for key in false_claims):
        raise NetworkObserverError("grant authority is incomplete or overbroad")
    current = now or dt.datetime.now(dt.timezone.utc)
    issued, expires = parse_time(spec["issuedAt"]), parse_time(spec["expiresAt"])
    if not issued <= current <= expires or expires - issued > dt.timedelta(minutes=40):
        raise NetworkObserverError("grant inactive or exceeds 40 minutes")
    expect(spec["outputPath"], candidate["spec"]["observation"]["outputPath"], "output path")
    return grant


def conditions(obj: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item.get("type", ""): item for item in obj.get("status", {}).get("conditions", []) if isinstance(item, dict)}


def current_true(obj: dict[str, Any], condition_type: str) -> bool:
    generation = obj.get("metadata", {}).get("generation")
    status = obj.get("status", {})
    item = conditions(obj).get(condition_type, {})
    return isinstance(generation, int) and status.get("observedGeneration") == generation and item.get("status") == "True" and item.get("observedGeneration") == generation


def container_image(obj: dict[str, Any], name: str) -> str | None:
    for container in obj.get("spec", {}).get("template", {}).get("spec", {}).get("containers", []):
        if container.get("name") == name:
            return container.get("image")
    return None


def ready_condition(node: dict[str, Any], condition_type: str) -> dict[str, Any]:
    return conditions(node).get(condition_type, {})


def semantic_hcp_spec(value: dict[str, Any]) -> dict[str, Any]:
    spec = value.get("spec", {})
    return {key: spec.get(key) for key in ("clusterSelector", "chartName", "repoURL", "releaseName", "namespace", "version", "reconcileStrategy", "valuesTemplate", "options")}


def evaluate_management(candidate: dict[str, Any], values: dict[str, dict[str, Any]], lifecycle: dict[str, Any], reviewed_hcp: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if sorted(values) != ["cluster", "hcp", "hrp", "workload-kubeconfig"]:
        return "WAIT-MANAGEMENT-OBJECTS", {}
    cluster, hcp, hrp_list, secret = values["cluster"], values["hcp"], values["hrp"], values["workload-kubeconfig"]
    expected_r, expected_e = candidate["spec"]["protocol"]["R"], candidate["spec"]["protocol"]["E"]
    if cluster.get("metadata", {}).get("uid") != lifecycle.get("details", {}).get("objects", {}).get("cluster", {}).get("uid"):
        return "FAIL-CLUSTER-UID-CORRELATION", {}
    annotations = hcp.get("metadata", {}).get("annotations", {})
    if annotations.get("openkubes.io/intent-revision") != expected_r or annotations.get("openkubes.io/enablement-revision") != expected_e:
        return "FAIL-HCP-REVISION", {}
    if semantic_hcp_spec(hcp) != semantic_hcp_spec(reviewed_hcp):
        return "FAIL-HCP-SPEC", {}
    if not all(current_true(hcp, item) for item in ("Ready", "HelmReleaseProxySpecsUpToDate", "HelmReleaseProxiesReady")):
        return "WAIT-HCP-READY", {}
    matching = hcp.get("status", {}).get("matchingClusters", [])
    if len(matching) != 1 or (matching[0].get("name"), matching[0].get("namespace")) != ("disposable-ok141", "disposable-ok141"):
        return "FAIL-HCP-SELECTION", {}
    items = hrp_list.get("items", [])
    if len(items) != 1:
        return "WAIT-EXACTLY-ONE-HRP", {"count": len(items)}
    hrp = items[0]
    labels = hrp.get("metadata", {}).get("labels", {})
    if not hrp.get("metadata", {}).get("name", "").startswith("cilium-disposable-ok141-") or labels.get("cluster.x-k8s.io/cluster-name") != "disposable-ok141" or labels.get("helmreleaseproxy.addons.cluster.x-k8s.io/helmchartproxy-name") != "disposable-ok141-cilium":
        return "FAIL-HRP-SELECTOR-IDENTITY", {}
    owners = hrp.get("metadata", {}).get("ownerReferences", [])
    if len([owner for owner in owners if owner.get("controller") is True and owner.get("kind") == "HelmChartProxy" and owner.get("name") == "disposable-ok141-cilium" and owner.get("uid") == hcp.get("metadata", {}).get("uid")]) != 1:
        return "FAIL-HRP-OWNER", {}
    hrp_spec, hcp_spec = hrp.get("spec", {}), hcp.get("spec", {})
    expected_spec = ("cilium", "oci://quay.io/cilium/charts", "1.19.6", "cilium", "kube-system", "Continuous")
    actual_spec = (hrp_spec.get("chartName"), hrp_spec.get("repoURL"), hrp_spec.get("version"), hrp_spec.get("releaseName"), hrp_spec.get("namespace"), hrp_spec.get("reconcileStrategy"))
    if actual_spec != expected_spec or hrp_spec.get("values") != hcp_spec.get("valuesTemplate"):
        return "FAIL-HRP-SPEC", {}
    ref = hrp_spec.get("clusterRef", {})
    if (ref.get("apiVersion"), ref.get("kind"), ref.get("namespace"), ref.get("name")) != ("cluster.x-k8s.io/v1beta2", "Cluster", "disposable-ok141", "disposable-ok141"):
        return "FAIL-HRP-CLUSTER-REF", {}
    if not current_true(hrp, "Ready") or not current_true(hrp, "HelmReleaseReady") or hrp.get("status", {}).get("status") != "deployed" or hrp.get("status", {}).get("revision", 0) < 1:
        return "WAIT-HRP-READY", {}
    data = secret.get("data", {}).get("value")
    if not isinstance(data, str) or not data:
        return "WAIT-WORKLOAD-KUBECONFIG", {}
    return "PASS-MANAGEMENT-ENABLEMENT", {
        "clusterUID": cluster["metadata"]["uid"],
        "hcpUID": hcp["metadata"]["uid"],
        "hcpGeneration": hcp["metadata"]["generation"],
        "hrpUID": hrp["metadata"]["uid"],
        "hrpGeneration": hrp["metadata"]["generation"],
        "helmRevision": hrp["status"]["revision"],
        "kubeconfigData": data,
        "endpoint": cluster.get("spec", {}).get("controlPlaneEndpoint", {}),
    }


def daemonset_ready(obj: dict[str, Any], expected: int) -> bool:
    generation, status = obj.get("metadata", {}).get("generation"), obj.get("status", {})
    return status.get("observedGeneration") == generation and all(status.get(field) == expected for field in ("desiredNumberScheduled", "updatedNumberScheduled", "numberAvailable", "numberReady"))


def deployment_ready(obj: dict[str, Any]) -> bool:
    generation, status = obj.get("metadata", {}).get("generation"), obj.get("status", {})
    return status.get("observedGeneration") == generation and status.get("availableReplicas") == 1 and status.get("updatedReplicas") == 1


def evaluate_workload(candidate: dict[str, Any], values: dict[str, dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    items = values.get("nodes", {}).get("items", [])
    expected = candidate["spec"]["workload"]["expectedNodeCount"]
    if len(items) != expected:
        return "WAIT-NODE-COUNT", {"count": len(items)}
    node_names, node_evidence = set(), []
    for node in items:
        meta, spec = node.get("metadata", {}), node.get("spec", {})
        ready, network = ready_condition(node, "Ready"), ready_condition(node, "NetworkUnavailable")
        if ready.get("status") != "True" or network.get("status") != "False" or network.get("reason") != "CiliumIsUp":
            return "WAIT-NODE-NETWORK", {"node": meta.get("name")}
        if not meta.get("uid") or not spec.get("providerID"):
            return "WAIT-NODE-IDENTITY", {"node": meta.get("name")}
        node_names.add(meta["name"])
        node_evidence.append({"name": meta["name"], "uid": meta["uid"], "providerID": spec["providerID"], "ready": True, "networkUnavailable": False, "networkReason": "CiliumIsUp"})
    cilium, envoy, operator = values["cilium-daemonset"], values["envoy-daemonset"], values["cilium-operator"]
    if not daemonset_ready(cilium, expected) or not daemonset_ready(envoy, expected) or not deployment_ready(operator):
        return "WAIT-CILIUM-ROLLOUT", {}
    images = candidate["spec"]["workload"]["expectedImages"]
    actual_images = {"cilium-agent": container_image(cilium, "cilium-agent"), "cilium-envoy": container_image(envoy, "cilium-envoy"), "cilium-operator": container_image(operator, "cilium-operator")}
    if actual_images != images:
        return "FAIL-CILIUM-IMAGE", {"actual": actual_images}
    pods = values.get("cilium-pods", {}).get("items", [])
    if len(pods) != expected:
        return "WAIT-CILIUM-PODS", {"count": len(pods)}
    pod_nodes = set()
    for pod in pods:
        meta, pod_spec, status = pod.get("metadata", {}), pod.get("spec", {}), pod.get("status", {})
        container_ready = {item.get("name"): item.get("ready") for item in status.get("containerStatuses", [])}
        if status.get("phase") != "Running" or container_ready.get("cilium-agent") is not True or not meta.get("uid"):
            return "WAIT-CILIUM-PODS", {"pod": meta.get("name")}
        pod_nodes.add(pod_spec.get("nodeName"))
    if pod_nodes != node_names:
        return "FAIL-CILIUM-POD-NODE-COVERAGE", {}
    chosen = sorted(pods, key=lambda item: item["metadata"]["name"])[0]
    return "PASS-STATIC-NETWORK-SOURCES", {
        "nodes": sorted(node_evidence, key=lambda item: item["name"]),
        "nodeNames": sorted(node_names),
        "images": actual_images,
        "ciliumDaemonSetUID": cilium["metadata"]["uid"],
        "envoyDaemonSetUID": envoy["metadata"]["uid"],
        "operatorDeploymentUID": operator["metadata"]["uid"],
        "probePod": {"name": chosen["metadata"]["name"], "uid": chosen["metadata"]["uid"]},
    }


def path_ok(path: Any) -> tuple[bool, list[str]]:
    if not isinstance(path, dict):
        return False, []
    timestamps = []
    for protocol in ("http", "icmp"):
        item = path.get(protocol)
        if not isinstance(item, dict) or item.get("status") != "" or not item.get("lastProbed"):
            return False, timestamps
        timestamps.append(item["lastProbed"])
    return True, timestamps


def evaluate_probe(payload: dict[str, Any], expected_nodes: list[str], now: dt.datetime, maximum_age: int) -> tuple[str, dict[str, Any]]:
    timestamp = parse_time(payload.get("timestamp", ""))
    if abs((now - timestamp).total_seconds()) > maximum_age:
        return "FAIL-STALE-FUNCTIONAL-PROBE", {}
    nodes = payload.get("nodes", [])
    if sorted(item.get("name") for item in nodes) != sorted(expected_nodes):
        return "FAIL-PROBE-NODE-COVERAGE", {}
    last_probed = []
    for node in nodes:
        for section in ("host", "health-endpoint"):
            ok, timestamps = path_ok(node.get(section, {}).get("primary-address"))
            if not ok:
                return "FAIL-FUNCTIONAL-CONNECTIVITY", {"node": node.get("name"), "section": section}
            last_probed.extend(timestamps)
    if any(abs((now - parse_time(value)).total_seconds()) > maximum_age for value in last_probed):
        return "FAIL-STALE-FUNCTIONAL-PATH", {}
    return "PASS-FUNCTIONAL-NETWORK-PROBE", {"timestamp": timestamp.isoformat(), "nodeCount": len(nodes), "successfulPathCount": len(last_probed)}


def run_raw(kubectl: Path, kubeconfig: Path, uri: str, runner: Callable[..., Any]) -> dict[str, Any]:
    completed = runner([str(kubectl), "--kubeconfig", str(kubeconfig), "get", "--raw", uri], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if completed.returncode != 0:
        raise NetworkObserverError("bounded raw GET failed")
    value = json.loads(completed.stdout)
    if not isinstance(value, dict):
        raise NetworkObserverError("bounded raw GET returned non-object")
    return value


def write_exclusive(path: Path, value: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(value)


def verify_runtime_file(path: Path, expected_digest: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or digest(path) != expected_digest:
        raise NetworkObserverError("predecessor evidence identity mismatch")
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise NetworkObserverError("predecessor evidence is not an object")
    return value


def execute(candidate_path: Path, grant_path: Path, lifecycle_path: Path, hcp_submission_path: Path, management_client: Path, workload_client: Path, now: dt.datetime | None = None, runner: Callable[..., Any] = subprocess.run, sleeper: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    candidate = validate_candidate(candidate_path)
    grant = validate_grant(candidate_path, grant_path, now)
    spec, grant_spec = candidate["spec"], grant["spec"]
    lifecycle = verify_runtime_file(lifecycle_path, grant_spec["lifecycleEvidenceDigest"])
    if lifecycle.get("closureState") != "PASS-CURRENT-LIFECYCLE-API-EVIDENCE":
        raise NetworkObserverError("lifecycle predecessor did not pass")
    hcp_submission = verify_runtime_file(hcp_submission_path, grant_spec["hcpSubmissionEvidenceDigest"])
    if hcp_submission.get("operation") != "helmchartproxy" or hcp_submission.get("semanticDigest") != "sha256:cd1a21b0b611a3a928e6e7d63d7eb2c4b4657570152ac3c6ae6061a48d4b788e":
        raise NetworkObserverError("HCP submission predecessor mismatch")
    mgmt_kubeconfig = Path(spec["management"]["credentialPath"])
    if mgmt_kubeconfig.is_symlink() or not mgmt_kubeconfig.is_file() or (mgmt_kubeconfig.stat().st_mode & 0o777) != 0o600:
        raise NetworkObserverError("unsafe management kubeconfig")
    mgmt_identity = EXECUTOR.inspect_identity(mgmt_kubeconfig)
    expect(mgmt_identity["identityDigest"], spec["management"]["credentialIdentityDigest"], "management credential identity")
    if digest(workload_client) != spec["workload"]["clientDigest"]:
        raise NetworkObserverError("workload kubectl digest mismatch")
    if digest(management_client) != "sha256:bb211f2b31f2b3bc60562b44cc1e3b712a16a98e9072968ba255beb04cefcfdf":
        raise NetworkObserverError("management kubectl digest mismatch")
    output = Path(spec["observation"]["outputPath"])
    ephemeral = Path(spec["workload"]["ephemeralKubeconfigPath"])
    if output.exists() or ephemeral.exists():
        raise NetworkObserverError("exclusive runtime output already exists")
    started = dt.datetime.now(dt.timezone.utc)
    history = []
    final_state, details = "TIMEOUT-NETWORK-NOT-READY", {}
    workload_identity: dict[str, str] | None = None
    probe_performed = False
    reviewed_hcp = read_yaml(resolve(candidate_path, spec["predecessor"]["hcpPath"]))
    try:
        for iteration in range(1, spec["observation"]["maximumIterations"] + 1):
            mgmt = {item["id"]: run_raw(management_client, mgmt_kubeconfig, item["rawURI"], runner) for item in spec["management"]["queries"]}
            management_state, management_details = evaluate_management(candidate, mgmt, lifecycle, reviewed_hcp)
            if management_state == "PASS-MANAGEMENT-ENABLEMENT":
                raw = base64.b64decode(management_details.pop("kubeconfigData"), validate=True)
                write_exclusive(ephemeral, raw)
                workload_identity = EXECUTOR.inspect_identity(ephemeral)
                endpoint = management_details.pop("endpoint")
                parsed = urlparse(workload_identity["server"])
                if parsed.hostname != endpoint.get("host") or parsed.port != endpoint.get("port"):
                    final_state, details = "FAIL-WORKLOAD-ENDPOINT-CORRELATION", management_details
                    break
                workload = {item["id"]: run_raw(workload_client, ephemeral, item["rawURI"], runner) for item in spec["workload"]["queries"]}
                workload_state, workload_details = evaluate_workload(candidate, workload)
                if workload_state == "PASS-STATIC-NETWORK-SOURCES":
                    pod = workload_details["probePod"]["name"]
                    command = [str(workload_client), "--kubeconfig", str(ephemeral), "exec", "--namespace", "kube-system", pod, "--container", "cilium-agent", "--", *spec["sources"]["cilium"]["functionalProbe"]]
                    probe_performed = True
                    completed = runner(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
                    if completed.returncode != 0:
                        final_state, details = "FAIL-FUNCTIONAL-PROBE-EXEC", {**management_details, **workload_details}
                    else:
                        probe_state, probe_details = evaluate_probe(json.loads(completed.stdout), workload_details["nodeNames"], now or dt.datetime.now(dt.timezone.utc), spec["observation"]["functionalProbeMaximumAgeSeconds"])
                        final_state, details = probe_state, {**management_details, **workload_details, "functionalProbe": probe_details}
                        if probe_state == "PASS-FUNCTIONAL-NETWORK-PROBE":
                            final_state = "PASS-NETWORK-READY"
                    break
                final_state, details = workload_state, {**management_details, **workload_details}
                ephemeral.unlink(missing_ok=True)
            else:
                final_state, details = management_state, management_details
            history.append({"iteration": iteration, "state": final_state})
            if final_state.startswith("FAIL-"):
                break
            if iteration < spec["observation"]["maximumIterations"]:
                sleeper(spec["observation"]["intervalSeconds"])
        history.append({"iteration": len(history) + 1, "state": final_state})
    finally:
        ephemeral.unlink(missing_ok=True)
    evidence = {
        "apiVersion": "evidence.openkubes.io/v1alpha1",
        "kind": "GO1LNetworkReadyEvidence",
        "candidateDigest": digest(candidate_path),
        "grantID": grant_spec["grantID"],
        "protocolDigest": spec["protocol"]["digest"],
        "fixtureDigest": spec["protocol"]["fixtureDigest"],
        "R": spec["protocol"]["R"],
        "E": spec["protocol"]["E"],
        "lifecycleEvidenceDigest": grant_spec["lifecycleEvidenceDigest"],
        "hcpSubmissionEvidenceDigest": grant_spec["hcpSubmissionEvidenceDigest"],
        "managementCredentialIdentityDigest": mgmt_identity["identityDigest"],
        "workloadTargetIdentityDigest": workload_identity["identityDigest"] if workload_identity else None,
        "startedAt": started.isoformat(),
        "completedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "iterations": history,
        "closureState": final_state,
        "NetworkReady": final_state == "PASS-NETWORK-READY",
        "details": details,
        "workloadKubeconfigRemoved": not ephemeral.exists(),
        "secretPayloadRetained": False,
        "rawProbeOutputRetained": False,
        "persistentMutationPerformed": False,
        "fixedPodExecProbePerformed": probe_performed,
    }
    evidence["semanticDigest"] = canonical_digest({key: value for key, value in evidence.items() if key not in ("startedAt", "completedAt", "semanticDigest")})
    write_exclusive(output, (json.dumps(evidence, sort_keys=True, separators=(",", ":")) + "\n").encode())
    if final_state != "PASS-NETWORK-READY":
        raise NetworkObserverError(f"NetworkReady did not pass: {final_state}")
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "verify-grant", "observe"))
    parser.add_argument("--candidate", type=Path, default=CANDIDATE)
    parser.add_argument("--grant", type=Path)
    parser.add_argument("--lifecycle-evidence", type=Path)
    parser.add_argument("--hcp-submission-evidence", type=Path)
    parser.add_argument("--management-kubectl", type=Path)
    parser.add_argument("--workload-kubectl", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "verify":
            validate_candidate(args.candidate.resolve())
            print(digest(args.candidate.resolve()))
        elif args.command == "verify-grant":
            if args.grant is None:
                raise NetworkObserverError("grant is required")
            validate_grant(args.candidate.resolve(), args.grant.resolve())
            print(digest(args.grant.resolve()))
        else:
            required = (args.grant, args.lifecycle_evidence, args.hcp_submission_evidence, args.management_kubectl, args.workload_kubectl)
            if not args.execute or any(value is None for value in required):
                raise NetworkObserverError("observe requires --execute and all bound runtime inputs")
            result = execute(args.candidate.resolve(), args.grant.resolve(), args.lifecycle_evidence.resolve(), args.hcp_submission_evidence.resolve(), args.management_kubectl.resolve(), args.workload_kubectl.resolve())
            print(json.dumps({"closureState": result["closureState"], "semanticDigest": result["semanticDigest"]}, sort_keys=True))
        return 0
    except (NetworkObserverError, OSError, KeyError, TypeError, ValueError, yaml.YAMLError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
