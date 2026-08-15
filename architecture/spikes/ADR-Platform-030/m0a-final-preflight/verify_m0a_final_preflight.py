#!/usr/bin/env python3
"""Fail-closed verifier for the non-authorizing OK-141 M0a final preflight."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import yaml


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent


class VerificationError(ValueError):
    pass


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def expect(actual, expected, claim: str) -> None:
    if actual != expected:
        raise VerificationError(f"{claim}: expected {expected!r}, got {actual!r}")


def resolve(reference: dict) -> Path:
    path = (HERE / reference["path"]).resolve()
    if SPIKE not in path.parents or not path.is_file():
        raise VerificationError(f"reference missing or outside spike root: {path}")
    expect(digest(path), reference["digest"], f"digest for {reference['path']}")
    return path


def verify(path: Path) -> str:
    document = yaml.safe_load(path.read_text())
    spec = document["spec"]
    expect(spec["state"], "READY-FOR-EXPLICIT-DECISIONS-NO-GO", "preflight state")

    baseline = spec["baseline"]
    for key in ("installationProtocol", "offlineClosure", "installer"):
        resolve(baseline[key])

    installation = baseline["installationSet"]
    expect(installation["objectCount"], 19, "CAAPH object count")
    expect(installation["targetResourcesIncluded"], False, "target-resource exclusion")

    target = spec["targetObservation"]
    expect(target["operation"], "READ-ONLY", "observation operation")
    expect(target["caaph"], {
        "namespacePresent": False,
        "helmChartProxyCRDPresent": False,
        "helmReleaseProxyCRDPresent": False,
    }, "CAAPH absence")
    expect(target["lifecycleInventory"], {
        "clusters": 0,
        "machines": 0,
        "machineDeployments": 0,
    }, "CAPI lifecycle inventory")
    expect(target["nodes"]["total"], target["nodes"]["ready"], "ready node count")

    credential = spec["currentCredential"]
    expect(credential["acceptedForInstallation"], False, "current credential rejection")
    expect(credential["secretMaterialRecorded"], False, "secret-material exclusion")
    expect(credential["group"], "system:masters", "current credential group")

    decisions = {item["id"]: item for item in spec["explicitDecisionsRequired"]}
    expect(set(decisions), {
        "M0AI-COMPATIBILITY-RISK",
        "M0AI-CONTROLLER-RBAC-RISK",
        "M0AI-INSTALLER-CREDENTIAL",
        "M0AI-INSTALLATION-GRANT",
    }, "decision inventory")
    if any(item["state"] not in {"UNDECIDED", "NOT-PREPARED", "NOT-GRANTED"} for item in decisions.values()):
        raise VerificationError("an explicit decision was closed by a non-authorizing preflight")

    auth = spec["authorization"]
    expect(auth["decision"], "NO-GO", "authorization decision")
    for claim in (
        "mutationAuthorized",
        "credentialIssuanceAuthorized",
        "m0aInstallationGranted",
        "m0bInstallationGranted",
        "go1Granted",
        "failureInjectionGranted",
    ):
        expect(auth[claim], False, claim)

    rules = " ".join(spec["rules"])
    for phrase in ("no Secret token kubeconfig private key", "grants no authority", "separate gates", "remain NO-GO"):
        if phrase not in rules:
            raise VerificationError(f"required fail-closed rule missing: {phrase}")

    return digest(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight", type=Path, required=True)
    parser.add_argument("--digest-file", type=Path)
    args = parser.parse_args()
    try:
        result = verify(args.preflight.resolve())
        if args.digest_file:
            expect(args.digest_file.read_text().strip(), result, "preflight digest file")
        print(result)
        return 0
    except (OSError, KeyError, TypeError, VerificationError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
