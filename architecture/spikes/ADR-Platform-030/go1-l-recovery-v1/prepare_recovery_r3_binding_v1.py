#!/usr/bin/env python3
"""Prepare a fresh private R3 binding from three exact ok-infra GETs."""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml


HERE = Path(__file__).resolve().parent
MODULE_SPEC = importlib.util.spec_from_file_location(
    "observe_recovery_snapshot_attempt_for_r3", HERE / "observe_recovery_snapshot_attempt_v1.py"
)
BASE = importlib.util.module_from_spec(MODULE_SPEC)
assert MODULE_SPEC.loader is not None
MODULE_SPEC.loader.exec_module(BASE)
V2 = BASE.V2
V1 = BASE.V1
R3Error = BASE.SnapshotError
TOOL_DIGEST = BASE.TOOL_DIGEST
PROTOCOL_DIGEST = "sha256:0be2957f7c417e9c7c25f2595b5168a95f11e72c76508d83f774719045df8bd9"
FAILED_INTENT = "sha256:636fe23404ac53109f44d6346534dcf1367ae91c572d5e18bd32cd0a3128a16e"
ATTEMPT_ID = re.compile(r"^r3-v[1-9][0-9]*-[0-9]{8}-[0-9]{2}$")
TARGETS = [
    {
        "id": "golden-image-cloner-binding",
        "identity": "rbac.authorization.k8s.io/v1|RoleBinding|ok-images|disposable-ok141-talos-golden-image-cloner",
        "mode": "exact",
        "rawURI": "/apis/rbac.authorization.k8s.io/v1/namespaces/ok-images/rolebindings/disposable-ok141-talos-golden-image-cloner",
    },
    {
        "id": "golden-image-cloner-role",
        "identity": "rbac.authorization.k8s.io/v1|Role|ok-images|disposable-ok141-talos-golden-image-cloner",
        "mode": "exact",
        "rawURI": "/apis/rbac.authorization.k8s.io/v1/namespaces/ok-images/roles/disposable-ok141-talos-golden-image-cloner",
    },
    {
        "id": "infra-namespace",
        "identity": "v1|Namespace|_|disposable-ok141",
        "mode": "exact",
        "rawURI": "/api/v1/namespaces/disposable-ok141",
    },
]


def verify_candidate(path: Path) -> dict[str, Any]:
    candidate = V1.read(path)
    spec = candidate["spec"]
    if spec["version"] != "ok141-go1-l-recovery-r3-binding/v1" or spec["state"] != "READY-FOR-EXPLICIT-READ-ONLY-GRANT":
        raise R3Error("candidate identity or state mismatch")
    if spec["protocolDigest"] != PROTOCOL_DIGEST:
        raise R3Error("protocol digest mismatch")
    predecessor = spec["predecessor"]
    if predecessor["r2State"] != "PASS-R2-CLEAN":
        raise R3Error("R2 predecessor is not clean")
    for claim in ("r2CandidateDigest", "r2EvidenceDigest"):
        value = predecessor.get(claim)
        if not isinstance(value, str) or not value.startswith("sha256:") or len(value) != 71:
            raise R3Error(f"R2 predecessor lacks {claim}")
    attempt = spec["attempt"]
    if not ATTEMPT_ID.fullmatch(attempt["id"]):
        raise R3Error("invalid R3 attempt identity")
    if spec["tool"]["executorDigest"] != V1.sha256(Path(__file__).resolve()):
        raise R3Error("executor digest mismatch")
    if spec["tool"]["kubectlDigest"] != TOOL_DIGEST:
        raise R3Error("kubectl digest mismatch")
    if spec["kubeconfigPath"] != "/Users/arash/.kube/ok-infra.yaml":
        raise R3Error("unexpected credential path")
    if spec["queries"] != TARGETS:
        raise R3Error("R3 query set or order mismatch")
    evidence = spec["evidence"]
    expected_evidence = f"/private/tmp/ok141-go1-l-recovery-{attempt['id']}-preflight-evidence.json"
    expected_binding = f"/private/tmp/ok141-go1-l-recovery-{attempt['id']}-runtime-binding.yaml"
    if evidence["outputPath"] != expected_evidence or evidence["bindingOutputPath"] != expected_binding:
        raise R3Error("private output identity mismatch")
    if evidence["freshnessMaximumMinutes"] != 10 or not evidence["outputsMustBeAbsent"]:
        raise R3Error("binding freshness or output precondition mismatch")
    if any(spec["authorization"].values()):
        raise R3Error("candidate grants authority")
    return candidate


def verify_grant(candidate_path: Path, grant_path: Path, now: dt.datetime | None = None) -> dict[str, Any]:
    candidate = verify_candidate(candidate_path)
    grant = V1.read(grant_path)
    spec = grant["spec"]
    if spec["state"] != "GRANTED" or not spec["readOnlyAuthorized"] or not spec["credentialUseAuthorized"]:
        raise R3Error("R3 preflight is not granted")
    if spec["candidateDigest"] != V1.sha256(candidate_path):
        raise R3Error("grant candidate digest mismatch")
    if spec["maximumRuns"] != 1 or spec["consumed"]:
        raise R3Error("grant is reused or not single-run")
    for claim in (
        "mutationAuthorized", "cleanupAuthorized", "retryAuthorized", "secretReadAuthorized",
        "r3DeleteAuthorized", "recreateAuthorized", "go1LAuthorized", "go1Authorized",
        "failureInjectionAuthorized",
    ):
        if spec[claim]:
            raise R3Error("grant carries excluded authority")
    current = now or dt.datetime.now(dt.timezone.utc)
    start, end = V1.parse_time(spec["notBefore"]), V1.parse_time(spec["notAfter"])
    if not start <= current <= end or end - start > dt.timedelta(minutes=20):
        raise R3Error("grant window is inactive or exceeds 20 minutes")
    evidence = candidate["spec"]["evidence"]
    if spec["outputPath"] != evidence["outputPath"] or spec["bindingOutputPath"] != evidence["bindingOutputPath"]:
        raise R3Error("grant output mismatch")
    return grant


