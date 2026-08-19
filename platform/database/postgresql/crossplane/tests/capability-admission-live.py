#!/usr/bin/env python3
"""Ask a real API server whether the CapabilityVerified contract actually holds.

Reading our own YAML is not a verdict on a CRD. This capability already shipped a CRD that a
file-reading check certified and every API server rejected, so the schema and its CEL rules are
installed on a DISPOSABLE cluster here and exercised with artifacts the server must refuse.

Every rejection below is a real 422/400 from the API server, not a local comparison. Skips
loudly when no cluster is reachable: an unverified schema is UNVERIFIED, never OK.
"""

from __future__ import annotations

import argparse
import copy
import json
import subprocess
import sys
from pathlib import Path

import yaml

TESTS_DIR = Path(__file__).resolve().parent
CAPABILITY_DIR = TESTS_DIR.parent.parent
CRD_PATH = CAPABILITY_DIR / "crossplane/capabilityverified-crd.yaml"
FIXTURE_PATH = TESTS_DIR / "capabilityverified-pgvector.yaml"
CRD_NAME = "capabilityverifieds.evidence.platform.openkubes.ai"


def kubectl(context: str, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["kubectl", "--context", context, *args],
        input=stdin,
        capture_output=True,
        text=True,
    )


def server_reachable(context: str) -> bool:
    return kubectl(context, "get", "--raw", "/readyz").returncode == 0


def apply(context: str, doc: dict, dry_run: bool = True) -> subprocess.CompletedProcess:
    args = ["apply", "-f", "-"]
    if dry_run:
        args.append("--dry-run=server")
    return kubectl(context, *args, stdin=yaml.safe_dump(doc, sort_keys=False))


def expect_rejected(context: str, name: str, doc: dict, expect_text: str | None = None) -> None:
    result = apply(context, doc)
    if result.returncode == 0:
        raise AssertionError(
            f"NEGATIVE CONTROL FAILED: the API server ACCEPTED {name!r}, which the contract "
            "must refuse"
        )
    message = (result.stderr or result.stdout).strip().replace("\n", " ")
    if expect_text and expect_text.lower() not in message.lower():
        raise AssertionError(
            f"NEGATIVE CONTROL FAILED: {name!r} was rejected, but not for the stated reason.\n"
            f"  expected to mention: {expect_text!r}\n  server said: {message}"
        )
    print(f"NEGATIVE CONTROL PASS: {name}: server refused it")


def expect_accepted(context: str, name: str, doc: dict) -> None:
    result = apply(context, doc)
    if result.returncode != 0:
        message = (result.stderr or result.stdout).strip().replace("\n", " ")
        raise AssertionError(f"the API server REJECTED a valid artifact ({name}): {message}")
    print(f"PASS: {name}: server accepted it")


