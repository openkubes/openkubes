#!/usr/bin/env python3
"""Prove CapabilityConformant is decided by a probe, and that every admissibility term bites.

Bound 4's whole point is that a declaration echoed back in status is not evidence: on ok-robotics
`status.pgDataImageInfo` carries a pinned pgvector digest on a cluster where `CREATE EXTENSION
vector` fails. So this renders the real Composition against real observed state and asserts:

  1. with an admitted, matching `CapabilityVerified`  -> Valid/CapabilityProvenByFunction
  2. with the declaration alone                        -> Pending/CapabilityProbePending, never Valid
  3. with each admissibility term broken in turn       -> NOT Valid

Case 3 is the part that earns its keep. A selector that accepted any artifact carrying the right
kind would pass case 1 and case 2 and still certify a proof taken from another database, or against
an image that has since been replaced. Each tamper below therefore removes exactly one term.
"""

from __future__ import annotations

import argparse
import copy
import re
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
ARTIFACT_PATH = TESTS_DIR / "capabilityverified-pgvector.yaml"

# The image digest ok-robotics actually reports for the running instance, so the digest term is
# exercised against a real value rather than a placeholder.
RUNNING_IMAGE = (
    "ghcr.io/cloudnative-pg/postgresql:18.6-202608131513-minimal-trixie"
    "@sha256:e488b1434919f455f2ee4e18a181ce9b33f34cdd8dfb821126855486bce6ad34"
)
RUNNING_DIGEST = "sha256:e488b1434919f455f2ee4e18a181ce9b33f34cdd8dfb821126855486bce6ad34"


class CapabilityError(ValueError):
    pass


class RenderedYamlLoader(yaml.SafeLoader):
    """Keep date-time fields as strings, including deliberately invalid controls."""


RenderedYamlLoader.yaml_implicit_resolvers = {
    key: [r for r in resolvers if r[0] != "tag:yaml.org,2002:timestamp"]
    for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def load_all(path: Path) -> list[dict[str, Any]]:
    return [d for d in yaml.safe_load_all(path.read_text()) if isinstance(d, dict)]


def observed_with_running_image() -> list[dict[str, Any]]:
    """The shared observed fixture, plus the image digest CNPG reports when it resolves one.

    The committed fixture deliberately has no `pgDataImageInfo.image`, which is why capability
    renders Pending there: with no running digest, no proof can bind to anything. Injecting it
    here keeps one observed fixture rather than a near-duplicate that could drift from it.
    """
    docs = copy.deepcopy(load_all(OBSERVED_PATH))
    for doc in docs:
        manifest = doc.get("status", {}).get("atProvider", {}).get("manifest", {})
        if manifest.get("kind") == "Cluster":
            manifest["status"]["pgDataImageInfo"]["image"] = RUNNING_IMAGE
            return docs
    raise CapabilityError("observed fixture has no CNPG Cluster manifest")


def matching_artifact() -> dict[str, Any]:
    """The fixture, re-bound to the render's XR and observed Cluster.

    LIMIT OF THIS TEST, and it is not small: `crossplane composition render` does not use the
    uid in the XR file. It synthesises a deterministic v5 UUID from the XR name and hands THAT
    to the function as `.observed.composite.resource.metadata.uid`, while `--include-full-xr`
    echoes the file's uid — which makes the discrepancy invisible unless you print what the
    function sees. Measured 2026-08-20: an artifact bound to the LIVE Database uid
    (a6b4b2ff-…) was rejected here because the function saw eee6a418-… instead.

    So the positive case below binds the fixture's uid, which is itself the render-synthesised
    value. That exercises the uid TERM (tampering with it is rejected, see the tampers) but it
    does NOT prove binding against a real cluster identity. Only an admitted artifact selected
    by the live composite can do that, and it is why local green here is not delivered-capability
    evidence.

    The committed fixture points at the bundled-image proof cluster on purpose — it is not
    evidence for this Database. Re-binding here is what makes it admissible, and it is done
    explicitly so the difference between "a real proof" and "a proof for THIS database" stays
    visible in the test rather than hidden in a fixture.
    """
    artifact = copy.deepcopy(yaml.safe_load(ARTIFACT_PATH.read_text()))
    xr = yaml.safe_load(XR_PATH.read_text())
    artifact["metadata"]["labels"] = {"platform.openkubes.ai/source-cluster": "ok-robotics"}
    artifact["spec"]["databaseRef"].update(name=xr["metadata"]["name"], uid=xr["metadata"]["uid"])
    artifact["spec"]["clusterRef"].update(
        namespace="database-ok-robotics",
        name="ok-robotics",
        uid="1c47d9d1-2cc2-4619-8265-a1598cb22274",
    )
    artifact["spec"]["delivery"].update(imageName=RUNNING_IMAGE, imageDigest=RUNNING_DIGEST)
    artifact["spec"]["probeDigest"] = "sha256:" + "1" * 64
    return artifact


def check_named(artifact: dict[str, Any], name: str) -> dict[str, Any]:
    return next(c for c in artifact["spec"]["checks"] if c["name"] == name)


def render(artifacts: list[dict[str, Any]] | None) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="ok-150-capability-") as directory:
        work = Path(directory)
        observed_path = work / "observed.yaml"
        observed_path.write_text(yaml.safe_dump_all(observed_with_running_image(), sort_keys=False))
        command = [
            "crossplane",
            "composition",
            "render",
            str(XR_PATH),
            str(COMPOSITION_PATH),
            str(TESTS_DIR / "functions.yaml"),
            "--crossplane-version=v2.3.3",
            "--include-full-xr",
            f"--observed-resources={observed_path}",
        ]
        extra_path = work / "extra.yaml"
        extras = [yaml.safe_load((TESTS_DIR / "target-ok-robotics.yaml").read_text())]
        if artifacts is not None:
            extras.extend(artifacts)
        extra_path.write_text(yaml.safe_dump_all(extras, sort_keys=False))
        command.append(f"--extra-resources={extra_path}")
        result = subprocess.run(
            command, cwd=CAPABILITY_DIR, check=False, capture_output=True, text=True
        )
        if result.returncode != 0:
            raise CapabilityError(f"render failed ({result.returncode}): {result.stderr.strip()}")
        docs = [
            d
            for d in yaml.load_all(result.stdout, Loader=RenderedYamlLoader)
            if isinstance(d, dict)
        ]
        databases = [d for d in docs if d.get("kind") == "Database" and "status" in d]
        if len(databases) != 1:
            raise CapabilityError(f"expected one rendered Database, got {len(databases)}")
        return databases[0]


