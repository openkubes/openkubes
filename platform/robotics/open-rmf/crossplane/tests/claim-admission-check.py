#!/usr/bin/env python3
"""Exercise live OpenRMFClaim admission with non-mutating server dry-runs."""

from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile

import yaml

ROOT = Path(__file__).resolve().parent.parent
AUTHORITY_REASON = "OpenRMFClaim allocation authorization denied"
CONTROL_REASON = "OpenRMFClaim control fields are controller-owned"
METADATA_REASON = "OpenRMFClaim metadata controls are controller-owned"
PORTABLE_FIELDS = {"clusterRef", "namespace", "mode", "hostname", "credentialsSecretRef"}
CONTROL_VALUES = {
    "compositionRef": {"name": "unreviewed-composition"},
    "compositionSelector": {"matchLabels": {"authorization": "unreviewed"}},
    "compositionRevisionRef": {"name": "unreviewed-revision"},
    "compositionRevisionSelector": {"matchLabels": {"authorization": "unreviewed"}},
    "compositionUpdatePolicy": "Manual",
    "compositeDeletePolicy": "Foreground",
    "resourceRef": {
        "apiVersion": "platform.openkubes.ai/v1alpha1",
        "kind": "OpenRMFInstance",
        "name": "unreviewed-resource",
    },
    "writeConnectionSecretToRef": {"name": "claimant-secret"},
}


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=False, capture_output=True, text=True)


def identity(user: str, groups: list[str]) -> list[str]:
    result = [f"--as={user}", "--as-group=system:authenticated"]
    result.extend(f"--as-group={group}" for group in groups)
    return result


def assert_accepted(result: subprocess.CompletedProcess[str], name: str) -> None:
    assert result.returncode == 0, f"{name} was not admitted: {result.stderr}"
    print(f"ACCEPTED: {name}")


def assert_rejected(result: subprocess.CompletedProcess[str], name: str, reason: str) -> None:
    assert result.returncode != 0, f"live API accepted unauthorized {name}"
    assert reason in result.stderr, f"{name} failed for an unexpected reason: {result.stderr}"
    print(f"REJECTED: {name} ({reason})")


def assert_admitted_duplicate(result: subprocess.CompletedProcess[str], name: str) -> None:
    assert result.returncode != 0, f"duplicate {name} unexpectedly reported success"
    assert "already exists" in result.stderr.lower(), result.stderr
    assert "ValidatingAdmissionPolicy" not in result.stderr, result.stderr
    print(f"ADMITTED BY POLICY: {name} (storage correctly reported AlreadyExists)")


