#!/usr/bin/env python3
"""Materialize a private binding from a reviewed immutable R0 attempt."""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import stat
import sys
from pathlib import Path
from typing import Any

import yaml


HERE = Path(__file__).resolve().parent
BASE_SPEC = importlib.util.spec_from_file_location(
    "materialize_recovery_binding_v1_for_attempt", HERE / "materialize_recovery_binding_v1.py"
)
BASE = importlib.util.module_from_spec(BASE_SPEC)
assert BASE_SPEC.loader is not None
BASE_SPEC.loader.exec_module(BASE)
OBS_SPEC = importlib.util.spec_from_file_location(
    "observe_recovery_snapshot_attempt_for_binding", HERE / "observe_recovery_snapshot_attempt_v1.py"
)
OBS = importlib.util.module_from_spec(OBS_SPEC)
assert OBS_SPEC.loader is not None
OBS_SPEC.loader.exec_module(OBS)
BindingError = BASE.BindingError
BINDING_VERSION = "ok141-go1-l-recovery-runtime-binding/attempt-v1"


def validate_snapshot(
    evidence_path: Path, candidate_path: Path
) -> tuple[dict[str, Any], dict[str, Any], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    candidate = OBS.verify_candidate(candidate_path)
    if evidence_path.is_symlink() or not evidence_path.is_file() or stat.S_IMODE(evidence_path.stat().st_mode) != 0o600:
        raise BindingError("snapshot must be a mode-0600 regular non-symlink file")
    evidence = json.loads(evidence_path.read_text())
    expected_top_level = {
        "candidateDigest", "attemptID", "grantID", "startedAt", "completedAt",
        "credentialBytesEmitted", "credentialUseAuthorized", "secretReadsPerformed",
        "mutationPerformed", "planes",
    }
    if set(evidence) != expected_top_level:
        raise BindingError("snapshot top-level field set mismatch")
    if evidence["candidateDigest"] != BASE.sha(candidate_path):
        raise BindingError("observation candidate mismatch")
    if evidence["attemptID"] != candidate["spec"]["attempt"]["id"]:
        raise BindingError("attempt identity mismatch")
    if evidence["credentialBytesEmitted"] is not False or evidence["secretReadsPerformed"] is not False or evidence["mutationPerformed"] is not False:
        raise BindingError("snapshot crossed a security boundary")
    if evidence["credentialUseAuthorized"] is not True:
        raise BindingError("snapshot lacks credential-use evidence")
    if set(evidence.get("planes", {})) != {"ok-mgmt", "ok-infra"}:
        raise BindingError("plane set mismatch")

    mgmt = BASE.index(evidence["planes"]["ok-mgmt"])
    infra = BASE.index(evidence["planes"]["ok-infra"])
    if set(mgmt) != set(BASE.MGMT_PRESENT + BASE.MGMT_ABSENT + BASE.MGMT_API_NOT_SERVED):
        raise BindingError("management query set mismatch")
    if set(infra) != set(BASE.INFRA_PRESENT + BASE.INFRA_ABSENT):
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
    for query_id in BASE.MGMT_PRESENT:
        BASE.one_present(mgmt, query_id)
    for query_id in BASE.INFRA_PRESENT:
        BASE.one_present(infra, query_id)
    BASE.require_outcomes(mgmt, BASE.MGMT_ABSENT, "ABSENT")
    BASE.require_outcomes(mgmt, BASE.MGMT_API_NOT_SERVED, "API_NOT_SERVED")
    BASE.require_outcomes(infra, BASE.INFRA_ABSENT, "ABSENT")
    for query_id in [item for item in BASE.MGMT_PRESENT if item != "misrouted-load-balancer"] + BASE.INFRA_PRESENT:
        source = mgmt if query_id in BASE.MGMT_PRESENT else infra
        if BASE.one_present(source, query_id).get("intentRevision") != BASE.FAILED_INTENT:
            raise BindingError(f"unexpected failed intent revision: {query_id}")
    if BASE.one_present(mgmt, "misrouted-load-balancer").get("intentRevision") is not None:
        raise BindingError("generated Service unexpectedly claims direct intent provenance")
    return candidate, evidence, mgmt, infra


def materialize(evidence_path: Path, candidate_path: Path) -> dict[str, Any]:
    candidate, evidence, mgmt, infra = validate_snapshot(evidence_path, candidate_path)
    completed = BASE.timestamp(evidence["completedAt"])
    binding = candidate["spec"]["runtimeBinding"]
    lifecycle_ids = [item for item in BASE.MGMT_PRESENT if item not in ("mgmt-namespace", "misrouted-load-balancer")]
    return {
        "apiVersion": "recovery.openkubes.io/v1alpha1",
        "kind": "GO1LRecoveryRuntimeBinding",
        "metadata": {"name": binding["name"], "ticket": "OK-141"},
        "spec": {
            "bindingVersion": BINDING_VERSION,
            "state": "READY-FOR-EXPLICIT-UID-PRECONDITIONED-CLEANUP-GRANT",
            "protocolDigest": BASE.PROTOCOL_DIGEST,
            "attemptID": evidence["attemptID"],
            "observedAt": completed.isoformat(),
            "expiresAt": (completed + dt.timedelta(minutes=binding["freshnessMaximumMinutes"])).isoformat(),
            "sourceEvidenceDigests": [BASE.sha(evidence_path)],
            "sourceObservationCandidateDigest": evidence["candidateDigest"],
            "sourceGrantID": evidence["grantID"],
            "objects": {
                "okMgmt": {
                    "namespace": BASE.retained(BASE.one_present(mgmt, "mgmt-namespace")),
                    "lifecycle": [BASE.retained(BASE.one_present(mgmt, item)) for item in lifecycle_ids],
                    "misroutedService": BASE.retained(BASE.one_present(mgmt, "misrouted-load-balancer")),
                },
                "okInfra": {
                    "namespace": BASE.retained(BASE.one_present(infra, "infra-namespace")),
                    "role": BASE.retained(BASE.one_present(infra, "golden-image-cloner-role")),
                    "roleBinding": BASE.retained(BASE.one_present(infra, "golden-image-cloner-binding")),
                },
            },
            "generatedInventory": {
                "machines": [], "kubevirtMachines": [],
                "localProviderVMAPI": "API_NOT_SERVED", "localProviderVMIAPI": "API_NOT_SERVED",
                "providerVirtualMachines": [], "providerVirtualMachineInstances": [],
            },
            "credentialsIncluded": False,
            "publicUIDPublicationAllowed": False,
            "executable": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify-evidence", "materialize"))
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        candidate_path, evidence_path = args.candidate.resolve(), args.evidence.resolve()
        if args.command == "verify-evidence":
            validate_snapshot(evidence_path, candidate_path)
            result = {"evidenceDigest": BASE.sha(evidence_path), "bindingWritten": False}
        else:
            if args.output is None or not str(args.output).startswith("/private/tmp/"):
                raise BindingError("private /private/tmp output is required")
            output = args.output.resolve()
            if output.exists():
                raise BindingError("binding output already exists")
            output.write_text(yaml.safe_dump(materialize(evidence_path, candidate_path), sort_keys=False))
            output.chmod(0o600)
            result = {
                "evidenceDigest": BASE.sha(evidence_path),
                "bindingDigest": BASE.sha(output),
                "bindingWritten": True,
            }
        print(json.dumps(result, sort_keys=True))
        return 0
    except (BindingError, OBS.SnapshotError, KeyError, OSError, TypeError, ValueError, json.JSONDecodeError, yaml.YAMLError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
