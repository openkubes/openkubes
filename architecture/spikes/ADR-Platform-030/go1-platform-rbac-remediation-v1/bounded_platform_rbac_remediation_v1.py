#!/usr/bin/env python3
"""Add exactly three evidence-proven list permissions to two bound RBAC objects."""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

import yaml


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
CANDIDATE = HERE / "platform-rbac-remediation-candidate-v1.yaml"
REG_DIR = SPIKE / "go1-registration-audience-remediation-v1"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path); value = importlib.util.module_from_spec(spec)
    assert spec.loader is not None; spec.loader.exec_module(value); return value


REGREM = load_module("ok141_registration_remediation_for_rbac", REG_DIR / "bounded_registration_audience_remediation_v1.py")
DEFAULT, REG = REGREM.DEFAULT, REGREM.REG


class RBACError(ValueError): pass


def sha_bytes(value: bytes) -> str: return "sha256:" + hashlib.sha256(value).hexdigest()
def sha(path: Path) -> str: return sha_bytes(path.read_bytes())
def read(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text())
    if not isinstance(value, dict): raise RBACError(f"expected mapping: {path}")
    return value
def expect(actual: Any, expected: Any, context: str) -> None:
    if actual != expected: raise RBACError(f"{context}: expected {expected!r}, got {actual!r}")
def parse_time(value: str | dt.datetime) -> dt.datetime:
    parsed = value if isinstance(value, dt.datetime) else dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None: raise RBACError("timestamp lacks timezone")
    return parsed.astimezone(dt.timezone.utc)


TRUE = ("managementCredentialAndSecretReadGranted", "targetAdminCredentialGranted", "exactRoleReadsGranted", "exactRoleReplacementsGranted", "optimisticConcurrencyGranted", "nonAtomicPartialStateAccepted", "automaticArgoReconciliationAcknowledged")
FALSE = ("retryGranted", "rollbackOrCleanupGranted", "platformObservationGranted", "evidencePublicationGranted", "failureInjectionGranted")


