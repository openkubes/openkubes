#!/usr/bin/env python3
"""Fail-closed verifier for redacted OK-141 D1-v3 closure evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import yaml


class ClosureError(ValueError):
    pass


ORDER = ["application-dashboards", "application-alerting", "application-core", "registration-secret", "app-project"]


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def verify(path: Path) -> dict:
    value = yaml.safe_load(path.read_text())
    if not isinstance(value, dict):
        raise ClosureError("expected one YAML object")
    spec = value.get("spec", {})
    errors: list[str] = []
    if spec.get("state") != "PASS-D1-GITOPS-QUIESCED-REDACTED":
        errors.append("state mismatch")
    execution = spec.get("execution", {})
    if execution.get("plannedDeleteCount") != 5 or execution.get("completedDeleteCount") != 5:
        errors.append("delete count mismatch")
    if execution.get("orderedTargets") != ORDER or execution.get("liveResourceVersionPreconditionUsedCount") != 5:
        errors.append("ordered precondition mismatch")
    for key in ("allTargetsAbsent", "immutableUIDBindingUsed", "applicationFinalizersAbsentAtDelete", "backgroundPropagationUsed"):
        if execution.get(key) is not True:
            errors.append(f"{key} not proven")
    for key in ("retryPerformed", "rollbackPerformed", "forceDeletePerformed", "finalizerMutationPerformed", "cleanupPerformed"):
        if execution.get(key) is not False:
            errors.append(f"{key} boundary mismatch")
    if any(v is not False for v in spec.get("boundary", {}).values()):
        errors.append("downstream delete boundary mismatch")
    if any(v is not False for v in spec.get("redaction", {}).values()):
        errors.append("redaction boundary mismatch")
    auth = spec.get("authorization", {})
    if auth.get("decision") != "NO-GO" or any(v is not False for k, v in auth.items() if k.endswith("Granted")):
        errors.append("closure grants authority")
    rendered = json.dumps(value, sort_keys=True)
    if any(marker in rendered for marker in ('"uid":', '"resourceVersion":', '"endpoint":', '"token":', '"kubeconfig":')):
        errors.append("forbidden raw field marker")
    if errors:
        raise ClosureError("; ".join(errors))
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--closure", type=Path, required=True)
    args = parser.parse_args()
    value = verify(args.closure.resolve())
    print(json.dumps({"closureDigest": digest(args.closure.resolve()), "semanticDigest": canonical_digest(value), "state": "PASS-D1-V3-CLOSURE-REDACTED-NO-GO"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ClosureError, OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
