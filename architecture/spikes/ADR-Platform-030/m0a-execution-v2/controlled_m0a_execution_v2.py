#!/usr/bin/env python3
"""Three-grant M0a v2 executor; mutation is impossible without an exact grant."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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


V1 = _load("ok141_m0a_v1_executor", SPIKE / "m0a-execution" / "controlled_m0a_execution.py")
INSTALLER = V1.INSTALLER
POLICY_NAME = "ok141-m0a-installer-v2.openkubes.io"
SA_NAME = "ok141-m0a-installer-v2"
SA_NAMESPACE = "openkubes-system"
BOOTSTRAP_OBJECTS = (
    ("ServiceAccount", "serviceaccount", SA_NAME, SA_NAMESPACE),
    ("ClusterRole", "clusterrole", SA_NAME, None),
    ("ClusterRoleBinding", "clusterrolebinding", SA_NAME, None),
    ("ValidatingAdmissionPolicy", "validatingadmissionpolicy", POLICY_NAME, None),
    ("ValidatingAdmissionPolicyBinding", "validatingadmissionpolicybinding", POLICY_NAME, None),
)


class ExecutionError(ValueError):
    pass


def sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def expect(actual: Any, expected: Any, claim: str) -> None:
    if actual != expected:
        raise ExecutionError(f"{claim}: expected {expected!r}, got {actual!r}")


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


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo != timezone.utc:
        raise ExecutionError("grant timestamps must be UTC")
    return parsed


def verify_candidate(path: Path) -> tuple[dict[str, Any], dict[str, Path]]:
    document = read_yaml(path)
    spec = document["spec"]
    expect(spec["version"], "ok141-m0a-combined-candidate/v2", "candidate version")
    expect(spec["state"], "READY-FOR-THREE-SEPARATE-EXPLICIT-GRANTS", "candidate state")
    refs = {name: resolve(path.parent, reference) for name, reference in spec["references"].items()}
    expect(refs["executor"], Path(__file__).resolve(), "executor identity")
    expect(spec["target"]["kubeSystemNamespaceUID"], "c3b45aab-d2a1-4e64-8f12-77b99186ad4a", "target UID")
    expect(spec["fixtureDigest"], "sha256:a2ae3437645db5a83426b89d36d00693d2600e4ef20dc1aba2650dcda7f936f6", "fixture digest")
    expect(spec["credential"]["maximumDurationMinutes"], 10, "credential duration")
    expect(spec["credential"]["revocationPollMaximumSeconds"], 90, "revocation poll")
    expect(spec["executionWindow"]["maximumRuns"], 1, "maximum runs")
    expect(spec["executionWindow"]["grantsRequired"], ["M0A-C1-v2", "M0A-A1-v2", "M0a-I-v2"], "grant inventory")
    expect(spec["authorization"], {
        "decision": "NO-GO",
        "mutationAuthorized": False,
        "credentialGrantRequired": True,
        "admissionBootstrapGrantRequired": True,
        "installationGrantRequired": True,
        "m0bInstallationGranted": False,
        "go1Granted": False,
        "evidencePublicationGranted": False,
        "failureInjectionGranted": False,
    }, "candidate authorization")
    return document, refs


def verify_grant(candidate_path: Path, grant_path: Path, now: datetime | None = None) -> dict[str, Any]:
    candidate, _ = verify_candidate(candidate_path)
    grant = read_yaml(grant_path)["spec"]
    expect(grant["version"], "ok141-m0a-combined-grant/v2", "grant version")
    expect(grant["candidateDigest"], sha(candidate_path), "candidate grant binding")
    expect(grant["authority"], "github:arashkaffamanesh", "grant authority")
    expect(grant["decision"], "GO", "grant decision")
    expect(grant["mutationAuthorized"], True, "mutation authority")
    expected = (("credentialGrant", "M0A-C1-v2"), ("admissionGrant", "M0A-A1-v2"), ("installationGrant", "M0a-I-v2"))
    grant_ids = []
    for field, gate in expected:
        expect(grant[field]["gate"], gate, f"{field} gate")
        expect(grant[field]["granted"], True, f"{field} decision")
        grant_ids.append(grant[field]["grantID"])
    if len(set(grant_ids)) != 3 or any(not value for value in grant_ids):
        raise ExecutionError("three distinct non-empty grant IDs are required")
    start = parse_utc(grant["validFrom"])
    end = parse_utc(grant["validUntil"])
    maximum = candidate["spec"]["executionWindow"]["maximumDurationMinutes"] * 60
    if end <= start or (end - start).total_seconds() > maximum:
        raise ExecutionError("grant window is invalid or too long")
    current = now or datetime.now(timezone.utc)
    if current < start or current > end:
        raise ExecutionError("current time is outside the exact grant window")
    expect(grant["maximumRuns"], 1, "maximum run count")
    for field in ("rollbackGranted", "targetConvergenceGranted", "m0bInstallationGranted", "go1Granted", "evidencePublicationGranted", "failureInjectionGranted"):
        expect(grant[field], False, field)
    return grant


def kubectl(kubeconfig: Path, args: list[str], *, input_bytes: bytes | None = None, check: bool = True) -> subprocess.CompletedProcess:
    return V1.kubectl(kubeconfig, args, input_bytes=input_bytes, check=check)


def ensure_absent(kubeconfig: Path, kind: str, name: str, namespace: str | None, claim: str) -> None:
    args = ["get", kind, name]
    if namespace:
        args.extend(["--namespace", namespace])
    V1.ensure_absent(kubeconfig, args, claim)


def live_preflight(candidate: dict[str, Any], refs: dict[str, Path], admin_kubeconfig: Path) -> dict[str, Any]:
    spec = candidate["spec"]
    expect(admin_kubeconfig.resolve(), Path(spec["target"]["adminKubeconfigPath"]).resolve(), "admin kubeconfig path")
    bootstrap = V1.verify_bootstrap_identity(admin_kubeconfig)
    identity = V1.json_get(admin_kubeconfig, ["get", "namespace", "kube-system"])
    expect(identity["metadata"]["uid"], spec["target"]["kubeSystemNamespaceUID"], "live target UID")
    version = json.loads(kubectl(admin_kubeconfig, ["get", "--raw=/version"]).stdout)
    expect(version["gitVersion"], spec["target"]["kubernetesVersion"], "live Kubernetes version")
    api = kubectl(admin_kubeconfig, ["get", "--raw=/apis/admissionregistration.k8s.io/v1"]).stdout
    resources = {item["name"] for item in json.loads(api)["resources"]}
    for resource in ("validatingadmissionpolicies", "validatingadmissionpolicybindings"):
        if resource not in resources:
            raise ExecutionError(f"required admission API absent: {resource}")
    for _, kind, name, namespace in BOOTSTRAP_OBJECTS:
        ensure_absent(admin_kubeconfig, kind, name, namespace, f"{kind}/{name}")
    for kind, name, namespace in (
        ("namespace", "caaph-system", None),
        ("customresourcedefinition", "helmchartproxies.addons.cluster.x-k8s.io", None),
        ("customresourcedefinition", "helmreleaseproxies.addons.cluster.x-k8s.io", None),
    ):
        ensure_absent(admin_kubeconfig, kind, name, namespace, f"{kind}/{name}")
    reviewed = INSTALLER.verify_reviewed_object_set(read_yaml(refs["installationProtocol"]), refs["installationProtocol"])
    expect(reviewed.semantic_digest, spec["installation"]["semanticDigest"], "reviewed semantic digest")
    expect(len(reviewed.documents), 19, "reviewed object count")
    V1.ensure_no_namespaced_collisions(admin_kubeconfig, reviewed)
    lifecycle = {
        key: len(V1.json_get(admin_kubeconfig, ["get", resource, "--all-namespaces"]).get("items", []))
        for key, resource in (
            ("clusters", "clusters.cluster.x-k8s.io"),
            ("machines", "machines.cluster.x-k8s.io"),
            ("machineDeployments", "machinedeployments.cluster.x-k8s.io"),
        )
    }
    expect(lifecycle, {"clusters": 0, "machines": 0, "machineDeployments": 0}, "live CAPI inventory")
    return {
        "targetUID": identity["metadata"]["uid"],
        "kubernetesVersion": version["gitVersion"],
        "reviewedObjectCount": len(reviewed.documents),
        "reviewedSemanticDigest": reviewed.semantic_digest,
        "lifecycleInventory": lifecycle,
        "admissionAPIAvailable": True,
        "bootstrapIdentity": bootstrap,
    }


def discover_bootstrap_objects(admin_kubeconfig: Path) -> dict[str, str]:
    found: dict[str, str] = {}
    for label, kind, name, namespace in BOOTSTRAP_OBJECTS:
        args = ["get", kind, name]
        if namespace:
            args.extend(["--namespace", namespace])
        completed = kubectl(admin_kubeconfig, [*args, "-o", "json"], check=False)
        if completed.returncode != 0:
            stderr = completed.stderr.decode(errors="replace")
            if "NotFound" in stderr or "not found" in stderr:
                continue
            raise ExecutionError(f"cannot inspect bootstrap object {kind}/{name}")
        item = json.loads(completed.stdout)
        labels = item["metadata"].get("labels", {})
        if labels.get("openkubes.io/ticket") != "OK-141" or labels.get("openkubes.io/gate") != "M0A-C1-v2":
            raise ExecutionError(f"bootstrap object {kind}/{name} has foreign ownership")
        found[label] = item["metadata"]["uid"]
    return found


def wait_policy_ready(admin_kubeconfig: Path, timeout_seconds: int = 60) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last = "not observed"
    while time.monotonic() < deadline:
        policy = V1.json_get(admin_kubeconfig, ["get", "validatingadmissionpolicy", POLICY_NAME])
        status = policy.get("status", {})
        generation = policy["metadata"].get("generation")
        type_checking = status.get("typeChecking")
        warnings = type_checking.get("expressionWarnings") if isinstance(type_checking, dict) else None
        if status.get("observedGeneration") == generation and isinstance(type_checking, dict) and warnings in (None, []):
            return {"observedGeneration": generation, "expressionWarnings": 0}
        last = f"generation={generation} observed={status.get('observedGeneration')} warnings={warnings!r}"
        time.sleep(2)
    raise ExecutionError(f"admission policy type-check timeout: {last}")


def temporary_kubeconfig(admin_kubeconfig: Path, token: str, candidate: dict[str, Any]) -> Path:
    admin = read_yaml(admin_kubeconfig)
    current = admin["current-context"]
    context = next(item["context"] for item in admin["contexts"] if item["name"] == current)
    cluster = next(item["cluster"] for item in admin["clusters"] if item["name"] == context["cluster"])
    expect(cluster["server"], candidate["spec"]["target"]["apiServer"], "admin target server")
    config = {
        "apiVersion": "v1",
        "kind": "Config",
        "clusters": [{"name": "ok-mgmt", "cluster": cluster}],
        "contexts": [{"name": "installer@ok-mgmt", "context": {"cluster": "ok-mgmt", "user": "installer"}}],
        "current-context": "installer@ok-mgmt",
        "users": [{"name": "installer", "user": {"token": token}}],
    }
    handle = tempfile.NamedTemporaryFile(prefix="ok141-m0a-v2-", suffix=".kubeconfig", delete=False)
    try:
        Path(handle.name).chmod(0o600)
        handle.write(yaml.safe_dump(config, sort_keys=False).encode())
        handle.close()
        return Path(handle.name)
    except Exception:
        handle.close()
        Path(handle.name).unlink(missing_ok=True)
        raise


def auth_can_i(kubeconfig: Path, verb: str, resource: str, name: str | None = None, namespace: str | None = None) -> bool:
    return V1.auth_can_i(kubeconfig, verb, resource, name, namespace)


def authorization_probes(kubeconfig: Path, reviewed: Any) -> dict[str, Any]:
    create_types = {(V1.RESOURCE_MAP[item["kind"]][0], item["metadata"].get("namespace", V1.RESOURCE_MAP[item["kind"]][1])) for item in reviewed.documents}
    for resource, namespace in create_types:
        if not auth_can_i(kubeconfig, "create", resource, namespace=namespace):
            raise ExecutionError(f"create authorization missing for {resource} in {namespace}")
    for item in reviewed.documents:
        resource, default_namespace = V1.RESOURCE_MAP[item["kind"]]
        namespace = item["metadata"].get("namespace", default_namespace)
        if not auth_can_i(kubeconfig, "get", resource, item["metadata"]["name"], namespace):
            raise ExecutionError(f"exact get authorization missing for {resource}/{item['metadata']['name']}")
    forbidden = (
        ("patch", "namespaces", "caaph-system", None),
        ("update", "namespaces", "caaph-system", None),
        ("delete", "namespaces", "caaph-system", None),
        ("list", "deployments.apps", None, "caaph-system"),
        ("watch", "deployments.apps", None, "caaph-system"),
        ("get", "secrets", None, "caaph-system"),
        ("create", "secrets", None, "caaph-system"),
        ("create", "serviceaccounts/token", None, SA_NAMESPACE),
        ("impersonate", "users", "system:admin", None),
        ("bind", "clusterroles.rbac.authorization.k8s.io", "cluster-admin", None),
        ("escalate", "clusterroles.rbac.authorization.k8s.io", SA_NAME, None),
    )
    for verb, resource, name, namespace in forbidden:
        if auth_can_i(kubeconfig, verb, resource, name, namespace):
            raise ExecutionError(f"negative authorization probe allowed: {verb} {resource}")
    wrong = {
        "apiVersion": "v1",
        "kind": "Namespace",
        "metadata": {"name": "ok141-m0a-v2-wrong-name"},
    }
    denied = kubectl(kubeconfig, ["create", "--dry-run=server", "--filename", "-"], input_bytes=yaml.safe_dump(wrong).encode(), check=False)
    if denied.returncode == 0 or "OK-141 M0a v2 permits only" not in denied.stderr.decode(errors="replace"):
        raise ExecutionError("wrong-name admission dry-run was not denied by the bound policy")
    return {"createResourceTypes": len(create_types), "exactGetTargets": 19, "negativeAuthorizationProbes": len(forbidden), "negativeAdmissionProbes": 1}


def cleanup_bootstrap(admin_kubeconfig: Path, expected_uids: dict[str, str]) -> dict[str, Any]:
    live = discover_bootstrap_objects(admin_kubeconfig)
    for label, uid in live.items():
        if expected_uids.get(label) not in (None, uid):
            raise ExecutionError(f"bootstrap object {label} UID changed before cleanup")
    order = (
        ("ClusterRoleBinding", "clusterrolebinding", SA_NAME, None),
        ("ServiceAccount", "serviceaccount", SA_NAME, SA_NAMESPACE),
        ("ClusterRole", "clusterrole", SA_NAME, None),
        ("ValidatingAdmissionPolicyBinding", "validatingadmissionpolicybinding", POLICY_NAME, None),
        ("ValidatingAdmissionPolicy", "validatingadmissionpolicy", POLICY_NAME, None),
    )
    for label, kind, name, namespace in order:
        if label not in live:
            continue
        args = ["delete", kind, name, "--wait=true"]
        if namespace:
            args.extend(["--namespace", namespace])
        kubectl(admin_kubeconfig, args)
    remaining = discover_bootstrap_objects(admin_kubeconfig)
    if remaining:
        raise ExecutionError(f"temporary bootstrap objects remain: {sorted(remaining)}")
    return {"removed": True, "objectUIDs": live}


def poll_token_rejection(kubeconfig: Path, maximum_seconds: int) -> dict[str, Any]:
    started = time.monotonic()
    attempts = 0
    expected_username = f"system:serviceaccount:{SA_NAMESPACE}:{SA_NAME}"
    while time.monotonic() - started <= maximum_seconds:
        attempts += 1
        probe = kubectl(kubeconfig, ["auth", "whoami", "--output=json"], check=False)
        if probe.returncode != 0:
            stderr = probe.stderr.decode(errors="replace")
            if "Unauthorized" in stderr or "logged in" in stderr:
                return {"tokenRejected": True, "attempts": attempts, "elapsedSeconds": round(time.monotonic() - started, 3)}
        else:
            observed = json.loads(probe.stdout).get("status", {}).get("userInfo", {}).get("username")
            if observed != expected_username:
                return {
                    "tokenRejected": True,
                    "attempts": attempts,
                    "elapsedSeconds": round(time.monotonic() - started, 3),
                    "fallbackIdentity": observed,
                }
        time.sleep(2)
    raise ExecutionError(f"token still authenticated after {maximum_seconds}s bounded poll")


def execute(candidate_path: Path, grant_path: Path, admin_kubeconfig: Path, evidence_output: Path) -> dict[str, Any]:
    candidate, refs = verify_candidate(candidate_path)
    verify_grant(candidate_path, grant_path)
    clock = V1.verify_clock(candidate["spec"]["executionWindow"]["maximumClockSkewSeconds"])
    preflight = live_preflight(candidate, refs, admin_kubeconfig)
    reviewed = INSTALLER.verify_reviewed_object_set(read_yaml(refs["installationProtocol"]), refs["installationProtocol"])
    expect(sha(refs["riskAcceptance"]), candidate["spec"]["references"]["riskAcceptance"]["digest"], "risk acceptance at execution")
    temp_config: Path | None = None
    bootstrap_uids: dict[str, str] = {}
    evidence: dict[str, Any] = {
        "version": "ok141-m0a-execution-evidence/v2",
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
        bootstrap_payload = refs["credentialManifest"].read_bytes() + b"\n---\n" + refs["admissionManifest"].read_bytes()
        kubectl(admin_kubeconfig, ["create", "--filename", "-"], input_bytes=bootstrap_payload)
        bootstrap_uids = discover_bootstrap_objects(admin_kubeconfig)
        expect(set(bootstrap_uids), {item[0] for item in BOOTSTRAP_OBJECTS}, "temporary bootstrap inventory")
        evidence["policy"] = wait_policy_ready(admin_kubeconfig)
        requested_at = datetime.now(timezone.utc)
        token_result = kubectl(admin_kubeconfig, ["--namespace", SA_NAMESPACE, "create", "token", SA_NAME, "--duration=10m", "--audience", candidate["spec"]["target"]["apiAudience"], "--output=json"])
        token_request = json.loads(token_result.stdout)
        token = token_request["status"]["token"]
        if len(token) < 80:
            raise ExecutionError("TokenRequest returned an invalid token")
        expires_at = parse_utc(token_request["status"]["expirationTimestamp"])
        if (expires_at - requested_at).total_seconds() > 610:
            raise ExecutionError("TokenRequest expiry exceeds the accepted ten-minute boundary")
        evidence["credential"] = {
            "requestedAt": requested_at.isoformat().replace("+00:00", "Z"),
            "expiresAt": expires_at.isoformat().replace("+00:00", "Z"),
            "audience": candidate["spec"]["target"]["apiAudience"],
            "tokenMaterialRetained": False,
        }
        temp_config = temporary_kubeconfig(admin_kubeconfig, token, candidate)
        token = ""
        token_request["status"]["token"] = ""
        evidence["authorizationProbes"] = authorization_probes(temp_config, reviewed)
        reviewed = INSTALLER.verify_reviewed_object_set(read_yaml(refs["installationProtocol"]), refs["installationProtocol"])
        expect(reviewed.semantic_digest, candidate["spec"]["installation"]["semanticDigest"], "immediate pre-submit semantic digest")
        kubectl(temp_config, ["apply", "--server-side", "--field-manager", candidate["spec"]["installation"]["fieldManager"], "--filename", "-"], input_bytes=reviewed.payload)
        evidence["readiness"] = V1.wait_ready(admin_kubeconfig, candidate["spec"]["installation"]["readinessTimeoutSeconds"])
        evidence["objects"] = V1.object_evidence(admin_kubeconfig, reviewed)
        evidence["result"] = "SUCCESS"
        return evidence
    except Exception as exc:
        evidence.update({"result": "STOP-NOT-SUCCESS", "failureType": type(exc).__name__, "failure": str(exc)})
        raise
    finally:
        try:
            evidence["bootstrapCleanup"] = cleanup_bootstrap(admin_kubeconfig, bootstrap_uids)
        except Exception as cleanup_error:
            evidence["bootstrapCleanup"] = {"removed": False, "failureType": type(cleanup_error).__name__, "failure": str(cleanup_error)}
            evidence["result"] = "STOP-NOT-SUCCESS"
        if temp_config is not None:
            try:
                evidence["revocation"] = poll_token_rejection(temp_config, candidate["spec"]["credential"]["revocationPollMaximumSeconds"])
            except Exception as revoke_error:
                evidence["revocation"] = {"tokenRejected": False, "failureType": type(revoke_error).__name__, "failure": str(revoke_error)}
                evidence["result"] = "STOP-NOT-SUCCESS"
        if temp_config is not None:
            temp_config.unlink(missing_ok=True)
        evidence["finishedAt"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        evidence_output.parent.mkdir(parents=True, exist_ok=True)
        evidence_output.write_text(json.dumps(evidence, sort_keys=True, separators=(",", ":")) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("verify")
    check.add_argument("--candidate", type=Path, required=True)
    check.add_argument("--grant", type=Path)
    preflight_parser = sub.add_parser("preflight")
    preflight_parser.add_argument("--candidate", type=Path, required=True)
    preflight_parser.add_argument("--admin-kubeconfig", type=Path, required=True)
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
        if args.command == "preflight":
            candidate, refs = verify_candidate(args.candidate.resolve())
            result = live_preflight(candidate, refs, args.admin_kubeconfig.resolve())
            print(json.dumps({"result": "PASS", "mutationPerformed": False, "observation": result}, sort_keys=True, separators=(",", ":")))
            return 0
        if not args.execute:
            raise ExecutionError("execute command requires the explicit --execute flag")
        result = execute(args.candidate.resolve(), args.grant.resolve(), args.admin_kubeconfig.resolve(), args.evidence_output.resolve())
        if result["result"] != "SUCCESS" or not result.get("revocation", {}).get("tokenRejected"):
            raise ExecutionError("execution or bounded credential revocation did not succeed")
        print(json.dumps({"result": result["result"], "evidenceOutput": str(args.evidence_output)}, sort_keys=True, separators=(",", ":")))
        return 0
    except (ExecutionError, INSTALLER.InstallerError, OSError, KeyError, TypeError, ValueError, yaml.YAMLError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