def write(directory: str, name: str, manifest: dict) -> Path:
    path = Path(directory, f"{name}.yaml")
    path.write_text(yaml.safe_dump(manifest, sort_keys=False))
    return path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--schema-only", action="store_true")
    args = parser.parse_args()
    kubectl = shlex.split(os.environ["MGMT_KUBECTL"])

    generated = run([*kubectl, "get", "crd", "openrmfclaims.platform.openkubes.ai", "-o", "json"])
    assert generated.returncode == 0, generated.stderr
    crd = json.loads(generated.stdout)
    served = [v for v in crd["spec"]["versions"] if v["served"]]
    assert {v["name"] for v in served} == {"v1alpha1"}, (
        "generated Claim served-version drift: " + repr([v["name"] for v in served])
    )
    expected_fields = PORTABLE_FIELDS | set(CONTROL_VALUES)
    for version in served:
        live_fields = set(
            version["schema"]["openAPIV3Schema"]["properties"]["spec"]["properties"]
        )
        assert live_fields == expected_fields, (
            f"generated Claim spec field drift in {version['name']}: "
            f"live={sorted(live_fields)}, expected={sorted(expected_fields)}"
        )
    print("INSPECTED: every generated served Claim version and spec field is guarded")
    if args.schema_only:
        return

    user = os.environ["CLAIM_EDITOR_USER"]
    allowed_groups = os.environ["CLAIM_EDITOR_GROUPS"].split()
    peer_groups = os.environ.get("PEER_GROUPS", "").split()
    allowed = identity(user, allowed_groups)
    allowed_with_peers = identity(user, [*allowed_groups, *peer_groups])
    near_miss_user = "system:serviceaccount:crossplane-system:crossplane-near-miss"
    unmapped = identity(near_miss_user, ["system:masters"])
    near_miss_mapped = identity(near_miss_user, ["system:masters", *allowed_groups])
    controller = identity(
        "system:serviceaccount:crossplane-system:crossplane",
        ["system:serviceaccounts", "system:serviceaccounts:crossplane-system"],
    )

    source = ROOT / "examples/ok-robotics.yaml"
    claim = yaml.safe_load(source.read_text())
    namespace = claim["metadata"]["namespace"]
    name = claim["metadata"]["name"]

    with tempfile.TemporaryDirectory(prefix="openrmf-claim-admission-") as directory:
        exact_path = write(directory, "exact-allocation", claim)
        assert_admitted_duplicate(
            run([*kubectl, "create", "--dry-run=server", "-f", str(exact_path), *allowed]),
            "CREATE exact allocated Claim as mapped group",
        )
        assert_admitted_duplicate(
            run([*kubectl, "create", "--dry-run=server", "-f", str(exact_path), *allowed_with_peers]),
            "CREATE exact allocation with additional groups",
        )
        assert_rejected(
            run([*kubectl, "create", "--dry-run=server", "-f", str(exact_path), *unmapped]),
            "CREATE exact allocation as unmapped RBAC-capable identity",
            AUTHORITY_REASON,
        )

        for case_name, path, value in (
            ("unauthorized-claim-name", ("metadata", "name"), "another-openrmf"),
            ("unauthorized-clusterref", ("spec", "clusterRef"), "ok-shared"),
            ("unauthorized-namespace", ("spec", "namespace"), "another-tenant"),
            ("unauthorized-hostname", ("spec", "hostname"), "shadow.example.com"),
        ):
            candidate = copy.deepcopy(claim)
            node = candidate
            for part in path[:-1]:
                node = node[part]
            node[path[-1]] = value
            assert_rejected(
                run([*kubectl, "create", "--dry-run=server", "-f", str(write(directory, case_name, candidate)), *allowed]),
                f"CREATE {'.'.join(path)}={value}",
                AUTHORITY_REASON,
            )

        other_claim_namespace = copy.deepcopy(claim)
        other_claim_namespace["metadata"]["namespace"] = "default"
        assert_rejected(
            run([*kubectl, "create", "--dry-run=server", "-f", str(write(directory, "claim-namespace", other_claim_namespace)), *near_miss_mapped]),
            "CREATE in an unallocated Claim namespace",
            AUTHORITY_REASON,
        )

        for case_name, path, value in (
            ("secret-name", ("spec", "credentialsSecretRef", "name"), "another-secret"),
            ("secret-namespace", ("spec", "credentialsSecretRef", "namespace"), "default"),
        ):
            candidate = copy.deepcopy(claim)
            node = candidate
            for part in path[:-1]:
                node = node[part]
            node[path[-1]] = value
            result = run([*kubectl, "create", "--dry-run=server", "-f", str(write(directory, case_name, candidate)), *allowed])
            assert_rejected(result, f"CREATE {'.'.join(path)}={value}", "Unsupported value")
            assert ".".join(path) in result.stderr, result.stderr

        for case_name, key, value in (
            ("owner-reference", "ownerReferences", [{"apiVersion": "v1", "kind": "ConfigMap", "name": "owner", "uid": "00000000-0000-0000-0000-000000000000"}]),
            ("finalizer", "finalizers", ["example.invalid/finalizer"]),
            ("reserved-label", "labels", {"crossplane.io/claim-name": "captured"}),
            ("paused-annotation", "annotations", {"crossplane.io/paused": "true"}),
        ):
            candidate = copy.deepcopy(claim)
            candidate["metadata"][key] = value
            assert_rejected(
                run([*kubectl, "create", "--dry-run=server", "-f", str(write(directory, case_name, candidate)), *allowed]),
                f"CREATE claimant-selected metadata.{key}",
                METADATA_REASON,
            )

        for field, value in CONTROL_VALUES.items():
            candidate = copy.deepcopy(claim)
            candidate["spec"][field] = value
            assert_rejected(
                run([*kubectl, "create", "--dry-run=server", "-f", str(write(directory, f"control-{field}", candidate)), *allowed]),
                f"CREATE claimant-selected spec.{field}",
                CONTROL_REASON,
            )

        current = run([*kubectl, "get", "openrmfclaim", name, "-n", namespace, "-o", "yaml", *allowed])
        assert current.returncode == 0, (
            "UPDATE admission proof requires the deployed example Claim; no object was mutated. "
            + current.stderr
        )
        live_claim = yaml.safe_load(current.stdout)
        live_path = write(directory, "live-unchanged", live_claim)
        assert_accepted(
            run([*kubectl, "replace", "--dry-run=server", "-f", str(live_path), *allowed_with_peers]),
            "UPDATE exact allocation with unchanged controls and additional groups",
        )
        ordinary_metadata = copy.deepcopy(live_claim)
        ordinary_metadata["metadata"].setdefault("annotations", {})["claimant.example/note"] = "safe"
        assert_accepted(
            run([*kubectl, "replace", "--dry-run=server", "-f", str(write(directory, "ordinary-metadata", ordinary_metadata)), *allowed]),
            "UPDATE ordinary non-Crossplane annotation",
        )
        assert_rejected(
            run([*kubectl, "replace", "--dry-run=server", "-f", str(live_path), *unmapped]),
            "UPDATE exact allocation as unmapped RBAC-capable identity",
            AUTHORITY_REASON,
        )
        for case_name, path, value in (
            ("update-clusterref", ("spec", "clusterRef"), "ok-shared"),
            ("update-namespace", ("spec", "namespace"), "another-tenant"),
            ("update-hostname", ("spec", "hostname"), "shadow.example.com"),
        ):
            candidate = copy.deepcopy(live_claim)
            node = candidate
            for part in path[:-1]:
                node = node[part]
            node[path[-1]] = value
            assert_rejected(
                run([*kubectl, "replace", "--dry-run=server", "-f", str(write(directory, case_name, candidate)), *allowed]),
                f"UPDATE {'.'.join(path)}={value}",
                AUTHORITY_REASON,
            )

        for case_name, path, value in (
            ("update-secret-name", ("spec", "credentialsSecretRef", "name"), "another-secret"),
            ("update-secret-namespace", ("spec", "credentialsSecretRef", "namespace"), "default"),
        ):
            candidate = copy.deepcopy(live_claim)
            node = candidate
            for part in path[:-1]:
                node = node[part]
            node[path[-1]] = value
            result = run([*kubectl, "replace", "--dry-run=server", "-f", str(write(directory, case_name, candidate)), *allowed])
            assert_rejected(result, f"UPDATE {'.'.join(path)}={value}", "Unsupported value")
            assert ".".join(path) in result.stderr, result.stderr

        for case_name, key, value in (
            ("update-owner-reference", "ownerReferences", [{"apiVersion": "v1", "kind": "ConfigMap", "name": "owner", "uid": "00000000-0000-0000-0000-000000000000"}]),
            ("update-finalizer", "finalizers", ["example.invalid/finalizer"]),
            ("update-reserved-label", "labels", {"crossplane.io/claim-name": "captured"}),
            ("update-paused-annotation", "annotations", {"crossplane.io/paused": "true"}),
        ):
            candidate = copy.deepcopy(live_claim)
            candidate["metadata"][key] = value
            assert_rejected(
                run([*kubectl, "replace", "--dry-run=server", "-f", str(write(directory, case_name, candidate)), *allowed]),
                f"UPDATE claimant-selected metadata.{key}",
                METADATA_REASON,
            )

        for field, value in CONTROL_VALUES.items():
            candidate = copy.deepcopy(live_claim)
            candidate["spec"][field] = value
            assert_rejected(
                run([*kubectl, "replace", "--dry-run=server", "-f", str(write(directory, f"update-{field}", candidate)), *allowed]),
                f"UPDATE claimant-selected spec.{field}",
                CONTROL_REASON,
            )

        near_miss_control = copy.deepcopy(live_claim)
        near_miss_control["spec"]["compositionUpdatePolicy"] = "Manual"
        near_miss_path = write(directory, "near-miss-controller", near_miss_control)
        assert_rejected(
            run([*kubectl, "replace", "--dry-run=server", "-f", str(near_miss_path), *near_miss_mapped]),
            "UPDATE control field as mapped near-miss controller identity",
            CONTROL_REASON,
        )
        assert_accepted(
            run([*kubectl, "replace", "--dry-run=server", "-f", str(near_miss_path), *controller]),
            "UPDATE control field as exact Crossplane controller identity",
        )

    print("OK: live CREATE/UPDATE admission matrix used server dry-run only; nothing was persisted")


if __name__ == "__main__":
    main()
