#!/usr/bin/env python3
"""Verify the redacted OK-141 E1 closure checkpoint."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import yaml


HERE = Path(__file__).resolve().parent
EVIDENCE = HERE / "enablement-e1-closure-evidence-v1.yaml"


class VerificationError(ValueError):
    pass


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def expect(actual: Any, expected: Any, context: str) -> None:
    if actual != expected:
        raise VerificationError(f"{context}: expected {expected!r}, got {actual!r}")


def walk(value: Any, path: str = ""):
    if isinstance(value, dict):
        for key, item in value.items():
            current = f"{path}.{key}" if path else key
            yield current, item
            yield from walk(item, current)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from walk(item, f"{path}[{index}]")


def verify(path: Path = EVIDENCE) -> str:
    value = yaml.safe_load(path.read_text())
    if not isinstance(value, dict):
        raise VerificationError("evidence must be a mapping")
    expect(value.get("kind"), "OK141ControlledEnablementFailureClosure", "kind")
    spec = value["spec"]
    expect(spec["result"]["state"], "PASS-FAIL-CLOSED-RESTORED", "result")
    expected_result = {
        "initialNetworkReady": True,
        "faultWritten": True,
        "faultObserved": True,
        "NetworkReadyDuringFault": False,
        "runtimeReadyDuringFault": True,
        "exactRestoreWritten": True,
        "recoveryObserved": True,
        "NetworkReadyAfterRestore": True,
        "runtimeReadyAfterRestore": True,
    }
    for key, expected in expected_result.items():
        expect(spec["result"].get(key), expected, f"result.{key}")
    expected_safety = {
        "directRuntimeMutationPerformed": False,
        "runnerRepairPerformed": False,
        "deletePerformed": False,
        "retryPerformed": False,
        "rawObjectsRetained": False,
        "credentialPayloadRetained": False,
        "postRunReadOnlyPreflight": "PASS-READY-NO-WRITES",
    }
    for key, expected in expected_safety.items():
        expect(spec["safety"].get(key), expected, f"safety.{key}")
    expect(spec["ownership"]["desiredEnablementOwner"], "CAAPH-Helm", "owner")
    expect(
        spec["ownership"]["runnerRole"],
        "observe-correlate-evaluate-fail-closed",
        "runner role",
    )
    expect(spec["ownership"]["runnerOwnsEnablementRepair"], False, "repair owner")
    expect(
        spec["ownership"]["newOpenKubesReconcilerProvenNecessary"],
        False,
        "reconciler necessity",
    )
    publication = spec["publication"]
    expect(publication["state"], "NO-GO", "publication state")
    if any(item for key, item in publication.items() if key.endswith("Published")):
        raise VerificationError("publication claim is not redacted/fail-closed")
    forbidden_key_parts = (
        "resourceversion",
        "kubeconfig",
        "bearertoken",
        "privatekey",
        "secretvalue",
        "endpoint",
    )
    for key_path, item in walk(value):
        normalized = key_path.lower()
        if any(part in normalized for part in forbidden_key_parts):
            raise VerificationError(f"forbidden key category: {key_path}")
        if isinstance(item, str) and (
            "BEGIN PRIVATE KEY" in item or "apiVersion: v1\nclusters:" in item
        ):
            raise VerificationError("credential-like payload detected")
    return digest(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, default=EVIDENCE)
    args = parser.parse_args()
    try:
        print(
            json.dumps(
                {"state": "PASS-REDACTED", "digest": verify(args.evidence.resolve())},
                sort_keys=True,
            )
        )
        return 0
    except (OSError, TypeError, KeyError, yaml.YAMLError, VerificationError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
