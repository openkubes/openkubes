#!/usr/bin/env python3
"""Verify the non-authorizing v7 security and risk-decision package."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import yaml


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
BOUNDARY = HERE / "m0a-v7-security-boundary.yaml"
RISK = HERE / "m0a-v7-risk-acceptance-candidate.yaml"


class SecurityError(ValueError):
    pass


def sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def expect(actual: Any, expected: Any, claim: str) -> None:
    if actual != expected:
        raise SecurityError(f"{claim}: expected {expected!r}, got {actual!r}")


def resolve(base: Path, reference: dict[str, Any]) -> Path:
    path = (base / reference["path"]).resolve()
    if SPIKE.resolve() not in path.parents or not path.is_file():
        raise SecurityError(f"reference missing or outside spike root: {reference['path']}")
    expect(sha(path), reference["digest"], f"digest for {reference['path']}")
    return path


def verify() -> dict[str, Any]:
    boundary = yaml.safe_load(BOUNDARY.read_text())["spec"]
    risk = yaml.safe_load(RISK.read_text())["spec"]
    expect(boundary["version"], "ok141-m0a-security-boundary/v7", "security version")
    expect(boundary["state"], "BLOCKED-OFFLINE-CANDIDATE", "security state")
    resolve(BOUNDARY.parent, {
        "path": boundary["cause"]["evidencePath"],
        "digest": boundary["cause"]["evidenceDigest"],
    })
    partition_path = resolve(BOUNDARY.parent, boundary["partition"])
    partition = yaml.safe_load(partition_path.read_text())["spec"]
    expect((boundary["partition"]["administratorObjectCount"], boundary["partition"]["temporaryInstallerObjectCount"]), (8, 11), "partition counts")
    expect(partition["authorization"]["mutationAuthorized"], False, "partition mutation")
    expect(boundary["authorityDomains"]["temporaryInstaller"]["escalateAllowed"], False, "installer escalate")
    expect(boundary["authorityDomains"]["temporaryInstaller"]["bindAllowed"], False, "installer bind")
    expect(boundary["submissionBoundary"]["automaticRetryAllowed"], False, "automatic retry")
    expect(boundary["submissionBoundary"]["automaticRollbackAllowed"], False, "automatic rollback")
    expect(boundary["authorization"]["mutationAuthorized"], False, "boundary mutation")
    expect(boundary["authorization"]["evidencePublicationGranted"], False, "boundary publication")

    risk_ids = [item["id"] for item in boundary["riskClaims"]]
    expect(risk["risks"], risk_ids, "risk inventory")
    expect(risk["references"]["securityBoundary"]["digest"], sha(BOUNDARY), "risk security binding")
    resolve(RISK.parent, risk["references"]["v6RuntimeEvidence"])
    expected_text = (
        "Ich akzeptiere für OK-141/M0a-v7 die dokumentierte Admin-Content-Grenze, die nicht-atomare "
        "Split-Authority-Installation mit möglichem partiellem Zustand, die fortbestehende Installer-Content- "
        "und temporäre Admission-Bootstrap-Grenze sowie die bis expirationTimestamp+100s gebundene "
        f"Token-Ablehnungsbeobachtung, gebunden an Security-Kandidat {sha(BOUNDARY)}. Diese Akzeptanz erteilt "
        "keine Freigabe für Admin-Prerequisites, Credentials, Admission-Installation, CAAPH-Installation oder "
        "-Retry, Rollback, Evidence-Publication, M0b-I, GO-1, Target-Konvergenz oder Failure Injection."
    )
    expect(risk["acceptanceText"], expected_text, "acceptance text")
    expect(risk["acceptance"]["accepted"], False, "risk acceptance")
    expect(risk["authorization"]["mutationAuthorized"], False, "risk mutation")
    expect(risk["authorization"]["evidencePublicationGranted"], False, "risk publication")
    return {
        "state": boundary["state"],
        "securityCandidateDigest": sha(BOUNDARY),
        "risks": len(risk_ids),
        "separateGrantDomains": 4,
        "mutationAuthorized": False,
        "clusterContacted": False,
    }


def main() -> int:
    try:
        print(json.dumps(verify(), sort_keys=True, separators=(",", ":")))
        return 0
    except (SecurityError, KeyError, OSError, TypeError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
