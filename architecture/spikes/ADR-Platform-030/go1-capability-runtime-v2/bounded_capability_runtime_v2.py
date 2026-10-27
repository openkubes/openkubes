#!/usr/bin/env python3
"""Bounded OK-141 capability execution for the corrected v9 fixture."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


V1 = load_module(
    "ok141_capability_runtime_v1_base",
    SPIKE / "go1-capability-runtime-v1/bounded_capability_runtime_v1.py",
)

IDENTITIES = {
    "P": "sha256:2956184005f4860607e91672fce82164095dee6ebcbe57e5af883951a199c427",
    "R": "sha256:47bb651f6bc0bdb3a7a567efcd4ca4c776f872a63496fa55c2a6aed77d6fa995",
    "FixtureDigest": "sha256:11133538388c3562f135e814ba4560b76d9ffcb0dac6dab5019f7d75c5a71178",
}
SOURCE_REVISION = "c09c18759aeb7526d22106ccb001599f5f06bc4e"
SCRIPT_DIGEST = "sha256:98f41106b7ddc2f7ecffaca9bd9e3c3584d97ab41b169054d8be91ae9cdfb949"
LIVE_AMENDMENT_EVIDENCE_DIGEST = "sha256:252b26bf7a4342f510bc674b5a40ee996b95d628faa4da6d13cfaafb1c043691"


def expect(actual: Any, expected: Any, context: str) -> None:
    if actual != expected:
        raise V1.CapabilityRuntimeError(f"{context} mismatch")


def validate_candidate(path: Path) -> dict[str, Any]:
    candidate = V1.read_json(path)
    expect(candidate.get("kind"), "OK141CapabilityRuntimeCandidate", "kind")
    spec = candidate["spec"]
    expect(spec.get("version"), "ok141-capability-runtime/v2", "version")
    expect(spec.get("state"), "AUTHORIZED-BY-CONTINUOUS-DEV-GRANT", "state")
    expect(spec.get("identities"), IDENTITIES, "v9 identities")
    expect(spec.get("sourceRevision"), SOURCE_REVISION, "source revision")
    expect(spec.get("capability", {}).get("scriptDigest"), SCRIPT_DIGEST, "capability script")
    expect(
        spec.get("predecessor", {}).get("liveAmendmentEvidenceDigest"),
        LIVE_AMENDMENT_EVIDENCE_DIGEST,
        "live amendment evidence",
    )
    if spec.get("predecessor", {}).get("historicalV1RunReused") is not False:
        raise V1.CapabilityRuntimeError("historical failed run reuse boundary missing")

    tool_path = (path.parent / spec["tool"]["path"]).resolve()
    V1.safe_file(tool_path, spec["tool"]["digest"])
    V1.safe_file(Path(spec["tools"]["sharedAndManagementKubectl"]["path"]), spec["tools"]["sharedAndManagementKubectl"]["digest"])
    V1.safe_file(Path(spec["tools"]["workloadKubectl"]["path"]), spec["tools"]["workloadKubectl"]["digest"])
    V1.safe_file(Path(spec["capability"]["scriptPath"]), SCRIPT_DIGEST)
    V1.safe_file(Path(spec["tools"]["bash"]["path"]), spec["tools"]["bash"]["digest"])
    V1.safe_file(Path(spec["tools"]["curl"]["path"]), spec["tools"]["curl"]["digest"])
    V1.safe_file(Path(spec["tools"]["jq"]["path"]), spec["tools"]["jq"]["digest"])
    V1.safe_file(Path(spec["predecessor"]["liveAmendmentEvidencePath"]), LIVE_AMENDMENT_EVIDENCE_DIGEST, 0o600)
    for key in ("sharedKubeconfig", "managementKubeconfig"):
        V1.safe_file(Path(spec["credentials"][key]), spec["credentials"][key + "Digest"], 0o600)
    if len(spec["applications"]) != 3 or len(set(spec["applications"])) != 3:
        raise V1.CapabilityRuntimeError("exactly three unique Applications required")
    if spec["capability"].get("syntheticMutationAndCleanupOwnedByScript") is not True:
        raise V1.CapabilityRuntimeError("synthetic cleanup boundary missing")
    if len(spec["capability"]["runID"]) > 63:
        raise V1.CapabilityRuntimeError("run ID unexpectedly exceeds bounded test input")
    forbidden = spec["authorization"]["forbidden"]
    for required in ("arbitraryMutation", "failureInjection", "broadCleanup", "rawEvidencePublication"):
        if required not in forbidden:
            raise V1.CapabilityRuntimeError("authorization boundary incomplete")
    return candidate


def execute(path: Path) -> dict[str, Any]:
    # Reuse the already-reviewed credential, cleanup, and evidence implementation.
    # Only candidate validation changes for the additive v9 identity.
    validate_candidate(path)
    original = V1.validate_candidate
    V1.validate_candidate = validate_candidate
    try:
        return V1.execute(path)
    finally:
        V1.validate_candidate = original


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "execute"))
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "verify":
            validate_candidate(args.candidate.resolve())
            print(V1.digest(args.candidate.resolve()))
        else:
            if not args.execute:
                raise V1.CapabilityRuntimeError("execution flag required")
            print(json.dumps(execute(args.candidate.resolve()), sort_keys=True))
        return 0
    except (
        V1.CapabilityRuntimeError,
        KeyError,
        OSError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        Exception,
    ) as error:
        print(f"ERROR: {type(error).__name__}: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
