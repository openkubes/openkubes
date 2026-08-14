#!/usr/bin/env python3
"""Materialize the private cleanup binding from an additive R0-v3 snapshot."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import yaml


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("materialize_recovery_binding_v1_for_v2", HERE / "materialize_recovery_binding_v1.py")
BASE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(BASE)
BindingError = BASE.BindingError
OBSERVATION_CANDIDATE_DIGEST = "sha256:cc16cd21ae73948b1db83d1fa3490d545fd1b0616ecf81776281b36aa21df435"
BASE.OBSERVATION_CANDIDATE_DIGEST = OBSERVATION_CANDIDATE_DIGEST


def validate_snapshot(evidence_path: Path):
    return BASE.validate_snapshot(evidence_path)


def materialize(evidence_path: Path):
    binding = BASE.materialize(evidence_path)
    binding["metadata"]["name"] = "ok141-go1-l-recovery-runtime-binding-v2"
    binding["spec"]["bindingVersion"] = "ok141-go1-l-recovery-runtime-binding/v2"
    binding["spec"]["sourceObservationCandidateDigest"] = OBSERVATION_CANDIDATE_DIGEST
    return binding


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify-evidence", "materialize"))
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        path = args.evidence.resolve()
        if args.command == "verify-evidence":
            validate_snapshot(path)
            result = {"evidenceDigest": BASE.sha(path), "bindingWritten": False}
        else:
            if args.output is None or not str(args.output).startswith("/private/tmp/"):
                raise BindingError("private /private/tmp output is required")
            output = args.output.resolve()
            if output.exists():
                raise BindingError("binding output already exists")
            output.write_text(yaml.safe_dump(materialize(path), sort_keys=False))
            output.chmod(0o600)
            result = {"evidenceDigest": BASE.sha(path), "bindingDigest": BASE.sha(output), "bindingWritten": True}
        print(json.dumps(result, sort_keys=True))
        return 0
    except (BindingError, KeyError, OSError, TypeError, ValueError, json.JSONDecodeError, yaml.YAMLError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
