#!/usr/bin/env python3
"""R0-v3-bound cleanup executor preserving the historical v1 executor."""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Callable

import yaml


HERE = Path(__file__).resolve().parent
MODULE_SPEC = importlib.util.spec_from_file_location(
    "bounded_recovery_cleanup_v1_for_v2", HERE / "bounded_recovery_cleanup_v1.py"
)
BASE = importlib.util.module_from_spec(MODULE_SPEC)
assert MODULE_SPEC.loader is not None
sys.modules[MODULE_SPEC.name] = BASE
MODULE_SPEC.loader.exec_module(BASE)
CleanupError = BASE.CleanupError
CANDIDATE = HERE / "recovery-cleanup-candidate-v1-r0-v3.yaml"
TOOL = BASE.TOOL
TOOL_DIGEST = BASE.TOOL_DIGEST
BINDING_VERSION = "ok141-go1-l-recovery-runtime-binding/v2"
BINDING_NAME = "ok141-go1-l-recovery-runtime-binding-v2"


def validate_candidate(candidate_path: Path = CANDIDATE) -> dict[str, Any]:
    candidate = BASE.validate_candidate(candidate_path)
    materializer = candidate["spec"]["runtimeBindingMaterializer"]
    BASE.expect(materializer["path"], "materialize_recovery_binding_v2.py", "materializer path")
    source = materializer.get("sourceObservationCandidateDigest")
    if not isinstance(source, str) or not source.startswith("sha256:"):
        raise CleanupError("candidate lacks source observation identity")
    return candidate


def validate_binding(
    candidate: dict[str, Any], binding_path: Path, now: dt.datetime | None = None
) -> dict[str, Any]:
    binding = BASE.validate_binding(candidate, binding_path, now)
    BASE.expect(binding["metadata"]["name"], BINDING_NAME, "binding name")
    spec = binding["spec"]
    BASE.expect(spec.get("bindingVersion"), BINDING_VERSION, "binding version")
    BASE.expect(
        spec.get("sourceObservationCandidateDigest"),
        candidate["spec"]["runtimeBindingMaterializer"]["sourceObservationCandidateDigest"],
        "binding observation candidate",
    )
    return binding


def execute_once(
    candidate_path: Path,
    binding_path: Path,
    grant_path: Path,
    stage_id: str,
    kubeconfig: Path,
    kubectl: Path = TOOL,
    now: dt.datetime | None = None,
    runner: Callable[..., Any] = BASE.subprocess.run,
) -> dict[str, Any]:
    candidate = validate_candidate(candidate_path)
    binding = validate_binding(candidate, binding_path, now)
    grant = BASE.validate_grant(candidate_path, candidate, binding_path, grant_path, stage_id, now)
    BASE.ensure_credential(kubeconfig)
    if BASE.sha(kubectl) != TOOL_DIGEST:
        raise CleanupError("kubectl digest mismatch")
    expected_kubeconfig = Path(candidate["spec"]["credentials"][stage_id]["path"])
    BASE.expect(kubeconfig.resolve(), expected_kubeconfig.resolve(), "credential path")
    plane, targets = BASE.stage_targets(candidate, binding, stage_id)
    evidence_path = Path(grant["spec"]["outputPath"])
    if evidence_path.exists():
        raise CleanupError("evidence output already exists")
    evidence = {
        "candidateDigest": BASE.sha(candidate_path),
        "privateRuntimeBindingDigest": BASE.sha(binding_path),
        "grantID": grant["spec"]["grantID"],
        "startedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "completedAt": None,
        "stage": stage_id,
        "targetPlane": plane,
        "state": "STARTED-NO-DELETE-ATTEMPTED",
        "plannedIdentities": [target.identity for target in targets],
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
    return BASE.perform_targets(evidence_path, evidence, targets, kubectl, kubeconfig, runner)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "plan", "execute"))
    parser.add_argument("--candidate", type=Path, default=CANDIDATE)
    parser.add_argument("--binding", type=Path)
    parser.add_argument("--grant", type=Path)
    parser.add_argument("--stage", choices=("R1", "R3"))
    parser.add_argument("--kubeconfig", type=Path)
    parser.add_argument("--kubectl", type=Path, default=TOOL)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        candidate_path = args.candidate.resolve()
        candidate = validate_candidate(candidate_path)
        if args.command == "verify":
            result = {
                "candidateDigest": BASE.sha(candidate_path),
                "state": candidate["spec"]["state"],
                "mutationAuthorized": False,
            }
        elif args.command == "plan":
            if args.binding is None or args.stage is None:
                raise CleanupError("plan requires binding and stage")
            binding = validate_binding(candidate, args.binding.resolve())
            plane, targets = BASE.stage_targets(candidate, binding, args.stage)
            result = {
                "stage": args.stage,
                "targetPlane": plane,
                "targets": [target.identity for target in targets],
                "mutationAuthorized": False,
            }
        else:
            if (
                not args.execute
                or args.binding is None
                or args.grant is None
                or args.stage is None
                or args.kubeconfig is None
            ):
                raise CleanupError("execute requires --execute, binding, grant, stage and kubeconfig")
            result = execute_once(
                candidate_path,
                args.binding.resolve(),
                args.grant.resolve(),
                args.stage,
                args.kubeconfig.resolve(),
                args.kubectl.resolve(),
            )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (CleanupError, KeyError, OSError, TypeError, ValueError, json.JSONDecodeError, yaml.YAMLError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
