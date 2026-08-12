#!/usr/bin/env python3
"""Diagnostic M0a v5 executor; mutation requires an exact external grant."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import platform
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
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


V4 = _load("ok141_m0a_v4_executor_for_v5", SPIKE / "m0a-execution-v4" / "controlled_m0a_execution_v4.py")
V3 = V4.V3
V2 = V4.V2
V1 = V2.V1
INSTALLER = V4.INSTALLER
BOOTSTRAP_OBJECTS = V4.BOOTSTRAP_OBJECTS


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
    expect(spec["version"], "ok141-m0a-combined-candidate/v5", "candidate version")
    expect(spec["state"], "READY-FOR-THREE-SEPARATE-EXPLICIT-GRANTS", "candidate state")
    refs = {name: resolve(path.parent, reference) for name, reference in spec["references"].items()}
    expect(refs["executor"], Path(__file__).resolve(), "executor identity")
    expect(spec["target"]["kubernetesVersion"], "v1.34.1", "server version")
    tool = spec["toolchain"]
    expect(tool["release"], "v1.34.1", "tool release")
    expect(tool["gitCommit"], "93248f9ae092f571eb870b7664c534bfc7d00f03", "tool commit")
    expect(tool["binaryDigest"], "sha256:bb211f2b31f2b3bc60562b44cc1e3b712a16a98e9072968ba255beb04cefcfdf", "tool digest")
    expect(tool["binarySizeBytes"], 61851632, "tool size")
    expect(tool["platform"], "darwin/amd64", "tool platform")
    credential = spec["credential"]
    expect(credential["maximumDurationMinutes"], 10, "credential lifetime")
    expect(credential["rejectionDeadlineOffsetSeconds"], 100, "rejection boundary")
    expect(credential["mandatoryFirstPostBoundaryProbe"], True, "post-boundary probe")
    installation = spec["installation"]
    expect(installation["objectCount"], 19, "object count")
    expect(installation["positiveServerDryRunRequired"], False, "positive server dry-run")
    expect(installation["fullStreamServerDryRunFeasible"], False, "full-stream dry-run feasibility")
    expect(installation["submissionMethod"], "create", "submission method")
    expect(installation["maximumSubmissions"], 1, "submission count")
    expect(installation["allObjectsAbsentPrecondition"], True, "absence precondition")
    expect(installation["partialStatePossible"], True, "partial state")
    for claim in ("serverSideApplyAllowed", "patchAllowed", "updateAllowed", "deleteAllowed", "automaticRetryAllowed", "automaticRollbackAllowed", "targetResourcesAllowed"):
        expect(installation[claim], False, claim)
    diagnostic = spec["diagnostic"]
    expect(diagnostic["stdoutMaximumBytes"], 4096, "stdout bound")
    expect(diagnostic["stderrMaximumBytes"], 4096, "stderr bound")
    expect(diagnostic["pathsRedacted"], True, "path redaction")
    expect(diagnostic["tokensRedacted"], True, "token redaction")
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
    expect(grant["version"], "ok141-m0a-combined-grant/v5", "grant version")
    expect(grant["candidateDigest"], sha(candidate_path), "candidate grant binding")
    expect(grant["authority"], "github:arashkaffamanesh", "grant authority")
    expect(grant["decision"], "GO", "grant decision")
    expect(grant["mutationAuthorized"], True, "mutation authority")
    expected = (("credentialGrant", "M0A-C1-v5"), ("admissionGrant", "M0A-A1-v5"), ("installationGrant", "M0a-I-v5"))
    ids = []
    for field, gate in expected:
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
    for claim in ("rollbackGranted", "targetConvergenceGranted", "m0bInstallationGranted", "go1Granted", "evidencePublicationGranted", "failureInjectionGranted"):
        expect(grant[claim], False, claim)
    return grant


def configure_kubectl(binary: Path, candidate: dict[str, Any]) -> dict[str, Any]:
    spec = candidate["spec"]["toolchain"]
    expect(binary.resolve(), Path(spec["localCandidatePath"]).resolve(), "kubectl path")
    if not binary.is_file():
        raise ExecutionError("bound kubectl binary is absent")
    expect(binary.stat().st_size, spec["binarySizeBytes"], "kubectl size")
    expect(sha(binary), spec["binaryDigest"], "kubectl digest")
    machine = {"x86_64": "amd64", "arm64": "arm64"}.get(platform.machine(), platform.machine())
    expect(f"{sys.platform}/{machine}", spec["platform"], "local platform")
    completed = subprocess.run([str(binary), "version", "--client", "--output=json"], check=True, capture_output=True, timeout=30)
    version = json.loads(completed.stdout)["clientVersion"]
    expect(version["gitVersion"], spec["release"], "kubectl release")
    expect(version["gitCommit"], spec["gitCommit"], "kubectl commit")
    expect(version["platform"], spec["platform"], "kubectl platform")

    def bound_kubectl(kubeconfig: Path, args: list[str], *, input_bytes: bytes | None = None, check: bool = True):
        forbidden = {"exec", "edit", "debug", "cp", "port-forward", "proxy"}
        if forbidden.intersection(args):
            raise ExecutionError("forbidden kubectl operation")
        return subprocess.run(
            [str(binary), "--kubeconfig", str(kubeconfig), *args],
            input=input_bytes,
            check=check,
            capture_output=True,
            timeout=60,
        )

    V4.kubectl = bound_kubectl
    V3.kubectl = bound_kubectl
    V2.kubectl = bound_kubectl
    V1.kubectl = bound_kubectl
    return {"release": version["gitVersion"], "commit": version["gitCommit"], "platform": version["platform"], "digest": sha(binary)}


def kubectl(kubeconfig: Path, args: list[str], **kwargs):
    return V4.kubectl(kubeconfig, args, **kwargs)


def sanitize_output(data: bytes, *, paths: list[Path], maximum: int) -> str:
    text = data.decode(errors="replace")
    for path in paths:
        text = text.replace(str(path), "<redacted-path>")
    text = re.sub(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", "<redacted-token>", text)
    return text[:maximum]


def diagnostic(result: subprocess.CompletedProcess, operation: str, paths: list[Path], candidate: dict[str, Any]) -> dict[str, Any]:
    bounds = candidate["spec"]["diagnostic"]
    return {
        "operation": operation,
        "exitCode": result.returncode,
        "stdout": sanitize_output(result.stdout, paths=paths, maximum=bounds["stdoutMaximumBytes"]),
        "stderr": sanitize_output(result.stderr, paths=paths, maximum=bounds["stderrMaximumBytes"]),
        "outputTruncated": len(result.stdout) > bounds["stdoutMaximumBytes"] or len(result.stderr) > bounds["stderrMaximumBytes"],
        "payloadRetained": False,
    }


def decisive_post_boundary_probe(kubeconfig: Path, expires_at: datetime, offset_seconds: int) -> dict[str, Any]:
    boundary = expires_at + timedelta(seconds=offset_seconds)
    delay = (boundary - datetime.now(timezone.utc)).total_seconds()
    if delay > 0:
        time.sleep(delay)
    sampled_at = datetime.now(timezone.utc)
    if sampled_at < boundary:
        raise ExecutionError("post-boundary probe started before the bound time")
    probe = kubectl(kubeconfig, ["auth", "whoami", "--output=json"], check=False)
    result = {
        "boundary": boundary.isoformat().replace("+00:00", "Z"),
        "sampledAt": sampled_at.isoformat().replace("+00:00", "Z"),
        "notBeforeBoundary": True,
    }
    if probe.returncode != 0:
        stderr = probe.stderr.decode(errors="replace")
        if "Unauthorized" in stderr or "logged in" in stderr:
            result["tokenRejected"] = True
            return result
        raise ExecutionError("post-boundary credential probe failed without authoritative rejection")
    observed = json.loads(probe.stdout).get("status", {}).get("userInfo", {}).get("username")
    result.update({"tokenRejected": False, "observedUsername": observed})
    return result


def execute(candidate_path: Path, grant_path: Path, admin_kubeconfig: Path, kubectl_binary: Path, evidence_output: Path) -> dict[str, Any]:
    candidate, refs = verify_candidate(candidate_path)
    toolchain = configure_kubectl(kubectl_binary, candidate)
    grant = verify_grant(candidate_path, grant_path)
    expect(evidence_output.resolve(), Path(grant["evidenceOutputPath"]).resolve(), "grant-bound evidence output")
    if evidence_output.exists():
        raise ExecutionError("grant-bound raw evidence output already exists")
    clock = V1.verify_clock(candidate["spec"]["executionWindow"]["maximumClockSkewSeconds"])
    preflight = V4.live_preflight(candidate, refs, admin_kubeconfig)
    reviewed = INSTALLER.verify_reviewed_object_set(read_yaml(refs["installationProtocol"]), refs["installationProtocol"])
    temp_config: Path | None = None
    bootstrap_uids: dict[str, str] = {}
    expires_at: datetime | None = None
    real_submission_attempted = False
    evidence: dict[str, Any] = {
        "version": "ok141-m0a-execution-evidence/v5",
        "candidateDigest": sha(candidate_path),
        "grantDigest": sha(grant_path),
        "grantIDs": [grant[key]["grantID"] for key in ("credentialGrant", "admissionGrant", "installationGrant")],
        "fixtureDigest": candidate["spec"]["fixtureDigest"],
        "toolchain": toolchain,
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
        token_result = kubectl(admin_kubeconfig, ["--namespace", V3.SA_NAMESPACE, "create", "token", V3.SA_NAME, "--duration=10m", "--audience", candidate["spec"]["target"]["apiAudience"], "--output=json"])
        token_request = json.loads(token_result.stdout)
        token = token_request["status"]["token"]
        if len(token) < 80:
            raise ExecutionError("TokenRequest returned an invalid token")
        expires_at = parse_utc(token_request["status"]["expirationTimestamp"])
        if (expires_at - requested_at).total_seconds() > 610:
            raise ExecutionError("TokenRequest expiry exceeds the accepted ten-minute boundary")
        evidence["credential"] = {"requestedAt": requested_at.isoformat().replace("+00:00", "Z"), "expiresAt": expires_at.isoformat().replace("+00:00", "Z"), "audience": candidate["spec"]["target"]["apiAudience"], "tokenMaterialRetained": False}
        temp_config = V2.temporary_kubeconfig(admin_kubeconfig, token, candidate)
        token = ""
        token_request["status"]["token"] = ""
        evidence["authorizationProbes"] = V3.authorization_probes(temp_config, reviewed)
        reviewed = INSTALLER.verify_reviewed_object_set(read_yaml(refs["installationProtocol"]), refs["installationProtocol"])
        expect(reviewed.semantic_digest, candidate["spec"]["installation"]["semanticDigest"], "immediate pre-submit semantic digest")
        paths = [admin_kubeconfig, temp_config, kubectl_binary]
        real_submission_attempted = True
        created = kubectl(temp_config, ["create", "--filename", "-"], input_bytes=reviewed.payload, check=False)
        evidence["createDiagnostic"] = diagnostic(created, "create-exact-19-object-stream", paths, candidate)
        if created.returncode != 0:
            raise ExecutionError("create-only submission failed")
        inventory = V4.exact_object_inventory(admin_kubeconfig, reviewed)
        evidence["postSubmissionInventory"] = inventory
        expect(inventory["present"], 19, "created object count")
        evidence["readiness"] = V1.wait_ready(admin_kubeconfig, candidate["spec"]["installation"]["readinessTimeoutSeconds"])
        evidence["objects"] = V1.object_evidence(admin_kubeconfig, reviewed)
        evidence["result"] = "SUCCESS"
        return evidence
    except Exception as exc:
        evidence.update({"result": "STOP-NOT-SUCCESS", "failureType": type(exc).__name__, "failure": str(exc)})
        raise
    finally:
        if real_submission_attempted and "postSubmissionInventory" not in evidence:
            try:
                evidence["postSubmissionInventory"] = V4.exact_object_inventory(admin_kubeconfig, reviewed)
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
                evidence["revocation"] = decisive_post_boundary_probe(temp_config, expires_at, candidate["spec"]["credential"]["rejectionDeadlineOffsetSeconds"])
                if not evidence["revocation"]["tokenRejected"]:
                    evidence["result"] = "STOP-NOT-SUCCESS"
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
    tool = sub.add_parser("verify-toolchain")
    tool.add_argument("--candidate", type=Path, required=True)
    tool.add_argument("--kubectl-bin", type=Path, required=True)
    preflight = sub.add_parser("preflight")
    preflight.add_argument("--candidate", type=Path, required=True)
    preflight.add_argument("--kubectl-bin", type=Path, required=True)
    preflight.add_argument("--admin-kubeconfig", type=Path, required=True)
    run = sub.add_parser("execute")
    run.add_argument("--candidate", type=Path, required=True)
    run.add_argument("--grant", type=Path, required=True)
    run.add_argument("--kubectl-bin", type=Path, required=True)
    run.add_argument("--admin-kubeconfig", type=Path, required=True)
    run.add_argument("--evidence-output", type=Path, required=True)
    run.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        candidate, refs = verify_candidate(args.candidate.resolve())
        if args.command == "verify":
            print(json.dumps({"candidateDigest": sha(args.candidate.resolve()), "state": candidate["spec"]["state"], "mutationAuthorized": False}, sort_keys=True, separators=(",", ":")))
            return 0
        toolchain = configure_kubectl(args.kubectl_bin.resolve(), candidate)
        if args.command == "verify-toolchain":
            print(json.dumps({"result": "PASS", "mutationPerformed": False, "toolchain": toolchain}, sort_keys=True, separators=(",", ":")))
            return 0
        if args.command == "preflight":
            observation = V4.live_preflight(candidate, refs, args.admin_kubeconfig.resolve())
            print(json.dumps({"result": "PASS", "mutationPerformed": False, "toolchain": toolchain, "observation": observation}, sort_keys=True, separators=(",", ":")))
            return 0
        if not args.execute:
            raise ExecutionError("execute command requires the explicit --execute flag")
        result = execute(args.candidate.resolve(), args.grant.resolve(), args.admin_kubeconfig.resolve(), args.kubectl_bin.resolve(), args.evidence_output.resolve())
        if result["result"] != "SUCCESS" or not result.get("revocation", {}).get("tokenRejected"):
            raise ExecutionError("execution or post-boundary credential rejection did not succeed")
        print(json.dumps({"result": result["result"], "evidenceOutput": str(args.evidence_output)}, sort_keys=True, separators=(",", ":")))
        return 0
    except (ExecutionError, INSTALLER.InstallerError, OSError, KeyError, TypeError, ValueError, yaml.YAMLError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
