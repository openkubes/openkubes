#!/usr/bin/env python3
"""Prove §5.1's conditions are a SET, not a pipeline (PR #259 review finding 1).

The claim under test is that `RecoveryAssured` and `CapabilityConformant` attest different
subjects and carry different temporal semantics, so any combination of their states is coherent.
That was documented on #259 as prose; the machinery to assert it lands with OK-150, so this is
where it becomes checkable.

The assertion that matters is the NEGATIVE direction: `CapabilityConformant=Failed` coexisting
with `RecoveryAssured=Valid`. If the composition cannot produce that pair, §5.1 has silently
become a pipeline — capability failure would be suppressing recovery evidence, or recovery would
be gating capability — and no amount of passing-case testing would reveal it.

What makes the pair legitimate rather than accidental is that the capability probe is
side-effect-free: because its DDL rolls back, the in-restore run cannot mutate the very cluster
whose restorability the recovery artifact attests. Residue therefore makes an artifact
inadmissible, which is asserted here as the fourth case rather than left as a comment.
"""

from __future__ import annotations

import argparse
import copy
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

TESTS_DIR = Path(__file__).resolve().parent
CAPABILITY_DIR = TESTS_DIR.parent.parent
COMPOSITION_PATH = CAPABILITY_DIR / "crossplane/composition.yaml"
XR_PATH = TESTS_DIR / "xr-ok-robotics.yaml"
OBSERVED_PATH = TESTS_DIR / "observed-ok-robotics-valid.yaml"
RESTORE_FIXTURE = TESTS_DIR / "restoreverified-ok-robotics.yaml"
CAPABILITY_FIXTURE = TESTS_DIR / "capabilityverified-pgvector.yaml"
ADR_RELATIVE = "architecture/decisions/ADR-Platform-032-openkubes-dbaas.md"
ADR_PATH = next(
    (p / ADR_RELATIVE for p in TESTS_DIR.parents if (p / ADR_RELATIVE).is_file()),
    TESTS_DIR / ADR_RELATIVE,
)

RUNNING_IMAGE = (
    "ghcr.io/cloudnative-pg/postgresql:18.6-202608131513-minimal-trixie"
    "@sha256:e488b1434919f455f2ee4e18a181ce9b33f34cdd8dfb821126855486bce6ad34"
)
RUNNING_DIGEST = "sha256:e488b1434919f455f2ee4e18a181ce9b33f34cdd8dfb821126855486bce6ad34"
CLUSTER_UID = "1c47d9d1-2cc2-4619-8265-a1598cb22274"
RFC3339 = "%Y-%m-%dT%H:%M:%SZ"


class IndependenceError(ValueError):
    pass


def observed(with_pgvector: bool, with_image_digest: bool) -> list[dict[str, Any]]:
    docs = copy.deepcopy([d for d in yaml.safe_load_all(OBSERVED_PATH.read_text()) if d])
    for doc in docs:
        manifest = doc.get("status", {}).get("atProvider", {}).get("manifest", {})
        if manifest.get("kind") != "Cluster":
            continue
        info = manifest["status"]["pgDataImageInfo"]
        if with_pgvector:
            info["extensions"] = [{"name": "vector"}]
        else:
            # The extension is genuinely absent, which is what drives
            # CapabilityConformant=Failed/RequestedCapabilityAbsent.
            info.pop("extensions", None)
        if with_image_digest:
            info["image"] = RUNNING_IMAGE
    return docs


def restore_artifact() -> dict[str, Any]:
    """The admitted RestoreVerified from the shared fixture (first doc; the second is a decoy).

    Its timing is re-stamped relative to NOW. The fixture carries a fixed completedAt, and recovery
    evidence ages out — so a test that used it verbatim passed until the wall clock crossed the
    validity window and then failed for a reason unrelated to what it asserts. That happened:
    once recovery validity became its own 7-day quantity, a 2026-08-17 fixture expired mid-session
    and the independence check reported Pending/FreshVerificationPending. Independence has nothing
    to do with the calendar, so the fixture must not depend on it.
    """
    docs = [d for d in yaml.safe_load_all(RESTORE_FIXTURE.read_text()) if d]
    artifact = copy.deepcopy(docs[0])
    completed = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=1)
    artifact["spec"]["timing"]["startedAt"] = (completed - timedelta(minutes=2)).strftime(RFC3339)
    artifact["spec"]["timing"]["completedAt"] = completed.strftime(RFC3339)
    return artifact


