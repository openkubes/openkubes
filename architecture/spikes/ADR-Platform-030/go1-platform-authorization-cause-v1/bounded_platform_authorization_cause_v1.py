#!/usr/bin/env python3
"""Extract normalized RBAC denial facts from three exact Argo Application reads."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

import yaml


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
CANDIDATE = HERE / "platform-authorization-cause-candidate-v1.yaml"
OBSERVER_DIR = SPIKE / "go1-post-remediation-platform-observer-v1"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(value)
    return value


OBSERVER = load_module("ok141_post_remediation_for_auth_cause", OBSERVER_DIR / "bounded_post_remediation_platform_observer_v1.py")
DIAG = OBSERVER.DIAG


class CauseError(ValueError):
    pass


DENIAL = re.compile(
    r'cannot\s+(?P<verb>get|list|watch|create|patch|update|delete)\s+'
    r'resources?\s+"(?P<resource>[a-z0-9.\-]+)"'
    r'(?:\s+in\s+API\s+group\s+"(?P<group>[a-z0-9.\-]*)")?'
    r'(?:\s+in\s+the\s+namespace\s+"(?P<namespace>[^"]+)"|\s+at\s+the\s+cluster\s+scope)',
    re.IGNORECASE,
)
NONRESOURCE = re.compile(r'cannot\s+(?P<verb>get)\s+(?:non-resource\s+URL|path)\s+"(?P<path>/[^"]*)"', re.IGNORECASE)


def sha_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def sha(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def read(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text())
    if not isinstance(value, dict): raise CauseError(f"expected mapping: {path}")
    return value


def expect(actual: Any, expected: Any, context: str) -> None:
    if actual != expected: raise CauseError(f"{context}: expected {expected!r}, got {actual!r}")


def parse_time(value: str | dt.datetime) -> dt.datetime:
    parsed = value if isinstance(value, dt.datetime) else dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None: raise CauseError("timestamp lacks timezone")
    return parsed.astimezone(dt.timezone.utc)


def safe_evidence(path: Path, expected_digest: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or (path.stat().st_mode & 0o777) != 0o600:
        raise CauseError("unsafe predecessor evidence")
    expect(sha(path), expected_digest, "predecessor evidence digest")
    return read(path)


def validate_candidate(path: Path = CANDIDATE) -> dict[str, Any]:
    value = read(path); spec = value["spec"]
    expect(value.get("kind"), "GO1PlatformAuthorizationCauseCandidate", "kind")
    expect((spec["version"], spec["state"]), ("ok141-go1-platform-authorization-cause/v1", "OFFLINE-PROVEN-BLOCKED-NO-GO"), "state")
    expect(sha(HERE / spec["predecessor"]["closurePath"]), spec["predecessor"]["closureDigest"], "closure")
    evidence = safe_evidence(Path(spec["predecessor"]["privateEvidencePath"]), spec["predecessor"]["privateEvidenceDigest"])
    expect((evidence.get("semanticDigest"), evidence.get("readyCount"), evidence.get("allReady")), (spec["predecessor"]["privateEvidenceSemanticDigest"], 0, False), "predecessor result")
    expect(len(spec["argo"]["applications"]), 3, "Application count")
    expect(sha(HERE / spec["tool"]["path"]), spec["tool"]["digest"], "tool")
    expect(spec["authorization"]["decision"], "NO-GO", "authorization")
    if any(item for key, item in spec["authorization"].items() if key.endswith("Granted")): raise CauseError("candidate grants authority")
    return value


TRUE = ("sharedClusterContactGranted", "sharedCredentialUseGranted", "exactApplicationReadsGranted", "transientMessageInspectionGranted", "normalizedRBACExtractionGranted")
FALSE = ("secretPodLogOrTargetReadGranted", "mutationGranted", "retryGranted", "cleanupGranted", "evidencePublicationGranted", "failureInjectionGranted")


def validate_grant(candidate_path: Path, grant_path: Path, now: dt.datetime | None = None) -> dict[str, Any]:
    validate_candidate(candidate_path); grant = read(grant_path); spec = grant["spec"]
    expect(grant.get("kind"), "GO1PlatformAuthorizationCauseGrant", "grant kind")
    expect((spec.get("decision"), spec.get("authority"), spec.get("singleRun"), spec.get("consumed")), ("GO", "github:arashkaffamanesh", True, False), "grant identity")
    expect(spec.get("candidateDigest"), sha(candidate_path), "candidate digest")
    if any(spec.get(key) is not True for key in TRUE) or any(spec.get(key) is not False for key in FALSE): raise CauseError("grant authority incomplete or overbroad")
    current = now or dt.datetime.now(dt.timezone.utc); issued, expires = parse_time(spec["issuedAt"]), parse_time(spec["expiresAt"])
    if not issued <= current <= expires or expires - issued > dt.timedelta(minutes=10): raise CauseError("grant inactive or exceeds ten minutes")
    return grant


def namespace_category(value: str | None) -> str:
    if value == "ok-observability": return "OK-OBSERVABILITY"
    if value == "kube-system": return "KUBE-SYSTEM"
    return "OTHER" if value else "NONE"


def path_category(value: str) -> str:
    if value in ("/api", "/api/v1", "/apis", "/version", "/openapi/v2", "/openapi/v3"): return value.upper().replace("/", "-").strip("-") or "ROOT"
    return "OTHER"


def extract_findings(message: str) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for match in DENIAL.finditer(message):
        namespace = match.group("namespace")
        findings.append({
            "kind": "RESOURCE", "verb": match.group("verb").lower(),
            "apiGroup": (match.group("group") or ""), "resource": match.group("resource").lower(),
            "scope": "NAMESPACE" if namespace else "CLUSTER",
            "namespaceCategory": namespace_category(namespace),
        })
    for match in NONRESOURCE.finditer(message):
        findings.append({"kind": "NONRESOURCE", "verb": match.group("verb").lower(), "pathCategory": path_category(match.group("path")), "scope": "NONRESOURCE"})
    unique = {json.dumps(item, sort_keys=True, separators=(",", ":")): item for item in findings}
    return [unique[key] for key in sorted(unique)]


def execute(candidate_path: Path, grant_path: Path, runner: Callable[..., Any] = subprocess.run) -> dict[str, Any]:
    candidate = validate_candidate(candidate_path); grant = validate_grant(candidate_path, grant_path); spec = candidate["spec"]
    client, kubeconfig = Path(spec["argo"]["clientPath"]), Path(spec["argo"]["credentialPath"])
    expect(sha(client), spec["argo"]["clientDigest"], "client")
    if kubeconfig.is_symlink() or not kubeconfig.is_file() or (kubeconfig.stat().st_mode & 0o777) != 0o600: raise CauseError("unsafe shared Kubeconfig")
    expect(DIAG.EXECUTOR.inspect_identity(kubeconfig)["identityDigest"], spec["argo"]["credentialIdentityDigest"], "shared identity")
    output = Path(spec["outputPath"])
    if output.exists() or output.is_symlink(): raise CauseError("exclusive output already exists")
    applications = []; aggregate: list[dict[str, str]] = []; unparsed = 0
    for name in spec["argo"]["applications"]:
        uri = f"/apis/argoproj.io/v1alpha1/namespaces/{spec['argo']['namespace']}/applications/{name}"
        value = DIAG.raw_get(client, kubeconfig, uri, runner); conditions = []
        for condition in value.get("status", {}).get("conditions", []) or []:
            message = str(condition.get("message", "")); classification = DIAG.classify_message(message); findings = extract_findings(message)
            if classification == "AUTHORIZATION" and not findings: unparsed += 1
            aggregate.extend(findings)
            conditions.append({"type": condition.get("type"), "classification": classification, "messageDigest": sha_bytes(message.encode()), "findingCount": len(findings)})
        applications.append({"name": name, "conditions": conditions})
        value = {}; message = ""
    unique = {json.dumps(item, sort_keys=True, separators=(",", ":")): item for item in aggregate}
    findings = [unique[key] for key in sorted(unique)]
    evidence = {"apiVersion": "evidence.openkubes.io/v1alpha1", "kind": "GO1PlatformAuthorizationCauseEvidence", "candidateDigest": sha(candidate_path), "grantID": grant["spec"]["grantID"], "applications": applications, "normalizedFindings": findings, "findingCount": len(findings), "unparsedAuthorizationConditionCount": unparsed, "remediationDesignReady": bool(findings) and unparsed == 0, "queryCount": 3, "rawMessagesRetained": False, "subjectsRetained": False, "apiEndpointsRetained": False, "secretPodLogOrTargetReadPerformed": False, "mutationPerformed": False, "retryPerformed": False, "cleanupPerformed": False}
    evidence["semanticDigest"] = sha_bytes(json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode())
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream: json.dump(evidence, stream, sort_keys=True, separators=(",", ":")); stream.write("\n")
    return {"result": "PASS-PLATFORM-AUTHORIZATION-CAUSE-DIAGNOSTIC", "findingCount": len(findings), "unparsedAuthorizationConditionCount": unparsed, "remediationDesignReady": evidence["remediationDesignReady"], "outputPath": str(output), "outputDigest": sha(output)}


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("command", choices=("verify", "verify-grant", "diagnose")); parser.add_argument("--candidate", type=Path, default=CANDIDATE); parser.add_argument("--grant", type=Path); parser.add_argument("--execute", action="store_true"); args = parser.parse_args()
    try:
        if args.command == "verify": validate_candidate(args.candidate.resolve()); print(sha(args.candidate.resolve()))
        elif args.command == "verify-grant":
            if args.grant is None: raise CauseError("grant required")
            validate_grant(args.candidate.resolve(), args.grant.resolve()); print(sha(args.grant.resolve()))
        else:
            if args.grant is None or not args.execute: raise CauseError("diagnose requires grant and --execute")
            print(json.dumps(execute(args.candidate.resolve(), args.grant.resolve()), sort_keys=True))
        return 0
    except Exception as error:
        print(f"ERROR: {type(error).__name__}: {error}", file=sys.stderr); return 2


if __name__ == "__main__": raise SystemExit(main())
