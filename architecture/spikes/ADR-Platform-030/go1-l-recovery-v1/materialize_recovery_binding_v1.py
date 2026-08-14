#!/usr/bin/env python3
"""Materialize a private cleanup binding from a successful OK-141 R0-v2 snapshot."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import stat
import sys
from pathlib import Path
from typing import Any

import yaml


PROTOCOL_DIGEST = "sha256:0be2957f7c417e9c7c25f2595b5168a95f11e72c76508d83f774719045df8bd9"
OBSERVATION_CANDIDATE_DIGEST = "sha256:4cc18693b948844a0516492395e7943cd1f1925d66b35f25d35977c989bac71f"
FAILED_INTENT = "sha256:636fe23404ac53109f44d6346534dcf1367ae91c572d5e18bd32cd0a3128a16e"
MGMT_PRESENT = [
    "mgmt-namespace", "cluster", "kubevirt-cluster", "talos-control-plane",
    "talos-worker-template", "machine-deployment", "control-plane-machine-template",
    "worker-machine-template", "misrouted-load-balancer", "machine-sets",
]
MGMT_ABSENT = ["machines", "kubevirt-machines"]
MGMT_API_NOT_SERVED = ["local-provider-vms", "local-provider-vmis"]
INFRA_PRESENT = ["infra-namespace", "golden-image-cloner-role", "golden-image-cloner-binding"]
INFRA_ABSENT = ["intended-provider-load-balancer", "provider-vms", "provider-vmis"]


class BindingError(ValueError):
    pass


def sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def timestamp(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise BindingError("timestamp must include timezone")
    return parsed


def index(plane: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result = {item["id"]: item for item in plane}
    if len(result) != len(plane):
        raise BindingError("duplicate query identity")
    return result


def one_present(queries: dict[str, dict[str, Any]], query_id: str) -> dict[str, Any]:
    query = queries.get(query_id)
    if query is None or query.get("outcome") != "PRESENT" or len(query.get("objects", [])) != 1:
        raise BindingError(f"expected one PRESENT object: {query_id}")
    value = query["objects"][0]
    for claim in ("apiVersion", "kind", "name", "uid", "resourceVersion"):
        if not value.get(claim):
            raise BindingError(f"{query_id} lacks {claim}")
    if value.get("deletionTimestamp") is not None:
        raise BindingError(f"{query_id} is already deleting")
    return value


def require_outcomes(queries: dict[str, dict[str, Any]], ids: list[str], outcome: str) -> None:
    for query_id in ids:
        query = queries.get(query_id)
        if query is None or query.get("outcome") != outcome or query.get("objects") != []:
            raise BindingError(f"unexpected {query_id} outcome")


def identity(value: dict[str, Any]) -> str:
    namespace = value.get("namespace") or "_"
    return f"{value['apiVersion']}|{value['kind']}|{namespace}|{value['name']}"


def retained(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "identity": identity(value),
        "uid": value["uid"],
        "resourceVersion": value["resourceVersion"],
        "generation": value.get("generation"),
        "deletionTimestamp": value.get("deletionTimestamp"),
        "finalizers": value.get("finalizers") or [],
        "ownerReferences": value.get("ownerReferences") or [],
        "intentRevision": value.get("intentRevision"),
    }


def validate_snapshot(evidence_path: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    if evidence_path.is_symlink() or not evidence_path.is_file() or stat.S_IMODE(evidence_path.stat().st_mode) != 0o600:
        raise BindingError("snapshot must be a mode-0600 regular non-symlink file")
    evidence = json.loads(evidence_path.read_text())
    expected_top_level = {
        "candidateDigest", "grantID", "startedAt", "completedAt",
        "credentialBytesEmitted", "credentialUseAuthorized",
        "secretReadsPerformed", "mutationPerformed", "planes",
    }
    if set(evidence) != expected_top_level:
        raise BindingError("snapshot top-level field set mismatch")
    if evidence.get("candidateDigest") != OBSERVATION_CANDIDATE_DIGEST:
        raise BindingError("observation candidate mismatch")
    if evidence.get("credentialBytesEmitted") is not False or evidence.get("secretReadsPerformed") is not False or evidence.get("mutationPerformed") is not False:
        raise BindingError("snapshot crossed a security boundary")
    if set(evidence.get("planes", {})) != {"ok-mgmt", "ok-infra"}:
        raise BindingError("plane set mismatch")
    mgmt, infra = index(evidence["planes"]["ok-mgmt"]), index(evidence["planes"]["ok-infra"])
    if set(mgmt) != set(MGMT_PRESENT + MGMT_ABSENT + MGMT_API_NOT_SERVED):
        raise BindingError("management query set mismatch")
    if set(infra) != set(INFRA_PRESENT + INFRA_ABSENT):
        raise BindingError("infrastructure query set mismatch")
    expected_query_fields = {"id", "outcome", "objects"}
    expected_object_fields = {
        "apiVersion", "kind", "name", "namespace", "uid", "resourceVersion",
        "generation", "deletionTimestamp", "finalizers", "ownerReferences", "intentRevision",
    }
    for query in [*mgmt.values(), *infra.values()]:
        if set(query) != expected_query_fields:
            raise BindingError(f"unexpected query fields: {query.get('id')}")
        for value in query["objects"]:
            if set(value) != expected_object_fields:
                raise BindingError(f"unexpected object fields: {query['id']}")
    for query_id in MGMT_PRESENT:
        one_present(mgmt, query_id)
    for query_id in INFRA_PRESENT:
        one_present(infra, query_id)
    require_outcomes(mgmt, MGMT_ABSENT, "ABSENT")
    require_outcomes(mgmt, MGMT_API_NOT_SERVED, "API_NOT_SERVED")
    require_outcomes(infra, INFRA_ABSENT, "ABSENT")
    for query_id in [item for item in MGMT_PRESENT if item != "misrouted-load-balancer"] + INFRA_PRESENT:
        if one_present(mgmt if query_id in MGMT_PRESENT else infra, query_id).get("intentRevision") != FAILED_INTENT:
            raise BindingError(f"unexpected failed intent revision: {query_id}")
    service = one_present(mgmt, "misrouted-load-balancer")
    if service.get("intentRevision") is not None:
        raise BindingError("generated Service unexpectedly claims direct intent provenance")
    return evidence, mgmt, infra


def materialize(evidence_path: Path) -> dict[str, Any]:
    evidence, mgmt, infra = validate_snapshot(evidence_path)
    completed = timestamp(evidence["completedAt"])
    lifecycle_ids = [item for item in MGMT_PRESENT if item not in ("mgmt-namespace", "misrouted-load-balancer")]
    return {
        "apiVersion": "recovery.openkubes.io/v1alpha1",
        "kind": "GO1LRecoveryRuntimeBinding",
        "metadata": {"name": "ok141-go1-l-recovery-runtime-binding-v1", "ticket": "OK-141"},
        "spec": {
            "state": "READY-FOR-EXPLICIT-UID-PRECONDITIONED-CLEANUP-GRANT",
            "protocolDigest": PROTOCOL_DIGEST,
            "observedAt": completed.isoformat(),
            "expiresAt": (completed + dt.timedelta(minutes=10)).isoformat(),
            "sourceEvidenceDigests": [sha(evidence_path)],
            "sourceObservationCandidateDigest": evidence["candidateDigest"],
            "sourceGrantID": evidence["grantID"],
            "objects": {
                "okMgmt": {
                    "namespace": retained(one_present(mgmt, "mgmt-namespace")),
                    "lifecycle": [retained(one_present(mgmt, item)) for item in lifecycle_ids],
                    "misroutedService": retained(one_present(mgmt, "misrouted-load-balancer")),
                },
                "okInfra": {
                    "namespace": retained(one_present(infra, "infra-namespace")),
                    "role": retained(one_present(infra, "golden-image-cloner-role")),
                    "roleBinding": retained(one_present(infra, "golden-image-cloner-binding")),
                },
            },
            "generatedInventory": {
                "machines": [],
                "kubevirtMachines": [],
                "localProviderVMAPI": "API_NOT_SERVED",
                "localProviderVMIAPI": "API_NOT_SERVED",
                "providerVirtualMachines": [],
                "providerVirtualMachineInstances": [],
            },
            "credentialsIncluded": False,
            "publicUIDPublicationAllowed": False,
            "executable": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify-evidence", "materialize"))
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        path = args.evidence.resolve()
        if args.command == "verify-evidence":
            validate_snapshot(path)
            result = {"evidenceDigest": sha(path), "bindingWritten": False}
        else:
            if args.output is None or not str(args.output).startswith("/private/tmp/"):
                raise BindingError("private /private/tmp output is required")
            output = args.output.resolve()
            if output.exists():
                raise BindingError("binding output already exists")
            value = materialize(path)
            output.write_text(yaml.safe_dump(value, sort_keys=False))
            output.chmod(0o600)
            result = {"evidenceDigest": sha(path), "bindingDigest": sha(output), "bindingWritten": True}
        print(json.dumps(result, sort_keys=True))
        return 0
    except (BindingError, KeyError, OSError, TypeError, ValueError, json.JSONDecodeError, yaml.YAMLError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
