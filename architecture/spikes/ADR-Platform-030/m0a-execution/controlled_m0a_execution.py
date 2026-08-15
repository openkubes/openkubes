#!/usr/bin/env python3
"""Digest-bound M0A-C1 + M0a-I executor; refuses all mutation without two grants."""

from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import json
import os
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable

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


INSTALLER = _load("ok141_m0a_bounded_installer", SPIKE / "installation-closure" / "bounded_installer.py")
EXPECTED_CONTROLLER_IMAGE_DIGEST = "sha256:66344ab0107c0a3fcbce860697206ac7e6a2316a7af4a07f81a9f8d53e448e6a"


class ExecutionError(ValueError):
    pass


RESOURCE_MAP = {
    "Namespace": ("namespaces", None),
    "CustomResourceDefinition": ("customresourcedefinitions.apiextensions.k8s.io", None),
    "ServiceAccount": ("serviceaccounts", "caaph-system"),
    "Role": ("roles.rbac.authorization.k8s.io", "caaph-system"),
    "ClusterRole": ("clusterroles.rbac.authorization.k8s.io", None),
    "RoleBinding": ("rolebindings.rbac.authorization.k8s.io", "caaph-system"),
    "ClusterRoleBinding": ("clusterrolebindings.rbac.authorization.k8s.io", None),
    "ConfigMap": ("configmaps", "caaph-system"),
    "Service": ("services", "caaph-system"),
    "Deployment": ("deployments.apps", "caaph-system"),
    "Certificate": ("certificates.cert-manager.io", "caaph-system"),
    "Issuer": ("issuers.cert-manager.io", "caaph-system"),
    "MutatingWebhookConfiguration": ("mutatingwebhookconfigurations.admissionregistration.k8s.io", None),
    "ValidatingWebhookConfiguration": ("validatingwebhookconfigurations.admissionregistration.k8s.io", None),
}


def sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def expect(actual: Any, expected: Any, claim: str) -> None:
    if actual != expected:
        raise ExecutionError(f"{claim}: expected {expected!r}, got {actual!r}")


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode() + b"\n"


def read_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text())
    if not isinstance(value, dict):
        raise ExecutionError(f"expected mapping in {path}")
    return value


def resolve(base: Path, reference: dict[str, Any]) -> Path:
    path = (base / reference["path"]).resolve()
    if SPIKE.resolve() not in path.parents or not path.is_file():
        raise ExecutionError(f"reference missing or outside spike root: {path}")
    expect(sha(path), reference["digest"], f"digest for {reference['path']}")
    return path


def verify_candidate(path: Path) -> tuple[dict[str, Any], dict[str, Path]]:
    document = read_yaml(path)
    spec = document["spec"]
    expect(spec["state"], "READY-FOR-SEPARATE-EXPLICIT-GRANTS", "candidate state")
    refs = {name: resolve(path.parent, ref) for name, ref in spec["references"].items()}
    expect(refs["executor"].resolve(), Path(__file__).resolve(), "executor identity")
    expect(spec["target"]["kubeSystemNamespaceUID"], "c3b45aab-d2a1-4e64-8f12-77b99186ad4a", "target UID")
    expect(spec["fixtureDigest"], "sha256:a2ae3437645db5a83426b89d36d00693d2600e4ef20dc1aba2650dcda7f936f6", "fixture digest")
    expect(spec["credential"]["maximumDurationMinutes"], 60, "credential duration")
    expect(spec["executionWindow"]["maximumDurationMinutes"], 180, "window duration")
    expect(spec["executionWindow"]["maximumClockSkewSeconds"], 5, "maximum clock skew")
    expect(spec["authorization"], {
        "decision": "NO-GO",
        "mutationAuthorized": False,
        "credentialGrantRequired": True,
        "installationGrantRequired": True,
        "m0bInstallationGranted": False,
        "go1Granted": False,
        "failureInjectionGranted": False,
    }, "candidate authorization")
    return document, refs


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo != timezone.utc:
        raise ExecutionError("grant timestamps must be UTC")
    return parsed


