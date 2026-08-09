#!/usr/bin/env python3
import argparse
import hashlib
import json
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parent
PROTOCOL = ROOT / "m0b-protocol.yaml"
DIGEST = ROOT / "m0b-protocol.sha256"


def sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def verify() -> list[str]:
    errors = []
    spec = yaml.safe_load(PROTOCOL.read_text())["spec"]
    inventory = json.loads((ROOT / "platform-rendered-inventory.json").read_text())
    if spec["protocolState"] != "BLOCKED":
        errors.append("protocol must remain BLOCKED")
    auth = spec["authorization"]
    if auth["decision"] != "NO-GO" or auth["m0bGranted"] or auth["go1Granted"]:
        errors.append("M0b and GO-1 must remain NO-GO")
    if any(phase["enabled"] for phase in spec["phases"]):
        errors.append("all phases must remain disabled")
    if spec["installation"]["applyEnabled"] or spec["candidates"]["submitEnabled"]:
        errors.append("installation and candidate submission must remain disabled")
    if inventory["sourceProvenance"] != "LOCAL-IGNORED-DEPENDENCIES-NOT-AUTHORITATIVE":
        errors.append("local rendered inventory must not be represented as authoritative")
    if any(item["trackedAtSourceCommit"] for item in inventory["dependencyArtifacts"]):
        errors.append("observed local dependencies unexpectedly represented as tracked")
    if spec["sourceProjection"]["observedInventoryDigest"] != inventory["inventoryDigest"]:
        errors.append("rendered inventory digest mismatch")
    expected = DIGEST.read_text().strip() if DIGEST.exists() else ""
    actual = sha256(PROTOCOL)
    if expected != actual:
        errors.append(f"protocol digest mismatch: expected {expected!r}, got {actual!r}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--print-digest", action="store_true")
    args = parser.parse_args()
    if args.print_digest:
        print(sha256(PROTOCOL))
        return 0
    errors = verify()
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    print(f"PASS: M0b protocol verified ({sha256(PROTOCOL)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
