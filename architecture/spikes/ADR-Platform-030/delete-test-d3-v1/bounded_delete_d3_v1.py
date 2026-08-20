#!/usr/bin/env python3
"""Bounded D3 authoritative CAPI Cluster deletion."""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None: raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


D2 = load_module("ok141_delete_d2_for_d3", (HERE / "../delete-test-d2-v1/bounded_delete_d2_v1.py").resolve())
D3Error = D2.D2Error
file_digest = D2.file_digest
canonical_digest = D2.canonical_digest
read_yaml = D2.read_yaml
parse_time = D2.parse_time
write_exclusive = D2.write_exclusive
run_raw = D2.run_raw
exact_get = D2.exact_get

EXPECTED_BASE = "c0aeb15901e7914b4dc8e963ec29267a5e77325e"
EXPECTED_PROTOCOL = D2.EXPECTED_PROTOCOL
EXPECTED_D2_CLOSURE = "sha256:9c4e1bc7fd918e2a63b78a668be7beca3f5c5502d7ab589a80de0391f915dbba"
EXPECTED_KUBECTL = D2.EXPECTED_KUBECTL


def verify_candidate(path: Path) -> dict[str, Any]:
    candidate = read_yaml(path); spec = candidate.get("spec", {}); errors = []
    if spec.get("version") != "ok141-delete-d3/v1" or spec.get("state") != "OFFLINE-PREPARED-BLOCKED-NO-GO": errors.append("candidate identity mismatch")
    if spec.get("baseCommit") != EXPECTED_BASE: errors.append("base commit mismatch")
    bindings = spec.get("bindings", {})
    protocol = (path.parent / bindings.get("protocolPath", "")).resolve()
    closure = (path.parent / bindings.get("d2ClosurePath", "")).resolve()
    if not protocol.is_file() or canonical_digest(read_yaml(protocol)) != EXPECTED_PROTOCOL or bindings.get("protocolSemanticDigest") != EXPECTED_PROTOCOL: errors.append("protocol binding mismatch")
    if not closure.is_file() or file_digest(closure) != EXPECTED_D2_CLOSURE or bindings.get("d2ClosureDigest") != EXPECTED_D2_CLOSURE: errors.append("D2 closure binding mismatch")
    if spec.get("target") != {"namespace": "disposable-ok141", "name": "disposable-ok141", "clusterURI": "/apis/cluster.x-k8s.io/v1beta2/namespaces/disposable-ok141/clusters/disposable-ok141", "providerSecretURI": "/api/v1/namespaces/disposable-ok141/secrets/external-infra-kubeconfig-disposable-ok141", "namespaceURI": "/api/v1/namespaces/disposable-ok141"}: errors.append("target mismatch")
    operation = spec.get("operation", {})
    if operation.get("deleteOnly") != "Cluster" or operation.get("propagationPolicy") != "Foreground" or operation.get("childDelete") is not False or operation.get("providerSecretDelete") is not False: errors.append("ownership boundary mismatch")
    if operation.get("immutableIdentityFields") != ["name", "namespace", "uid"] or operation.get("deletePreconditionFields") != ["uid", "resourceVersion"] or operation.get("useLiveResourceVersionForDelete") is not True: errors.append("precondition boundary mismatch")
    if operation.get("onFailure") != "STOP-PRESERVE-NO-RETRY-NO-FINALIZER-MUTATION": errors.append("stop boundary mismatch")
    tool = spec.get("tool", {})
    if tool.get("digest") != file_digest(Path(__file__).resolve()) or tool.get("kubectlDigest") != EXPECTED_KUBECTL: errors.append("tool binding mismatch")
    auth = spec.get("authorization", {})
    if auth.get("decision") != "NO-GO" or any(v is not False for k, v in auth.items() if k.endswith("Granted")): errors.append("candidate grants authority")
    if errors: raise D3Error("; ".join(errors))
    return candidate


def grant_window(grant: dict[str, Any], now: dt.datetime) -> None:
    start, end = parse_time(grant.get("notBefore", "")), parse_time(grant.get("notAfter", ""))
    if not start <= now <= end or (end-start).total_seconds() > 1800: raise D3Error("grant window inactive or too large")
    if grant.get("maximumRuns") != 1 or grant.get("consumed") is not False: raise D3Error("grant not fresh")


def kubeconfig(candidate: dict[str, Any], kubectl: Path) -> Path:
    if file_digest(kubectl) != EXPECTED_KUBECTL: raise D3Error("kubectl digest mismatch")
    path = Path(candidate["spec"]["plane"]["kubeconfigPath"])
    if path.is_symlink() or not path.is_file() or stat.S_IMODE(path.stat().st_mode) != 0o600: raise D3Error("unsafe kubeconfig")
    return path