def verify_grant(candidate_path: Path, grant_path: Path, now: datetime | None = None) -> dict[str, Any]:
    candidate, _ = verify_candidate(candidate_path)
    grant = read_yaml(grant_path)["spec"]
    expect(grant["version"], "ok141-m0a-combined-grant/v1", "grant version")
    expect(grant["candidateDigest"], sha(candidate_path), "candidate grant binding")
    expect(grant["authority"], "github:arashkaffamanesh", "grant authority")
    expect(grant["decision"], "GO", "grant decision")
    expect(grant["mutationAuthorized"], True, "mutation authority")
    expect(grant["credentialGrant"]["gate"], "M0A-C1", "credential gate")
    expect(grant["credentialGrant"]["granted"], True, "credential grant")
    expect(grant["installationGrant"]["gate"], "M0A-I", "installation gate")
    expect(grant["installationGrant"]["granted"], True, "installation grant")
    if grant["credentialGrant"]["grantID"] == grant["installationGrant"]["grantID"]:
        raise ExecutionError("credential and installation grants require distinct IDs")
    start = parse_utc(grant["validFrom"])
    end = parse_utc(grant["validUntil"])
    if end <= start or (end - start).total_seconds() > candidate["spec"]["executionWindow"]["maximumDurationMinutes"] * 60:
        raise ExecutionError("grant window is invalid or too long")
    current = now or datetime.now(timezone.utc)
    if current < start or current > end:
        raise ExecutionError("current time is outside the exact grant window")
    expect(grant["maximumRuns"], 1, "maximum run count")
    expect(grant["rollbackGranted"], False, "rollback exclusion")
    expect(grant["targetConvergenceGranted"], False, "target convergence exclusion")
    expect(grant["go1Granted"], False, "GO-1 exclusion")
    return grant