def capability_artifact(residue: bool = False) -> dict[str, Any]:
    artifact = copy.deepcopy(yaml.safe_load(CAPABILITY_FIXTURE.read_text()))
    xr = yaml.safe_load(XR_PATH.read_text())
    artifact["metadata"]["labels"] = {"platform.openkubes.ai/source-cluster": "ok-robotics"}
    artifact["spec"]["databaseRef"].update(name=xr["metadata"]["name"], uid=xr["metadata"]["uid"])
    artifact["spec"]["clusterRef"].update(
        namespace="database-ok-robotics", name="ok-robotics", uid=CLUSTER_UID
    )
    artifact["spec"]["delivery"].update(imageName=RUNNING_IMAGE, imageDigest=RUNNING_DIGEST)
    artifact["spec"]["probeDigest"] = "sha256:" + "4" * 64
    if residue:
        for check in artifact["spec"]["checks"]:
            if check["name"] == "probe-left-no-residue":
                check["observed"]["probeTablesRemaining"] = 2
    return artifact


def approval_for(artifact: dict[str, Any]) -> dict[str, Any]:
    """Approve the method behind a RestoreVerified (§7, as amended).

    Independence has nothing to do with approval, but recovery evidence is now inadmissible without
    it — so a test asserting the two conditions are independent has to supply one, or it measures
    the approval gate instead of independence. restore-approval-check.py owns the approval paths.
    """
    return {
        "apiVersion": "platform.openkubes.ai/v1alpha1",
        "kind": "VerificationProfile",
        "metadata": {"name": f"approved-{artifact['metadata']['name']}"},
        "spec": {
            "checkProfileDigest": artifact["spec"]["checkProfileDigest"],
            "verifierVersion": artifact["spec"]["verifierVersion"],
            "checks": [c["name"] for c in artifact["spec"]["checks"]],
            "approval": {
                "approvedBy": "oidc:database-restore-verifiers",
                "approvedAt": "2026-08-24T00:00:00Z",
                "rationale": (
                    "Fixture approval so the independence assertions exercise independence rather "
                    "than the approval gate."
                ),
            },
        },
    }


def render(docs: list[dict[str, Any]], extras: list[dict[str, Any]]) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="ok-150-independence-") as directory:
        work = Path(directory)
        (work / "observed.yaml").write_text(yaml.safe_dump_all(docs, sort_keys=False))
        command = [
            "crossplane",
            "composition",
            "render",
            str(XR_PATH),
            str(COMPOSITION_PATH),
            str(TESTS_DIR / "functions.yaml"),
            "--crossplane-version=v2.3.3",
            "--include-full-xr",
            f"--observed-resources={work / 'observed.yaml'}",
        ]
        if extras:
            (work / "extra.yaml").write_text(yaml.safe_dump_all(extras, sort_keys=False))
            command.append(f"--extra-resources={work / 'extra.yaml'}")
        result = subprocess.run(
            command, cwd=CAPABILITY_DIR, check=False, capture_output=True, text=True
        )
        if result.returncode != 0:
            raise IndependenceError(f"render failed ({result.returncode}): {result.stderr.strip()}")
        databases = [
            d
            for d in yaml.safe_load_all(result.stdout)
            if isinstance(d, dict) and d.get("kind") == "Database" and "status" in d
        ]
        if len(databases) != 1:
            raise IndependenceError(f"expected one rendered Database, got {len(databases)}")
        return databases[0]["status"]["evidence"]