def capability_of(database: dict[str, Any]) -> tuple[str, str, str]:
    evidence = database["status"]["evidence"]["capability"]
    return evidence.get("state", ""), evidence.get("reason", ""), evidence.get("evidenceRef", "")


def check_extension_name_agreement() -> None:
    """The reader, the composed spec and the fixture must all name the extension identically.

    This is the defect's root cause, and it was invisible locally by construction: the Composition
    composed `pgvector`, the status reader matched `vector`, and the observed fixture also said
    `vector` — so the fixture agreed with the CODE instead of with the cluster, and every local
    test passed while $pgvectorObserved could never be true on a real cluster. Measured on
    ok-robotics 2026-08-20: status.pgDataImageInfo.extensions[0].name is "pgvector", and CNPG
    echoes back exactly the name the spec asked for.

    Consequence while it was broken: Pending/CapabilityProbePending was unreachable, so a
    declared-but-unprobed extension was reported as ABSENT — the two states §13 bound 4
    distinguishes had collapsed into one.
    """
    source = COMPOSITION_PATH.read_text()
    declared = re.findall(r'\{\{- \$pgvectorExtensionName := "([a-z0-9_-]+)" \}\}', source)
    if len(declared) != 1:
        raise CapabilityError(
            "the Composition must declare exactly one $pgvectorExtensionName constant; found "
            f"{len(declared)}. Two independent literals is how the reader and the composed spec "
            "drifted apart in the first place"
        )
    name = declared[0]

    if re.search(r'\{\{- if eq \$extension\.name "', source):
        raise CapabilityError(
            "the status reader compares $extension.name to a LITERAL; it must use "
            "$pgvectorExtensionName so it cannot drift from the name actually composed"
        )
    literals = re.findall(r"- name: (pgvector|vector)\b", source)
    if literals:
        raise CapabilityError(
            f"composed extension name is still a literal {literals}; use $pgvectorExtensionName"
        )

    observed = [d for d in yaml.safe_load_all(OBSERVED_PATH.read_text()) if d]
    fixture_names = []
    for doc in observed:
        manifest = doc.get("status", {}).get("atProvider", {}).get("manifest", {})
        if manifest.get("kind") == "Cluster":
            for extension in manifest["status"].get("pgDataImageInfo", {}).get("extensions", []):
                fixture_names.append(extension.get("name"))
    if fixture_names and set(fixture_names) != {name}:
        raise CapabilityError(
            f"the observed fixture declares {fixture_names} but the platform composes {name!r}. "
            "CNPG echoes the composed name, so a fixture that disagrees tests the code against "
            "itself instead of against the cluster"
        )
    print(
        f"PASS extension name: reader, composed spec and fixture all use {name!r} "
        "(the name ok-robotics actually reports)"
    )