def preflight(candidate_path: Path, grant_path: Path, kubectl: Path) -> dict[str, Any]:
    candidate = verify_candidate(candidate_path); grant = read_yaml(grant_path).get("spec", {}); grant_window(grant, dt.datetime.now(dt.timezone.utc))
    if grant.get("state") != "GRANTED" or grant.get("candidateDigest") != file_digest(candidate_path): raise D3Error("preflight grant mismatch")
    for key in ("credentialUseAuthorized", "secretMetadataReadAuthorized", "readOnlyAuthorized"):
        if grant.get(key) is not True: raise D3Error(f"{key} required")
    for key in ("mutationAuthorized", "deleteAuthorized", "retryAuthorized", "cleanupAuthorized", "failureInjectionAuthorized"):
        if grant.get(key) is not False: raise D3Error(f"{key} must be false")
    kc = kubeconfig(candidate, kubectl); target = candidate["spec"]["target"]
    cluster = exact_get(kubectl, kc, target["clusterURI"]); secret = exact_get(kubectl, kc, target["providerSecretURI"]); namespace = exact_get(kubectl, kc, target["namespaceURI"])
    cm = cluster.get("metadata", {}); sm = secret.get("metadata", {}); nm = namespace.get("metadata", {})
    if cm.get("deletionTimestamp") is not None or not cm.get("uid") or not cm.get("resourceVersion"): raise D3Error("unsafe Cluster identity")
    if sm.get("deletionTimestamp") is not None or sm.get("name") != "external-infra-kubeconfig-disposable-ok141": raise D3Error("provider Secret not safely retained")
    if nm.get("deletionTimestamp") is not None or nm.get("name") != "disposable-ok141": raise D3Error("management namespace unsafe")
    now = dt.datetime.now(dt.timezone.utc)
    binding = {"format": "ok141-delete-d3-runtime-binding/v1", "state": "PASS-D3-PREFLIGHT-PRIVATE-BOUND-NO-GO", "candidateDigest": file_digest(candidate_path), "grantID": grant["grantID"], "observedAt": now.isoformat(), "expiresAt": (now+dt.timedelta(minutes=5)).isoformat(), "cluster": {"name": cm["name"], "namespace": cm["namespace"], "uid": cm["uid"], "resourceVersion": cm["resourceVersion"]}, "providerSecretPresent": True, "managementNamespacePresent": True, "mutationPerformed": False, "deletePerformed": False}
    output = Path(candidate["spec"]["privateOutputs"]["bindingPath"]); write_exclusive(output, binding)
    evidence = {"format": "ok141-delete-d3-preflight-private-evidence/v1", "state": binding["state"], "candidateDigest": file_digest(candidate_path), "bindingDigest": file_digest(output), "sealedGetCount": 3, "clusterBound": True, "providerSecretRetained": True, "managementNamespaceRetained": True, "mutationPerformed": False, "deletePerformed": False, "secretContentRetained": False, "rawObjectsRetained": False, "uidValuesRetained": False, "resourceVersionValuesRetained": False}
    write_exclusive(Path(candidate["spec"]["privateOutputs"]["preflightEvidencePath"]), evidence); return evidence


def live_cluster(current: dict[str, Any], bound: dict[str, str]) -> dict[str, str]:
    metadata = current.get("metadata", {})
    for key in ("name", "namespace", "uid"):
        if str(metadata.get(key, "")) != str(bound.get(key, "")): raise D3Error("live immutable Cluster identity mismatch")
    if metadata.get("deletionTimestamp") is not None or not metadata.get("resourceVersion"): raise D3Error("Cluster already deleting or resourceVersion missing")
    result = dict(bound); result["resourceVersion"] = str(metadata["resourceVersion"]); return result


def delete_payload(record: dict[str, str]) -> bytes:
    return json.dumps({"apiVersion":"v1","kind":"DeleteOptions","preconditions":{"uid":record["uid"],"resourceVersion":record["resourceVersion"]},"propagationPolicy":"Foreground"}, sort_keys=True, separators=(",", ":")).encode()


