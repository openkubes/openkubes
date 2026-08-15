#!/usr/bin/env python3
"""UID-preconditioned R3 cleanup of the three ok-infra prerequisites."""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any, Callable

import yaml


HERE = Path(__file__).resolve().parent
MODULE_SPEC = importlib.util.spec_from_file_location(
    "bounded_recovery_cleanup_v1_for_r3", HERE / "bounded_recovery_cleanup_v1.py"
)
BASE = importlib.util.module_from_spec(MODULE_SPEC)
assert MODULE_SPEC.loader is not None
sys.modules[MODULE_SPEC.name] = BASE
MODULE_SPEC.loader.exec_module(BASE)
R3CleanupError = BASE.CleanupError
CANDIDATE = HERE / "recovery-r3-cleanup-candidate-v1.yaml"
TOOL = BASE.TOOL
TOOL_DIGEST = BASE.TOOL_DIGEST
PROTOCOL_DIGEST = "sha256:0be2957f7c417e9c7c25f2595b5168a95f11e72c76508d83f774719045df8bd9"
ATTEMPT_ID = re.compile(r"^r3-v[1-9][0-9]*-[0-9]{8}-[0-9]{2}$")
TARGETS = [
    {
        "key": "golden-image-cloner-binding",
        "identity": "rbac.authorization.k8s.io/v1|RoleBinding|ok-images|disposable-ok141-talos-golden-image-cloner",
        "rawURI": "/apis/rbac.authorization.k8s.io/v1/namespaces/ok-images/rolebindings/disposable-ok141-talos-golden-image-cloner",
    },
    {
        "key": "golden-image-cloner-role",
        "identity": "rbac.authorization.k8s.io/v1|Role|ok-images|disposable-ok141-talos-golden-image-cloner",
        "rawURI": "/apis/rbac.authorization.k8s.io/v1/namespaces/ok-images/roles/disposable-ok141-talos-golden-image-cloner",
    },
    {
        "key": "infra-namespace",
        "identity": "v1|Namespace|_|disposable-ok141",
        "rawURI": "/api/v1/namespaces/disposable-ok141",
    },
]


def validate_candidate(path: Path = CANDIDATE) -> dict[str, Any]:
    candidate = BASE.read(path)
    spec = candidate["spec"]
    BASE.expect(spec["version"], "ok141-go1-l-recovery-r3-cleanup/v1", "version")
    BASE.expect(spec["state"], "OFFLINE-PROVEN-BLOCKED-NO-GO", "state")
    BASE.expect(spec["protocolDigest"], PROTOCOL_DIGEST, "protocol")
    BASE.expect(spec["tool"]["digest"], BASE.sha(Path(__file__).resolve()), "executor digest")
    BASE.expect(spec["tool"]["kubectlDigest"], TOOL_DIGEST, "kubectl digest")
    BASE.expect(spec["kubeconfigPath"], "/Users/arash/.kube/ok-infra.yaml", "credential path")
    BASE.expect(spec["targets"], TARGETS, "target set and order")
    transport = spec["transport"]
    for claim in ("exactGETBeforeDelete", "uidPreconditionRequired", "resourceVersionEqualityRequiredBeforeDelete"):
        BASE.expect(transport[claim], True, claim)
    BASE.expect(transport["propagationPolicy"], "Foreground", "propagation")
    for claim in ("forceAllowed", "finalizerMutationAllowed", "automaticRetryAllowed", "automaticRollbackAllowed"):
        BASE.expect(transport[claim], False, claim)
    if any(value for key, value in spec["authorization"].items() if key.endswith(("Authorized", "Granted"))):
        raise R3CleanupError("candidate grants authority")
    return candidate


def validate_binding(binding_path: Path, now: dt.datetime | None = None) -> dict[str, Any]:
    binding = BASE.read(binding_path)
    if binding["kind"] != "GO1LRecoveryR3RuntimeBinding":
        raise R3CleanupError("binding kind mismatch")
    spec = binding["spec"]
    if spec["state"] != "READY-FOR-EXPLICIT-R3-DELETE-GRANT" or spec["protocolDigest"] != PROTOCOL_DIGEST:
        raise R3CleanupError("binding state or protocol mismatch")
    if not ATTEMPT_ID.fullmatch(spec["attemptID"]):
        raise R3CleanupError("binding attempt mismatch")
    for claim in ("sourceCandidateDigest", "sourceEvidenceDigest", "sourceR2EvidenceDigest"):
        value = spec.get(claim)
        if not isinstance(value, str) or not value.startswith("sha256:") or len(value) != 71:
            raise R3CleanupError(f"binding lacks {claim}")
    if spec["credentialsIncluded"] or spec["publicUIDPublicationAllowed"] or spec["executable"]:
        raise R3CleanupError("binding crosses security boundary")
    observed, expires = BASE.timestamp(spec["observedAt"]), BASE.timestamp(spec["expiresAt"])
    current = now or dt.datetime.now(dt.timezone.utc)
    if expires - observed > dt.timedelta(minutes=10) or not observed <= current <= expires:
        raise R3CleanupError("R3 binding is stale")
    if set(spec["objects"]) != {target["key"] for target in TARGETS}:
        raise R3CleanupError("binding object set mismatch")
    for target in TARGETS:
        value = spec["objects"][target["key"]]
        if value["identity"] != target["identity"] or not value.get("uid") or not value.get("resourceVersion"):
            raise R3CleanupError(f"binding identity mismatch: {target['key']}")
        if value.get("deletionTimestamp") is not None or value.get("finalizers") or value.get("ownerReferences"):
            raise R3CleanupError(f"unsafe binding state: {target['key']}")
    return binding


