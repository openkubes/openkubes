#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
CANDIDATE = HERE / "go1-l-submitter-candidate-v1.yaml"
DIGEST = HERE / "go1-l-submitter-candidate-v1.sha256"
SPEC = importlib.util.spec_from_file_location("ok141_go1_l_submitter_verify", HERE / "bounded_go1_l_submitter_v1.py")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def main() -> int:
    try:
        candidate = MODULE.load_candidate(CANDIDATE)
        reviewed = MODULE.validate_candidate(candidate, CANDIDATE)
        actual = MODULE.sha(CANDIDATE)
        MODULE.expect(DIGEST.read_text().strip(), actual, "candidate digest file")
        plans = [MODULE.build_plan(candidate, CANDIDATE, operation) for operation in reviewed]
        if any(plan["mutationAuthorized"] or plan["clusterContacted"] for plan in plans):
            raise MODULE.SubmitterError("offline plan claims mutation or cluster contact")
        print(json.dumps({
            "candidateDigest": actual,
            "state": candidate["spec"]["state"],
            "operations": len(reviewed),
            "objects": sum(len(item.documents) for item in reviewed.values()),
            "negativeControls": 11,
            "mutationAuthorized": False,
            "clusterContacted": False,
        }, sort_keys=True))
        return 0
    except (KeyError, OSError, MODULE.SubmitterError, MODULE.V1.HarnessError, TypeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
