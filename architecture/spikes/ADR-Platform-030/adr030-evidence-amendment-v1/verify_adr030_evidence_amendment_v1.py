#!/usr/bin/env python3
import argparse
import hashlib
import json
import sys
from pathlib import Path


class AmendmentError(ValueError):
    pass


REQUIRED = (
    "**Status:** Proposed",
    "**Evidence amendment:** 2026-08-20 (OK-141 outcome A for the tested DEV profile)",
    "OK-141 selected **outcome A**",
    "evaluation is sufficient when the evidenced consumers",
    "A continuously published Kubernetes status surface is optional",
    "exactly one narrow OpenKubes status adapter",
    "`ControlPlaneAvailable`",
    "The absence of a configured mechanism is not by itself evidence that OpenKubes must",
    "Create, Scale, Upgrade, Delete, retry, duplicate",
)

FORBIDDEN = (
    "**Status:** Accepted",
    "`ControlPlaneReady`",
    "Exactly one OpenKubes Status Aggregator owns",
    "A Cluster Enablement reconciler and normalized Condition surface must be designed",
)


def digest(path):
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify(path):
    text = Path(path).read_text()
    errors = [f"missing: {value}" for value in REQUIRED if value not in text]
    errors.extend(f"forbidden: {value}" for value in FORBIDDEN if value in text)
    if text.count("`ControlPlaneAvailable`") < 3:
        errors.append("ControlPlaneAvailable is not used consistently")
    if errors:
        raise AmendmentError("; ".join(errors))
    return text


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--adr", type=Path, required=True)
    args = parser.parse_args()
    verify(args.adr)
    print(json.dumps({
        "adrDigest": digest(args.adr),
        "state": "PASS-ADR030-EVIDENCE-AMENDMENT-PROPOSED",
    }, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (AmendmentError, OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