def identity(value: dict[str, Any]) -> str:
    namespace = value.get("namespace") or "_"
    return f"{value['apiVersion']}|{value['kind']}|{namespace}|{value['name']}"


def validate_result(query: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    if result["outcome"] != "PRESENT" or len(result["objects"]) != 1:
        raise R3Error(f"expected one present object: {query['id']}")
    value = result["objects"][0]
    if identity(value) != query["identity"]:
        raise R3Error(f"identity mismatch: {query['id']}")
    if not value.get("uid") or not value.get("resourceVersion"):
        raise R3Error(f"missing live identity fields: {query['id']}")
    if value.get("deletionTimestamp") is not None or value.get("finalizers") or value.get("ownerReferences"):
        raise R3Error(f"unsafe object state: {query['id']}")
    if value.get("intentRevision") != FAILED_INTENT:
        raise R3Error(f"intent revision mismatch: {query['id']}")
    return value


def bound(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "identity": identity(value),
        "uid": value["uid"],
        "resourceVersion": value["resourceVersion"],
        "deletionTimestamp": value.get("deletionTimestamp"),
        "finalizers": value.get("finalizers") or [],
        "ownerReferences": value.get("ownerReferences") or [],
        "intentRevision": value.get("intentRevision"),
    }


def execute(candidate_path: Path, grant_path: Path, kubectl: Path) -> dict[str, Any]:
    candidate = verify_candidate(candidate_path)
    grant = verify_grant(candidate_path, grant_path)
    if V1.sha256(kubectl) != TOOL_DIGEST:
        raise R3Error("local kubectl digest mismatch")
    spec = candidate["spec"]
    kubeconfig = Path(spec["kubeconfigPath"])
    if kubeconfig.is_symlink() or not kubeconfig.is_file() or (kubeconfig.stat().st_mode & 0o777) != 0o600:
        raise R3Error("unsafe ok-infra credential")
    evidence_path = Path(spec["evidence"]["outputPath"])
    binding_path = Path(spec["evidence"]["bindingOutputPath"])
    if evidence_path.exists() or binding_path.exists():
        raise R3Error("private output already exists")
    started = dt.datetime.now(dt.timezone.utc)
    results = [V2.run_query(kubectl, kubeconfig, query) for query in spec["queries"]]
    objects = [validate_result(query, result) for query, result in zip(spec["queries"], results)]
    completed = dt.datetime.now(dt.timezone.utc)
    evidence = {
        "candidateDigest": V1.sha256(candidate_path),
        "grantID": grant["spec"]["grantID"],
        "startedAt": started.isoformat(),
        "completedAt": completed.isoformat(),
        "credentialBytesEmitted": False,
        "secretReadsPerformed": False,
        "mutationPerformed": False,
        "results": results,
        "state": "PASS-R3-PREFLIGHT-BOUND",
    }
    evidence_path.write_text(json.dumps(evidence, sort_keys=True, separators=(",", ":")) + "\n")
    evidence_path.chmod(0o600)
    binding = {
        "apiVersion": "recovery.openkubes.io/v1alpha1",
        "kind": "GO1LRecoveryR3RuntimeBinding",
        "metadata": {"name": f"ok141-go1-l-recovery-{spec['attempt']['id']}-binding", "ticket": "OK-141"},
        "spec": {
            "state": "READY-FOR-EXPLICIT-R3-DELETE-GRANT",
            "protocolDigest": PROTOCOL_DIGEST,
            "attemptID": spec["attempt"]["id"],
            "observedAt": completed.isoformat(),
            "expiresAt": (completed + dt.timedelta(minutes=spec["evidence"]["freshnessMaximumMinutes"])).isoformat(),
            "sourceCandidateDigest": V1.sha256(candidate_path),
            "sourceEvidenceDigest": V1.sha256(evidence_path),
            "sourceR2EvidenceDigest": spec["predecessor"]["r2EvidenceDigest"],
            "objects": {query["id"]: bound(value) for query, value in zip(spec["queries"], objects)},
            "credentialsIncluded": False,
            "publicUIDPublicationAllowed": False,
            "executable": False,
        },
    }
    binding_path.write_text(yaml.safe_dump(binding, sort_keys=False))
    binding_path.chmod(0o600)
    return {
        "evidenceDigest": V1.sha256(evidence_path),
        "bindingDigest": V1.sha256(binding_path),
        "state": evidence["state"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "verify-grant", "prepare"))
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--grant", type=Path)
    parser.add_argument("--kubectl", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "verify":
            verify_candidate(args.candidate.resolve())
            print(V1.sha256(args.candidate.resolve()))
        elif args.command == "verify-grant":
            if args.grant is None:
                raise R3Error("grant is required")
            verify_grant(args.candidate.resolve(), args.grant.resolve())
            print(V1.sha256(args.grant.resolve()))
        else:
            if not args.execute or args.grant is None or args.kubectl is None:
                raise R3Error("prepare requires --execute, grant and kubectl")
            print(json.dumps(execute(args.candidate.resolve(), args.grant.resolve(), args.kubectl.resolve()), sort_keys=True))
        return 0
    except (R3Error, KeyError, OSError, TypeError, ValueError, json.JSONDecodeError, yaml.YAMLError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