def pair(evidence: dict[str, Any]) -> tuple[tuple[str, str], tuple[str, str]]:
    recovery = evidence["recovery"]
    capability = evidence["capability"]
    return (
        (recovery.get("state", ""), recovery.get("reason", "")),
        (capability.get("state", ""), capability.get("reason", "")),
    )


def failed_capability_with_valid_recovery() -> None:
    """THE case. If this pair is unreachable, §5.1 is a pipeline."""
    recovery, capability = pair(
        render(observed(with_pgvector=False, with_image_digest=False), (lambda a: [a, approval_for(a)])(restore_artifact()))
    )
    if recovery[0] != "Valid":
        raise IndependenceError(
            f"recovery should be Valid from the admitted artifact, got {recovery[0]}/{recovery[1]}"
            " — the fixture or its identity binding drifted, so this test proves nothing"
        )
    if capability[0] != "Failed":
        raise IndependenceError(
            f"capability should be Failed with the extension absent, got "
            f"{capability[0]}/{capability[1]}"
        )
    print(
        f"PASS Failed capability coexists with Valid recovery: "
        f"recovery {recovery[0]}/{recovery[1]}, capability {capability[0]}/{capability[1]}"
    )


def valid_capability_with_unproven_recovery() -> None:
    """The converse. Capability proven while recovery has no artifact at all."""
    recovery, capability = pair(
        render(observed(with_pgvector=True, with_image_digest=True), [capability_artifact()])
    )
    if capability != ("Valid", "CapabilityProvenByFunction"):
        raise IndependenceError(
            f"capability should be proven from its artifact, got {capability[0]}/{capability[1]}"
        )
    if recovery[0] == "Valid":
        raise IndependenceError(
            "recovery reads Valid with no RestoreVerified admitted — a capability proof is being "
            "credited as recovery evidence, which is the pipeline collapse in the other direction"
        )
    print(
        f"PASS Valid capability coexists with unproven recovery: "
        f"recovery {recovery[0]}/{recovery[1]}, capability {capability[0]}/{capability[1]}"
    )


def both_valid_together() -> None:
    """Neither excludes the other: the set's all-Valid corner must also be reachable."""
    recovery, capability = pair(
        render(
            observed(with_pgvector=True, with_image_digest=True),
            (lambda a: [a, approval_for(a), capability_artifact()])(restore_artifact()),
        )
    )
    if recovery[0] != "Valid" or capability[0] != "Valid":
        raise IndependenceError(
            f"both dimensions should reach Valid together, got recovery {recovery[0]}/{recovery[1]}"
            f" and capability {capability[0]}/{capability[1]}"
        )
    print(f"PASS both Valid together: {recovery[1]} + {capability[1]}")


def check_probe_sets_are_typed_and_disjoint() -> None:
    """Review finding 1, box 3: the probe sets must be typed, closed, and NOT the same set.

    The ADR used to say `RecoveryAssured` asserts "schema and capability conformance probes"
    passed — claiming something the typed evidence never carried, since RestoreVerified enumerates
    five schema/content checks and no capability probe. Two conditions with two artifacts and two
    closed enums is what makes them independent structurally rather than by convention, so the
    enums must stay disjoint: a shared check name would mean one verdict feeding both.
    """
    def checks_schema(path: Path) -> dict:
        crd = yaml.safe_load(path.read_text())
        spec = crd["spec"]["versions"][0]["schema"]["openAPIV3Schema"]["properties"]["spec"]
        return spec["properties"]["checks"]

    restore = checks_schema(CAPABILITY_DIR / "crossplane/restoreverified-crd.yaml")
    capability = checks_schema(CAPABILITY_DIR / "crossplane/capabilityverified-crd.yaml")

    for label, schema in (("RestoreVerified", restore), ("CapabilityVerified", capability)):
        names = schema["items"]["properties"]["name"].get("enum")
        assert names, f"{label}.checks[].name must be a closed enum, not free text"
        assert schema.get("minItems") == schema.get("maxItems") == len(names), (
            f"{label}.checks must be exactly the enumerated set (minItems == maxItems == "
            f"{len(names)}), so a changed probe set cannot be recorded under the old contract"
        )

    restore_names = set(restore["items"]["properties"]["name"]["enum"])
    capability_names = set(capability["items"]["properties"]["name"]["enum"])
    shared = sorted(restore_names & capability_names)
    assert not shared, (
        f"the two probe sets share check name(s) {shared}: one verdict would then feed both "
        "conditions, which is the pipeline coupling §5.1 rules out"
    )

    adr = ADR_PATH.read_text()
    missing = sorted(name for name in restore_names if name not in adr)
    assert not missing, (
        f"the ADR does not name the enumerated restore probes {missing}; finding 1 asks for them "
        "to be inspectable, and a set named nowhere cannot be reviewed for weakening"
    )
    assert "asserts NO capability conformance" in adr, (
        "the ADR must state that RecoveryAssured asserts no capability conformance; without it the "
        "independence is a convention rather than a decision"
    )
    print(
        f"PASS probe sets: {len(restore_names)} restore + {len(capability_names)} capability "
        "checks, both closed, disjoint, and named in the ADR"
    )


