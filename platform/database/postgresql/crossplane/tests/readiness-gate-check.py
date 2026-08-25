#!/usr/bin/env python3
"""Prove the XR's Crossplane `Ready` condition is gated on OBSERVED state, not on our own YAML.

Before this, the Composition set no composed-resource readiness at all, so every resource
were READY_UNSPECIFIED and the XR reported `Creating` forever — `kubectl wait --for=condition=Ready`
could never return on a database that had been serving for days.

The tempting fix is to gate on each composed resource's own Ready condition. That is wrong here:
every composed resource is a provider-kubernetes `Object` with readiness policy SuccessfulCreate,
so its Ready means "the manifest was applied". Gating on it would publish a Ready that restates our
own declaration back to us — precisely what §13 bound 4 exists to prevent. So exactly one resource
gates, on the CNPG Cluster's observed Ready condition.

WHAT THIS CAN AND CANNOT SEE. function-go-templating CONSUMES the
`gotemplating.fn.crossplane.io/ready` annotation and strips it, so the emitted value is not visible
in `crossplane composition render` output and cannot be asserted directly. This checker therefore
proves the two things that ARE observable, which together pin the behaviour:

  1. the gate is bound to `$clusterReady` and to nothing else, and no resource hardcodes a
     templated gate (static, from the Composition text); and
  2. `$clusterReady` genuinely tracks observed state, shown through `evidence.operational`, which
     is computed from the same variable in the same pass.

The positive end-to-end value is proven on a live cluster instead: after this change ok-robotics
reported `Ready=True/Available` and `kubectl wait --for=condition=Ready` returned 0.
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
OBSERVED_PATH = TESTS_DIR / "observed-ok-robotics-valid.yaml"

GATE_EXPR = 'ternary "True" "False" $clusterReady'
GATED_RESOURCE = "database-cluster"
NON_GATING_COUNT = 13


class GateError(ValueError):
    pass


def composition_text() -> str:
    return COMPOSITION_PATH.read_text()


def render(observed_docs: list[dict[str, Any]] | None) -> tuple[str, str]:
    """Render and return evidence.operational's (state, reason)."""
    with tempfile.TemporaryDirectory(prefix="ok-150-readiness-") as directory:
        argv = [
            "crossplane",
            "composition",
            "render",
            str(XR_PATH),
            str(COMPOSITION_PATH),
            str(TESTS_DIR / "functions.yaml"),
            "--crossplane-version=v2.3.3",
            f"--extra-resources={TESTS_DIR / 'target-ok-robotics.yaml'}",
        ]
        if observed_docs is not None:
            observed = Path(directory) / "observed.yaml"
            observed.write_text(yaml.safe_dump_all(observed_docs, sort_keys=False))
            argv.append(f"--observed-resources={observed}")
        result = subprocess.run(argv, cwd=CAPABILITY_DIR, capture_output=True, text=True)
        if result.returncode != 0:
            raise GateError(f"render failed ({result.returncode}): {result.stderr.strip()}")
        xrs = [
            d
            for d in yaml.safe_load_all(result.stdout)
            if isinstance(d, dict) and d.get("kind") == "Database" and "status" in d
        ]
        if len(xrs) != 1:
            raise GateError(f"expected one rendered Database, got {len(xrs)}")
        operational = xrs[0]["status"]["evidence"]["operational"]
        return operational.get("state", ""), operational.get("reason", "")


def observed_docs() -> list[dict[str, Any]]:
    return [d for d in yaml.safe_load_all(OBSERVED_PATH.read_text()) if d]


def set_cluster_ready(docs: list[dict[str, Any]], status: str) -> list[dict[str, Any]]:
    """Flip the observed CNPG Cluster's Ready condition, leaving everything else alone."""
    out = copy.deepcopy(docs)
    flipped = 0
    for doc in out:
        manifest = doc.get("status", {}).get("atProvider", {}).get("manifest", {})
        if manifest.get("kind") != "Cluster":
            continue
        for condition in manifest.get("status", {}).get("conditions", []):
            if condition.get("type") == "Ready":
                condition["status"] = status
                flipped += 1
    if flipped != 1:
        raise GateError(f"expected exactly one observed Cluster Ready condition, flipped {flipped}")
    return out


