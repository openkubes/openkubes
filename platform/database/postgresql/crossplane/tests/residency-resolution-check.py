#!/usr/bin/env python3
"""Prove residency resolves, and that a dangling reference is not silence (§13 bound 7).

§6.1 described residency as policy plus evidence, but the platform had no policy object and no
resolver, so `dataPolicyRef` would have been a field naming nothing. v1 omitted it rather than
ship it dangling. This asserts the mechanism that replaces that omission.

The case worth the most here is `dangling-reference`: a claim asks for a residency guarantee and
the named policy does not exist. Reporting that as "no constraint" would convert a governance
statement into silence, so it is Failed/DataPolicyUnresolved — we looked, and it is absent, which
is not the same as being unable to look.

The other half is the safety asymmetry: a policy constrains this Database, it never moves data.
`policy-cannot-redirect-storage` asserts that the composed backup store is byte-identical whether
a permissive policy, a prohibitive policy, or no policy at all is in force.
"""

from __future__ import annotations

import argparse
import copy
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml

TESTS_DIR = Path(__file__).resolve().parent
CAPABILITY_DIR = TESTS_DIR.parent.parent
COMPOSITION_PATH = CAPABILITY_DIR / "crossplane/composition.yaml"
XR_PATH = TESTS_DIR / "xr-ok-robotics.yaml"

# The zone the Composition's reviewed registry declares for ok-robotics' store.
PLATFORM_ZONE = "on-prem-de"


class ResidencyError(ValueError):
    pass


def policy(name: str, zones: list[str]) -> dict[str, Any]:
    return {
        "apiVersion": "platform.openkubes.ai/v1alpha1",
        "kind": "DataPolicy",
        "metadata": {"name": name},
        "spec": {"residency": {"allowedZones": zones}},
    }


def render(policy_ref: str | None, extras: list[dict[str, Any]] | None) -> dict[str, Any]:
    xr = yaml.safe_load(XR_PATH.read_text())
    if policy_ref is not None:
        xr["spec"]["dataPolicyRef"] = {"name": policy_ref}
    with tempfile.TemporaryDirectory(prefix="ok-150-residency-") as directory:
        work = Path(directory)
        xr_path = work / "xr.yaml"
        xr_path.write_text(yaml.safe_dump(xr, sort_keys=False))
        command = [
            "crossplane",
            "composition",
            "render",
            str(xr_path),
            str(COMPOSITION_PATH),
            str(TESTS_DIR / "functions.yaml"),
            "--crossplane-version=v2.3.3",
            "--include-full-xr",
        ]
        if extras:
            extra_path = work / "extra.yaml"
            extra_path.write_text(yaml.safe_dump_all(extras, sort_keys=False))
            command.append(f"--extra-resources={extra_path}")
        result = subprocess.run(
            command, cwd=CAPABILITY_DIR, check=False, capture_output=True, text=True
        )
        if result.returncode != 0:
            raise ResidencyError(f"render failed ({result.returncode}): {result.stderr.strip()}")
        docs = [d for d in yaml.safe_load_all(result.stdout) if isinstance(d, dict)]
        databases = [d for d in docs if d.get("kind") == "Database" and "status" in d]
        if len(databases) != 1:
            raise ResidencyError(f"expected one rendered Database, got {len(databases)}")
        return {"database": databases[0], "docs": docs}


def residency_of(rendered: dict[str, Any]) -> tuple[str, str]:
    block = rendered["database"]["status"].get("residency")
    if not isinstance(block, dict):
        raise ResidencyError("no status.residency block was published")
    return block.get("state", ""), block.get("reason", "")


def object_store_of(rendered: dict[str, Any]) -> dict[str, Any]:
    for doc in rendered["docs"]:
        spec = doc.get("spec")
        if not isinstance(spec, dict):
            continue
        manifest = spec.get("forProvider", {}).get("manifest", {})
        if manifest.get("kind") == "ObjectStore":
            return manifest
    raise ResidencyError("no composed ObjectStore found")


def expect(label: str, got: tuple[str, str], want: tuple[str, str]) -> None:
    if got != want:
        raise ResidencyError(f"{label}: expected {want[0]}/{want[1]}, got {got[0]}/{got[1]}")
    print(f"PASS {label}: {got[0]}/{got[1]}")


def positive() -> None:
    permissive = policy("eu-only", [PLATFORM_ZONE, "on-prem-nl"])
    expect(
        "policy permits the platform's zone",
        residency_of(render("eu-only", [permissive])),
        ("Valid", "ResidencyWithinPolicy"),
    )
    expect(
        "no policy requested",
        residency_of(render(None, None)),
        ("Unknown", "NoResidencyPolicyRequested"),
    )

    # The safety asymmetry: placement is platform-side, so the composed store must not vary with
    # the policy in force. If it ever did, a claimant could move data by naming a policy.
    permissive_store = object_store_of(render("eu-only", [permissive]))
    prohibitive_store = object_store_of(
        render("us-only", [policy("us-only", ["us-east-1"])])
    )
    absent_store = object_store_of(render(None, None))
    if not (permissive_store == prohibitive_store == absent_store):
        raise ResidencyError(
            "the composed backup store changed with the policy in force: a claimant could "
            "redirect storage by naming a policy, which inverts the whole authority model"
        )
    print("PASS policy-cannot-redirect-storage: composed ObjectStore identical in all three cases")


def negative_controls() -> None:
    expect(
        "dangling-reference: named policy does not exist",
        residency_of(render("does-not-exist", None)),
        ("Failed", "DataPolicyUnresolved"),
    )
    expect(
        "a DIFFERENT policy exists, not the named one",
        residency_of(render("wanted", [policy("something-else", [PLATFORM_ZONE])])),
        ("Failed", "DataPolicyUnresolved"),
    )
    expect(
        "platform zone outside the policy",
        residency_of(render("us-only", [policy("us-only", ["us-east-1"])])),
        ("Failed", "ResidencyOutsidePolicy"),
    )
    # A resolvable policy that permits nothing relevant must not read as satisfied just because
    # it resolved. Resolution and conformance are different questions.
    expect(
        "policy resolves but permits an unrelated zone only",
        residency_of(render("elsewhere", [policy("elsewhere", ["on-prem-nl"])])),
        ("Failed", "ResidencyOutsidePolicy"),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--negative-controls", action="store_true")
    args = parser.parse_args()
    try:
        if args.negative_controls:
            negative_controls()
        else:
            positive()
    except ResidencyError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
