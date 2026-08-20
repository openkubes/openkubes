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

    if spec.get("state") != "PASS-D4-D5-PROVIDER-RESIDUALS-ABSENT-REDACTED":
        errors.append("state mismatch")

    d4 = spec.get("d4", {})
    if d4.get("expectedControllerOwnedIdentities") != 24:
        errors.append("D4 expected count mismatch")
    if d4.get("confirmedAbsentControllerOwnedIdentities") != 24:
        errors.append("D4 absence count mismatch")
    if d4.get("loadBalancerServiceAbsent") is not True:
        errors.append("D4 load balancer absence not proven")
    for key in (
        "providerPersistentVolumesObserved",
        "providerPersistentVolumesReleased",
        "providerPersistentVolumesRetain",
        "longhornVolumesObserved",
        "longhornVolumesDetached",
    ):
        if d4.get(key) != 2:
            errors.append(f"D4 {key} mismatch")
    if d4.get("mutationPerformed") is not False:
        errors.append("D4 mutation boundary mismatch")

    d5 = spec.get("d5", {})
    if d5.get("plannedDeletes") != 7 or d5.get("completedDeletes") != 7:
        errors.append("D5 delete count mismatch")
    if d5.get("categories") != {
        "roleBindings": 1,
        "roles": 1,
        "providerNamespaces": 1,
        "providerPersistentVolumes": 2,
        "longhornVolumes": 2,
    }:
        errors.append("D5 category mismatch")
    for key in ("allBoundProviderResidualsAbsent", "permanentDataLossAccepted"):
        if d5.get(key) is not True:
            errors.append(f"D5 {key} not proven")
    for key in (
        "retryPerformed",
        "rollbackPerformed",
        "forceDeletePerformed",
        "finalizerMutationPerformed",
    ):
        if d5.get(key) is not False:
            errors.append(f"D5 {key} boundary mismatch")

    if spec.get("conclusion") != {
        "controllerGraphClosureProven": True,
        "providerResidualCleanupProven": True,
        "retainedStorageCleanupProven": True,
        "d6Required": True,
    }:
        errors.append("conclusion mismatch")

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
        "state": "PASS-D4-D5-CLOSURE-REDACTED-NO-GO",
    }, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (ClosureError, OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