def static_checks() -> None:
    text = composition_text()

    if text.count(GATE_EXPR) != 1:
        raise GateError(
            f"the gate must be bound to $clusterReady exactly once, found {text.count(GATE_EXPR)}"
        )
    print(f"PASS gate is bound to observed state: {GATE_EXPR}")

    # Exactly one resource may carry a templated gate, and it must be the CNPG Cluster's Object.
    templated = [
        line.strip()
        for line in text.splitlines()
        if "gotemplating.fn.crossplane.io/ready:" in line and "{{" in line
    ]
    if len(templated) != 1 or "$databaseReadyGate" not in templated[0]:
        raise GateError(f"exactly one templated ready gate expected, got {templated}")
    print("PASS exactly one composed resource gates Ready")

    literal = text.count('gotemplating.fn.crossplane.io/ready: "True"')
    if literal != NON_GATING_COUNT:
        raise GateError(
            f"expected {NON_GATING_COUNT} explicitly non-gating resources, found {literal}"
        )
    print(f"PASS the other {literal} resources are explicitly non-gating")

    # Every non-gating resource must say WHY in the line above it. A bare "True" is indistinguishable
    # from a resource whose readiness nobody thought about, which is how this defect survived.
    lines = text.splitlines()
    unexplained = [
        i + 1
        for i, line in enumerate(lines)
        if line.strip() == 'gotemplating.fn.crossplane.io/ready: "True"'
        and "Non-gating for Ready:" not in lines[i - 1]
    ]
    if unexplained:
        raise GateError(f"non-gating resources without a stated reason, at lines {unexplained}")
    print("PASS every non-gating resource states its reason")

    production_gate = ('(eq $operationalState "Valid") (eq $protectionState "Valid") '
                       '(eq $recoveryState "Valid") (eq $capabilityState "Valid") '
                       '$credentialApplied $credentialRotationSafe')
    if production_gate not in text:
        raise GateError(
            "production serviceReady must require the selected credential applied and proven-safe "
            "previous-credential rotation state"
        )
    print("PASS production serviceReady fails closed on unapplied active or overdue previous credential")


def positive() -> None:
    static_checks()
    state, reason = render(observed_docs())
    if (state, reason) != ("Valid", "ClusterReady"):
        raise GateError(f"a ready cluster must read Valid/ClusterReady, got {state}/{reason}")
    print(f"PASS observed-ready cluster: operational {state}/{reason} -> gate True")


def negative_controls() -> None:
    # 1. The variable the gate reads actually tracks the observed cluster.
    state, reason = render(set_cluster_ready(observed_docs(), "False"))
    if (state, reason) != ("Failed", "ClusterNotReady"):
        raise GateError(
            f"NEGATIVE CONTROL FAILED: a not-ready cluster must read Failed/ClusterNotReady "
            f"(so $clusterReady is false and the gate is False), got {state}/{reason}"
        )
    print(f"NEGATIVE CONTROL PASS: cluster Ready=False -> operational {state}/{reason} -> gate False")

    # 2. Nothing observed at all must not read as ready either.
    state, reason = render(None)
    if state == "Valid":
        raise GateError(
            f"NEGATIVE CONTROL FAILED: with no observed cluster the database must not be "
            f"operational, got {state}/{reason}"
        )
    print(f"NEGATIVE CONTROL PASS: no observed cluster -> operational {state}/{reason} -> gate False")

    # 3. The static checks must actually reject the failure mode they exist to prevent: a gate
    #    hardcoded True would make Ready meaningless again, silently.
    text = composition_text()
    hardcoded = text.replace(
        "gotemplating.fn.crossplane.io/ready: {{ $databaseReadyGate | quote }}",
        'gotemplating.fn.crossplane.io/ready: "True"',
    )
    if hardcoded == text:
        raise GateError("NEGATIVE CONTROL FAILED: could not construct the hardcoded-gate variant")
    original = COMPOSITION_PATH.read_text()
    try:
        COMPOSITION_PATH.write_text(hardcoded)
        try:
            static_checks()
        except GateError:
            print("NEGATIVE CONTROL PASS: a gate hardcoded to True is rejected")
        else:
            raise GateError("NEGATIVE CONTROL FAILED: a gate hardcoded to True was accepted")
    finally:
        COMPOSITION_PATH.write_text(original)

    # 4. Credential application is a production serving precondition, not merely status prose.
    without_credential_gate = composition_text().replace(
        ' (eq $capabilityState "Valid") $credentialApplied $credentialRotationSafe',
        ' (eq $capabilityState "Valid")',
    )
    if without_credential_gate == composition_text():
        raise GateError("NEGATIVE CONTROL FAILED: could not construct credential-gate regression")
    original = COMPOSITION_PATH.read_text()
    try:
        COMPOSITION_PATH.write_text(without_credential_gate)
        try:
            static_checks()
        except GateError:
            print("NEGATIVE CONTROL PASS: production Ready without credential application is rejected")
        else:
            raise GateError("NEGATIVE CONTROL FAILED: production Ready omitted credential application")
    finally:
        COMPOSITION_PATH.write_text(original)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--negative-controls", action="store_true")
    args = parser.parse_args()
    try:
        if args.negative_controls:
            negative_controls()
        else:
            positive()
    except GateError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