def structural_independence() -> None:
    """Neither admissibility expression may read the other's state.

    Behavioural cases can pass by luck on one fixture; this reads the composition itself, so a
    future edit that couples the two is caught even if no fixture happens to expose it.
    """
    source = COMPOSITION_PATH.read_text()

    def expression(start_marker: str) -> str:
        # The chain runs from its marker to the next top-level `{{- if`, which is the branch
        # that consumes the result.
        tail = source[source.index(start_marker) :]
        return tail[: tail.index("\n            {{- if ")]

    capability_expr = expression("{{- $capabilityAdmissible := and")
    recovery_expr = expression("{{- $admissible := and")

    leaked = [
        token
        for token in ("$recoveryState", "$recoveryReason", "$selectedRestore", "RestoreVerified")
        if token in capability_expr
    ]
    if leaked:
        raise IndependenceError(
            f"capability admissibility reads recovery state {leaked}: the conditions are coupled, "
            "so one can suppress the other"
        )
    leaked = [
        token
        for token in (
            "$capabilityState",
            "$capabilityReason",
            "$selectedCapability",
            "CapabilityVerified",
        )
        if token in recovery_expr
    ]
    if leaked:
        raise IndependenceError(
            f"recovery admissibility reads capability state {leaked}: the conditions are coupled"
        )
    print("PASS structural: neither admissibility expression reads the other's state")


def residue_keeps_the_pair_honest() -> None:
    """Side-effect-freeness is what makes the coexistence legitimate, so it is asserted.

    A probe that left tables behind could have mutated the cluster whose restorability the
    recovery artifact attests. Such an artifact must not prove capability — and must not disturb
    recovery either, which is what keeps this an independence property rather than a trade.
    """
    recovery, capability = pair(
        render(
            observed(with_pgvector=True, with_image_digest=True),
            (lambda a: [a, approval_for(a), capability_artifact(residue=True)])(restore_artifact()),
        )
    )
    if capability[0] == "Valid":
        raise IndependenceError(
            "an artifact from a probe that left tables behind proved capability; residue is an "
            "admissibility term precisely because such a run may have mutated the restored cluster"
        )
    if recovery[0] != "Valid":
        raise IndependenceError(
            f"an inadmissible capability artifact disturbed recovery ({recovery[0]}/{recovery[1]}): "
            "that is coupling, not independence"
        )
    print(
        f"PASS residue: capability {capability[0]}/{capability[1]} while recovery stays "
        f"{recovery[0]}/{recovery[1]}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--negative-controls", action="store_true")
    args = parser.parse_args()
    try:
        if args.negative_controls:
            failed_capability_with_valid_recovery()
            residue_keeps_the_pair_honest()
        else:
            check_probe_sets_are_typed_and_disjoint()
            structural_independence()
            valid_capability_with_unproven_recovery()
            both_valid_together()
    except IndependenceError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
