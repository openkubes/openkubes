#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
CANDIDATE = HERE / "m0b-registration-materializer-candidate-v1.yaml"
DIGEST = HERE / "m0b-registration-materializer-candidate-v1.sha256"
SCRIPT = HERE / "materialize_registration_v1.py"
TEST = HERE / "test_materialize_registration_v1.py"


class VerificationError(ValueError):
    pass


def sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def expect(actual: Any, expected: Any, context: str) -> None:
    if actual != expected:
        raise VerificationError(f"{context}: expected {expected!r}, got {actual!r}")


def resolve(ref: dict[str, Any]) -> Path:
    path = (CANDIDATE.parent / ref["path"]).resolve()
    if SPIKE.resolve() not in path.parents or not path.is_file():
        raise VerificationError(f"invalid reference: {ref['path']}")
    expect(sha(path), ref["digest"], ref["path"])
    return path


def verify(candidate: dict[str, Any] | None = None, run_tests: bool = True) -> dict[str, Any]:
    root = candidate or yaml.safe_load(CANDIDATE.read_text())
    spec = root["spec"]
    expect(spec["state"], "OFFLINE-PROVEN-BLOCKED-NO-GO", "state")
    for ref in spec["references"].values():
        resolve(ref)
    expect(DIGEST.read_text().strip(), sha(CANDIDATE), "candidate digest")
    authorization = spec["authorization"]
    expect(authorization["decision"], "NO-GO", "decision")
    expect(authorization["mutationAuthorized"], False, "mutation")
    if any(value for key, value in authorization.items() if key.endswith("Granted")):
        raise VerificationError("all grants must remain false")
    handling = spec["credentialHandling"]
    expect(handling["runtimeInput"], "stdin-json-only", "runtime input")
    expect(handling["localCredentialFilesCreated"], False, "local credential files")
    expect(handling["shellExecution"], False, "shell execution")
    expect(handling["credentialBytesInGitLogsOrEvidence"], "forbidden", "credential evidence")
    expect(spec["grantValidation"]["antiReplayPersistenceProvidedByMaterializer"], False, "anti-replay claim")
    execution = spec["executionSemantics"]
    expect(execution["operation"], "create-only", "operation")
    expect(execution["objectCount"], 2, "object count")
    expect(execution["partialStatePossible"], True, "partial-state claim")
    if any(execution[key] for key in ("retryAllowed", "rollbackOrCleanupAllowed")):
        raise VerificationError("retry rollback or cleanup became allowed")
    source = SCRIPT.read_text()
    if "shell=False" not in source or "tempfile" in source:
        raise VerificationError("materializer source shell/temp-file boundary mismatch")
    if run_tests:
        completed = subprocess.run(
            [sys.executable, str(TEST)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if completed.returncode or "PASS: 9 materializer checks" not in completed.stdout:
            raise VerificationError("offline materializer tests failed")
    return {
        "state": spec["state"],
        "candidateDigest": sha(CANDIDATE),
        "offlineChecks": 9,
        "mutationAuthorized": False,
        "clusterContacted": False,
    }


def negative_controls() -> None:
    base = yaml.safe_load(CANDIDATE.read_text())
    cases = []
    changed = copy.deepcopy(base)
    changed["spec"]["authorization"]["materializerExecutionGranted"] = True
    cases.append(("premature-grant", changed))
    changed = copy.deepcopy(base)
    changed["spec"]["credentialHandling"]["localCredentialFilesCreated"] = True
    cases.append(("local-secret-file", changed))
    changed = copy.deepcopy(base)
    changed["spec"]["credentialHandling"]["shellExecution"] = True
    cases.append(("shell-enabled", changed))
    changed = copy.deepcopy(base)
    changed["spec"]["grantValidation"]["antiReplayPersistenceProvidedByMaterializer"] = True
    cases.append(("false-anti-replay-claim", changed))
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
