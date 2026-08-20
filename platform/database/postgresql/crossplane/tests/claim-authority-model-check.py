#!/usr/bin/env python3
"""Exercise the exact DatabaseClaim authority model locally.

This does not compile CEL or prove API-server admission. Live admission is a
separately gated server-side matrix; the filename makes that boundary explicit.
"""

from __future__ import annotations

import argparse
import copy
import importlib.util
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.dont_write_bytecode = True
SPEC = importlib.util.spec_from_file_location(
    "claim_policy_check", ROOT / "tests" / "claim-policy-check.py"
)
claim_policy_check = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(claim_policy_check)
EXPECTED = claim_policy_check.EXPECTED
mapping = claim_policy_check.mapping
require = claim_policy_check.require


def policy() -> dict:
    return next(yaml.safe_load_all((ROOT / "claim-admission-policy.yaml").read_text()))


def allowed(candidate: tuple[str, ...], groups: tuple[str, ...], current: dict) -> bool:
    reviewed = mapping(current)
    return reviewed[0] in groups and candidate == reviewed[1:]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--negative-controls", action="store_true")
    args = parser.parse_args()
    current = policy()
    allocation = EXPECTED[1:]
    require(allowed(allocation, (EXPECTED[0],), current), "reviewed exact tuple must be admitted")
    require(allowed(allocation, ("oidc:peer", EXPECTED[0]), current),
            "an unrelated peer group must not cancel the authorized group")

    labels = ("claimNamespace", "claimName", "clusterRef", "namespace",
              "credentialsSecretName", "credentialsSecretNamespace")
    rejected = []
    for index, label in enumerate(labels):
        candidate = list(allocation)
        candidate[index] = f"unauthorized-{index}"
        require(not allowed(tuple(candidate), (EXPECTED[0],), current),
                f"changed {label} must be denied")
        rejected.append(label)
    require(not allowed(allocation, ("oidc:unmapped",), current), "unmapped group must be denied")
    rejected.append("group")

    if args.negative_controls:
        broken = copy.deepcopy(current)
        variables = {v["name"]: v for v in broken["spec"]["variables"]}
        variables["authorizations"]["expression"] = variables["authorizations"]["expression"].replace(
            "'clusterRef': 'ok-robotics'", "'clusterRef': 'unauthorized-2'"
        )
        require(not allowed(allocation, (EXPECTED[0],), broken),
                "mutated policy must reject the formerly valid tuple")
        print("REJECTED [mutated clusterRef]: reviewed tuple no longer matched")
        print("OK: authority-model negative control demonstrated the tuple check can fail")
        return

    print("OK: authority model accepted the exact tuple and rejected near-misses for " + ", ".join(rejected))


if __name__ == "__main__":
    main()