def safe_private(path: Path, digest: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or (path.stat().st_mode & 0o777) != 0o600: raise RBACError("unsafe predecessor evidence")
    expect(sha(path), digest, "predecessor evidence"); return read(path)


def validate_candidate(path: Path = CANDIDATE) -> dict[str, Any]:
    value = read(path); spec = value["spec"]
    expect(value.get("kind"), "GO1PlatformRBACRemediationCandidate", "kind")
    expect((spec["version"], spec["state"]), ("ok141-go1-platform-rbac-remediation/v1", "OFFLINE-PROVEN-BLOCKED-NO-GO"), "state")
    expect(sha(HERE / spec["predecessor"]["closurePath"]), spec["predecessor"]["closureDigest"], "closure")
    evidence = safe_private(Path(spec["predecessor"]["privateEvidencePath"]), spec["predecessor"]["privateEvidenceDigest"])
    expect((evidence.get("semanticDigest"), evidence.get("findingCount"), evidence.get("unparsedAuthorizationConditionCount"), evidence.get("remediationDesignReady")), (spec["predecessor"]["privateEvidenceSemanticDigest"], 3, 0, True), "cause evidence")
    expected = [("", ["replicationcontrollers", "resourcequotas"], ["list"]), ("cilium.io", ["ciliumpodippools"], ["list"])]
    actual = [(item["apiGroup"], item["resources"], item["verbs"]) for item in spec["target"]["objects"]]
    expect(actual, expected, "exact RBAC delta")
    expect(sha(HERE / spec["tool"]["path"]), spec["tool"]["digest"], "tool")
    expect(spec["authorization"]["decision"], "NO-GO", "authorization")
    if any(item for key, item in spec["authorization"].items() if key.endswith("Granted") or key.endswith("Accepted") or key.endswith("Acknowledged")): raise RBACError("candidate grants authority")
    return value


def validate_grant(candidate_path: Path, grant_path: Path, now: dt.datetime | None = None) -> dict[str, Any]:
    validate_candidate(candidate_path); grant = read(grant_path); spec = grant["spec"]
    expect(grant.get("kind"), "GO1PlatformRBACRemediationGrant", "grant kind")
    expect((spec.get("decision"), spec.get("authority"), spec.get("singleRun"), spec.get("consumed")), ("GO", "github:arashkaffamanesh", True, False), "grant identity")
    expect(spec.get("candidateDigest"), sha(candidate_path), "candidate digest")
    if any(spec.get(key) is not True for key in TRUE) or any(spec.get(key) is not False for key in FALSE): raise RBACError("grant incomplete or overbroad")
    current = now or dt.datetime.now(dt.timezone.utc); issued, expires = parse_time(spec["issuedAt"]), parse_time(spec["expiresAt"])
    if not issued <= current <= expires or expires - issued > dt.timedelta(minutes=15): raise RBACError("grant inactive or exceeds 15 minutes")
    return grant


def exact_rule(item: dict[str, Any]) -> dict[str, Any]:
    return {"apiGroups": [item["apiGroup"]], "resources": item["resources"], "verbs": item["verbs"]}


def amended(value: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    rule = exact_rule(item)
    for existing in value.get("rules", []) or []:
        if item["apiGroup"] in existing.get("apiGroups", []) and set(item["resources"]).issubset(existing.get("resources", [])) and set(item["verbs"]).issubset(existing.get("verbs", [])):
            raise RBACError(f"permission already present: {item['id']}")
    result = copy.deepcopy(value); result.setdefault("rules", []).append(rule)
    result.get("metadata", {}).pop("managedFields", None); result.get("metadata", {}).pop("selfLink", None)
    return result


def execute(candidate_path: Path, grant_path: Path, runner: Callable[..., Any] = subprocess.run) -> dict[str, Any]:
    candidate = validate_candidate(candidate_path); grant = validate_grant(candidate_path, grant_path); spec = candidate["spec"]
    _, binding = DEFAULT.validate_predecessors({"spec": {"predecessor": {"privateEvidenceDigest": "sha256:d3382b75d2df4910ffe791c173cd0df169cc33461796beb1934d38fce2e86c0c", "privateEvidenceSemanticDigest": "sha256:50c55e6e7770109baabe9e4e62eb17330d1f346b6ff609032b8e1d90c6bd3a25"}, "runtimeBinding": {"path": "/private/tmp/ok141-go1-runtime-binding-v2.json", "digest": "sha256:2e5f56cf305e6eb9241f00b2d019583664529560a0c68159ec52b9efa6653e47", "semanticDigest": "sha256:5f89ee33972c778844a61e9e31b4fbfefa232949f33588fb9d81fe0948794c64"}}})
    management, target = spec["management"], spec["target"]
    client = Path(target["clientPath"]); expect(sha(client), target["clientDigest"], "target client")
    admin = Path(target["ephemeralAdminKubeconfigPath"])
    if admin.exists() or admin.is_symlink(): raise RBACError("ephemeral admin path exists")
    reads: list[tuple[dict[str, Any], dict[str, Any], str, str]] = []; updates = []
    try:
        admin = DEFAULT.materialize_admin({"spec": {"management": management, "target": target}}, binding, runner)
        for item in target["objects"]:
            code, stdout, _ = REG.raw_get(client, admin, item["uri"], runner)
            if code != 0: raise RBACError(f"exact RBAC GET failed: {item['id']}")
            current = json.loads(stdout); metadata = current.get("metadata", {}); uid, rv = metadata.get("uid", ""), metadata.get("resourceVersion", "")
            if not uid or not rv: raise RBACError(f"missing concurrency identity: {item['id']}")
            reads.append((item, amended(current, item), uid, rv)); current = {}; stdout = b""
        for item, document, uid, rv in reads:
            code, stdout, _ = REGREM.raw_replace(client, admin, item["uri"], document, runner)
            if code != 0: raise RBACError(f"RBAC replace failed; partial state preserved: {item['id']}")
            returned = json.loads(stdout); meta = returned.get("metadata", {})
            if meta.get("uid") != uid or not meta.get("resourceVersion") or meta.get("resourceVersion") == rv: raise RBACError(f"replacement identity verification failed: {item['id']}")
            updates.append({"id": item["id"], "uidPreserved": True, "resourceVersionAdvanced": True, "exactRuleAdded": True}); returned = {}; stdout = b""
    finally:
        admin.unlink(missing_ok=True)
    evidence = {"apiVersion": "evidence.openkubes.io/v1alpha1", "kind": "GO1PlatformRBACRemediationEvidence", "candidateDigest": sha(candidate_path), "grantID": grant["spec"]["grantID"], "updates": updates, "updateCount": len(updates), "optimisticConcurrencyUsed": True, "nonAtomicExecution": True, "automaticArgoReconciliationMayResume": True, "adminKubeconfigRemoved": not admin.exists() and not admin.is_symlink(), "credentialPayloadRetained": False, "rawObjectsRetained": False, "retryPerformed": False, "rollbackOrCleanupPerformed": False, "platformObservationPerformed": False, "failureInjectionPerformed": False}
    if len(updates) != 2 or not evidence["adminKubeconfigRemoved"]: raise RBACError("remediation closure incomplete")
    evidence["semanticDigest"] = sha_bytes(json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode())
    output = Path(spec["outputPath"])
    if output.exists() or output.is_symlink(): raise RBACError("exclusive output exists")
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream: json.dump(evidence, stream, sort_keys=True, separators=(",", ":")); stream.write("\n")
    return {"result": "PASS-PLATFORM-RBAC-REMEDIATION", "updateCount": 2, "outputPath": str(output), "outputDigest": sha(output)}


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("command", choices=("verify", "verify-grant", "remediate")); parser.add_argument("--candidate", type=Path, default=CANDIDATE); parser.add_argument("--grant", type=Path); parser.add_argument("--execute", action="store_true"); args = parser.parse_args()
    try:
        if args.command == "verify": validate_candidate(args.candidate.resolve()); print(sha(args.candidate.resolve()))
        elif args.command == "verify-grant":
            if args.grant is None: raise RBACError("grant required")
            validate_grant(args.candidate.resolve(), args.grant.resolve()); print(sha(args.grant.resolve()))
        else:
            if args.grant is None or not args.execute: raise RBACError("remediate requires grant and --execute")
            print(json.dumps(execute(args.candidate.resolve(), args.grant.resolve()), sort_keys=True))
        return 0
    except Exception as error:
        print(f"ERROR: {type(error).__name__}: {error}", file=sys.stderr); return 2


if __name__ == "__main__": raise SystemExit(main())
