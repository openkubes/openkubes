#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
CANDIDATE = HERE / "go1-l-admin-identity-c0-candidate-v1.yaml"
DIGEST = HERE / "go1-l-admin-identity-c0-candidate-v1.sha256"
SPEC = importlib.util.spec_from_file_location("ok141_admin_identity_c0_verify", HERE / "inspect_admin_identity_c0_v1.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def main() -> int:
    try:
        candidate = MODULE.load_candidate(CANDIDATE)
        MODULE.validate_candidate(candidate, CANDIDATE)
        actual = MODULE.sha(CANDIDATE)
        MODULE.expect(DIGEST.read_text().strip(), actual, "candidate digest file")
        result = MODULE.plan(candidate, CANDIDATE)
        if result["credentialInspectionGranted"] or result["clusterContacted"] or result["mutationAuthorized"]:
            raise MODULE.InspectionError("offline plan grants inspection, contact, or mutation")
        print(json.dumps({
            "candidateDigest": actual,
            "state": candidate["spec"]["state"],
            "credentialFiles": len(candidate["spec"]["credentialFiles"]),
            "negativeControls": 8,
            "credentialInspectionGranted": False,
            "clusterContacted": False,
            "mutationAuthorized": False,
        }, sort_keys=True))
        return 0
    except (KeyError, OSError, MODULE.InspectionError, MODULE.V1.HarnessError, TypeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
