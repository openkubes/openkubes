#!/usr/bin/env python3
import argparse
import hashlib
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parent
PROTOCOL = ROOT / "m0a-protocol.yaml"
DIGEST = ROOT / "m0a-protocol.sha256"
CANDIDATE = ROOT / "helmchartproxy-v3-candidate.yaml"
INVENTORY = ROOT / "caaph-installation-inventory.yaml"


def sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def verify() -> list[str]:
    errors = []
    protocol = yaml.safe_load(PROTOCOL.read_text())
    candidate = yaml.safe_load(CANDIDATE.read_text())
    inventory = yaml.safe_load(INVENTORY.read_text())
    spec = protocol["spec"]

    if spec["protocolState"] != "BLOCKED":
        errors.append("protocol must remain BLOCKED")
    auth = spec["authorization"]
    if auth["decision"] != "NO-GO" or auth["m0aGranted"] or auth["go1Granted"]:
        errors.append("M0a and GO-1 must remain NO-GO")
    if any(phase["enabled"] for phase in spec["phases"]):
        errors.append("all phases must remain disabled")
    if spec["installation"]["applyEnabled"] or spec["candidate"]["submitEnabled"]:
        errors.append("installation and candidate submission must remain disabled")
    if candidate["metadata"]["annotations"]["openkubes.io/candidate-status"] != "blocked-no-go":
        errors.append("candidate must remain blocked-no-go")
    if inventory["spec"]["authorization"]["applyEnabled"]:
        errors.append("installation inventory must remain non-applicable")
    resolution = spec["artifactResolution"]
    if resolution["chartContentDigest"] != resolution["fixtureArtifactDigest"]:
        errors.append("OCI content and fixture artifact digests differ")
    if resolution["caaphDigestFieldAvailable"]:
        errors.append("CAAPH v0.6.4 must not be represented as digest-enforcing")
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
    print(f"PASS: M0a protocol verified ({sha256(PROTOCOL)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