def execute(candidate_path: Path, grant_path: Path, binding_path: Path, kubectl: Path) -> dict[str, Any]:
    candidate = verify_candidate(candidate_path); grant = read_yaml(grant_path).get("spec", {}); grant_window(grant, dt.datetime.now(dt.timezone.utc))
    if binding_path.is_symlink() or not binding_path.is_file() or stat.S_IMODE(binding_path.stat().st_mode) != 0o600: raise D3Error("unsafe binding")
    binding = json.loads(binding_path.read_text())
    if binding.get("format") != "ok141-delete-d3-runtime-binding/v1" or binding.get("state") != "PASS-D3-PREFLIGHT-PRIVATE-BOUND-NO-GO" or binding.get("candidateDigest") != file_digest(candidate_path) or dt.datetime.now(dt.timezone.utc) > parse_time(binding.get("expiresAt", "")): raise D3Error("binding mismatch or expired")
    if grant.get("state") != "GRANTED" or grant.get("candidateDigest") != file_digest(candidate_path) or grant.get("d3BindingDigest") != file_digest(binding_path): raise D3Error("execution grant mismatch")
    for key in ("credentialUseAuthorized","mutationAuthorized","deleteAuthorized","partialStateAccepted"):
        if grant.get(key) is not True: raise D3Error(f"{key} required")
    for key in ("retryAuthorized","rollbackAuthorized","cleanupAuthorized","forceDeleteAuthorized","finalizerMutationAuthorized","childDeleteAuthorized","providerSecretDeleteAuthorized","d4MutationAuthorized","outageAuthorized","failureInjectionAuthorized"):
        if grant.get(key) is not False: raise D3Error(f"{key} must be false")
    if grant.get("stopPolicy") != "STOP-PRESERVE-NO-RETRY-NO-FINALIZER-MUTATION": raise D3Error("stop policy mismatch")
    kc = kubeconfig(candidate, kubectl); target = candidate["spec"]["target"]
    current = exact_get(kubectl, kc, target["clusterURI"]); record = live_cluster(current, binding["cluster"])
    result = run_raw(kubectl, kc, "delete", target["clusterURI"], delete_payload(record))
    if result.returncode != 0: raise D3Error("preconditioned Cluster delete failed")
    success = False
    for index in range(candidate["spec"]["operation"]["absencePollMaximumIterations"]):
        probe = run_raw(kubectl, kc, "get", target["clusterURI"])
        if probe.returncode != 0 and b"not found" in probe.stderr.lower(): success = True; break
        if probe.returncode != 0: raise D3Error("Cluster absence GET failed")
        if index+1 < candidate["spec"]["operation"]["absencePollMaximumIterations"]: time.sleep(candidate["spec"]["operation"]["absencePollIntervalSeconds"])
    evidence = {"format":"ok141-delete-d3-execution-private-evidence/v1","state":"PASS-D3-CAPI-CLUSTER-ABSENT-PRIVATE" if success else "STOP-D3-PARTIAL-PRESERVE-NO-RETRY","candidateDigest":file_digest(candidate_path),"bindingDigest":file_digest(binding_path),"grantID":grant["grantID"],"clusterDeleteRequested":True,"clusterAbsent":success,"foregroundPropagationUsed":True,"childDeleteRequestedByRunner":False,"providerSecretDeleteRequested":False,"retryPerformed":False,"rollbackPerformed":False,"cleanupPerformed":False,"forceDeletePerformed":False,"finalizerMutationPerformed":False,"rawObjectsRetained":False,"credentialContentRetained":False}
    write_exclusive(Path(candidate["spec"]["privateOutputs"]["executionEvidencePath"]), evidence)
    if not success: raise D3Error("CAPI Cluster deletion did not complete; private partial-state evidence written")
    return evidence


def main():
    parser=argparse.ArgumentParser(); parser.add_argument("command",choices=("verify","preflight","delete")); parser.add_argument("--candidate",type=Path,required=True); parser.add_argument("--grant",type=Path); parser.add_argument("--binding",type=Path); parser.add_argument("--kubectl",type=Path); parser.add_argument("--execute",action="store_true"); args=parser.parse_args(); candidate=args.candidate.resolve()
    if args.command=="verify":
        value=verify_candidate(candidate); print(json.dumps({"candidateDigest":file_digest(candidate),"semanticDigest":canonical_digest(value),"state":"PASS-D3-CANDIDATE-OFFLINE-NO-GO"},sort_keys=True))
    elif args.command=="preflight":
        if not args.execute or args.grant is None or args.kubectl is None: raise D3Error("preflight requires grant, kubectl and --execute")
        print(json.dumps(preflight(candidate,args.grant.resolve(),args.kubectl.resolve()),sort_keys=True))
    else:
        if not args.execute or args.grant is None or args.binding is None or args.kubectl is None: raise D3Error("delete requires grant, binding, kubectl and --execute")
        print(json.dumps(execute(candidate,args.grant.resolve(),args.binding.resolve(),args.kubectl.resolve()),sort_keys=True))


if __name__=="__main__":
    try: main()
    except (D3Error,OSError,ValueError,KeyError,json.JSONDecodeError,subprocess.TimeoutExpired) as error:
        print(f"ERROR: {error}",file=sys.stderr); raise SystemExit(1)
