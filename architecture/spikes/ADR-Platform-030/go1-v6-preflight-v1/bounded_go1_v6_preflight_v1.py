#!/usr/bin/env python3
"""Bounded read-only preflight for the OK-141 GO-1 v6 protocol."""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

import yaml


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
REPOSITORY = SPIKE.parents[2]
CANDIDATE = HERE / "go1-v6-preflight-candidate-v1.yaml"
EXPECTED_PROTOCOL_DIGEST = "sha256:e45e5f6b8254e666226aa874810bf2ca51f76f2411e0316adb52a7ce51254885"


class PreflightError(ValueError):
    pass


EXPECTED_CREDENTIAL_PATHS = {
    "ok-infra": "/Users/arash/.kube/ok-infra.yaml",
    "ok-mgmt": "/Users/arash/.kube/ok-mgmt.yaml",
    "ok-shared": "/Users/arash/.kube/ok-shared.yaml",
}
EXPECTED_ABSENCE_CLAIMS = [
    ("infra-namespace", "ok-infra", "v1|Namespace||disposable-ok141"),
    ("infra-image-role", "ok-infra", "rbac.authorization.k8s.io/v1|Role|ok-images|disposable-ok141-talos-golden-image-cloner"),
    ("infra-image-rolebinding", "ok-infra", "rbac.authorization.k8s.io/v1|RoleBinding|ok-images|disposable-ok141-talos-golden-image-cloner"),
    ("mgmt-namespace", "ok-mgmt", "v1|Namespace||disposable-ok141"),
    ("provider-access-secret", "ok-mgmt", "v1|Secret|disposable-ok141|external-infra-kubeconfig-disposable-ok141"),
    ("cluster", "ok-mgmt", "cluster.x-k8s.io/v1beta2|Cluster|disposable-ok141|disposable-ok141"),
    ("kubevirt-cluster", "ok-mgmt", "infrastructure.cluster.x-k8s.io/v1alpha1|KubevirtCluster|disposable-ok141|disposable-ok141"),
    ("talos-control-plane", "ok-mgmt", "controlplane.cluster.x-k8s.io/v1alpha3|TalosControlPlane|disposable-ok141|disposable-ok141-cp"),
    ("talos-worker-config", "ok-mgmt", "bootstrap.cluster.x-k8s.io/v1alpha3|TalosConfigTemplate|disposable-ok141|disposable-ok141-workers-v1-9-6"),
    ("machine-deployment", "ok-mgmt", "cluster.x-k8s.io/v1beta2|MachineDeployment|disposable-ok141|disposable-ok141-workers"),
    ("control-plane-template", "ok-mgmt", "infrastructure.cluster.x-k8s.io/v1alpha1|KubevirtMachineTemplate|disposable-ok141|disposable-ok141-cp-7f5dd4276432"),
    ("worker-template", "ok-mgmt", "infrastructure.cluster.x-k8s.io/v1alpha1|KubevirtMachineTemplate|disposable-ok141|disposable-ok141-workers-7f5dd4276432"),
    ("cilium-hcp", "ok-mgmt", "addons.cluster.x-k8s.io/v1alpha1|HelmChartProxy|disposable-ok141|disposable-ok141-cilium"),
]
EXPECTED_ABSENCE_QUERIES = [
    ("infra-namespace-query", "ok-infra", "namespaces", None, "disposable-ok141", "direct-absence", ("infra-namespace",)),
    ("infra-image-role-query", "ok-infra", "roles.rbac.authorization.k8s.io", "ok-images", "disposable-ok141-talos-golden-image-cloner", "direct-absence", ("infra-image-role",)),
    ("infra-image-rolebinding-query", "ok-infra", "rolebindings.rbac.authorization.k8s.io", "ok-images", "disposable-ok141-talos-golden-image-cloner", "direct-absence", ("infra-image-rolebinding",)),
    ("mgmt-namespace-query", "ok-mgmt", "namespaces", None, "disposable-ok141", "namespace-absence-implies-contained-object-absence", tuple(item[0] for item in EXPECTED_ABSENCE_CLAIMS[3:])),
]
EXPECTED_READINESS_QUERIES = [
    ("caaph-deployment", "ok-mgmt", "deployments.apps", "caaph-system", "caaph-controller-manager", "deployment-current-and-available"),
    ("caaph-certificate", "ok-mgmt", "certificates.cert-manager.io", "caaph-system", "caaph-serving-cert", "condition-ready"),
    ("caaph-hcp-crd", "ok-mgmt", "customresourcedefinitions.apiextensions.k8s.io", None, "helmchartproxies.addons.cluster.x-k8s.io", "condition-established"),
    ("caaph-hrp-crd", "ok-mgmt", "customresourcedefinitions.apiextensions.k8s.io", None, "helmreleaseproxies.addons.cluster.x-k8s.io", "condition-established"),
    ("caaph-metrics-endpoints", "ok-mgmt", "endpoints", "caaph-system", "caaph-controller-manager-metrics-service", "endpoint-address-present"),
    ("caaph-webhook-endpoints", "ok-mgmt", "endpoints", "caaph-system", "caaph-webhook-service", "endpoint-address-present"),
    ("argo-namespace", "ok-shared", "namespaces", None, "argocd", "phase-active"),
    ("argo-application-crd", "ok-shared", "customresourcedefinitions.apiextensions.k8s.io", None, "applications.argoproj.io", "condition-established"),
    ("argo-applicationset-crd", "ok-shared", "customresourcedefinitions.apiextensions.k8s.io", None, "applicationsets.argoproj.io", "condition-established"),
    ("argo-appproject-crd", "ok-shared", "customresourcedefinitions.apiextensions.k8s.io", None, "appprojects.argoproj.io", "condition-established"),
    ("argo-server", "ok-shared", "deployments.apps", "argocd", "argocd-server", "deployment-current-and-available"),
    ("argo-application-controller", "ok-shared", "statefulsets.apps", "argocd", "argocd-application-controller", "statefulset-current-and-ready"),
    ("argo-default-project", "ok-shared", "appprojects.argoproj.io", "argocd", "default", "object-present"),
]


