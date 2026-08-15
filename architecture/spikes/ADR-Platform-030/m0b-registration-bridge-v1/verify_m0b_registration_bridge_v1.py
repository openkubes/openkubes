#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
CANDIDATE = HERE / "m0b-registration-bridge-candidate-v1.yaml"
DIGEST = HERE / "m0b-registration-bridge-candidate-v1.sha256"
SCRIPT = HERE / "registration_bridge_v1.py"
TEST = HERE / "test_registration_bridge_v1.py"


class VerificationError(ValueError):
    pass


def sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def expect(actual: Any, expected: Any, context: str) -> None:
    if actual != expected:
        raise VerificationError(f"{context}: expected {expected!r}, got {actual!r}")


def resolve(reference: dict[str, Any]) -> Path:
    path = (CANDIDATE.parent / reference["path"]).resolve()
    if SPIKE.resolve() not in path.parents or not path.is_file():
        raise VerificationError(f"invalid reference: {reference['path']}")
    expect(sha(path), reference["digest"], reference["path"])
    return path


def verify(candidate: dict[str, Any] | None = None, run_tests: bool = True) -> dict[str, Any]:
    root = candidate or yaml.safe_load(CANDIDATE.read_text())
    spec = root["spec"]
    expect(spec["state"], "OFFLINE-PROVEN-BLOCKED-NO-GO", "state")
    for reference in spec["references"].values():
        resolve(reference)
    expect(DIGEST.read_text().strip(), sha(CANDIDATE), "candidate digest")
    auth = spec["authorization"]
    expect(auth["decision"], "NO-GO", "decision")
    expect(auth["mutationAuthorized"], False, "mutation")
    if any(value for key, value in auth.items() if key.endswith("Granted")):
        raise VerificationError("all grants must remain false")
    pair = spec["pairedGrantModel"]
    expect(pair["reciprocalPairedGrantIDsRequired"], True, "reciprocal pairing")
    expect(pair["maximumRunsShared"], 1, "maximum runs")
    expect(pair["materializerGrantHasIndependentConsumptionReceipt"], False, "materializer receipt claim")
    handling = spec["credentialHandling"]
    expect(handling["tokenUtilityToBridge"], "anonymous-pipe", "token utility transport")
    expect(handling["bridgeToMaterializer"], "subprocess-stdin", "materializer transport")
    expect(handling["newCredentialFilesCreated"], False, "credential files")
    expect(handling["rawChildOutputForwarded"], False, "raw child output")
    expect(handling["shellExecution"], False, "shell execution")
    expect(handling["cryptographicMemoryErasureClaimed"], False, "memory erasure")
    execution = spec["executionSemantics"]
    expect(execution["targetTokenRequestCount"], 1, "TokenRequest count")
    expect(execution["okSharedCreateObjectCount"], 2, "registration object count")
    expect(execution["partialStatePossible"], True, "partial-state claim")
    if execution["retryAllowed"] or execution["rollbackOrCleanupAllowed"]:
        raise VerificationError("retry rollback or cleanup became allowed")
    source = SCRIPT.read_text()
    for marker in ("os.pipe()", "shell=False", "stdin", "stdout=subprocess.PIPE", "stderr=subprocess.PIPE"):
        if marker not in source:
            raise VerificationError(f"bridge source marker missing: {marker}")
    if "tempfile" in source or "shell=True" in source:
        raise VerificationError("bridge source violates shell/temp-file boundary")
    if run_tests:
        completed = subprocess.run(
            [sys.executable, str(TEST)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        if completed.returncode or "PASS: 10 bridge checks" not in completed.stdout:
            raise VerificationError(f"offline bridge tests failed: {completed.stderr}")
    return {
        "state": spec["state"],
        "candidateDigest": sha(CANDIDATE),
        "offlineChecks": 10,
        "mutationAuthorized": False,
        "clusterContacted": False,
    }


def negative_controls() -> None:
    base = yaml.safe_load(CANDIDATE.read_text())
    cases = []
    changed = copy.deepcopy(base)
    changed["spec"]["authorization"]["bridgeExecutionGranted"] = True
    cases.append(("premature-bridge-grant", changed))
    changed = copy.deepcopy(base)
    changed["spec"]["pairedGrantModel"]["maximumRunsShared"] = 2
    cases.append(("multi-run-pair", changed))
    changed = copy.deepcopy(base)
    changed["spec"]["credentialHandling"]["newCredentialFilesCreated"] = True
    cases.append(("credential-file", changed))
    changed = copy.deepcopy(base)
    changed["spec"]["credentialHandling"]["rawChildOutputForwarded"] = True
    cases.append(("raw-child-output", changed))
    changed = copy.deepcopy(base)
    changed["spec"]["executionSemantics"]["retryAllowed"] = True
    cases.append(("unauthorized-retry", changed))
    for name, candidate in cases:
        try:
            verify(candidate, run_tests=False)
        except (VerificationError, KeyError, OSError, TypeError, yaml.YAMLError):
            continue
        raise VerificationError(f"negative control did not fail closed: {name}")


def main() -> int:
    try:
        result = verify()
        negative_controls()
        result["negativeControls"] = 5
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    except (VerificationError, KeyError, OSError, TypeError, yaml.YAMLError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
