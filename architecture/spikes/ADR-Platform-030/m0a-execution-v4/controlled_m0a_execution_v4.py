#!/usr/bin/env python3
"""Three-grant M0a v4 executor; mutation requires an exact external grant."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
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


V3 = _load("ok141_m0a_v3_executor_for_v4", SPIKE / "m0a-execution-v3" / "controlled_m0a_execution_v3.py")
V2 = V3.V2
INSTALLER = V3.INSTALLER
BOOTSTRAP_OBJECTS = V3.BOOTSTRAP_OBJECTS


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
    expect(spec["version"], "ok141-m0a-combined-candidate/v4", "candidate version")
    expect(spec["state"], "READY-FOR-THREE-SEPARATE-EXPLICIT-GRANTS", "candidate state")
    refs = {name: resolve(path.parent, reference) for name, reference in spec["references"].items()}
    expect(refs["executor"], Path(__file__).resolve(), "executor identity")
    expect(refs["authorizationProbe"], (SPIKE / "m0a-execution-v3" / "authorization_probe_v3.py").resolve(), "probe identity")
    expect(spec["target"]["kubeSystemNamespaceUID"], "c3b45aab-d2a1-4e64-8f12-77b99186ad4a", "target UID")
    expect(spec["credential"]["maximumDurationMinutes"], 10, "credential lifetime")
    expect(spec["credential"]["rejectionDeadlineOffsetSeconds"], 100, "rejection deadline offset")
    expect(spec["authorizationProbe"]["tokenRequestSubresourceArgs"], V3.PROBE.token_request_denial_args(), "TokenRequest probe")
    installation = spec["installation"]
    expect(installation["objectCount"], 19, "installation count")
    expect(installation["submissionMethod"], "create", "submission method")
    expect(installation["maximumSubmissions"], 1, "submission count")
    expect(installation["allObjectsAbsentPrecondition"], True, "absence precondition")
    expect(installation["idempotent"], False, "create idempotency")
    expect(installation["partialStatePossible"], True, "partial state")
    expect(installation["allowedInstallerVerbs"], ["create", "get"], "installer verbs")
    for claim in ("serverSideApplyAllowed", "patchAllowed", "updateAllowed", "deleteAllowed", "automaticRetryAllowed", "automaticRollbackAllowed", "targetResourcesAllowed"):
        expect(installation[claim], False, claim)
    expect(spec["failureBoundary"]["tokenRejectionDeadline"], "expirationTimestamp-plus-100s", "rejection deadline")
    expect(spec["failureBoundary"]["automaticCaaphRollbackAllowed"], False, "rollback boundary")
    expect(spec["authorization"], {
        "decision": "NO-GO",
        "mutationAuthorized": False,
        "credentialGrantRequired": True,
        "admissionBootstrapGrantRequired": True,
        "installationGrantRequired": True,
        "retryGranted": False,
        "rollbackGranted": False,
        "m0bInstallationGranted": False,
        "go1Granted": False,
        "evidencePublicationGranted": False,
        "targetConvergenceGranted": False,
        "failureInjectionGranted": False,
    }, "candidate authorization")
    return document, refs


def verify_grant(candidate_path: Path, grant_path: Path, now: datetime | None = None) -> dict[str, Any]:
    candidate, _ = verify_candidate(candidate_path)
    grant = read_yaml(grant_path)["spec"]
    expect(grant["version"], "ok141-m0a-combined-grant/v4", "grant version")
    expect(grant["candidateDigest"], sha(candidate_path), "candidate grant binding")
    expect(grant["authority"], "github:arashkaffamanesh", "grant authority")
    expect(grant["decision"], "GO", "grant decision")
    expect(grant["mutationAuthorized"], True, "mutation authority")
    expected_gates = (
        ("credentialGrant", "M0A-C1-v4"),
        ("admissionGrant", "M0A-A1-v4"),
        ("installationGrant", "M0a-I-v4"),
    )
    ids = []
    for field, gate in expected_gates:
        expect(grant[field]["gate"], gate, f"{field} gate")
        expect(grant[field]["granted"], True, f"{field} decision")
        ids.append(grant[field]["grantID"])
    if len(set(ids)) != 3:
        raise ExecutionError("three distinct grant IDs are required")
    start = parse_utc(grant["validFrom"])
    end = parse_utc(grant["validUntil"])
    if end <= start or (end - start).total_seconds() > candidate["spec"]["executionWindow"]["maximumDurationMinutes"] * 60:
        raise ExecutionError("grant window is invalid or too long")
    current = now or datetime.now(timezone.utc)
    if current < start or current > end:
        raise ExecutionError("current time is outside the exact grant window")
    expect(grant["maximumRuns"], 1, "maximum run count")
    output = Path(grant["evidenceOutputPath"])
    if not output.is_absolute() or Path("/private/tmp") not in output.resolve().parents:
        raise ExecutionError("raw evidence output must be an absolute path below /private/tmp")
    for claim in (
        "rollbackGranted", "targetConvergenceGranted", "m0bInstallationGranted",
        "go1Granted", "evidencePublicationGranted", "failureInjectionGranted",
    ):
        expect(grant[claim], False, claim)
    return grant


def kubectl(kubeconfig: Path, args: list[str], **kwargs):
    return V3.kubectl(kubeconfig, args, **kwargs)


def exact_object_inventory(admin_kubeconfig: Path, reviewed: Any) -> dict[str, Any]:
    objects = []
    for item in reviewed.documents:
        resource, default_namespace = V2.V1.RESOURCE_MAP[item["kind"]]
        namespace = item["metadata"].get("namespace", default_namespace)
        args = ["get", resource, item["metadata"]["name"], "--output=json"]
        if namespace:
            args[1:1] = ["--namespace", namespace]
        result = kubectl(admin_kubeconfig, args, check=False)
        identity = {
            "apiVersion": item["apiVersion"],
            "kind": item["kind"],
            "namespace": namespace,
            "name": item["metadata"]["name"],
        }
        if result.returncode == 0:
            live = json.loads(result.stdout)
            metadata = live.get("metadata", {})
            identity.update({
                "present": True,
                "uid": metadata.get("uid"),
                "resourceVersion": metadata.get("resourceVersion"),
                "generation": metadata.get("generation"),
            })
        elif "NotFound" in result.stderr.decode(errors="replace") or "not found" in result.stderr.decode(errors="replace"):
            identity["present"] = False
        else:
            raise ExecutionError(f"post-submit inventory failed for {item['kind']}/{item['metadata']['name']}")
        objects.append(identity)
    present = sum(1 for item in objects if item["present"])
    return {"expected": len(objects), "present": present, "absent": len(objects) - present, "objects": objects}


def live_preflight(candidate: dict[str, Any], refs: dict[str, Path], admin_kubeconfig: Path) -> dict[str, Any]:
    observation = V2.live_preflight(candidate, refs, admin_kubeconfig)
    reviewed = INSTALLER.verify_reviewed_object_set(read_yaml(refs["installationProtocol"]), refs["installationProtocol"])
    inventory = exact_object_inventory(admin_kubeconfig, reviewed)
    expect(inventory["expected"], 19, "preflight identity count")
    expect(inventory["present"], 0, "preflight existing identity count")
    observation["exactIdentityAbsence"] = inventory["absent"]
    return observation


def execute(candidate_path: Path, grant_path: Path, admin_kubeconfig: Path, evidence_output: Path) -> dict[str, Any]:
    candidate, refs = verify_candidate(candidate_path)
    grant = verify_grant(candidate_path, grant_path)
    expect(evidence_output.resolve(), Path(grant["evidenceOutputPath"]).resolve(), "grant-bound evidence output")
    if evidence_output.exists():
        raise ExecutionError("grant-bound raw evidence output already exists")
    clock = V2.V1.verify_clock(candidate["spec"]["executionWindow"]["maximumClockSkewSeconds"])
    preflight = live_preflight(candidate, refs, admin_kubeconfig)
    reviewed = INSTALLER.verify_reviewed_object_set(read_yaml(refs["installationProtocol"]), refs["installationProtocol"])
    temp_config: Path | None = None
    bootstrap_uids: dict[str, str] = {}
    expires_at: datetime | None = None
    submission_attempted = False
    evidence: dict[str, Any] = {
        "version": "ok141-m0a-execution-evidence/v4",
        "candidateDigest": sha(candidate_path),
        "grantDigest": sha(grant_path),
        "grantIDs": [grant[key]["grantID"] for key in ("credentialGrant", "admissionGrant", "installationGrant")],
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
        bootstrap_uids = V2.discover_bootstrap_objects(admin_kubeconfig)
        expect(set(bootstrap_uids), {item[0] for item in BOOTSTRAP_OBJECTS}, "temporary bootstrap inventory")
        evidence["policy"] = V2.wait_policy_ready(admin_kubeconfig)
        requested_at = datetime.now(timezone.utc)
        token_result = kubectl(
            admin_kubeconfig,
            ["--namespace", V3.SA_NAMESPACE, "create", "token", V3.SA_NAME, "--duration=10m", "--audience", candidate["spec"]["target"]["apiAudience"], "--output=json"],
        )
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
        temp_config = V2.temporary_kubeconfig(admin_kubeconfig, token, candidate)
        token = ""
        token_request["status"]["token"] = ""
        evidence["authorizationProbes"] = V3.authorization_probes(temp_config, reviewed)
        reviewed = INSTALLER.verify_reviewed_object_set(read_yaml(refs["installationProtocol"]), refs["installationProtocol"])
        expect(reviewed.semantic_digest, candidate["spec"]["installation"]["semanticDigest"], "immediate pre-submit semantic digest")
        submission_attempted = True
        kubectl(temp_config, ["create", "--filename", "-"], input_bytes=reviewed.payload)
        inventory = exact_object_inventory(admin_kubeconfig, reviewed)
        evidence["postSubmissionInventory"] = inventory
        expect(inventory["present"], 19, "created object count")
        evidence["readiness"] = V2.V1.wait_ready(admin_kubeconfig, candidate["spec"]["installation"]["readinessTimeoutSeconds"])
        evidence["objects"] = V2.V1.object_evidence(admin_kubeconfig, reviewed)
        evidence["result"] = "SUCCESS"
        return evidence
    except Exception as exc:
        evidence.update({"result": "STOP-NOT-SUCCESS", "failureType": type(exc).__name__, "failure": str(exc)})
        raise
    finally:
        if submission_attempted and "postSubmissionInventory" not in evidence:
            try:
                evidence["postSubmissionInventory"] = exact_object_inventory(admin_kubeconfig, reviewed)
            except Exception as inventory_error:
                evidence["postSubmissionInventory"] = {"failureType": type(inventory_error).__name__, "failure": str(inventory_error)}
                evidence["result"] = "STOP-NOT-SUCCESS"
        try:
            evidence["bootstrapCleanup"] = V2.cleanup_bootstrap(admin_kubeconfig, bootstrap_uids)
        except Exception as cleanup_error:
            evidence["bootstrapCleanup"] = {"removed": False, "failureType": type(cleanup_error).__name__, "failure": str(cleanup_error)}
            evidence["result"] = "STOP-NOT-SUCCESS"
        if temp_config is not None and expires_at is not None:
            try:
                evidence["revocation"] = V3.poll_token_rejection_until_expiry(
                    temp_config,
                    expires_at,
                    candidate["spec"]["credential"]["rejectionDeadlineOffsetSeconds"],
                )
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
            raise ExecutionError("execution or expiry-bound credential rejection did not succeed")
        print(json.dumps({"result": result["result"], "evidenceOutput": str(args.evidence_output)}, sort_keys=True, separators=(",", ":")))
        return 0
    except (ExecutionError, INSTALLER.InstallerError, OSError, KeyError, TypeError, ValueError, yaml.YAMLError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