def check_named(doc: dict, name: str) -> dict:
    return next(c for c in doc["spec"]["checks"] if c["name"] == name)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", default="docker-desktop")
    args = parser.parse_args()
    context = args.context

    if not server_reachable(context):
        print(
            f"SKIPPED: no API server on context {context} — the CapabilityVerified schema and its "
            "CEL rules are UNVERIFIED, not OK.",
            file=sys.stderr,
        )
        print(
            "         Start one (Docker Desktop Kubernetes, kind, minikube) and rerun, or pass "
            "--context <ctx>.",
            file=sys.stderr,
        )
        return 0

    install = kubectl(context, "apply", "-f", str(CRD_PATH))
    if install.returncode != 0:
        print(f"FAIL: could not install the CRD: {install.stderr.strip()}", file=sys.stderr)
        return 1
    established = kubectl(
        context, "wait", f"crd/{CRD_NAME}", "--for=condition=Established", "--timeout=60s"
    )
    if established.returncode != 0:
        print(f"FAIL: CRD never became Established: {established.stderr.strip()}", file=sys.stderr)
        return 1
    print(f"  installed {CRD_NAME} on {context}")

    valid = yaml.safe_load(FIXTURE_PATH.read_text())

    try:
        expect_accepted(context, "the real bundled-image proof", valid)

        # Immutability. Create for real, then try to change the spec: a mutable evidence record
        # could be edited into a passing verdict after the fact.
        created = apply(context, valid, dry_run=False)
        if created.returncode != 0:
            raise AssertionError(f"could not create the artifact: {created.stderr.strip()}")
        mutated = copy.deepcopy(valid)
        mutated["spec"]["capability"]["observedVersion"] = "9.9.9"
        expect_rejected(context, "mutated spec (immutability)", mutated, "immutable")

        # Delivery mechanism coherence — each mechanism must record what it actually used.
        volume_without_digest = copy.deepcopy(valid)
        volume_without_digest["metadata"]["name"] = "control-imagevolume-no-digest"
        volume_without_digest["spec"]["delivery"]["mechanism"] = "ImageVolume"
        expect_rejected(
            context, "ImageVolume proof with no extensionImageDigest", volume_without_digest,
            "extensionImageDigest",
        )

        bundled_with_digest = copy.deepcopy(valid)
        bundled_with_digest["metadata"]["name"] = "control-bundled-with-ext-digest"
        bundled_with_digest["spec"]["delivery"]["extensionImageDigest"] = "sha256:" + "a" * 64
        expect_rejected(
            context, "BundledImage proof claiming an extension image", bundled_with_digest,
            "must not record",
        )

        # A tag is not an identity: a re-pushed tag would leave a proof looking valid.
        tag_as_digest = copy.deepcopy(valid)
        tag_as_digest["metadata"]["name"] = "control-tag-as-digest"
        tag_as_digest["spec"]["delivery"]["imageDigest"] = "18.6-standard-trixie"
        expect_rejected(context, "tag where an image digest is required", tag_as_digest)

        # The five checks are a set, not a suggestion. Four of them is a weaker probe wearing
        # the same contract.
        four_checks = copy.deepcopy(valid)
        four_checks["metadata"]["name"] = "control-four-checks"
        four_checks["spec"]["checks"] = [
            c for c in valid["spec"]["checks"] if c["name"] != "probe-left-no-residue"
        ]
        expect_rejected(context, "probe missing the residue check", four_checks)

        unknown_check = copy.deepcopy(valid)
        unknown_check["metadata"]["name"] = "control-unknown-check"
        unknown_check["spec"]["checks"][0] = {
            "name": "extension-looks-fine",
            "observed": {"extensionVersion": "0.8.6"},
        }
        expect_rejected(context, "invented check name", unknown_check)

        duplicate_check = copy.deepcopy(valid)
        duplicate_check["metadata"]["name"] = "control-duplicate-check"
        duplicate_check["spec"]["checks"][1] = copy.deepcopy(
            check_named(duplicate_check, "catalog-lists-extension")
        )
        expect_rejected(context, "duplicate check name (list-map key)", duplicate_check)

        # An observed value with nothing in it is the shape of a check that never ran.
        empty_observed = copy.deepcopy(valid)
        empty_observed["metadata"]["name"] = "control-empty-observed"
        check_named(empty_observed, "extension-created")["observed"] = {}
        expect_rejected(context, "check with an empty observed object", empty_observed)

        # The distance is the value that separates a real L2 computation from a placeholder,
        # so it must be a number the database could actually have returned.
        bad_distance = copy.deepcopy(valid)
        bad_distance["metadata"]["name"] = "control-bad-distance"
        check_named(bad_distance, "operator-returns-true-distance")["observed"][
            "farthestDistance"
        ] = "not-a-distance"
        expect_rejected(context, "non-numeric distance", bad_distance)

        ungoverned_capability = copy.deepcopy(valid)
        ungoverned_capability["metadata"]["name"] = "control-ungoverned-capability"
        ungoverned_capability["spec"]["capability"]["name"] = "postgresql.extension.postgis"
        expect_rejected(
            context, "capability outside the §6.4 allowlist", ungoverned_capability
        )

        # An unknown field inside `observed` cannot be stored by EITHER path, and both halves
        # are worth proving because together they are why `additionalProperties` beside
        # `properties` is unnecessary here (and illegal in a structural schema). Strict decoding
        # refuses it at the door; a non-strict client gets it silently pruned.
        smuggled = copy.deepcopy(valid)
        smuggled["metadata"]["name"] = "control-smuggled-field"
        check_named(smuggled, "extension-created")["observed"]["itWorkedTrustMe"] = True
        expect_rejected(context, "unknown observed field via strict apply", smuggled, "unknown field")

        non_strict = kubectl(
            context, "create", "--validate=false", "-f", "-",
            stdin=yaml.safe_dump(smuggled, sort_keys=False),
        )
        if non_strict.returncode != 0:
            raise AssertionError(
                f"non-strict create failed, so pruning is unproven: {non_strict.stderr.strip()}"
            )
        stored = kubectl(
            context, "get", f"capabilityverified/{smuggled['metadata']['name']}", "-o", "json"
        )
        observed = next(
            c["observed"]
            for c in json.loads(stored.stdout)["spec"]["checks"]
            if c["name"] == "extension-created"
        )
        if "itWorkedTrustMe" in observed:
            raise AssertionError(
                "NEGATIVE CONTROL FAILED: an unknown observed field survived storage; the schema "
                "is not pruning and a probe could smuggle its own vocabulary"
            )
        print(
            f"NEGATIVE CONTROL PASS: unknown observed field: pruned to {sorted(observed)} when "
            "submitted non-strictly"
        )

        print(
            "OK: the API server enforces immutability, delivery coherence, the exact five-check "
            "set, the governed capability list, digest identity and observed-value pruning"
        )
    except AssertionError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    finally:
        # The disposable cluster is left as found; the CRD's own deletion removes the artifacts.
        kubectl(context, "delete", "crd", CRD_NAME, "--ignore-not-found", "--wait=false")

    return 0


if __name__ == "__main__":
    sys.exit(main())