def validate_grant(
    candidate_path: Path,
    binding_path: Path,
    grant_path: Path,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    grant = BASE.read(grant_path)
    spec = grant["spec"]
    BASE.expect(spec["state"], "GRANTED", "grant state")
    BASE.expect(spec["candidateDigest"], BASE.sha(candidate_path), "grant candidate")
    BASE.expect(spec["privateRuntimeBindingDigest"], BASE.sha(binding_path), "grant binding")
    BASE.expect(spec["maximumRuns"], 1, "maximum runs")
    BASE.expect(spec["consumed"], False, "grant consumed")
    for claim in (
        "readOnlyPreconditionAuthorized", "credentialUseAuthorized", "mutationAuthorized",
        "destructiveCleanupAuthorized", "uidPreconditionAuthorized",
    ):
        BASE.expect(spec[claim], True, claim)
    for claim in (
        "retryAuthorized", "forceDeleteAuthorized", "finalizerRemovalAuthorized",
        "secretReadAuthorized", "recreateAuthorized", "go1LAuthorized", "go1Authorized",
        "failureInjectionAuthorized",
    ):
        BASE.expect(spec[claim], False, claim)
    current = now or dt.datetime.now(dt.timezone.utc)
    start, end = BASE.timestamp(spec["notBefore"]), BASE.timestamp(spec["notAfter"])
    if end - start > dt.timedelta(minutes=15) or not start <= current <= end:
        raise R3CleanupError("grant is inactive or exceeds 15 minutes")
    BASE.expect(spec["outputPath"], "/private/tmp/ok141-go1-l-recovery-r3-cleanup-evidence.json", "evidence output")
    return grant


def targets(binding: dict[str, Any]) -> list[Any]:
    return [
        BASE.Target(
            target["key"], target["identity"], target["rawURI"],
            binding["spec"]["objects"][target["key"]]["uid"],
            binding["spec"]["objects"][target["key"]]["resourceVersion"],
        )
        for target in TARGETS
    ]


def execute(
    candidate_path: Path,
    binding_path: Path,
    grant_path: Path,
    kubeconfig: Path,
    kubectl: Path = TOOL,
    now: dt.datetime | None = None,
    runner: Callable[..., Any] = BASE.subprocess.run,
) -> dict[str, Any]:
    validate_candidate(candidate_path)
    binding = validate_binding(binding_path, now)
    grant = validate_grant(candidate_path, binding_path, grant_path, now)
    BASE.ensure_credential(kubeconfig)
    if kubeconfig.resolve() != Path("/Users/arash/.kube/ok-infra.yaml").resolve():
        raise R3CleanupError("credential path mismatch")
    if BASE.sha(kubectl) != TOOL_DIGEST:
        raise R3CleanupError("kubectl digest mismatch")
    evidence_path = Path(grant["spec"]["outputPath"])
    if evidence_path.exists():
        raise R3CleanupError("evidence output already exists")
    planned = targets(binding)
    evidence = {
        "candidateDigest": BASE.sha(candidate_path),
        "privateRuntimeBindingDigest": BASE.sha(binding_path),
        "grantID": grant["spec"]["grantID"],
        "startedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "completedAt": None,
        "stage": "R3",
        "targetPlane": "ok-infra",
        "state": "STARTED-NO-DELETE-ATTEMPTED",
        "plannedIdentities": [target.identity for target in planned],
        "submittedIdentities": [],
        "currentTarget": None,
        "deleteAttempted": False,
        "uidPreconditionsUsed": True,
        "forceDeleteUsed": False,
        "finalizerMutationPerformed": False,
        "retryPerformed": False,
        "automaticRollbackPerformed": False,
        "credentialBytesEmitted": False,
    }
    return BASE.perform_targets(evidence_path, evidence, planned, kubectl, kubeconfig, runner)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "plan", "execute"))
    parser.add_argument("--candidate", type=Path, default=CANDIDATE)
    parser.add_argument("--binding", type=Path)
    parser.add_argument("--grant", type=Path)
    parser.add_argument("--kubeconfig", type=Path)
    parser.add_argument("--kubectl", type=Path, default=TOOL)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        candidate_path = args.candidate.resolve()
        candidate = validate_candidate(candidate_path)
        if args.command == "verify":
            result = {"candidateDigest": BASE.sha(candidate_path), "state": candidate["spec"]["state"], "mutationAuthorized": False}
        elif args.command == "plan":
            if args.binding is None:
                raise R3CleanupError("plan requires binding")
            binding = validate_binding(args.binding.resolve())
            result = {"stage": "R3", "targetPlane": "ok-infra", "targets": [item.identity for item in targets(binding)], "mutationAuthorized": False}
        else:
            if not args.execute or args.binding is None or args.grant is None or args.kubeconfig is None:
                raise R3CleanupError("execute requires --execute, binding, grant and kubeconfig")
            result = execute(
                candidate_path, args.binding.resolve(), args.grant.resolve(),
                args.kubeconfig.resolve(), args.kubectl.resolve(),
            )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (R3CleanupError, KeyError, OSError, TypeError, ValueError, json.JSONDecodeError, yaml.YAMLError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
