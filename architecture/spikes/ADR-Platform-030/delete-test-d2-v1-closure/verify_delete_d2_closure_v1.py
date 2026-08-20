#!/usr/bin/env python3

import argparse
import hashlib
import json
import sys
from pathlib import Path

import yaml


class ClosureError(ValueError): pass


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(value: object) -> str:
    return "sha256:" + hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def verify(path: Path) -> dict:
    value = yaml.safe_load(path.read_text())
    spec = value.get("spec", {}) if isinstance(value, dict) else {}
    errors = []
    if spec.get("state") != "PASS-D2-ENABLEMENT-QUIESCED-REDACTED": errors.append("state mismatch")
    result = spec.get("result", {})
    for key in ("hcpDeleteRequested", "hcpAbsent", "hrpAbsent", "nativeControllerClosureObserved"):
        if result.get(key) is not True: errors.append(f"{key} not proven")
    for key in ("hrpDeleteRequestedByRunner", "targetResourceDeleteRequestedByRunner", "retryPerformed", "rollbackPerformed", "forceDeletePerformed", "finalizerMutationPerformed", "cleanupPerformed"):
        if result.get(key) is not False: errors.append(f"{key} boundary mismatch")
    if any(v is not False for v in spec.get("boundary", {}).values()): errors.append("downstream delete boundary mismatch")
    if any(v is not False for v in spec.get("redaction", {}).values()): errors.append("redaction mismatch")
    auth = spec.get("authorization", {})
    if auth.get("decision") != "NO-GO" or any(v is not False for k, v in auth.items() if k.endswith("Granted")): errors.append("closure grants authority")
    if errors: raise ClosureError("; ".join(errors))
    return value


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--closure", type=Path, required=True); args = parser.parse_args()
    value = verify(args.closure)
    print(json.dumps({"closureDigest": digest(args.closure), "semanticDigest": canonical(value), "state": "PASS-D2-CLOSURE-REDACTED-NO-GO"}, sort_keys=True))


if __name__ == "__main__":
    try: main()
    except (ClosureError, OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr); raise SystemExit(1)