def run(command: list[str], *, input_bytes: bytes | None = None, check: bool = True, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(command, input=input_bytes, check=check, capture_output=True, env=env, timeout=60)


def kubectl(admin_kubeconfig: Path, args: list[str], *, input_bytes: bytes | None = None, check: bool = True) -> subprocess.CompletedProcess:
    forbidden = {"exec", "edit", "debug", "cp", "port-forward", "proxy"}
    if forbidden.intersection(args):
        raise ExecutionError("forbidden kubectl operation")
    return run(["kubectl", "--kubeconfig", str(admin_kubeconfig), *args], input_bytes=input_bytes, check=check)


def json_get(kubeconfig: Path, args: list[str]) -> dict[str, Any]:
    completed = kubectl(kubeconfig, [*args, "-o", "json"])
    return json.loads(completed.stdout)


def ensure_absent(kubeconfig: Path, args: list[str], claim: str) -> None:
    completed = kubectl(kubeconfig, args, check=False)
    if completed.returncode == 0:
        raise ExecutionError(f"{claim} already exists")
    stderr = completed.stderr.decode(errors="replace")
    if "NotFound" not in stderr and "not found" not in stderr:
        raise ExecutionError(f"cannot prove {claim} absent")


def ensure_no_namespaced_collisions(admin_kubeconfig: Path, reviewed: Any) -> None:
    checked: set[str] = set()
    for item in reviewed.documents:
        resource, namespace = RESOURCE_MAP[item["kind"]]
        if not namespace or resource in checked:
            continue
        checked.add(resource)
        collection = json_get(admin_kubeconfig, ["get", resource, "--all-namespaces"])
        expected_names = {
            candidate["metadata"]["name"]
            for candidate in reviewed.documents
            if RESOURCE_MAP[candidate["kind"]][0] == resource
        }
        collisions = [
            f"{candidate['metadata'].get('namespace')}/{candidate['metadata']['name']}"
            for candidate in collection.get("items", [])
            if candidate["metadata"]["name"] in expected_names
            and candidate["metadata"].get("namespace") != "caaph-system"
        ]
        if collisions:
            raise ExecutionError(f"same-named namespaced target collision: {sorted(collisions)}")


def verify_clock(maximum_skew_seconds: int) -> dict[str, Any]:
    before = datetime.now(timezone.utc)
    request = urllib.request.Request(
        f"https://api.github.com/zen?ok141={int(before.timestamp())}",
        method="HEAD",
        headers={"Cache-Control": "no-cache", "Pragma": "no-cache", "User-Agent": "openkubes-ok141-m0a"},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        date_header = response.headers.get("Date")
    after = datetime.now(timezone.utc)
    if not date_header:
        raise ExecutionError("independent UTC source returned no Date header")
    independent = parsedate_to_datetime(date_header).astimezone(timezone.utc)
    midpoint = before + (after - before) / 2
    skew = abs((midpoint - independent).total_seconds())
    if skew > maximum_skew_seconds:
        raise ExecutionError(f"UTC skew {skew:.3f}s exceeds {maximum_skew_seconds}s")
    return {
        "source": "github-api-date-header-no-cache",
        "observedAt": midpoint.isoformat().replace("+00:00", "Z"),
        "skewSeconds": round(skew, 3),
        "roundTripSeconds": round((after - before).total_seconds(), 3),
    }


def verify_bootstrap_identity(admin_kubeconfig: Path) -> dict[str, str]:
    config = read_yaml(admin_kubeconfig)
    current = config.get("current-context")
    context = next((item["context"] for item in config.get("contexts", []) if item["name"] == current), None)
    if not context or context.get("user") != "ok-mgmt-admin":
        raise ExecutionError("bootstrap kubeconfig context or user identity differs")
    user = next((item["user"] for item in config.get("users", []) if item["name"] == context["user"]), None)
    if not user or not user.get("client-certificate-data") or not user.get("client-key-data"):
        raise ExecutionError("bootstrap kubeconfig is not the expected embedded certificate identity")
    certificate = base64.b64decode(user["client-certificate-data"])
    pem = certificate.decode() if certificate.startswith(b"-----BEGIN CERTIFICATE-----") else ssl.DER_cert_to_PEM_cert(certificate)
    fd, name = tempfile.mkstemp(prefix="ok141-m0a-cert-", suffix=".pem")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as handle:
            handle.write(pem)
        decoded = ssl._ssl._test_decode_cert(name)
    finally:
        Path(name).unlink(missing_ok=True)
    subject = {key: value for group in decoded["subject"] for key, value in group}
    expect(subject.get("commonName"), "kubernetes-admin", "bootstrap certificate CN")
    expect(subject.get("organizationName"), "system:masters", "bootstrap certificate organization")
    if not auth_can_i(admin_kubeconfig, "*", "*"):
        raise ExecutionError("bootstrap identity no longer has the accepted administrator authority")
    return {"username": "kubernetes-admin", "group": "system:masters", "certificateNotAfter": decoded["notAfter"]}


def live_preflight(candidate: dict[str, Any], refs: dict[str, Path], admin_kubeconfig: Path) -> dict[str, Any]:
    spec = candidate["spec"]
    expect(admin_kubeconfig.resolve(), Path(spec["target"]["adminKubeconfigPath"]).resolve(), "admin kubeconfig path")
    bootstrap_identity = verify_bootstrap_identity(admin_kubeconfig)
    identity = json_get(admin_kubeconfig, ["get", "namespace", "kube-system"])
    expect(identity["metadata"]["uid"], spec["target"]["kubeSystemNamespaceUID"], "live target UID")
    version = json.loads(kubectl(admin_kubeconfig, ["get", "--raw=/version"]).stdout)
    expect(version["gitVersion"], spec["target"]["kubernetesVersion"], "live Kubernetes version")
    for kind, name, namespace in (
        ("serviceaccount", "ok141-m0a-installer", "openkubes-system"),
        ("clusterrole", "ok141-m0a-installer", None),
        ("clusterrolebinding", "ok141-m0a-installer", None),
        ("namespace", "caaph-system", None),
        ("customresourcedefinition", "helmchartproxies.addons.cluster.x-k8s.io", None),
        ("customresourcedefinition", "helmreleaseproxies.addons.cluster.x-k8s.io", None),
    ):
        args = ["get", kind, name]
        if namespace:
            args.extend(["--namespace", namespace])
        ensure_absent(admin_kubeconfig, args, f"{kind}/{name}")
    reviewed = INSTALLER.verify_reviewed_object_set(read_yaml(refs["installationProtocol"]), refs["installationProtocol"])
    expect(reviewed.semantic_digest, spec["installation"]["semanticDigest"], "reviewed semantic digest")
    ensure_no_namespaced_collisions(admin_kubeconfig, reviewed)
    lifecycle = {}
    for key, resource in (
        ("clusters", "clusters.cluster.x-k8s.io"),
        ("machines", "machines.cluster.x-k8s.io"),
        ("machineDeployments", "machinedeployments.cluster.x-k8s.io"),
    ):
        lifecycle[key] = len(json_get(admin_kubeconfig, ["get", resource, "--all-namespaces"]).get("items", []))
    expect(lifecycle, {"clusters": 0, "machines": 0, "machineDeployments": 0}, "live CAPI inventory")
    return {
        "targetUID": identity["metadata"]["uid"],
        "kubernetesVersion": version["gitVersion"],
        "reviewedObjectCount": len(reviewed.documents),
        "reviewedSemanticDigest": reviewed.semantic_digest,
        "lifecycleInventory": lifecycle,
        "namespacedCollisions": 0,
        "bootstrapIdentity": bootstrap_identity,
    }


def temporary_kubeconfig(admin_kubeconfig: Path, token: str, candidate: dict[str, Any]) -> Path:
    admin = read_yaml(admin_kubeconfig)
    current = admin["current-context"]
    context = next(item["context"] for item in admin["contexts"] if item["name"] == current)
    cluster = next(item["cluster"] for item in admin["clusters"] if item["name"] == context["cluster"])
    target = candidate["spec"]["target"]
    expect(cluster["server"], target["apiServer"], "admin target server")
    config = {
        "apiVersion": "v1",
        "kind": "Config",
        "clusters": [{"name": "ok-mgmt", "cluster": cluster}],
        "contexts": [{"name": "ok141-m0a-installer@ok-mgmt", "context": {"cluster": "ok-mgmt", "user": "ok141-m0a-installer"}}],
        "current-context": "ok141-m0a-installer@ok-mgmt",
        "users": [{"name": "ok141-m0a-installer", "user": {"token": token}}],
    }
    fd, name = tempfile.mkstemp(prefix="ok141-m0a-", suffix=".kubeconfig")
    try:
        os.fchmod(fd, 0o600)
        os.write(fd, yaml.safe_dump(config, sort_keys=False).encode())
    finally:
        os.close(fd)
    return Path(name)


def auth_can_i(kubeconfig: Path, verb: str, resource: str, name: str | None = None, namespace: str | None = None) -> bool:
    target = f"{resource}/{name}" if name else resource
    args = ["auth", "can-i", verb, target]
    if namespace:
        args.extend(["--namespace", namespace])
    completed = kubectl(kubeconfig, args, check=False)
    return completed.returncode == 0 and completed.stdout.decode().strip() == "yes"


def authorization_probes(kubeconfig: Path, reviewed: Any) -> dict[str, Any]:
    positive = []
    for item in reviewed.documents:
        resource, default_namespace = RESOURCE_MAP[item["kind"]]
        namespace = item["metadata"].get("namespace", default_namespace)
        name = item["metadata"]["name"]
        for verb in ("get", "patch"):
            if not auth_can_i(kubeconfig, verb, resource, name, namespace):
                raise ExecutionError(f"positive authorization probe failed: {verb} {resource}/{name}")
        positive.append(f"{resource}/{name}")
    negative_requests = [
        ("get", "secrets", None, "caaph-system"),
        ("create", "secrets", None, "caaph-system"),
        ("list", "deployments.apps", None, "caaph-system"),
        ("delete", "namespaces", "caaph-system", None),
        ("patch", "namespaces", "unrelated", None),
        ("patch", "clusterroles.rbac.authorization.k8s.io", "unrelated", None),
        ("create", "serviceaccounts/token", None, "openkubes-system"),
        ("impersonate", "users", "system:admin", None),
    ]
    for verb, resource, name, namespace in negative_requests:
        if auth_can_i(kubeconfig, verb, resource, name, namespace):
            raise ExecutionError(f"negative authorization probe unexpectedly allowed: {verb} {resource}")
    return {"positiveTargets": len(positive), "negativeProbes": len(negative_requests)}


def wait_ready(admin_kubeconfig: Path, timeout_seconds: int = 600) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last = "not observed"
    while time.monotonic() < deadline:
        try:
            deployment = json_get(admin_kubeconfig, ["--namespace", "caaph-system", "get", "deployment", "caaph-controller-manager"])
            cert = json_get(admin_kubeconfig, ["--namespace", "caaph-system", "get", "certificate", "caaph-serving-cert"])
            crds = [
                json_get(admin_kubeconfig, ["get", "customresourcedefinition", name])
                for name in ("helmchartproxies.addons.cluster.x-k8s.io", "helmreleaseproxies.addons.cluster.x-k8s.io")
            ]
            endpoints = [
                json_get(admin_kubeconfig, ["--namespace", "caaph-system", "get", "endpoints", name])
                for name in ("caaph-controller-manager-metrics-service", "caaph-webhook-service")
            ]
            pods = json_get(admin_kubeconfig, ["--namespace", "caaph-system", "get", "pods", "--selector", "cluster.x-k8s.io/provider=helm,control-plane=controller-manager"])
            dep_ready = deployment.get("status", {}).get("availableReplicas", 0) >= 1 and deployment.get("status", {}).get("observedGeneration") == deployment["metadata"].get("generation")
            cert_ready = any(item.get("type") == "Ready" and item.get("status") == "True" for item in cert.get("status", {}).get("conditions", []))
            crd_ready = all(any(item.get("type") == "Established" and item.get("status") == "True" for item in crd.get("status", {}).get("conditions", [])) for crd in crds)
            endpoints_ready = all(any(subset.get("addresses") for subset in item.get("subsets", [])) for item in endpoints)
            pod_items = pods.get("items", [])
            image_ids = [status.get("imageID", "") for pod in pod_items for status in pod.get("status", {}).get("containerStatuses", [])]
            pod_ready = len(pod_items) == 1 and any(item.endswith("@" + EXPECTED_CONTROLLER_IMAGE_DIGEST) for item in image_ids)
            if dep_ready and cert_ready and crd_ready and endpoints_ready and pod_ready:
                hcp = json_get(admin_kubeconfig, ["get", "helmchartproxies.addons.cluster.x-k8s.io", "--all-namespaces"])
                hrp = json_get(admin_kubeconfig, ["get", "helmreleaseproxies.addons.cluster.x-k8s.io", "--all-namespaces"])
                expect(len(hcp.get("items", [])), 0, "HelmChartProxy inventory")
                expect(len(hrp.get("items", [])), 0, "HelmReleaseProxy inventory")
                return {"deploymentAvailable": True, "certificateReady": True, "crdsEstablished": 2, "serviceEndpointsReady": 2, "controllerImageDigest": EXPECTED_CONTROLLER_IMAGE_DIGEST, "targetResources": 0}
            last = f"deployment={dep_ready} certificate={cert_ready} crds={crd_ready} endpoints={endpoints_ready} podImage={pod_ready}"
        except (ExecutionError, KeyError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
            last = str(exc)
        time.sleep(5)
    raise ExecutionError(f"CAAPH readiness timeout: {last}")


def object_evidence(admin_kubeconfig: Path, reviewed: Any) -> list[dict[str, Any]]:
    evidence = []
    for item in reviewed.documents:
        resource, default_namespace = RESOURCE_MAP[item["kind"]]
        namespace = item["metadata"].get("namespace", default_namespace)
        args = ["get", resource, item["metadata"]["name"]]
        if namespace:
            args.extend(["--namespace", namespace])
        live = json_get(admin_kubeconfig, args)
        metadata = live["metadata"]
        evidence.append({
            "apiVersion": live["apiVersion"],
            "kind": live["kind"],
            "namespace": metadata.get("namespace"),
            "name": metadata["name"],
            "uid": metadata["uid"],
            "generation": metadata.get("generation"),
            "creationTimestamp": metadata.get("creationTimestamp"),
        })
    return evidence


def discover_credential_objects(admin_kubeconfig: Path) -> dict[str, str]:
    live: dict[str, str] = {}
    for key, kind, name, namespace in (
        ("ServiceAccount", "serviceaccount", "ok141-m0a-installer", "openkubes-system"),
        ("ClusterRole", "clusterrole", "ok141-m0a-installer", None),
        ("ClusterRoleBinding", "clusterrolebinding", "ok141-m0a-installer", None),
    ):
        args = ["get", kind, name]
        if namespace:
            args.extend(["--namespace", namespace])
        completed = kubectl(admin_kubeconfig, [*args, "-o", "json"], check=False)
        if completed.returncode != 0:
            stderr = completed.stderr.decode(errors="replace")
            if "NotFound" in stderr or "not found" in stderr:
                continue
            raise ExecutionError(f"cannot inspect credential object {kind}/{name}")
        item = json.loads(completed.stdout)
        labels = item["metadata"].get("labels", {})
        if labels.get("openkubes.io/ticket") != "OK-141" or labels.get("openkubes.io/gate") != "M0A-C1":
            raise ExecutionError(f"credential object {kind}/{name} has foreign ownership")
        live[key] = item["metadata"]["uid"]
    return live


def revoke(admin_kubeconfig: Path, expected_uids: dict[str, str]) -> dict[str, Any]:
    live = discover_credential_objects(admin_kubeconfig)
    for key, uid in live.items():
        if key in expected_uids and expected_uids[key] != uid:
            raise ExecutionError(f"credential object {key} UID changed before revocation")
    for key, kind, name, namespace in (
        ("ServiceAccount", "serviceaccount", "ok141-m0a-installer", "openkubes-system"),
        ("ClusterRoleBinding", "clusterrolebinding", "ok141-m0a-installer", None),
        ("ClusterRole", "clusterrole", "ok141-m0a-installer", None),
    ):
        if key not in live:
            continue
        args = ["delete", kind, name, "--wait=true"]
        if namespace:
            args.extend(["--namespace", namespace])
        kubectl(admin_kubeconfig, args)
    for kind, name, namespace in (
        ("serviceaccount", "ok141-m0a-installer", "openkubes-system"),
        ("clusterrole", "ok141-m0a-installer", None),
        ("clusterrolebinding", "ok141-m0a-installer", None),
    ):
        args = ["get", kind, name]
        if namespace:
            args.extend(["--namespace", namespace])
        ensure_absent(admin_kubeconfig, args, f"revoked {kind}/{name}")
    return {"revoked": True, "objectUIDs": live}


def execute(candidate_path: Path, grant_path: Path, admin_kubeconfig: Path, evidence_output: Path) -> dict[str, Any]:
    candidate, refs = verify_candidate(candidate_path)
    grant = verify_grant(candidate_path, grant_path)
    clock = verify_clock(candidate["spec"]["executionWindow"]["maximumClockSkewSeconds"])
    preflight = live_preflight(candidate, refs, admin_kubeconfig)
    reviewed = INSTALLER.verify_reviewed_object_set(read_yaml(refs["installationProtocol"]), refs["installationProtocol"])
    rbac_manifest = refs["credentialManifest"]
    temp_config: Path | None = None
    credential_uids: dict[str, str] = {}
    bootstrap_started = False
    evidence: dict[str, Any] = {
        "version": "ok141-m0a-execution-evidence/v1",
        "candidateDigest": sha(candidate_path),
        "grantDigest": sha(grant_path),
        "fixtureDigest": candidate["spec"]["fixtureDigest"],
        "target": preflight,
        "clock": clock,
        "startedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "result": "STARTED",
        "secretMaterialRetained": False,
    }
    try:
        bootstrap_started = True
        kubectl(admin_kubeconfig, ["apply", "--server-side", "--field-manager", candidate["spec"]["credential"]["fieldManager"], "--filename", "-"], input_bytes=rbac_manifest.read_bytes())
        credential_uids = discover_credential_objects(admin_kubeconfig)
        expect(set(credential_uids), {"ServiceAccount", "ClusterRole", "ClusterRoleBinding"}, "credential bootstrap inventory")
        token_result = kubectl(admin_kubeconfig, ["--namespace", "openkubes-system", "create", "token", "ok141-m0a-installer", "--duration=60m", "--audience", candidate["spec"]["target"]["apiAudience"]])
        token = token_result.stdout.decode().strip()
        if len(token) < 80:
            raise ExecutionError("TokenRequest returned an invalid token")
        temp_config = temporary_kubeconfig(admin_kubeconfig, token, candidate)
        token = ""
        probes = authorization_probes(temp_config, reviewed)
        kubectl(temp_config, ["apply", "--server-side", "--field-manager", candidate["spec"]["installation"]["fieldManager"], "--filename", "-"], input_bytes=reviewed.payload)
        readiness = wait_ready(admin_kubeconfig, candidate["spec"]["installation"]["readinessTimeoutSeconds"])
        objects = object_evidence(admin_kubeconfig, reviewed)
        evidence.update({"authorizationProbes": probes, "readiness": readiness, "objects": objects, "result": "SUCCESS"})
        return evidence
    except Exception as exc:
        evidence.update({"result": "STOP-NOT-SUCCESS", "failureType": type(exc).__name__, "failure": str(exc)})
        raise
    finally:
        if bootstrap_started:
            try:
                evidence["revocation"] = revoke(admin_kubeconfig, credential_uids)
                if temp_config is None:
                    raise ExecutionError("temporary credential was not available for revocation verification")
                token_probe = kubectl(temp_config, ["get", "--raw=/version"], check=False)
                if token_probe.returncode == 0:
                    raise ExecutionError("revoked ServiceAccount token still authenticates")
                token_stderr = token_probe.stderr.decode(errors="replace")
                if "Unauthorized" not in token_stderr and "logged in" not in token_stderr:
                    raise ExecutionError("token rejection was not an authentication rejection")
                evidence["revocation"]["tokenRejectedAfterRevocation"] = True
            except Exception as revoke_error:
                evidence["revocation"] = {"revoked": False, "failureType": type(revoke_error).__name__, "failure": str(revoke_error)}
                evidence["result"] = "STOP-NOT-SUCCESS"
        if temp_config is not None:
            temp_config.unlink(missing_ok=True)
        evidence["finishedAt"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        evidence_output.parent.mkdir(parents=True, exist_ok=True)
        evidence_output.write_bytes(canonical(evidence))


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("verify")
    check.add_argument("--candidate", type=Path, required=True)
    check.add_argument("--grant", type=Path)
    run_parser = sub.add_parser("execute")
    run_parser.add_argument("--candidate", type=Path, required=True)
    run_parser.add_argument("--grant", type=Path, required=True)
    run_parser.add_argument("--admin-kubeconfig", type=Path, required=True)
    run_parser.add_argument("--evidence-output", type=Path, required=True)
    run_parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "verify":
            candidate, _ = verify_candidate(args.candidate.resolve())
            result = {"candidateDigest": sha(args.candidate.resolve()), "state": candidate["spec"]["state"], "mutationAuthorized": False}
            if args.grant:
                result["grant"] = verify_grant(args.candidate.resolve(), args.grant.resolve())
            print(json.dumps(result, sort_keys=True, separators=(",", ":")))
            return 0
        if not args.execute:
            raise ExecutionError("execute command requires the explicit --execute flag")
        result = execute(args.candidate.resolve(), args.grant.resolve(), args.admin_kubeconfig.resolve(), args.evidence_output.resolve())
        if result["result"] != "SUCCESS" or not result.get("revocation", {}).get("tokenRejectedAfterRevocation"):
            raise ExecutionError("execution or mandatory credential revocation did not succeed")
        print(json.dumps({"result": result["result"], "evidenceOutput": str(args.evidence_output)}, sort_keys=True, separators=(",", ":")))
        return 0
    except (ExecutionError, INSTALLER.InstallerError, OSError, KeyError, TypeError, ValueError, yaml.YAMLError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