def sha_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def sha(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def read(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text())
    if not isinstance(value, dict):
        raise PreflightError(f"expected mapping: {path}")
    return value


def expect(actual: Any, expected: Any, context: str) -> None:
    if actual != expected:
        raise PreflightError(f"{context}: expected {expected!r}, got {actual!r}")


def resolve(candidate_path: Path, requested: str) -> Path:
    path = (candidate_path.parent / requested).resolve()
    if SPIKE.resolve() not in path.parents or not path.is_file():
        raise PreflightError(f"reference missing or outside spike root: {requested}")
    return path


def validate_candidate(candidate_path: Path = CANDIDATE) -> dict[str, Any]:
    candidate = read(candidate_path)
    expect(candidate.get("apiVersion"), "test.openkubes.io/v1alpha1", "apiVersion")
    expect(candidate.get("kind"), "GO1V6PreflightCandidate", "kind")
    spec = candidate["spec"]
    expect(spec["version"], "ok141-go1-v6-preflight/v1", "version")
    expect(spec["state"], "OFFLINE-PROVEN-BLOCKED-NO-GO", "state")
    bindings = spec["bindings"]
    expect(bindings["protocol"]["digest"], EXPECTED_PROTOCOL_DIGEST, "protocol digest")
    for name, binding in bindings.items():
        expect(sha(resolve(candidate_path, binding["path"])), binding["digest"], f"{name} binding")
    expect(sha(resolve(candidate_path, spec["tool"]["path"])), spec["tool"]["digest"], "tool binding")
    expect(spec["tool"]["arbitraryCommandAllowed"], False, "arbitrary command boundary")
    expect(spec["tool"]["arbitraryQueryAllowed"], False, "arbitrary query boundary")
    authorization = spec["authorization"]
    expect(authorization["decision"], "NO-GO", "authorization")
    expect(authorization["grantIDs"], [], "grant inventory")
    expect(authorization["authorizedDigest"], None, "authorized digest")
    if any(value for key, value in authorization.items() if key.endswith("Granted")):
        raise PreflightError("candidate grants execution authority")
    credentials = {item["plane"]: item for item in spec["credentials"]}
    expect(set(credentials), {"ok-infra", "ok-mgmt", "ok-shared"}, "credential planes")
    for item in credentials.values():
        expect(item["path"], EXPECTED_CREDENTIAL_PATHS[item["plane"]], f"{item['plane']} path")
        expect(item["requiredMode"], "0600", f"{item['plane']} mode")
        expect(item["materialState"], "UNINSPECTED", f"{item['plane']} state")
    boundary = spec["queryBoundary"]
    expect(boundary, {
        "verb": "get", "exactNameOnly": True, "collectionGetAllowed": False,
        "listWatchDiscoveryAllowed": False, "secretReadAllowed": False,
        "mutationAllowed": False,
    }, "query boundary")
    claims = spec["absenceClaims"]
    absence = spec["absenceQueries"]
    readiness = spec["readinessQueries"]
    expect(len(claims), 13, "absence claim count")
    expect(len(absence), 4, "absence query count")
    expect(len(readiness), 13, "readiness query count")
    if len({item["id"] for item in claims + absence + readiness}) != 30:
        raise PreflightError("query IDs must be globally unique")
    expect([(item["id"], item["plane"], item["identity"]) for item in claims], EXPECTED_ABSENCE_CLAIMS, "absence claim inventory")
    expect([
        (item["id"], item["plane"], item["resource"], item.get("namespace"), item["name"], item["proofRule"], tuple(item["provesClaims"]))
        for item in absence
    ], EXPECTED_ABSENCE_QUERIES, "absence query inventory")
    expect([
        (item["id"], item["plane"], item["resource"], item.get("namespace"), item["name"], item["rule"])
        for item in readiness
    ], EXPECTED_READINESS_QUERIES, "readiness query inventory")
    claim_ids = {item["id"] for item in claims}
    proved_ids = [claim for query in absence for claim in query["provesClaims"]]
    expect(set(proved_ids), claim_ids, "absence proof coverage")
    expect(len(proved_ids), len(claim_ids), "one proof per absence claim")
    if any(item["resource"] == "secrets" for item in absence + readiness):
        raise PreflightError("Secret object reads are forbidden")
    expect(spec["acceptance"]["requiredAbsenceClaimCount"], len(claims), "absence claim acceptance")
    expect(spec["acceptance"]["requiredAbsenceQueryCount"], len(absence), "absence query acceptance")
    expect(spec["acceptance"]["requiredReadinessCount"], len(readiness), "readiness acceptance")
    expect(spec["conclusions"]["clusterContacted"], False, "cluster contact")
    expect(spec["conclusions"]["mutationAuthorized"], False, "mutation authority")
    return candidate


def build_command(query: dict[str, Any], credential: str = "RUNTIME-BOUND-KUBECONFIG") -> list[str]:
    command = ["kubectl", "--kubeconfig", credential, "get", query["resource"], query["name"]]
    if query.get("namespace"):
        command.extend(["--namespace", query["namespace"]])
    command.extend(["--ignore-not-found=true", "--output=json"])
    return command


def build_plan(candidate: dict[str, Any]) -> dict[str, Any]:
    spec = candidate["spec"]
    return {
        "candidateDigest": sha(CANDIDATE),
        "protocolDigest": spec["bindings"]["protocol"]["digest"],
        "queries": [
            {"class": query_class, "id": item["id"], "plane": item["plane"], "command": build_command(item)}
            for query_class, queries in (("absence", spec["absenceQueries"]), ("readiness", spec["readinessQueries"]))
            for item in queries
        ],
        "queryCount": 17,
        "logicalAbsenceClaimCount": 13,
        "credentialUseGranted": False,
        "clusterContacted": False,
        "mutationAuthorized": False,
    }


def parse_time(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise PreflightError("timestamp must include timezone")
    return parsed


def inspect_credential(path: Path) -> dict[str, str]:
    if not path.is_file() or path.is_symlink() or path.stat().st_size == 0:
        raise PreflightError("credential must be a non-empty regular non-symlink file")
    if stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise PreflightError("credential mode must be 0600")
    if REPOSITORY.resolve() in path.resolve().parents:
        raise PreflightError("credential must remain outside the repository")
    config = read(path)
    context = config.get("current-context")
    contexts = {item["name"]: item["context"] for item in config.get("contexts", [])}
    if context not in contexts:
        raise PreflightError("current context is missing")
    cluster_name = contexts[context].get("cluster")
    user_name = contexts[context].get("user")
    clusters = {item["name"]: item["cluster"] for item in config.get("clusters", [])}
    users = {item["name"]: item["user"] for item in config.get("users", [])}
    cluster = clusters.get(cluster_name, {})
    user = users.get(user_name, {})
    if cluster.get("insecure-skip-tls-verify") or cluster.get("proxy-url"):
        raise PreflightError("insecure TLS or proxy is forbidden")
    server = cluster.get("server", "")
    ca_data = cluster.get("certificate-authority-data", "")
    if not server.startswith("https://") or not ca_data:
        raise PreflightError("HTTPS server and embedded CA are required")
    if user.get("exec") or user.get("auth-provider") or user.get("tokenFile") or user.get("client-certificate") or user.get("client-key"):
        raise PreflightError("external credential loading or execution is forbidden")
    if not ((user.get("client-certificate-data") and user.get("client-key-data")) or user.get("token")):
        raise PreflightError("embedded client certificate/key or token is required")
    try:
        ca_bytes = base64.b64decode(ca_data, validate=True)
    except ValueError as error:
        raise PreflightError("invalid embedded CA") from error
    if not ca_bytes:
        raise PreflightError("embedded CA is empty")
    identity = {"server": server, "caFingerprint": sha_bytes(ca_bytes)}
    identity["identityDigest"] = sha_bytes(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode())
    return identity


def validate_grant(candidate_path: Path, grant: dict[str, Any], identities: dict[str, dict[str, str]], now: dt.datetime) -> None:
    expect(grant.get("apiVersion"), "authorization.openkubes.io/v1alpha1", "grant apiVersion")
    expect(grant.get("kind"), "GO1V6PreflightGrant", "grant kind")
    spec = grant["spec"]
    expect(spec["decision"], "GO", "grant decision")
    expect(spec["candidateDigest"], sha(candidate_path), "grant candidate")
    expect(spec["protocolDigest"], EXPECTED_PROTOCOL_DIGEST, "grant protocol")
    expect(spec["singleRun"], True, "single-run boundary")
    expect(spec["readOnly"], True, "read-only boundary")
    expect(spec["mutationAuthorized"], False, "mutation boundary")
    expect(spec["expectedCredentialIdentities"], identities, "credential identity bindings")
    if not spec.get("grantID"):
        raise PreflightError("grant ID is missing")
    issued, expires = parse_time(spec["issuedAt"]), parse_time(spec["expiresAt"])
    if not issued <= now <= expires or expires - issued > dt.timedelta(minutes=15):
        raise PreflightError("grant is outside its maximum 15-minute window")


def condition_true(item: dict[str, Any], condition_type: str) -> bool:
    return any(c.get("type") == condition_type and c.get("status") == "True" for c in item.get("status", {}).get("conditions", []))


def evaluate_readiness(item: dict[str, Any], rule: str) -> dict[str, Any]:
    metadata, status = item.get("metadata", {}), item.get("status", {})
    if rule == "deployment-current-and-available":
        passed = status.get("observedGeneration") == metadata.get("generation") and status.get("availableReplicas", 0) >= 1
    elif rule == "statefulset-current-and-ready":
        desired = item.get("spec", {}).get("replicas", 1)
        passed = status.get("observedGeneration") == metadata.get("generation") and status.get("readyReplicas", 0) == desired
    elif rule == "condition-ready":
        passed = condition_true(item, "Ready")
    elif rule == "condition-established":
        passed = condition_true(item, "Established")
    elif rule == "endpoint-address-present":
        passed = any(subset.get("addresses") for subset in item.get("subsets", []))
    elif rule == "phase-active":
        passed = status.get("phase") == "Active"
    elif rule == "object-present":
        passed = bool(metadata.get("name"))
    else:
        raise PreflightError(f"unsupported readiness rule: {rule}")
    if not passed:
        raise PreflightError(f"readiness rule failed: {rule}")
    return {"rule": rule, "result": "PASS"}


def get_exact(query: dict[str, Any], kubeconfig: Path, runner: Callable[..., Any]) -> bytes:
    completed = runner(build_command(query, str(kubeconfig)), stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if completed.returncode != 0:
        raise PreflightError(f"exact GET failed for {query['id']}")
    return completed.stdout


def write_exclusive(path: Path, value: dict[str, Any]) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(path, flags, 0o600)
    try:
        os.write(fd, json.dumps(value, indent=2, sort_keys=True).encode() + b"\n")
    finally:
        os.close(fd)


def run_preflight(candidate_path: Path, grant_path: Path, now: dt.datetime, runner: Callable[..., Any] = subprocess.run) -> dict[str, Any]:
    candidate = validate_candidate(candidate_path)
    spec = candidate["spec"]
    credentials = {item["plane"]: Path(item["path"]) for item in spec["credentials"]}
    identities = {plane: inspect_credential(path) for plane, path in credentials.items()}
    grant = read(grant_path)
    validate_grant(candidate_path, grant, identities, now)
    evidence: dict[str, Any] = {
        "apiVersion": "evidence.openkubes.io/v1alpha1",
        "kind": "GO1V6PreflightEvidence",
        "spec": {
            "version": "ok141-go1-v6-preflight-evidence/v1",
            "candidateDigest": sha(candidate_path),
            "protocolDigest": EXPECTED_PROTOCOL_DIGEST,
            "grantID": grant["spec"]["grantID"],
            "observedAt": now.isoformat().replace("+00:00", "Z"),
            "credentialIdentityDigests": {plane: value["identityDigest"] for plane, value in identities.items()},
            "mutationPerformed": False,
            "secretBodiesRetained": False,
            "result": "STARTED",
        },
    }
    try:
        absence_results = []
        absent_claims = []
        for query in spec["absenceQueries"]:
            payload = get_exact(query, credentials[query["plane"]], runner)
            if payload.strip():
                raise PreflightError(f"create target is present: {query['id']}")
            absence_results.append({"id": query["id"], "plane": query["plane"], "result": "ABSENT", "proofRule": query["proofRule"]})
            absent_claims.extend(query["provesClaims"])
        readiness_results = []
        for query in spec["readinessQueries"]:
            payload = get_exact(query, credentials[query["plane"]], runner)
            if not payload.strip():
                raise PreflightError(f"prerequisite is absent: {query['id']}")
            item = json.loads(payload)
            result = evaluate_readiness(item, query["rule"])
            readiness_results.append({"id": query["id"], "plane": query["plane"], **result})
        evidence["spec"].update({
            "absence": absence_results,
            "absenceClaims": [{"id": claim_id, "result": "ABSENT"} for claim_id in absent_claims],
            "readiness": readiness_results,
            "result": spec["acceptance"]["successState"],
            "freshUntil": (now + dt.timedelta(minutes=spec["evidence"]["freshnessMinutes"])).isoformat().replace("+00:00", "Z"),
        })
        return evidence
    except Exception as error:
        evidence["spec"].update({"result": "STOP-FAIL-CLOSED", "failureType": type(error).__name__, "failure": str(error)})
        raise
    finally:
        write_exclusive(Path(spec["evidence"]["rawLocalPath"]), evidence)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "plan", "run"))
    parser.add_argument("--candidate", type=Path, default=CANDIDATE)
    parser.add_argument("--grant", type=Path)
    args = parser.parse_args()
    try:
        candidate = validate_candidate(args.candidate.resolve())
        if args.command == "verify":
            result = {"candidateDigest": sha(args.candidate.resolve()), "state": candidate["spec"]["state"], "clusterContacted": False}
        elif args.command == "plan":
            result = build_plan(candidate)
        else:
            if args.grant is None:
                raise PreflightError("run requires a separate grant")
            result = run_preflight(args.candidate.resolve(), args.grant.resolve(), dt.datetime.now(dt.timezone.utc))
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (PreflightError, OSError, KeyError, TypeError, ValueError, yaml.YAMLError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
