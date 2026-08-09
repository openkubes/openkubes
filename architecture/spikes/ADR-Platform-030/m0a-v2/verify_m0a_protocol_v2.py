#!/usr/bin/env python3
import argparse
import hashlib
import importlib.util
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parent
SPIKE = ROOT.parent
HARNESS = SPIKE / "harness"
PROTOCOL = ROOT / "m0a-protocol-v2.yaml"
DIGEST = ROOT / "m0a-protocol-v2.sha256"
CANDIDATE = ROOT / "helmchartproxy-v4-candidate.yaml"
INVENTORY = SPIKE / "m0a/caaph-installation-inventory.yaml"
FIXTURE = "sha256:a2ae3437645db5a83426b89d36d00693d2600e4ef20dc1aba2650dcda7f936f6"
R = "sha256:636fe23404ac53109f44d6346534dcf1367ae91c572d5e18bd32cd0a3128a16e"
E = "sha256:2a849d69e9c64344e907c1bce3bb1abf3d8f77217377081a5be055d62c213300"
HISTORICAL = {
    "sha256:67fa2e63bba98d8cc70f680e8df56dea5803c0a0d8c5db81ab78578daacebd9f",
    "sha256:62e4d20fdd352474f4a5d2ea6639d7d63fa494af58b9b4532169bd96437d9f78",
}


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


V4 = _load("ok141_phase_r_v4_m0a", HARNESS / "ok141_phase_r_v4.py")


def sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def verify() -> list[str]:
    errors = []
    protocol = yaml.safe_load(PROTOCOL.read_text())
    candidate = yaml.safe_load(CANDIDATE.read_text())
    inventory = yaml.safe_load(INVENTORY.read_text())
    spec = protocol["spec"]

    fixture = spec["fixture"]
    if (fixture["fixtureDigest"], fixture["R"], fixture["E"]) != (FIXTURE, R, E):
        errors.append("current Fixture/R/E binding mismatch")
    fixture_path = (ROOT / fixture["path"]).resolve()
    if fixture_path != (HARNESS / "fixtures/execution/phase-r-v4.json").resolve():
        errors.append("fixture path does not resolve to Phase-R-v4")
    else:
        try:
            fixture_document = V4.V1.read_yaml_or_json(fixture_path)
            if V4.validate(fixture_document, HARNESS) != FIXTURE:
                errors.append("Phase-R-v4 fixture verification mismatch")
        except (OSError, ValueError, V4.V1.HarnessError) as exc:
            errors.append(f"Phase-R-v4 verification failed: {exc}")
    encoded = V4.V1.jcs(protocol)
    if any(identity in encoded for identity in HISTORICAL):
        errors.append("historical Fixture/R identity reused by M0a v2")

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
    annotations = candidate["metadata"]["annotations"]
    if (
        annotations.get("openkubes.io/intent-revision"),
        annotations.get("openkubes.io/enablement-revision"),
        annotations.get("openkubes.io/execution-fixture"),
    ) != (R, E, FIXTURE):
        errors.append("candidate identity carriers do not match current fixture")
    if spec["candidate"].get("objectDigest") != sha256(CANDIDATE):
        errors.append("candidate object digest mismatch")
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
