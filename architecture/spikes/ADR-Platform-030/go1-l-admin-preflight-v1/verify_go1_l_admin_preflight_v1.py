#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
CANDIDATE = HERE / "go1-l-admin-preflight-candidate-v1.yaml"
DIGEST = HERE / "go1-l-admin-preflight-candidate-v1.sha256"
SPEC = importlib.util.spec_from_file_location("ok141_admin_preflight_verify", HERE / "bounded_admin_preflight_v1.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def main() -> int:
    try:
        candidate = MODULE.load_candidate(CANDIDATE)
        MODULE.validate_candidate(candidate, CANDIDATE)
        actual = MODULE.sha(CANDIDATE)
        MODULE.expect(DIGEST.read_text().strip(), actual, "candidate digest file")
        plans = [MODULE.build_plan(candidate, CANDIDATE, item["id"]) for item in candidate["spec"]["operations"]]
        if any(plan["credentialUseGranted"] or plan["clusterContacted"] or plan["mutationAuthorized"] for plan in plans):
            raise MODULE.PreflightError("offline plan claims credential use, cluster contact, or mutation")
        print(json.dumps({
            "candidateDigest": actual,
            "state": candidate["spec"]["state"],
            "operations": len(plans),
            "queries": sum(plan["queryCount"] for plan in plans),
            "negativeControls": 15,
            "credentialUseGranted": False,
            "clusterContacted": False,
            "mutationAuthorized": False,
        }, sort_keys=True))
        return 0
    except (KeyError, OSError, MODULE.PreflightError, MODULE.V1.HarnessError, TypeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
