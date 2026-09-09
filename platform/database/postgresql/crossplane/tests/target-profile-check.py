#!/usr/bin/env python3
"""Prove target placement resolves exactly once and cannot be supplied by a claimant."""
from __future__ import annotations
import copy, pathlib, subprocess, tempfile, yaml

TESTS = pathlib.Path(__file__).resolve().parent
ROOT = TESTS.parent.parent
XR = TESTS / "xr-ok-robotics.yaml"
COMPOSITION = ROOT / "crossplane/composition.yaml"
FUNCTIONS = TESTS / "functions.yaml"
TARGET = yaml.safe_load((TESTS / "target-ok-robotics.yaml").read_text())


def render(extras: list[dict]) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory(prefix="db-target-") as directory:
        path = pathlib.Path(directory) / "extra.yaml"
        path.write_text(yaml.safe_dump_all(extras, sort_keys=False))
        return subprocess.run([
            "crossplane", "composition", "render", str(XR), str(COMPOSITION), str(FUNCTIONS),
            "--crossplane-version=v2.3.3", f"--required-resources={path}",
        ], cwd=ROOT, check=False, capture_output=True, text=True)


def rejected(name: str, extras: list[dict]) -> None:
    result = render(extras)
    if result.returncode == 0 or "expected exactly one reviewed DatabaseTargetProfile" not in result.stderr:
        raise ValueError(f"{name} did not fail closed: rc={result.returncode} stderr={result.stderr}")
    print(f"NEGATIVE CONTROL PASS: {name}: target profile unresolved")


def main() -> int:
    valid = render([TARGET])
    if valid.returncode:
        raise ValueError(valid.stderr)
    print("PASS: exact target profile composes")
    rejected("missing target profile", [])
    wrong_ref = copy.deepcopy(TARGET); wrong_ref["spec"]["clusterRef"] = "another-cluster"
    rejected("profile spec.clusterRef mismatch", [wrong_ref])
    wrong_name = copy.deepcopy(TARGET); wrong_name["metadata"]["name"] = "another-cluster"
    rejected("profile metadata.name mismatch", [wrong_name])
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
