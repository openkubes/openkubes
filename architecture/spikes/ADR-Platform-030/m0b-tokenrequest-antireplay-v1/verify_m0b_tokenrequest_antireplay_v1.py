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
CANDIDATE = HERE / "m0b-tokenrequest-antireplay-candidate-v1.yaml"
DIGEST = HERE / "m0b-tokenrequest-antireplay-candidate-v1.sha256"
SCRIPT = HERE / "tokenrequest_antireplay_v1.py"
TEST = HERE / "test_tokenrequest_antireplay_v1.py"


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
    token = spec["tokenRequest"]
    expect(token["expirationSeconds"], 10800, "token expiration")
    expect(token["nativeArgoRotationClaimed"], False, "native rotation")
    expect(token["tokenDigestRetained"], False, "token digest retention")
    replay = spec["antiReplay"]
    expect(replay["receiptCreation"], "O_CREAT-O_EXCL", "receipt creation")
    expect(replay["failedAttemptConsumesGrant"], True, "failed attempt consumption")
    expect(replay["receiptDeletionPreventedByUtility"], False, "receipt deletion claim")
    expect(replay["productionDurabilityClaimed"], False, "production durability")
    handling = spec["credentialHandling"]
    expect(handling["shellExecution"], False, "shell execution")
    expect(handling["regularFileTokenSinkAccepted"], False, "regular-file sink")
    expect(handling["stdoutOrStderrTokenSinkAccepted"], False, "stdio sink")
    expect(handling["cryptographicMemoryErasureClaimed"], False, "memory erasure")
    source = SCRIPT.read_text()
    for marker in ("os.O_EXCL", "shell=False", "require_pipe", "stdout=subprocess.PIPE", "stderr=subprocess.PIPE"):
        if marker not in source:
            raise VerificationError(f"executable boundary marker missing: {marker}")
    for forbidden in ("tokenDigest", "shell=True"):
        if forbidden in source:
            raise VerificationError(f"forbidden executable pattern: {forbidden}")
    if run_tests:
        completed = subprocess.run(
            [sys.executable, str(TEST)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            env={**dict(), "PYTHONDONTWRITEBYTECODE": "1"},
        )
        if completed.returncode or "PASS: 12 TokenRequest/anti-replay checks" not in completed.stdout:
            raise VerificationError(f"offline tests failed: {completed.stderr}")
    return {
        "state": spec["state"],
        "candidateDigest": sha(CANDIDATE),
        "offlineChecks": 12,
        "mutationAuthorized": False,
        "clusterContacted": False,
    }


def negative_controls() -> None:
    base = yaml.safe_load(CANDIDATE.read_text())
    cases = []
    changed = copy.deepcopy(base)
    changed["spec"]["authorization"]["tokenRequestGranted"] = True
    cases.append(("premature-grant", changed))
    changed = copy.deepcopy(base)
    changed["spec"]["tokenRequest"]["nativeArgoRotationClaimed"] = True
    cases.append(("false-rotation", changed))
    changed = copy.deepcopy(base)
    changed["spec"]["antiReplay"]["receiptDeletionPreventedByUtility"] = True
    cases.append(("false-deletion-protection", changed))
    changed = copy.deepcopy(base)
    changed["spec"]["credentialHandling"]["regularFileTokenSinkAccepted"] = True
    cases.append(("regular-file-token-sink", changed))
    changed = copy.deepcopy(base)
    changed["spec"]["credentialHandling"]["cryptographicMemoryErasureClaimed"] = True
    cases.append(("false-memory-erasure", changed))
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
