#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
CANDIDATE = HERE / "provider-access-materializer-candidate-v1.yaml"
DIGEST = HERE / "provider-access-materializer-candidate-v1.sha256"
SPEC = importlib.util.spec_from_file_location("ok141_provider_access_materializer_verify", HERE / "bounded_provider_access_materializer_v1.py")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def main() -> int:
    try:
        candidate = MODULE.load_candidate(CANDIDATE)
        spec = MODULE.validate_candidate(candidate, CANDIDATE)
        actual = MODULE.V2.sha(CANDIDATE)
        MODULE.expect(DIGEST.read_text().strip(), actual, "candidate digest file")
        plan = MODULE.build_plan(candidate, CANDIDATE)
        if plan["sourceCredentialBytesRead"] or plan["secretPayloadBuilt"] or plan["mutationAuthorized"] or plan["clusterContacted"]:
            raise MODULE.MaterializerError("offline plan crossed a runtime boundary")
        print(json.dumps({
            "candidateDigest": actual,
            "state": spec["state"],
            "operation": plan["operation"],
            "secretIdentity": plan["secretIdentity"],
            "sourceCredentialBytesRead": False,
            "secretPayloadBuilt": False,
            "mutationAuthorized": False,
            "clusterContacted": False,
        }, sort_keys=True))
        return 0
    except (KeyError, OSError, MODULE.MaterializerError, MODULE.SUBMITTER.SubmitterError, MODULE.V2.SubmitterError, TypeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
