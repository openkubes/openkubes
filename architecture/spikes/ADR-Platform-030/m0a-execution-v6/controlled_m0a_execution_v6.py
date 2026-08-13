#!/usr/bin/env python3
"""M0a-v6 executor; mutation remains impossible without a v6 grant."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


V5 = load("ok141_m0a_v5_for_v6", SPIKE / "m0a-execution-v5" / "controlled_m0a_execution_v5.py")
FIX = load("ok141_m0a_v6_fixes", HERE / "m0a_v6_fixes.py")


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


def verify_candidate(path: Path) -> tuple[dict[str, Any], dict[str, Path], dict[str, Any], dict[str, Path]]:
    document = read_yaml(path)
    spec = document["spec"]
    expect(spec["version"], "ok141-m0a-combined-candidate/v6", "candidate version")
    expect(spec["state"], "READY-FOR-THREE-SEPARATE-EXPLICIT-GRANTS", "candidate state")
    refs = {name: resolve(path.parent, ref) for name, ref in spec["references"].items()}
    expect(refs["executor"], Path(__file__).resolve(), "executor identity")
    base, base_refs = V5.verify_candidate(refs["baseCandidate"])
    rendered = FIX.amend_admission_manifest(refs["admissionAmendment"])
    expect("sha256:" + hashlib.sha256(rendered).hexdigest(), spec["admission"]["renderedDigest"], "rendered admission")
    expect(spec["credential"]["postBoundaryWait"], "RECHECK-UNTIL-NOT-BEFORE", "boundary wait")
    expect(spec["authorization"], {
        "decision": "NO-GO", "mutationAuthorized": False,
        "credentialGrantRequired": True, "admissionBootstrapGrantRequired": True,
        "installationGrantRequired": True, "retryGranted": False,
        "rollbackGranted": False, "m0bInstallationGranted": False,
        "go1Granted": False, "evidencePublicationGranted": False,
        "targetConvergenceGranted": False, "failureInjectionGranted": False,
    }, "authorization")
    return document, refs, base, base_refs


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo != timezone.utc:
        raise ExecutionError("grant timestamps must be UTC")
    return parsed


def verify_grant(candidate_path: Path, grant_path: Path, now: datetime | None = None) -> dict[str, Any]:
    candidate, _, base, _ = verify_candidate(candidate_path)
    grant = read_yaml(grant_path)["spec"]
    expect(grant["version"], "ok141-m0a-combined-grant/v6", "grant version")
    expect(grant["candidateDigest"], sha(candidate_path), "candidate binding")
    expect(grant["authority"], "github:arashkaffamanesh", "authority")
    expect((grant["decision"], grant["mutationAuthorized"]), ("GO", True), "decision")
    ids = []
    for field, gate in (("credentialGrant", "M0A-C1-v6"), ("admissionGrant", "M0A-A1-v6"), ("installationGrant", "M0a-I-v6")):
        expect((grant[field]["gate"], grant[field]["granted"]), (gate, True), field)
        ids.append(grant[field]["grantID"])
    if len(set(ids)) != 3:
        raise ExecutionError("three distinct grant IDs are required")
    start, end = parse_utc(grant["validFrom"]), parse_utc(grant["validUntil"])
    if end <= start or (end - start).total_seconds() > base["spec"]["executionWindow"]["maximumDurationMinutes"] * 60:
        raise ExecutionError("grant window is invalid or too long")
    current = now or datetime.now(timezone.utc)
    if not start <= current <= end:
        raise ExecutionError("current time is outside the grant window")
    expect(grant["maximumRuns"], 1, "maximum runs")
    output = Path(grant["evidenceOutputPath"])
    if not output.is_absolute() or Path("/private/tmp") not in output.resolve().parents:
        raise ExecutionError("evidence output must be below /private/tmp")
    for field in ("retryGranted", "rollbackGranted", "targetConvergenceGranted", "m0bInstallationGranted", "go1Granted", "evidencePublicationGranted", "failureInjectionGranted"):
        expect(grant[field], False, field)
    return grant


def decisive_probe(kubeconfig: Path, expires_at: datetime, offset: int) -> dict[str, Any]:
    boundary = expires_at + timedelta(seconds=offset)
    sampled = FIX.wait_until_not_before(boundary, now=lambda: datetime.now(timezone.utc), sleep=V5.time.sleep)
    probe = V5.kubectl(kubeconfig, ["auth", "whoami", "--output=json"], check=False)
    result = {"boundary": boundary.isoformat().replace("+00:00", "Z"), "sampledAt": sampled.isoformat().replace("+00:00", "Z"), "notBeforeBoundary": True}
    if probe.returncode != 0:
        stderr = probe.stderr.decode(errors="replace")
        if "Unauthorized" in stderr or "logged in" in stderr:
            result["tokenRejected"] = True
            return result
        raise ExecutionError("post-boundary probe failed without authoritative rejection")
    result.update({"tokenRejected": False, "observedUsername": json.loads(probe.stdout).get("status", {}).get("userInfo", {}).get("username")})
    return result


def execute(candidate_path: Path, grant_path: Path, admin: Path, kubectl_bin: Path, output: Path) -> dict[str, Any]:
    candidate, refs, base, base_refs = verify_candidate(candidate_path)
    toolchain = V5.configure_kubectl(kubectl_bin, base)
    grant = verify_grant(candidate_path, grant_path)
    expect(output.resolve(), Path(grant["evidenceOutputPath"]).resolve(), "evidence path")
    if output.exists():
        raise ExecutionError("grant-bound evidence already exists")
    clock = V5.V1.verify_clock(base["spec"]["executionWindow"]["maximumClockSkewSeconds"])
    preflight = V5.V4.live_preflight(base, base_refs, admin)
    reviewed = V5.INSTALLER.verify_reviewed_object_set(read_yaml(base_refs["installationProtocol"]), base_refs["installationProtocol"])
    temp: Path | None = None
    bootstrap_uids: dict[str, str] = {}
    expires: datetime | None = None
    attempted = False
    evidence: dict[str, Any] = {
        "version": "ok141-m0a-execution-evidence/v6", "candidateDigest": sha(candidate_path),
        "grantDigest": sha(grant_path), "grantIDs": [grant[x]["grantID"] for x in ("credentialGrant", "admissionGrant", "installationGrant")],
        "fixtureDigest": base["spec"]["fixtureDigest"], "toolchain": toolchain, "target": preflight,
        "clock": clock, "startedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "result": "STARTED", "secretMaterialRetained": False,
    }
    try:
        admission = FIX.amend_admission_manifest(refs["admissionAmendment"])
        payload = base_refs["credentialManifest"].read_bytes() + b"\n---\n" + admission
        V5.kubectl(admin, ["create", "--filename", "-"], input_bytes=payload)
        bootstrap_uids = V5.V2.discover_bootstrap_objects(admin)
        expect(set(bootstrap_uids), {x[0] for x in V5.BOOTSTRAP_OBJECTS}, "bootstrap inventory")
        evidence["policy"] = V5.V2.wait_policy_ready(admin)
        requested = datetime.now(timezone.utc)
        token_result = V5.kubectl(admin, ["--namespace", V5.V3.SA_NAMESPACE, "create", "token", V5.V3.SA_NAME, "--duration=10m", "--audience", base["spec"]["target"]["apiAudience"], "--output=json"])
        token_request = json.loads(token_result.stdout)
        token = token_request["status"]["token"]
        expires = parse_utc(token_request["status"]["expirationTimestamp"])
        if len(token) < 80 or (expires - requested).total_seconds() > 610:
            raise ExecutionError("invalid TokenRequest result")
        evidence["credential"] = {"requestedAt": requested.isoformat().replace("+00:00", "Z"), "expiresAt": expires.isoformat().replace("+00:00", "Z"), "audience": base["spec"]["target"]["apiAudience"], "tokenMaterialRetained": False}
        temp = V5.V2.temporary_kubeconfig(admin, token, base)
        token = ""
        evidence["authorizationProbes"] = V5.V3.authorization_probes(temp, reviewed)
        reviewed = V5.INSTALLER.verify_reviewed_object_set(read_yaml(base_refs["installationProtocol"]), base_refs["installationProtocol"])
        expect(reviewed.semantic_digest, base["spec"]["installation"]["semanticDigest"], "pre-submit digest")
        attempted = True
        created = V5.kubectl(temp, ["create", "--filename", "-"], input_bytes=reviewed.payload, check=False)
        evidence["createDiagnostic"] = V5.diagnostic(created, "create-exact-19-object-stream", [admin, temp, kubectl_bin], base)
        if created.returncode != 0:
            raise ExecutionError("create-only submission failed")
        inventory = V5.V4.exact_object_inventory(admin, reviewed)
        evidence["postSubmissionInventory"] = inventory
        expect(inventory["present"], 19, "created object count")
        evidence["readiness"] = V5.V1.wait_ready(admin, base["spec"]["installation"]["readinessTimeoutSeconds"])
        evidence["objects"] = V5.V1.object_evidence(admin, reviewed)
        evidence["result"] = "SUCCESS"
        return evidence
    except Exception as exc:
        evidence.update({"result": "STOP-NOT-SUCCESS", "failureType": type(exc).__name__, "failure": str(exc)})
        raise
    finally:
        if attempted and "postSubmissionInventory" not in evidence:
            try: evidence["postSubmissionInventory"] = V5.V4.exact_object_inventory(admin, reviewed)
            except Exception as exc: evidence["postSubmissionInventory"] = {"failureType": type(exc).__name__, "failure": str(exc)}
        try: evidence["bootstrapCleanup"] = V5.V2.cleanup_bootstrap(admin, bootstrap_uids)
        except Exception as exc: evidence.update({"result": "STOP-NOT-SUCCESS", "bootstrapCleanup": {"removed": False, "failureType": type(exc).__name__, "failure": str(exc)}})
        if temp is not None and expires is not None:
            try:
                evidence["revocation"] = decisive_probe(temp, expires, base["spec"]["credential"]["rejectionDeadlineOffsetSeconds"])
                if not evidence["revocation"]["tokenRejected"]: evidence["result"] = "STOP-NOT-SUCCESS"
            except Exception as exc: evidence.update({"result": "STOP-NOT-SUCCESS", "revocation": {"tokenRejected": False, "failureType": type(exc).__name__, "failure": str(exc)}})
        if temp is not None: temp.unlink(missing_ok=True)
        evidence["finishedAt"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(evidence, sort_keys=True, separators=(",", ":")) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "verify-grant", "execute"))
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--grant", type=Path)
    parser.add_argument("--kubectl-bin", type=Path)
    parser.add_argument("--admin-kubeconfig", type=Path)
    parser.add_argument("--evidence-output", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        candidate, _, _, _ = verify_candidate(args.candidate.resolve())
        result = {"candidateDigest": sha(args.candidate.resolve()), "state": candidate["spec"]["state"], "mutationAuthorized": False}
        if args.command == "verify-grant":
            if args.grant is None:
                raise ExecutionError("grant is required")
            verify_grant(args.candidate.resolve(), args.grant.resolve())
            result["grantValidNow"] = True
        elif args.command == "execute":
            if not args.execute or None in (args.grant, args.kubectl_bin, args.admin_kubeconfig, args.evidence_output):
                raise ExecutionError("execute requires exact grant, toolchain, target, output, and --execute")
            run = execute(args.candidate.resolve(), args.grant.resolve(), args.admin_kubeconfig.resolve(), args.kubectl_bin.resolve(), args.evidence_output.resolve())
            if run["result"] != "SUCCESS" or not run.get("revocation", {}).get("tokenRejected"):
                raise ExecutionError("execution or credential rejection did not succeed")
            result = {"result": "SUCCESS", "evidenceOutput": str(args.evidence_output)}
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    except (ExecutionError, OSError, KeyError, TypeError, ValueError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
