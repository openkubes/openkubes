#!/usr/bin/env python3
"""Bounded exact-GET observer between OK-141 GO1-L stages G1 and G3."""

from __future__ import annotations

import argparse
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

import yaml


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
CANDIDATE = HERE / "go1-l-lifecycle-observer-candidate-v1.yaml"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


EXECUTOR = load_module("ok141_executor_v2_for_lifecycle_observer", SPIKE / "go1-l-executor-v2" / "bounded_go1_l_executor_v2.py")


class ObserverError(ValueError):
    pass


def read_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        value = yaml.safe_load(stream)
    if not isinstance(value, dict):
        raise ObserverError(f"expected mapping: {path}")
    return value


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def parse_time(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def resolve(candidate_path: Path, requested: str) -> Path:
    path = (candidate_path.parent / requested).resolve()
    if SPIKE.resolve() not in path.parents or not path.is_file():
        raise ObserverError(f"reference missing or outside spike root: {requested}")
    return path


def expect(actual: Any, expected: Any, context: str) -> None:
    if actual != expected:
        raise ObserverError(f"{context}: expected {expected!r}, got {actual!r}")


def validate_candidate(candidate_path: Path = CANDIDATE) -> dict[str, Any]:
    candidate = read_yaml(candidate_path)
    expect(candidate.get("apiVersion"), "evidence.openkubes.io/v1alpha1", "apiVersion")
    expect(candidate.get("kind"), "GO1LLifecycleAPIObserverCandidate", "kind")
    spec = candidate["spec"]
    expect(spec["version"], "ok141-go1-l-lifecycle-api-observer/v1", "version")
    expect(spec["state"], "OFFLINE-PROVEN-BLOCKED-NO-GO", "state")
    for section in ("protocol", "runtimePackage", "preflight"):
        expect(digest(resolve(candidate_path, spec[section]["path"])), spec[section]["digest"], f"{section} digest")
    closure_path = resolve(candidate_path, spec["credential"]["closurePath"])
    expect(digest(closure_path), spec["credential"]["closureDigest"], "credential closure digest")
    closure = read_yaml(closure_path)
    expect(closure["spec"]["identities"]["ok-mgmt"]["identityDigest"], spec["credential"]["identityDigest"], "ok-mgmt identity")
    expect(spec["credential"]["claim"], "HTTPS-API-ENDPOINT-AND-CA-ONLY", "identity claim")
    expect(spec["client"]["digest"], "sha256:bb211f2b31f2b3bc60562b44cc1e3b712a16a98e9072968ba255beb04cefcfdf", "client digest")
    observation = spec["observation"]
    expect((observation["intervalSeconds"], observation["maximumIterations"], observation["maximumDurationSeconds"]), (15, 180, 2700), "poll boundary")
    queries = observation["queries"]
    expect([query["id"] for query in queries], ["cluster", "infrastructure-cluster", "control-plane", "workers"], "query IDs")
    if len({query["rawURI"] for query in queries}) != 4 or any("?" in query["rawURI"] for query in queries):
        raise ObserverError("queries must be four unique exact raw GETs")
    acceptance = spec["acceptance"]
    expect(acceptance["requiredObjects"], ["cluster", "infrastructure-cluster", "control-plane", "workers"], "required objects")
    expect(acceptance["requiredClusterCondition"], {"type": "ControlPlaneInitialized", "status": "True", "observedGenerationMustEqualObjectGeneration": True}, "cluster condition")
    expect((acceptance["nodeReadyRequired"], acceptance["networkReadyRequired"], acceptance["controlPlaneAvailableRequired"]), (False, False, False), "bootstrap boundary")
    tool = spec["tool"]
    expect(digest(resolve(candidate_path, tool["path"])), tool["digest"], "tool digest")
    if tool["discoveryListWatchAllowed"] or tool["mutationAllowed"] or tool["retrySubmissionAllowed"] or tool["rollbackOrCleanupAllowed"]:
        raise ObserverError("tool expands the read-only boundary")
    authorization = spec["authorization"]
    expect(authorization["decision"], "NO-GO", "authorization")
    expect(authorization["grantIDs"], [], "grant inventory")
    if any(value for key, value in authorization.items() if key.endswith("Granted")):
        raise ObserverError("candidate grants live authority")
    return candidate


def validate_grant(candidate_path: Path, grant_path: Path, now: dt.datetime | None = None) -> dict[str, Any]:
    candidate = validate_candidate(candidate_path)
    grant = read_yaml(grant_path)
    expect(grant.get("apiVersion"), "authorization.openkubes.io/v1alpha1", "grant apiVersion")
    expect(grant.get("kind"), "GO1LLifecycleAPIObserverGrant", "grant kind")
    spec = grant["spec"]
    expect(spec["decision"], "GO", "grant decision")
    expect(spec["candidateDigest"], digest(candidate_path), "candidate digest")
    expect(spec["protocolDigest"], candidate["spec"]["protocol"]["digest"], "protocol digest")
    expect(spec["fixtureDigest"], candidate["spec"]["protocol"]["fixtureDigest"], "fixture digest")
    expect(spec["runtimePackageDigest"], candidate["spec"]["runtimePackage"]["digest"], "runtime package")
    expect(spec["credentialIdentityDigest"], candidate["spec"]["credential"]["identityDigest"], "credential identity")
    expect(spec["authority"], "github:arashkaffamanesh", "authority")
    if not spec.get("grantID") or spec.get("singleRun") is not True or spec.get("consumed") is not False:
        raise ObserverError("grant is not unused single-run authority")
    if sorted(spec["g1OperationEvidenceDigests"]) != ["capi-lifecycle", "management-namespace", "provider-access-secret", "provider-prerequisites"]:
        raise ObserverError("grant does not bind exactly four G1 operation outcomes")
    for value in spec["g1OperationEvidenceDigests"].values():
        if not isinstance(value, str) or not value.startswith("sha256:") or len(value) != 71:
            raise ObserverError("invalid G1 predecessor digest")
    expected_true = ("clusterContactGranted", "credentialUseGranted", "readOnlyObserverGranted")
    expected_false = ("mutationGranted", "g3Granted", "go1Granted", "retryGranted", "rollbackOrCleanupGranted", "evidencePublicationGranted", "failureInjectionGranted")
    if any(spec.get(key) is not True for key in expected_true) or any(spec.get(key) is not False for key in expected_false):
        raise ObserverError("grant authority exceeds the exact read-only observer")
    current = now or dt.datetime.now(dt.timezone.utc)
    issued, expires = parse_time(spec["issuedAt"]), parse_time(spec["expiresAt"])
    if not issued <= current <= expires or expires - issued > dt.timedelta(minutes=50):
        raise ObserverError("grant is inactive or exceeds 50 minutes")
    expect(spec["outputPath"], candidate["spec"]["observation"]["outputPath"], "output path")
    return grant


def condition_map(obj: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item.get("type", ""): item for item in obj.get("status", {}).get("conditions", []) if isinstance(item, dict)}


def identity_for(obj: dict[str, Any]) -> str:
    api = obj.get("apiVersion", "")
    meta = obj.get("metadata", {})
    namespace = meta.get("namespace") or "_"
    return f"{api}|{obj.get('kind', '')}|{namespace}|{meta.get('name', '')}"


def retained(query: dict[str, Any], obj: dict[str, Any]) -> dict[str, Any]:
    meta, status = obj.get("metadata", {}), obj.get("status", {})
    conditions = []
    for item in status.get("conditions", []):
        if isinstance(item, dict):
            conditions.append({key: item[key] for key in ("type", "status", "reason", "observedGeneration") if key in item})
    return {
        "queryID": query["id"],
        "identity": identity_for(obj),
        "uid": meta.get("uid"),
        "generation": meta.get("generation"),
        "observedGeneration": status.get("observedGeneration"),
        "intentRevision": meta.get("annotations", {}).get("openkubes.io/intent-revision"),
        "conditions": conditions,
    }


def evaluate(candidate: dict[str, Any], objects: dict[str, dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    spec = candidate["spec"]
    required = spec["acceptance"]["requiredObjects"]
    if sorted(objects) != sorted(required):
        return "WAIT-OBJECTS", {"missing": sorted(set(required) - set(objects))}
    query_by_id = {item["id"]: item for item in spec["observation"]["queries"]}
    retained_objects = {}
    for query_id in required:
        obj = objects[query_id]
        if identity_for(obj) != query_by_id[query_id]["identity"]:
            return "FAIL-IDENTITY", {"queryID": query_id}
        if obj.get("metadata", {}).get("annotations", {}).get("openkubes.io/intent-revision") != spec["protocol"]["intentRevision"]:
            return "FAIL-INTENT-REVISION", {"queryID": query_id}
        if not isinstance(obj.get("metadata", {}).get("uid"), str) or not obj["metadata"]["uid"]:
            return "WAIT-UID", {"queryID": query_id}
        retained_objects[query_id] = retained(query_by_id[query_id], obj)

    cluster = objects["cluster"]
    cluster_meta, cluster_spec, cluster_status = cluster["metadata"], cluster.get("spec", {}), cluster.get("status", {})
    generation = cluster_meta.get("generation")
    if not isinstance(generation, int) or cluster_status.get("observedGeneration") != generation:
        return "WAIT-CLUSTER-GENERATION", {"objects": retained_objects}
    expected_refs = {
        "infrastructureRef": ("infrastructure.cluster.x-k8s.io", "KubevirtCluster", "disposable-ok141"),
        "controlPlaneRef": ("controlplane.cluster.x-k8s.io", "TalosControlPlane", "disposable-ok141-cp"),
    }
    for field, expected in expected_refs.items():
        ref = cluster_spec.get(field, {})
        if (ref.get("apiGroup"), ref.get("kind"), ref.get("name")) != expected:
            return "FAIL-TYPED-REFERENCE", {"field": field, "objects": retained_objects}
    endpoint = cluster_spec.get("controlPlaneEndpoint", {})
    if not isinstance(endpoint.get("host"), str) or not endpoint["host"] or not isinstance(endpoint.get("port"), int) or endpoint["port"] <= 0:
        return "WAIT-CONTROL-PLANE-ENDPOINT", {"objects": retained_objects}
    condition = condition_map(cluster).get("ControlPlaneInitialized")
    if not condition or condition.get("status") != "True" or condition.get("observedGeneration") != generation:
        return "WAIT-CONTROL-PLANE-INITIALIZED", {"objects": retained_objects}
    return "PASS-CURRENT-LIFECYCLE-API-EVIDENCE", {
        "objects": retained_objects,
        "endpoint": {"present": True, "port": endpoint["port"]},
        "condition": {key: condition[key] for key in ("type", "status", "reason", "observedGeneration") if key in condition},
    }


def run_query(kubectl: Path, kubeconfig: Path, query: dict[str, Any], runner: Callable[..., Any]) -> tuple[str, dict[str, Any] | None]:
    completed = runner([str(kubectl), "--kubeconfig", str(kubeconfig), "get", "--raw", query["rawURI"]], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if completed.returncode != 0:
        text = (completed.stdout + completed.stderr).decode(errors="replace")
        if "NotFound" in text or "not found" in text.lower() or '"code":404' in text:
            return "ABSENT", None
        raise ObserverError(f"exact GET failed for {query['id']}")
    value = json.loads(completed.stdout)
    if not isinstance(value, dict):
        raise ObserverError(f"non-object response for {query['id']}")
    return "PRESENT", value


def execute(candidate_path: Path, grant_path: Path, kubectl: Path, now: dt.datetime | None = None, runner: Callable[..., Any] = subprocess.run, sleeper: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    candidate = validate_candidate(candidate_path)
    grant = validate_grant(candidate_path, grant_path, now)
    spec = candidate["spec"]
    if digest(kubectl) != spec["client"]["digest"]:
        raise ObserverError("kubectl digest mismatch")
    kubeconfig = Path(spec["credential"]["path"])
    if kubeconfig.is_symlink() or not kubeconfig.is_file() or (kubeconfig.stat().st_mode & 0o777) != 0o600:
        raise ObserverError("unsafe ok-mgmt kubeconfig")
    current_identity = EXECUTOR.inspect_identity(kubeconfig)
    expect(current_identity["identityDigest"], spec["credential"]["identityDigest"], "point-of-use credential identity")
    output = Path(spec["observation"]["outputPath"])
    if output.exists():
        raise ObserverError("evidence output already exists")
    started = dt.datetime.now(dt.timezone.utc)
    history = []
    final_details: dict[str, Any] = {}
    state = "TIMEOUT-LIFECYCLE-API-NOT-READY"
    for iteration in range(1, spec["observation"]["maximumIterations"] + 1):
        objects = {}
        absent = []
        for query in spec["observation"]["queries"]:
            outcome, obj = run_query(kubectl, kubeconfig, query, runner)
            if outcome == "PRESENT" and obj is not None:
                objects[query["id"]] = obj
            else:
                absent.append(query["id"])
        if absent:
            state, details = "WAIT-OBJECTS", {"missing": absent}
        else:
            state, details = evaluate(candidate, objects)
        history.append({"iteration": iteration, "state": state})
        final_details = details
        if state == "PASS-CURRENT-LIFECYCLE-API-EVIDENCE" or state.startswith("FAIL-"):
            break
        if iteration < spec["observation"]["maximumIterations"]:
            sleeper(spec["observation"]["intervalSeconds"])
    evidence = {
        "apiVersion": "evidence.openkubes.io/v1alpha1",
        "kind": "GO1LLifecycleAPIEvidence",
        "candidateDigest": digest(candidate_path),
        "grantID": grant["spec"]["grantID"],
        "protocolDigest": spec["protocol"]["digest"],
        "fixtureDigest": spec["protocol"]["fixtureDigest"],
        "intentRevision": spec["protocol"]["intentRevision"],
        "g1OperationEvidenceDigests": grant["spec"]["g1OperationEvidenceDigests"],
        "credentialIdentityDigest": current_identity["identityDigest"],
        "startedAt": started.isoformat(),
        "completedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "iterations": history,
        "closureState": state,
        "details": final_details,
        "predecessorClass": "CURRENT-LIFECYCLE-API-EVIDENCE" if state == "PASS-CURRENT-LIFECYCLE-API-EVIDENCE" else None,
        "secretReadsPerformed": False,
        "credentialBytesEmitted": False,
        "mutationPerformed": False,
    }
    evidence["semanticDigest"] = canonical_digest({key: value for key, value in evidence.items() if key not in ("startedAt", "completedAt", "semanticDigest")})
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(output, flags, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(evidence, stream, sort_keys=True, separators=(",", ":"))
        stream.write("\n")
    if state != "PASS-CURRENT-LIFECYCLE-API-EVIDENCE":
        raise ObserverError(f"observer did not pass: {state}")
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "verify-grant", "observe"))
    parser.add_argument("--candidate", type=Path, default=CANDIDATE)
    parser.add_argument("--grant", type=Path)
    parser.add_argument("--kubectl", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "verify":
            validate_candidate(args.candidate.resolve())
            print(digest(args.candidate.resolve()))
        elif args.command == "verify-grant":
            if args.grant is None:
                raise ObserverError("grant is required")
            validate_grant(args.candidate.resolve(), args.grant.resolve())
            print(digest(args.grant.resolve()))
        else:
            if not args.execute or args.grant is None or args.kubectl is None:
                raise ObserverError("observe requires --execute, --grant and --kubectl")
            result = execute(args.candidate.resolve(), args.grant.resolve(), args.kubectl.resolve())
            print(json.dumps({"closureState": result["closureState"], "semanticDigest": result["semanticDigest"]}, sort_keys=True))
        return 0
    except (ObserverError, OSError, KeyError, TypeError, ValueError, yaml.YAMLError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
