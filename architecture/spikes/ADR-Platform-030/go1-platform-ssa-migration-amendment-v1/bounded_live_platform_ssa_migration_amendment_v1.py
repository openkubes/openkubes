#!/usr/bin/env python3
"""Apply the exact OK-141 SSA migration-disable amendment once."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any

import yaml


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


BASE = load_module(
    "ok141_live_ssa_base",
    SPIKE / "go1-platform-ssa-amendment-v1/bounded_live_platform_ssa_amendment_v1.py",
)
VERIFY = load_module(
    "ok141_ssa_migration_verifier",
    HERE / "verify_platform_ssa_migration_amendment_v1.py",
)


class LiveMigrationError(RuntimeError):
    pass


def digest_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def write_private(path: Path, value: dict[str, Any], exclusive: bool = False) -> None:
    payload = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if exclusive:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            output.write(payload)
    else:
        path.write_bytes(payload)
        path.chmod(0o600)


def validate_candidate(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if value.get("kind") != "OK141LivePlatformSSAMigrationAmendmentCandidate":
        raise LiveMigrationError("candidate kind mismatch")
    spec = value.get("spec", {})
    if spec.get("state") != "LIVE-AUTHORIZED-ONCE" or not spec.get("standingGrantAcknowledged"):
        raise LiveMigrationError("candidate authorization mismatch")
    amendment = SPIKE / spec["amendmentPath"]
    if digest_file(amendment) != spec["amendmentDigest"]:
        raise LiveMigrationError("amendment digest mismatch")
    if VERIFY.validate(amendment) != spec["identities"]["FixtureDigest"]:
        raise LiveMigrationError("amendment verification failed")
    tool = HERE / spec["toolPath"]
    if digest_file(tool) != spec["toolDigest"]:
        raise LiveMigrationError("tool digest mismatch")
    return value


def execute(candidate_path: Path) -> dict[str, Any]:
    candidate = validate_candidate(candidate_path)
    spec = candidate["spec"]
    client = Path(spec["clientPath"])
    mgmt = Path(spec["managementKubeconfigPath"])
    shared = Path(spec["sharedKubeconfigPath"])
    output = Path(spec["outputPath"])
    if digest_file(client) != spec["clientDigest"]:
        raise LiveMigrationError("client digest mismatch")
    for path in (mgmt, shared):
        if path.is_symlink() or not path.is_file() or stat.S_IMODE(path.stat().st_mode) != 0o600:
            raise LiveMigrationError("unsafe kubeconfig")
    if output.exists() or output.is_symlink():
        raise LiveMigrationError("exclusive output exists")

    amendment_path = SPIKE / spec["amendmentPath"]
    amendment = json.loads(amendment_path.read_text())["spec"]
    old = amendment["base"]
    new = amendment["identities"]
    apps = {
        item["metadata"]["name"]: item
        for item in yaml.safe_load_all((SPIKE / amendment["platform"]["applicationsPath"]).read_text())
        if item
    }
    annotations = {
        "openkubes.io/intent-revision": new["R"],
        "openkubes.io/execution-fixture": new["FixtureDigest"],
    }
    prepared: list[tuple[Path, str, str, dict[str, Any], dict[str, Any]]] = []
    lifecycle = [
        ("", "v1", None, "namespaces", "disposable-ok141"),
        ("cluster.x-k8s.io", "v1beta1", "disposable-ok141", "clusters", "disposable-ok141"),
        ("infrastructure.cluster.x-k8s.io", "v1alpha1", "disposable-ok141", "kubevirtclusters", "disposable-ok141"),
        ("controlplane.cluster.x-k8s.io", "v1alpha3", "disposable-ok141", "taloscontrolplanes", "disposable-ok141-cp"),
        ("bootstrap.cluster.x-k8s.io", "v1alpha3", "disposable-ok141", "talosconfigtemplates", "disposable-ok141-workers-v1-9-6"),
        ("cluster.x-k8s.io", "v1beta1", "disposable-ok141", "machinedeployments", "disposable-ok141-workers"),
        ("infrastructure.cluster.x-k8s.io", "v1alpha1", "disposable-ok141", "kubevirtmachinetemplates", "disposable-ok141-cp-7f5dd4276432"),
        ("infrastructure.cluster.x-k8s.io", "v1alpha1", "disposable-ok141", "kubevirtmachinetemplates", "disposable-ok141-workers-7f5dd4276432"),
    ]
    for item in lifecycle:
        raw_uri = BASE.uri(*item)
        current = BASE.raw(client, mgmt, "get", raw_uri)
        current_annotations = current.get("metadata", {}).get("annotations", {})
        if (
            current_annotations.get("openkubes.io/intent-revision") != old["R"]
            or current_annotations.get("openkubes.io/execution-fixture") != old["fixtureDigest"]
        ):
            raise LiveMigrationError("lifecycle base identity mismatch")
        replacement = BASE.clean(current)
        replacement["metadata"].setdefault("annotations", {}).update(annotations)
        prepared.append((mgmt, "lifecycle", raw_uri, current, replacement))

    hcp_uri = BASE.uri(
        "addons.cluster.x-k8s.io", "v1alpha1", "disposable-ok141",
        "helmchartproxies", "disposable-ok141-cilium",
    )
    hcp = BASE.raw(client, mgmt, "get", hcp_uri)
    hcp_annotations = hcp.get("metadata", {}).get("annotations", {})
    if (
        hcp_annotations.get("openkubes.io/intent-revision") != old["R"]
        or hcp_annotations.get("openkubes.io/execution-fixture") != old["fixtureDigest"]
    ):
        raise LiveMigrationError("HCP base identity mismatch")
    hcp_replacement = BASE.clean(hcp)
    hcp_replacement["metadata"].setdefault("annotations", {}).update(annotations)
    prepared.append((mgmt, "enablement", hcp_uri, hcp, hcp_replacement))

    registration_uri = BASE.uri("", "v1", "argocd", "secrets", "disposable-ok141-cluster")
    registration = BASE.raw(client, shared, "get", registration_uri)
    registration_annotations = registration.get("metadata", {}).get("annotations", {})
    if any((
        registration_annotations.get("openkubes.io/intent-revision") != old["R"],
        registration_annotations.get("openkubes.io/platform-revision") != old["P"],
        registration_annotations.get("openkubes.io/execution-fixture") != old["fixtureDigest"],
    )):
        raise LiveMigrationError("registration base identity mismatch")
    registration_replacement = BASE.clean(registration)
    registration_replacement["metadata"].setdefault("annotations", {}).update({
        **annotations, "openkubes.io/platform-revision": new["P"]
    })
    prepared.append((shared, "registration", registration_uri, registration, registration_replacement))

    for name in (
        "disposable-ok141-observability-core",
        "disposable-ok141-observability-alerting",
        "disposable-ok141-observability-dashboards",
    ):
        raw_uri = BASE.uri("argoproj.io", "v1alpha1", "argocd", "applications", name)
        current = BASE.raw(client, shared, "get", raw_uri)
        current_annotations = current.get("metadata", {}).get("annotations", {})
        if any((
            current_annotations.get("openkubes.io/intent-revision") != old["R"],
            current_annotations.get("openkubes.io/platform-revision") != old["P"],
            current_annotations.get("openkubes.io/execution-fixture") != old["fixtureDigest"],
        )):
            raise LiveMigrationError("Application base identity mismatch")
        if current.get("spec", {}).get("source", {}).get("targetRevision") != amendment["platform"]["sourceCommit"]:
            raise LiveMigrationError("Application source revision changed")
        replacement = BASE.clean(current)
        replacement["metadata"].setdefault("annotations", {}).update({
            **annotations, "openkubes.io/platform-revision": new["P"]
        })
        if name.endswith("-core"):
            current_options = current.get("spec", {}).get("syncPolicy", {}).get("syncOptions", [])
            wanted = apps[name]["spec"]["syncPolicy"]["syncOptions"]
            if "ServerSideApply=true" not in current_options:
                raise LiveMigrationError("Core lost SSA")
            if "ClientSideApplyMigration=false" in current_options:
                raise LiveMigrationError("migration option already present")
            if sorted(current_options + ["ClientSideApplyMigration=false"]) != sorted(wanted):
                raise LiveMigrationError("Core sync-option delta is not exact")
            replacement["spec"]["syncPolicy"]["syncOptions"] = copy.deepcopy(wanted)
        prepared.append((shared, "application", raw_uri, current, replacement))

    if len(prepared) != 13:
        raise LiveMigrationError("prepared object count mismatch")
    evidence: dict[str, Any] = {
        "apiVersion": "evidence.openkubes.io/v1alpha1",
        "kind": "OK141LivePlatformSSAMigrationAmendmentEvidence",
        "candidateDigest": digest_file(candidate_path),
        "amendmentDigest": spec["amendmentDigest"],
        "identities": new,
        "preflightObjectCount": 13,
        "updatedObjectCount": 0,
        "updates": [],
        "state": "STARTED",
        "retryPerformed": False,
        "rollbackOrCleanupPerformed": False,
        "failureInjectionPerformed": False,
        "rawObjectsRetained": False,
    }
    write_private(output, evidence, exclusive=True)
    try:
        for kubeconfig, category, raw_uri, current, replacement in prepared:
            uid = current.get("metadata", {}).get("uid")
            resource_version = current.get("metadata", {}).get("resourceVersion")
            if not uid or not resource_version:
                raise LiveMigrationError("prepared object lacks UID/resourceVersion")
            returned = BASE.raw(
                client, kubeconfig, "replace", raw_uri,
                json.dumps(replacement, sort_keys=True, separators=(",", ":")).encode(),
            )
            if (
                returned.get("metadata", {}).get("uid") != uid
                or returned.get("metadata", {}).get("resourceVersion") == resource_version
            ):
                raise LiveMigrationError("optimistic-concurrency postcondition failed")
            evidence["updates"].append({"category": category, "uidPreserved": True, "resourceVersionAdvanced": True})
            evidence["updatedObjectCount"] = len(evidence["updates"])
            write_private(output, evidence)
    except Exception:
        evidence["state"] = "STOP-PARTIAL-STATE-PRESERVED"
        write_private(output, evidence)
        raise

    final = {}
    for name in (
        "disposable-ok141-observability-core",
        "disposable-ok141-observability-alerting",
        "disposable-ok141-observability-dashboards",
    ):
        raw_uri = BASE.uri("argoproj.io", "v1alpha1", "argocd", "applications", name)
        final[name] = BASE.summary(BASE.raw(client, shared, "get", raw_uri))
    evidence.update({
        "state": "PASS-AMENDED-AWAITING-CORE-SYNC",
        "coreServerSideApplyRetained": True,
        "coreClientSideApplyMigrationDisabled": True,
        "finalApplications": final,
    })
    evidence["semanticDigest"] = BASE.digest_bytes(
        json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
    )
    write_private(output, evidence)
    return {
        "state": evidence["state"],
        "evidenceDigest": digest_file(output),
        "updatedObjectCount": evidence["updatedObjectCount"],
        "finalApplications": final,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "amend"))
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "verify":
            validate_candidate(args.candidate.resolve())
            print(digest_file(args.candidate.resolve()))
        else:
            if not args.execute:
                raise LiveMigrationError("amend requires --execute")
            print(json.dumps(execute(args.candidate.resolve()), sort_keys=True))
        return 0
    except Exception as error:
        print(f"ERROR: {type(error).__name__}: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
