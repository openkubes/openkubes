#!/usr/bin/env python3
"""Bounded D2 CAAPH quiescence preparation and execution."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import yaml


HERE = Path(__file__).resolve().parent
EXPECTED_BASE = "9f98dfc3167df647bfb1cb8e1545cc1b2caa3f2b"
EXPECTED_PROTOCOL = "sha256:4cd457c5f40bdf3ae871cbe56ba7c151f7ac3242bd73129557f25cf620a2d0bc"
EXPECTED_D1_CLOSURE = "sha256:0f5b25ea43f4b4d72514746916a8093214717901b625d9d568b0d73a7cf58f56"
EXPECTED_KUBECTL = "sha256:bb211f2b31f2b3bc60562b44cc1e3b712a16a98e9072968ba255beb04cefcfdf"


class D2Error(ValueError):
    pass


def file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def read_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text())
    if not isinstance(value, dict):
        raise D2Error("expected one YAML object")
    return value


def parse_time(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def write_exclusive(path: Path, value: object) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump(value, stream, sort_keys=True, separators=(",", ":"))
        stream.write("\n")


def run_raw(kubectl: Path, kubeconfig: Path, method: str, uri: str, payload: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    command = [str(kubectl), "--kubeconfig", str(kubeconfig), method, "--raw", uri]
    if payload is not None:
        command.extend(["-f", "-"])
    return subprocess.run(command, input=payload, capture_output=True, check=False, timeout=30)


def exact_get(kubectl: Path, kubeconfig: Path, uri: str) -> dict[str, Any]:
    result = run_raw(kubectl, kubeconfig, "get", uri)
    if result.returncode != 0 or len(result.stdout) > 5 * 1024 * 1024:
        raise D2Error("exact GET failed")
    value = json.loads(result.stdout)
    if not isinstance(value, dict):
        raise D2Error("invalid exact GET response")
    return value


def derive_hrp(hcp: dict[str, Any], collection: dict[str, Any]) -> dict[str, Any]:
    metadata = hcp.get("metadata", {})
    uid, name = str(metadata.get("uid", "")), str(metadata.get("name", ""))
    if not uid or not name:
        raise D2Error("HCP identity missing")
    matches = []
    for item in collection.get("items", []):
        owners = item.get("metadata", {}).get("ownerReferences", [])
        if any(owner.get("apiVersion") == "addons.cluster.x-k8s.io/v1alpha1" and owner.get("kind") == "HelmChartProxy" and owner.get("name") == name and str(owner.get("uid", "")) == uid and owner.get("controller") is True for owner in owners):
            matches.append(item)
    if len(matches) != 1:
        raise D2Error("expected exactly one controller-owned HelmReleaseProxy")
    return matches[0]


def verify_candidate(path: Path) -> dict[str, Any]:
    candidate = read_yaml(path)
    spec = candidate.get("spec", {})
    errors: list[str] = []
    if spec.get("version") != "ok141-delete-d2/v1" or spec.get("state") != "OFFLINE-PREPARED-BLOCKED-NO-GO":
        errors.append("candidate identity mismatch")
    if spec.get("baseCommit") != EXPECTED_BASE:
        errors.append("base commit mismatch")
    bindings = spec.get("bindings", {})
    protocol = (path.parent / bindings.get("protocolPath", "")).resolve()
    closure = (path.parent / bindings.get("d1ClosurePath", "")).resolve()
    if not protocol.is_file() or canonical_digest(read_yaml(protocol)) != EXPECTED_PROTOCOL or bindings.get("protocolSemanticDigest") != EXPECTED_PROTOCOL:
        errors.append("protocol binding mismatch")
    if not closure.is_file() or file_digest(closure) != EXPECTED_D1_CLOSURE or bindings.get("d1ClosureDigest") != EXPECTED_D1_CLOSURE:
        errors.append("D1 closure binding mismatch")
    target = spec.get("target", {})
    expected_target = {
        "namespace": "disposable-ok141", "name": "disposable-ok141-cilium",
        "hcpURI": "/apis/addons.cluster.x-k8s.io/v1alpha1/namespaces/disposable-ok141/helmchartproxies/disposable-ok141-cilium",
        "hrpCollectionURI": "/apis/addons.cluster.x-k8s.io/v1alpha1/namespaces/disposable-ok141/helmreleaseproxies",
    }
    if target != expected_target:
        errors.append("target mismatch")
    operation = spec.get("operation", {})
    if operation.get("deleteOnly") != "HelmChartProxy" or operation.get("directHRPDelete") is not False or operation.get("targetResourceDelete") is not False:
        errors.append("ownership boundary mismatch")
    if operation.get("immutableIdentityFields") != ["name", "namespace", "uid"] or operation.get("deletePreconditionFields") != ["uid", "resourceVersion"] or operation.get("useLiveResourceVersionForDelete") is not True:
        errors.append("precondition boundary mismatch")
    if operation.get("onFailure") != "STOP-PRESERVE-NO-RETRY-NO-FINALIZER-MUTATION":
        errors.append("stop boundary mismatch")
    tool = spec.get("tool", {})
    if tool.get("digest") != file_digest(Path(__file__).resolve()) or tool.get("kubectlDigest") != EXPECTED_KUBECTL:
        errors.append("tool binding mismatch")
    auth = spec.get("authorization", {})
    if auth.get("decision") != "NO-GO" or any(value is not False for key, value in auth.items() if key.endswith("Granted")):
        errors.append("candidate grants authority")
    if errors:
        raise D2Error("; ".join(errors))
    return candidate


def verify_window(grant: dict[str, Any], maximum_seconds: int, now: dt.datetime) -> None:
    start, end = parse_time(grant.get("notBefore", "")), parse_time(grant.get("notAfter", ""))
    if not start <= now <= end or (end - start).total_seconds() > maximum_seconds:
        raise D2Error("grant window inactive or too large")
    if grant.get("maximumRuns") != 1 or grant.get("consumed") is not False:
        raise D2Error("grant not fresh and single-use")


def validate_kubeconfig(candidate: dict[str, Any], kubectl: Path) -> Path:
    if file_digest(kubectl) != EXPECTED_KUBECTL:
        raise D2Error("kubectl digest mismatch")
    kubeconfig = Path(candidate["spec"]["plane"]["kubeconfigPath"])
    if kubeconfig.is_symlink() or not kubeconfig.is_file() or stat.S_IMODE(kubeconfig.stat().st_mode) != 0o600:
        raise D2Error("unsafe kubeconfig")
    return kubeconfig


def preflight(candidate_path: Path, grant_path: Path, kubectl: Path) -> dict[str, Any]:
    candidate = verify_candidate(candidate_path)
    grant = read_yaml(grant_path).get("spec", {})
    verify_window(grant, 1200, dt.datetime.now(dt.timezone.utc))
    if grant.get("state") != "GRANTED" or grant.get("candidateDigest") != file_digest(candidate_path):
        raise D2Error("preflight grant mismatch")
    if grant.get("credentialUseAuthorized") is not True or grant.get("readOnlyAuthorized") is not True:
        raise D2Error("read authority missing")
    for key in ("mutationAuthorized", "deleteAuthorized", "retryAuthorized", "cleanupAuthorized", "d3Authorized", "failureInjectionAuthorized"):
        if grant.get(key) is not False:
            raise D2Error(f"{key} must be false")
    kubeconfig = validate_kubeconfig(candidate, kubectl)
    target = candidate["spec"]["target"]
    hcp = exact_get(kubectl, kubeconfig, target["hcpURI"])
    hrp_collection = exact_get(kubectl, kubeconfig, target["hrpCollectionURI"])
    hrp = derive_hrp(hcp, hrp_collection)
    records = []
    for query_id, value in (("helm-chart-proxy", hcp), ("helm-release-proxy", hrp)):
        metadata = value.get("metadata", {})
        if metadata.get("deletionTimestamp") is not None or not metadata.get("uid") or not metadata.get("resourceVersion"):
            raise D2Error("unsafe live object identity")
        records.append({"queryID": query_id, "name": metadata["name"], "namespace": metadata["namespace"], "uid": metadata["uid"], "resourceVersion": metadata["resourceVersion"]})
    now = dt.datetime.now(dt.timezone.utc)
    binding = {
        "format": "ok141-delete-d2-runtime-binding/v1", "state": "PASS-D2-PREFLIGHT-PRIVATE-BOUND-NO-GO",
        "candidateDigest": file_digest(candidate_path), "grantID": grant["grantID"],
        "observedAt": now.isoformat(), "expiresAt": (now + dt.timedelta(minutes=5)).isoformat(),
        "records": records, "derivedHRPCount": 1, "mutationPerformed": False, "deletePerformed": False,
    }
    output = Path(candidate["spec"]["privateOutputs"]["bindingPath"])
    write_exclusive(output, binding)
    evidence = {
        "format": "ok141-delete-d2-preflight-private-evidence/v1", "state": binding["state"],
        "candidateDigest": file_digest(candidate_path), "bindingDigest": file_digest(output),
        "sealedGetCount": 2, "derivedHRPCount": 1, "ownerCorrelationPassed": True,
        "mutationPerformed": False, "deletePerformed": False, "rawObjectsRetained": False,
        "uidValuesRetained": False, "resourceVersionValuesRetained": False, "credentialContentRetained": False,
    }
    write_exclusive(Path(candidate["spec"]["privateOutputs"]["preflightEvidencePath"]), evidence)
    return evidence


def validate_binding(candidate: dict[str, Any], path: Path) -> tuple[dict[str, Any], list[dict[str, str]]]:
    if path.is_symlink() or not path.is_file() or stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise D2Error("unsafe binding")
    binding = json.loads(path.read_text())
    if binding.get("format") != "ok141-delete-d2-runtime-binding/v1" or binding.get("state") != "PASS-D2-PREFLIGHT-PRIVATE-BOUND-NO-GO":
        raise D2Error("binding identity mismatch")
    if binding.get("candidateDigest") != file_digest(HERE / "delete-d2-candidate-v1.yaml") or dt.datetime.now(dt.timezone.utc) > parse_time(binding.get("expiresAt", "")):
        raise D2Error("binding candidate mismatch or expired")
    records = binding.get("records", [])
    if [record.get("queryID") for record in records] != ["helm-chart-proxy", "helm-release-proxy"]:
        raise D2Error("binding record mismatch")
    return binding, records


def live_record(current: dict[str, Any], bound: dict[str, str]) -> dict[str, str]:
    metadata = current.get("metadata", {})
    for key in ("name", "namespace", "uid"):
        if str(metadata.get(key, "")) != str(bound.get(key, "")):
            raise D2Error("live immutable identity mismatch")
    if metadata.get("deletionTimestamp") is not None or not metadata.get("resourceVersion"):
        raise D2Error("target already deleting or resourceVersion missing")
    result = dict(bound)
    result["resourceVersion"] = str(metadata["resourceVersion"])
    return result


def delete_payload(record: dict[str, str]) -> bytes:
    return json.dumps({"apiVersion": "v1", "kind": "DeleteOptions", "preconditions": {"uid": record["uid"], "resourceVersion": record["resourceVersion"]}, "propagationPolicy": "Background"}, sort_keys=True, separators=(",", ":")).encode()


def absent(kubectl: Path, kubeconfig: Path, uri: str) -> bool:
    result = run_raw(kubectl, kubeconfig, "get", uri)
    if result.returncode == 0:
        return False
    if b"not found" in result.stderr.lower():
        return True
    raise D2Error("absence GET failed")


def execute(candidate_path: Path, grant_path: Path, binding_path: Path, kubectl: Path) -> dict[str, Any]:
    candidate = verify_candidate(candidate_path)
    binding, records = validate_binding(candidate, binding_path)
    grant = read_yaml(grant_path).get("spec", {})
    verify_window(grant, 1200, dt.datetime.now(dt.timezone.utc))
    if grant.get("state") != "GRANTED" or grant.get("candidateDigest") != file_digest(candidate_path) or grant.get("d2BindingDigest") != file_digest(binding_path):
        raise D2Error("execution grant mismatch")
    for key in ("credentialUseAuthorized", "mutationAuthorized", "deleteAuthorized", "partialStateAccepted"):
        if grant.get(key) is not True:
            raise D2Error(f"{key} required")
    for key in ("retryAuthorized", "rollbackAuthorized", "cleanupAuthorized", "forceDeleteAuthorized", "finalizerMutationAuthorized", "directHRPDeleteAuthorized", "targetResourceDeleteAuthorized", "d3Authorized", "outageAuthorized", "failureInjectionAuthorized"):
        if grant.get(key) is not False:
            raise D2Error(f"{key} must be false")
    if grant.get("stopPolicy") != "STOP-PRESERVE-NO-RETRY-NO-FINALIZER-MUTATION":
        raise D2Error("stop policy mismatch")
    kubeconfig = validate_kubeconfig(candidate, kubectl)
    target = candidate["spec"]["target"]
    current = exact_get(kubectl, kubeconfig, target["hcpURI"])
    current_record = live_record(current, records[0])
    result = run_raw(kubectl, kubeconfig, "delete", target["hcpURI"], delete_payload(current_record))
    if result.returncode != 0:
        raise D2Error("preconditioned HCP delete failed")
    hrp_uri = target["hrpCollectionURI"] + "/" + records[1]["name"]
    success = False
    for index in range(candidate["spec"]["operation"]["absencePollMaximumIterations"]):
        if absent(kubectl, kubeconfig, target["hcpURI"]) and absent(kubectl, kubeconfig, hrp_uri):
            success = True
            break
        if index + 1 < candidate["spec"]["operation"]["absencePollMaximumIterations"]:
            time.sleep(candidate["spec"]["operation"]["absencePollIntervalSeconds"])
    evidence = {
        "format": "ok141-delete-d2-execution-private-evidence/v1",
        "state": "PASS-D2-ENABLEMENT-QUIESCED-PRIVATE" if success else "STOP-D2-PARTIAL-PRESERVE-NO-RETRY",
        "candidateDigest": file_digest(candidate_path), "bindingDigest": file_digest(binding_path), "grantID": grant["grantID"],
        "hcpDeleteRequested": True, "hrpDeleteRequestedByRunner": False, "targetResourceDeleteRequestedByRunner": False,
        "hcpAbsent": success, "hrpAbsent": success, "nativeControllerClosureObserved": success,
        "retryPerformed": False, "rollbackPerformed": False, "cleanupPerformed": False,
        "forceDeletePerformed": False, "finalizerMutationPerformed": False, "rawObjectsRetained": False,
        "credentialContentRetained": False,
    }
    write_exclusive(Path(candidate["spec"]["privateOutputs"]["executionEvidencePath"]), evidence)
    if not success:
        raise D2Error("native CAAPH closure did not complete; private partial-state evidence written")
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "preflight", "delete"))
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--grant", type=Path)
    parser.add_argument("--binding", type=Path)
    parser.add_argument("--kubectl", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    candidate = args.candidate.resolve()
    if args.command == "verify":
        value = verify_candidate(candidate)
        print(json.dumps({"candidateDigest": file_digest(candidate), "semanticDigest": canonical_digest(value), "state": "PASS-D2-CANDIDATE-OFFLINE-NO-GO"}, sort_keys=True))
    elif args.command == "preflight":
        if not args.execute or args.grant is None or args.kubectl is None:
            raise D2Error("preflight requires grant, kubectl and --execute")
        print(json.dumps(preflight(candidate, args.grant.resolve(), args.kubectl.resolve()), sort_keys=True))
    else:
        if not args.execute or args.grant is None or args.binding is None or args.kubectl is None:
            raise D2Error("delete requires grant, binding, kubectl and --execute")
        print(json.dumps(execute(candidate, args.grant.resolve(), args.binding.resolve(), args.kubectl.resolve()), sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (D2Error, OSError, ValueError, KeyError, json.JSONDecodeError, subprocess.TimeoutExpired) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