def assert_proven() -> None:
    state, reason, ref = capability_of(render([matching_artifact()]))
    if (state, reason) != ("Valid", "CapabilityProvenByFunction"):
        raise CapabilityError(
            f"an admitted matching proof must give Valid/CapabilityProvenByFunction, got "
            f"{state}/{reason}"
        )
    if not ref.startswith("CapabilityVerified/"):
        raise CapabilityError(
            f"a proven capability must cite the artifact that decided it, not the declaration "
            f"field; evidenceRef={ref!r}"
        )
    print(f"PASS proven: {state}/{reason} citing {ref}")


def assert_declaration_alone_is_not_evidence() -> None:
    """No artifact, extension declared present: the ok-robotics state. Pending, never Valid."""
    state, reason, ref = capability_of(render(None))
    if (state, reason) != ("Pending", "CapabilityProbePending"):
        raise CapabilityError(
            f"a declared-but-unprobed capability must be Pending/CapabilityProbePending, got "
            f"{state}/{reason}"
        )
    if "pgDataImageInfo" not in ref:
        raise CapabilityError(f"unproven capability should cite the declaration it read: {ref!r}")
    print(f"PASS declaration alone: {state}/{reason} — not Valid, citing the declaration")


def tampers() -> dict[str, Any]:
    """One removed admissibility term each. Every case must fail to reach Valid."""

    def other_database() -> dict[str, Any]:
        a = matching_artifact()
        a["spec"]["databaseRef"]["uid"] = "00000000-0000-4000-8000-999999999999"
        return a

    def other_cluster() -> dict[str, Any]:
        a = matching_artifact()
        a["spec"]["clusterRef"]["uid"] = "00000000-0000-4000-8000-888888888888"
        return a

    def stale_image() -> dict[str, Any]:
        """§6.3: the image was replaced, so the proof speaks about something no longer running."""
        a = matching_artifact()
        a["spec"]["delivery"]["imageDigest"] = "sha256:" + "b" * 64
        return a

    def stub_operator() -> dict[str, Any]:
        """Ordering right, distance wrong — a stub returning a constant still sorts."""
        a = matching_artifact()
        check_named(a, "operator-returns-true-distance")["observed"]["farthestDistance"] = "1"
        return a

    def residue_left() -> dict[str, Any]:
        """A probe that left tables behind is not side-effect-free, so it is not admissible."""
        a = matching_artifact()
        check_named(a, "probe-left-no-residue")["observed"]["probeTablesRemaining"] = 1
        return a

    def missing_check() -> dict[str, Any]:
        a = matching_artifact()
        a["spec"]["checks"] = [
            c for c in a["spec"]["checks"] if c["name"] != "operator-orders-by-distance"
        ]
        return a

    def empty_observed() -> dict[str, Any]:
        a = matching_artifact()
        check_named(a, "extension-created")["observed"] = {}
        return a

    def future_completion() -> dict[str, Any]:
        a = matching_artifact()
        a["spec"]["timing"]["completedAt"] = "2099-01-01T00:00:00Z"
        return a

    def no_probe_digest() -> dict[str, Any]:
        a = matching_artifact()
        a["spec"]["probeDigest"] = ""
        return a

    def wrong_capability() -> dict[str, Any]:
        a = matching_artifact()
        a["spec"]["capability"]["name"] = "postgresql.extension.postgis"
        return a

    return {
        "proof for another database": other_database,
        "proof against another cluster": other_cluster,
        "proof against a replaced image (§6.3)": stale_image,
        "stub operator: ordering right, distance wrong": stub_operator,
        "probe left tables behind": residue_left,
        "one of the five checks missing": missing_check,
        "check with an empty observed object": empty_observed,
        "completedAt in the future": future_completion,
        "no probe digest": no_probe_digest,
        "capability outside the governed list": wrong_capability,
    }


def negative_controls() -> None:
    for name, build in tampers().items():
        state, reason, _ = capability_of(render([build()]))
        if state == "Valid":
            raise CapabilityError(
                f"NEGATIVE CONTROL FAILED: {name} was accepted as proven capability"
            )
        print(f"NEGATIVE CONTROL PASS: {name}: {state}/{reason}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--negative-controls", action="store_true")
    args = parser.parse_args()
    try:
        if args.negative_controls:
            negative_controls()
        else:
            check_extension_name_agreement()
            assert_declaration_alone_is_not_evidence()
            assert_proven()
    except CapabilityError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
