#!/usr/bin/env python3
"""Fail-closed UID-preconditioned cleanup executor for OK-141 GO1-L recovery."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import yaml


HERE = Path(__file__).resolve().parent
CANDIDATE = HERE / "recovery-cleanup-candidate-v1.yaml"
PROTOCOL = HERE / "go1-l-recovery-protocol-v1.yaml"
TOOL = Path("/private/tmp/ok141-kubectl-v1.34.1-darwin-amd64")
TOOL_DIGEST = "sha256:bb211f2b31f2b3bc60562b44cc1e3b712a16a98e9072968ba255beb04cefcfdf"


class CleanupError(ValueError):
    pass


@dataclass(frozen=True)
class Target:
    key: str
    identity: str
    raw_uri: str
    uid: str
    resource_version: str


def sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text())
    if not isinstance(value, dict):
        raise CleanupError(f"not a mapping: {path}")
    return value


def expect(actual: Any, expected: Any, claim: str) -> None:
    if actual != expected:
        raise CleanupError(f"{claim}: expected {expected!r}, got {actual!r}")


def timestamp(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise CleanupError("timestamp must include timezone")
    return parsed


def validate_candidate(candidate_path: Path = CANDIDATE) -> dict[str, Any]:
    candidate = read(candidate_path)
    expect(candidate["apiVersion"], "execution.openkubes.io/v1alpha1", "apiVersion")
    expect(candidate["kind"], "GO1LRecoveryCleanupCandidate", "kind")
    spec = candidate["spec"]
    expect(spec["version"], "ok141-go1-l-recovery-cleanup/v1", "version")
    expect(spec["state"], "OFFLINE-PROVEN-BLOCKED-NO-GO", "state")
    source = spec["sourceProtocol"]
    expect(sha((candidate_path.parent / source["path"]).resolve()), source["digest"], "protocol digest")
    tool = spec["tool"]
    expect(sha((candidate_path.parent / tool["path"]).resolve()), tool["digest"], "executor digest")
    expect(tool["kubectlPath"], str(TOOL), "kubectl path")
    expect(tool["kubectlDigest"], TOOL_DIGEST, "kubectl digest")
    expect(tool["arbitraryCommandAllowed"], False, "arbitrary command")
    materializer = spec["runtimeBindingMaterializer"]
    expect(sha((candidate_path.parent / materializer["path"]).resolve()), materializer["digest"], "materializer digest")
    expect(materializer["outputRoot"], "/private/tmp", "materializer output root")
    expect(materializer["freshnessMaximumMinutes"], 10, "binding freshness")
    expect(materializer["publicUIDPublicationAllowed"], False, "UID publication")

    stages = spec["stages"]
    expect([item["id"] for item in stages], ["R1", "R3"], "stage order")
    expect(stages[0]["targetPlane"], "ok-mgmt", "R1 plane")
    expect([item["key"] for item in stages[0]["targets"]], ["okMgmt.namespace"], "R1 targets")
    expect(stages[1]["targetPlane"], "ok-infra", "R3 plane")
    expect(
        [item["key"] for item in stages[1]["targets"]],
        ["okInfra.roleBinding", "okInfra.role", "okInfra.namespace"],
        "R3 targets",
    )
    for stage in stages:
        for target in stage["targets"]:
            if not target["rawURI"].startswith(("/api/", "/apis/")):
                raise CleanupError("target raw URI is not absolute")
    transport = spec["transport"]
    expect(transport["operation"], "DeleteWithUIDPrecondition", "transport")
    expect(transport["exactGETBeforeDelete"], True, "pre-delete GET")
    expect(transport["uidPreconditionRequired"], True, "UID precondition")
    expect(transport["propagationPolicy"], "Foreground", "propagation")
    for claim in ("forceAllowed", "finalizerMutationAllowed", "automaticRetryAllowed", "automaticRollbackAllowed"):
        expect(transport[claim], False, claim)
    authorization = spec["authorization"]
    expect(authorization["decision"], "NO-GO", "authorization")
    if any(value for key, value in authorization.items() if key.endswith(("Authorized", "Granted"))):
        raise CleanupError("candidate grants authority")
    return candidate


def target_value(binding: dict[str, Any], dotted: str) -> dict[str, Any]:
    value: Any = binding["spec"]["objects"]
    for part in dotted.split("."):
        value = value[part]
    if not isinstance(value, dict):
        raise CleanupError(f"binding target is invalid: {dotted}")
    return value


def validate_binding(
    candidate: dict[str, Any], binding_path: Path, now: dt.datetime | None = None
) -> dict[str, Any]:
    binding = read(binding_path)
    expect(binding["kind"], "GO1LRecoveryRuntimeBinding", "binding kind")
    spec = binding["spec"]
    expect(spec["state"], "READY-FOR-EXPLICIT-UID-PRECONDITIONED-CLEANUP-GRANT", "binding state")
    expect(spec["protocolDigest"], candidate["spec"]["sourceProtocol"]["digest"], "binding protocol")
    expect(spec["credentialsIncluded"], False, "binding credentials")
    expect(spec["executable"], False, "binding executable")
    if not spec["sourceEvidenceDigests"] or not all(item.startswith("sha256:") for item in spec["sourceEvidenceDigests"]):
        raise CleanupError("binding lacks source evidence")
    observed, expires = timestamp(spec["observedAt"]), timestamp(spec["expiresAt"])
    current = now or dt.datetime.now(dt.timezone.utc)
    if expires - observed > dt.timedelta(minutes=10) or not observed <= current <= expires:
        raise CleanupError("runtime binding is stale or has an invalid freshness window")

    for stage in candidate["spec"]["stages"]:
        for configured in stage["targets"]:
            bound = target_value(binding, configured["key"])
            expect(bound["identity"], configured["identity"], f"{configured['key']} identity")
            if not bound.get("uid") or not bound.get("resourceVersion"):
                raise CleanupError(f"{configured['key']} lacks UID or resourceVersion")
            if bound.get("deletionTimestamp") is not None:
                raise CleanupError(f"{configured['key']} is already deleting")
            if bound.get("finalizers") or bound.get("ownerReferences"):
                raise CleanupError(f"{configured['key']} has unexpected ownership metadata")
    return binding


def validate_grant(
    candidate_path: Path,
    candidate: dict[str, Any],
    binding_path: Path,
    grant_path: Path,
    stage_id: str,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    grant = read(grant_path)
    spec = grant["spec"]
    expect(spec["state"], "GRANTED", "grant state")
    expect(spec["candidateDigest"], sha(candidate_path), "grant candidate")
    expect(spec["protocolDigest"], candidate["spec"]["sourceProtocol"]["digest"], "grant protocol")
    expect(spec["privateRuntimeBindingDigest"], sha(binding_path), "grant binding")
    expect(spec["authorizedStage"], stage_id, "grant stage")
    expect(spec["maximumRuns"], 1, "maximum runs")
    expect(spec["consumed"], False, "grant consumed")
    for claim in ("readOnlyPreconditionAuthorized", "credentialUseAuthorized", "mutationAuthorized", "destructiveCleanupAuthorized", "uidPreconditionAuthorized"):
        expect(spec[claim], True, claim)
    for claim in ("retryAuthorized", "forceDeleteAuthorized", "finalizerRemovalAuthorized", "secretReadAuthorized", "recreateAuthorized", "go1LAuthorized", "go1Authorized", "failureInjectionAuthorized"):
        expect(spec[claim], False, claim)
    current = now or dt.datetime.now(dt.timezone.utc)
    start, end = timestamp(spec["notBefore"]), timestamp(spec["notAfter"])
    if end - start > dt.timedelta(minutes=15) or not start <= current <= end:
        raise CleanupError("grant is inactive or exceeds 15 minutes")
    expected_output = f"/private/tmp/ok141-go1-l-recovery-{stage_id.lower()}-cleanup-evidence.json"
    expect(spec["outputPath"], expected_output, "evidence output")
    return grant


def stage_targets(candidate: dict[str, Any], binding: dict[str, Any], stage_id: str) -> tuple[str, list[Target]]:
    stages = {item["id"]: item for item in candidate["spec"]["stages"]}
    if stage_id not in stages:
        raise CleanupError("unsupported stage")
    stage = stages[stage_id]
    targets = []
    for configured in stage["targets"]:
        bound = target_value(binding, configured["key"])
        targets.append(Target(configured["key"], configured["identity"], configured["rawURI"], bound["uid"], bound["resourceVersion"]))
    return stage["targetPlane"], targets


def ensure_credential(path: Path) -> None:
    if path.is_symlink() or not path.is_file() or stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise CleanupError("credential must be a mode-0600 regular non-symlink file")


def run_get(kubectl: Path, kubeconfig: Path, target: Target, runner: Callable[..., Any]) -> None:
    completed = runner(
        [str(kubectl), "--kubeconfig", str(kubeconfig), "get", f"--raw={target.raw_uri}"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise CleanupError(f"precondition GET failed: {target.key}")
    value = json.loads(completed.stdout)
    metadata = value.get("metadata", {})
    expect(metadata.get("uid"), target.uid, f"{target.key} live UID")
    expect(metadata.get("resourceVersion"), target.resource_version, f"{target.key} live resourceVersion")
    if metadata.get("deletionTimestamp") is not None:
        raise CleanupError(f"{target.key} is already deleting")


def run_delete(kubectl: Path, kubeconfig: Path, target: Target, runner: Callable[..., Any]) -> None:
    payload = json.dumps(
        {
            "apiVersion": "v1",
            "kind": "DeleteOptions",
            "propagationPolicy": "Foreground",
            "preconditions": {
                "resourceVersion": target.resource_version,
                "uid": target.uid,
            },
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    completed = runner(
        [str(kubectl), "--kubeconfig", str(kubeconfig), "delete", f"--raw={target.raw_uri}", "--filename=-", "--wait=false"],
        input=payload,
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise CleanupError(f"UID-preconditioned DELETE failed: {target.key}")


def write_evidence(path: Path, evidence: dict[str, Any]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(evidence, sort_keys=True, separators=(",", ":")) + "\n")
    temporary.chmod(0o600)
    temporary.replace(path)
    path.chmod(0o600)


def perform_targets(
    evidence_path: Path,
    evidence: dict[str, Any],
    targets: list[Target],
    kubectl: Path,
    kubeconfig: Path,
    runner: Callable[..., Any],
) -> dict[str, Any]:
    write_evidence(evidence_path, evidence)
    try:
        for target in targets:
            run_get(kubectl, kubeconfig, target, runner)
            evidence["state"] = "DELETE-ATTEMPT-IN-PROGRESS"
            evidence["currentTarget"] = target.identity
            evidence["deleteAttempted"] = True
            write_evidence(evidence_path, evidence)
            run_delete(kubectl, kubeconfig, target, runner)
            evidence["submittedIdentities"].append(target.identity)
            evidence["state"] = "DELETE-ACCEPTED-CONTINUING" if len(evidence["submittedIdentities"]) < len(targets) else "ALL-DELETES-ACCEPTED"
            evidence["currentTarget"] = None
            evidence["deleteAttempted"] = False
            write_evidence(evidence_path, evidence)
    except (CleanupError, OSError, ValueError, json.JSONDecodeError):
        evidence["state"] = "STOPPED-PRESERVE-NO-RETRY"
        evidence["completedAt"] = dt.datetime.now(dt.timezone.utc).isoformat()
        write_evidence(evidence_path, evidence)
        raise
    evidence["completedAt"] = dt.datetime.now(dt.timezone.utc).isoformat()
    write_evidence(evidence_path, evidence)
    return evidence


def execute_once(
    candidate_path: Path,
    binding_path: Path,
    grant_path: Path,
    stage_id: str,
    kubeconfig: Path,
    kubectl: Path = TOOL,
    now: dt.datetime | None = None,
    runner: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    candidate = validate_candidate(candidate_path)
    binding = validate_binding(candidate, binding_path, now)
    grant = validate_grant(candidate_path, candidate, binding_path, grant_path, stage_id, now)
    ensure_credential(kubeconfig)
    if sha(kubectl) != TOOL_DIGEST:
        raise CleanupError("kubectl digest mismatch")
    expected_kubeconfig = Path(candidate["spec"]["credentials"][stage_id]["path"])
    expect(kubeconfig.resolve(), expected_kubeconfig.resolve(), "credential path")
    plane, targets = stage_targets(candidate, binding, stage_id)
    evidence_path = Path(grant["spec"]["outputPath"])
    if evidence_path.exists():
        raise CleanupError("evidence output already exists")
    evidence = {
        "candidateDigest": sha(candidate_path),
        "privateRuntimeBindingDigest": sha(binding_path),
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
    return perform_targets(evidence_path, evidence, targets, kubectl, kubeconfig, runner)


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
            result = {"candidateDigest": sha(candidate_path), "state": candidate["spec"]["state"], "mutationAuthorized": False}
        elif args.command == "plan":
            if args.binding is None or args.stage is None:
                raise CleanupError("plan requires binding and stage")
            binding = validate_binding(candidate, args.binding.resolve())
            plane, targets = stage_targets(candidate, binding, args.stage)
            result = {"stage": args.stage, "targetPlane": plane, "targets": [target.identity for target in targets], "mutationAuthorized": False}
        else:
            if not args.execute or args.binding is None or args.grant is None or args.stage is None or args.kubeconfig is None:
                raise CleanupError("execute requires --execute, binding, grant, stage and kubeconfig")
            result = execute_once(candidate_path, args.binding.resolve(), args.grant.resolve(), args.stage, args.kubeconfig.resolve(), args.kubectl.resolve())
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (CleanupError, KeyError, OSError, TypeError, ValueError, json.JSONDecodeError, yaml.YAMLError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
