#!/usr/bin/env python3
import argparse
import hashlib
import json
import sys
from pathlib import Path

import yaml


class ClosureError(ValueError):
    pass


def digest(path):
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical(value):
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def verify(path):
    value = yaml.safe_load(Path(path).read_text())
    spec = value.get("spec", {}) if isinstance(value, dict) else {}
    errors = []
    if spec.get("state") != "PASS-D6-D7-DISPOSABLE-ENVIRONMENT-ABSENT-REDACTED":
        errors.append("state mismatch")

    d6 = spec.get("d6", {})
    if d6.get("plannedDeletes") != 2 or d6.get("completedDeletes") != 2:
        errors.append("D6 delete count mismatch")
    for key in (
        "providerAccessSecretAbsent",
        "managementNamespaceAbsent",
        "uidAndResourceVersionPreconditionsUsed",
    ):
        if d6.get(key) is not True:
            errors.append(f"D6 {key} not proven")
    for key in (
        "retryPerformed",
        "rollbackPerformed",
        "forceDeletePerformed",
        "finalizerMutationPerformed",
    ):
        if d6.get(key) is not False:
            errors.append(f"D6 {key} boundary mismatch")

    d7 = spec.get("d7", {})
    if d7.get("expectedAbsentUniqueIdentities") != 39:
        errors.append("D7 expected count mismatch")
    if d7.get("confirmedAbsentUniqueIdentities") != 39:
        errors.append("D7 absence count mismatch")
    if d7.get("confirmedAbsentByPlane") != {
        "okShared": 5,
        "okMgmt": 18,
        "okInfra": 16,
    }:
        errors.append("D7 plane counts mismatch")
    for key in ("mutationPerformed", "deletePerformed", "retryPerformed"):
        if d7.get(key) is not False:
            errors.append(f"D7 {key} boundary mismatch")

    expected_conclusion = {
        "gitOpsBindingsAbsent": True,
        "lifecycleGraphAbsent": True,
        "providerGraphAbsent": True,
        "retainedStorageAbsent": True,
        "retainedCredentialsAbsent": True,
        "disposableEnvironmentAbsent": True,
        "deleteScenarioComplete": True,
    }
    if spec.get("conclusion") != expected_conclusion:
        errors.append("terminal conclusion mismatch")
    if any(v is not False for v in spec.get("redaction", {}).values()):
        errors.append("redaction mismatch")
    auth = spec.get("authorization", {})
    if auth.get("decision") != "NO-GO" or any(
        v is not False for k, v in auth.items() if k.endswith("Granted")
    ):
        errors.append("closure grants authority")

    if errors:
        raise ClosureError("; ".join(errors))
    return value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--closure", type=Path, required=True)
    args = parser.parse_args()
    value = verify(args.closure)
    print(json.dumps({
        "closureDigest": digest(args.closure),
        "semanticDigest": canonical(value),
        "state": "PASS-D6-D7-TERMINAL-CLOSURE-REDACTED-NO-GO",
    }, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (ClosureError, OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
