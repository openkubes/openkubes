#!/usr/bin/env python3
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parent
SPIKE = ROOT.parent
HARNESS = SPIKE / "harness"
PROTOCOL = ROOT / "m0b-protocol-v2.yaml"
DIGEST = ROOT / "m0b-protocol-v2.sha256"
INVENTORY = ROOT / "platform-rendered-inventory-v2.json"
FIXTURE = "sha256:a2ae3437645db5a83426b89d36d00693d2600e4ef20dc1aba2650dcda7f936f6"
R = "sha256:636fe23404ac53109f44d6346534dcf1367ae91c572d5e18bd32cd0a3128a16e"
P = "sha256:b0f25c639a45d895b889997f5ecc2325db45dd5d51b0684998c94d5e17bd47bf"
SOURCE_COMMIT = "b5f7be6a7ddab798f31f32197fcbb9e86a9798b6"
SOURCE_LOCK = "sha256:cdcc6f63b6202a89e90510ddb371cfd3130ff2ebc450336b3ee66e0f1fa85bf5"
HISTORICAL = {
    "sha256:67fa2e63bba98d8cc70f680e8df56dea5803c0a0d8c5db81ab78578daacebd9f",
    "sha256:62e4d20fdd352474f4a5d2ea6639d7d63fa494af58b9b4532169bd96437d9f78",
    "sha256:0dcfbe10f271aeb7e82d94fbad0ff2691dec67f69c7452578662df09a650439b",
}


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


V4 = _load("ok141_phase_r_v4_m0b", HARNESS / "ok141_phase_r_v4.py")


def sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def verify() -> list[str]:
    errors = []
    protocol = yaml.safe_load(PROTOCOL.read_text())
    spec = protocol["spec"]
    inventory = json.loads(INVENTORY.read_text())
    fixture = spec["fixture"]
    if (fixture["fixtureDigest"], fixture["R"], fixture["P"]) != (FIXTURE, R, P):
        errors.append("current Fixture/R/P binding mismatch")
    fixture_path = (ROOT / fixture["path"]).resolve()
    if fixture_path != (HARNESS / "fixtures/execution/phase-r-v4.json").resolve():
        errors.append("fixture path does not resolve to Phase-R-v4")
    else:
        try:
            if V4.validate(V4.V1.read_yaml_or_json(fixture_path), HARNESS) != FIXTURE:
                errors.append("Phase-R-v4 fixture verification mismatch")
        except (OSError, ValueError, V4.V1.HarnessError) as exc:
            errors.append(f"Phase-R-v4 verification failed: {exc}")
    if any(identity in V4.V1.jcs(protocol) for identity in HISTORICAL):
        errors.append("historical Fixture/R/P identity reused by M0b v2")
    if spec["protocolState"] != "BLOCKED":
        errors.append("protocol must remain BLOCKED")
    auth = spec["authorization"]
    if auth["decision"] != "NO-GO" or auth["m0bGranted"] or auth["go1Granted"]:
        errors.append("M0b and GO-1 must remain NO-GO")
    if any(phase["enabled"] for phase in spec["phases"]):
        errors.append("all phases must remain disabled")
    if spec["installation"]["applyEnabled"] or spec["candidates"]["submitEnabled"]:
        errors.append("installation and candidate submission must remain disabled")
    if inventory["sourceProvenance"] != "GIT-TRACKED-TRANSITIVE-CLOSURE-AUTHORITATIVE":
        errors.append("rendered inventory source is not authoritative")
    if len(inventory["dependencyArtifacts"]) != 3 or not all(
        item["trackedAtSourceCommit"] for item in inventory["dependencyArtifacts"]
    ):
        errors.append("exact three-package Git-tracked closure is not proven")
    source = spec["sourceProjection"]
    if source["sourceCommit"] != SOURCE_COMMIT or source["artifactLockDigest"] != SOURCE_LOCK:
        errors.append("authoritative source commit or lock mismatch")
    if inventory["sourceCommit"] != SOURCE_COMMIT or inventory["artifactLock"]["digest"] != SOURCE_LOCK:
        errors.append("inventory source commit or lock mismatch")
    if source["coreRenderedRawDigest"] != inventory["coreRenderedRawDigest"]:
        errors.append("raw render digest mismatch")
    if spec["sourceProjection"]["observedInventoryDigest"] != inventory["inventoryDigest"]:
        errors.append("rendered inventory digest mismatch")
    if spec["sourceProjection"]["inventoryArtifactDigest"] != sha256(INVENTORY):
        errors.append("inventory artifact digest mismatch")
    for claim in spec["candidates"].values():
        if not isinstance(claim, dict) or "path" not in claim:
            continue
        candidate_path = ROOT / claim["path"]
        if claim.get("digest") != sha256(candidate_path):
            errors.append(f"candidate digest mismatch: {claim['path']}")
    blockers = {item["id"]: item["status"] for item in spec["blockers"]}
    if blockers.get("M0B-SOURCE-PROVENANCE") != "CLOSED":
        errors.append("source-provenance blocker must be evidence-closed")
    if any(status != "BLOCKED" for blocker, status in blockers.items() if blocker != "M0B-SOURCE-PROVENANCE"):
        errors.append("all non-provenance blockers must remain BLOCKED")
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
