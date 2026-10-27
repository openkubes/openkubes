#!/usr/bin/env python3
"""Propagate the exact OK-141 v9 identity amendment once."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import time
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
    "ok141_live_capability_boundary_base",
    SPIKE / "go1-platform-ssa-amendment-v1/bounded_live_platform_ssa_amendment_v1.py",
)


class LiveCapabilityBoundaryError(RuntimeError):
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
    if value.get("kind") != "OK141LiveCapabilityNameBoundaryAmendmentCandidate":
        raise LiveCapabilityBoundaryError("candidate kind mismatch")
    spec = value.get("spec", {})
    if spec.get("state") != "LIVE-AUTHORIZED-ONCE" or not spec.get("standingGrantAcknowledged"):
        raise LiveCapabilityBoundaryError("candidate authorization mismatch")
    amendment = SPIKE / spec["amendmentPath"]
    if digest_file(amendment) != spec["amendmentDigest"]:
        raise LiveCapabilityBoundaryError("amendment digest mismatch")
    verifier = SPIKE / spec["verifierPath"]
    result = subprocess.run([sys.executable, str(verifier)], check=False, capture_output=True)
    if result.returncode != 0:
        raise LiveCapabilityBoundaryError("offline amendment verifier failed")
    tool = HERE / spec["toolPath"]
    if digest_file(tool) != spec["toolDigest"]:
        raise LiveCapabilityBoundaryError("tool digest mismatch")
    amendment_value = json.loads(amendment.read_text())
    if amendment_value["spec"]["identities"] != spec["identities"]:
        raise LiveCapabilityBoundaryError("candidate identity mismatch")
    return value


def desired_applications(amendment: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        item["metadata"]["name"]: item
        for item in yaml.safe_load_all((SPIKE / amendment["platform"]["applicationsPath"]).read_text())
        if item
    }


def normalized_application_spec(value: dict[str, Any]) -> dict[str, Any]:
    """Normalize the one API-omitted explicit false used by directory sources."""
    result = copy.deepcopy(value)
    directory = result.get("source", {}).get("directory")
    if isinstance(directory, dict) and directory.get("recurse") is False:
        directory.pop("recurse")
    return result


def app_summary(value: dict[str, Any], expected_revision: str) -> dict[str, Any]:
    status = value.get("status", {})
    return {
        "desiredRevisionCurrent": value.get("spec", {}).get("source", {}).get("targetRevision") == expected_revision,
        "appliedRevisionCurrent": status.get("sync", {}).get("revision") == expected_revision,
        "sync": status.get("sync", {}).get("status", "Unknown"),
        "health": status.get("health", {}).get("status", "Unknown"),
        "conditionTypes": sorted(
            item.get("type", "") for item in status.get("conditions", []) if item.get("type")
        ),
    }


def execute(candidate_path: Path) -> dict[str, Any]:
    candidate = validate_candidate(candidate_path)
    spec = candidate["spec"]
    client = Path(spec["clientPath"])
    mgmt = Path(spec["managementKubeconfigPath"])
    shared = Path(spec["sharedKubeconfigPath"])
    output = Path(spec["outputPath"])
    if digest_file(client) != spec["clientDigest"]:
        raise LiveCapabilityBoundaryError("client digest mismatch")
    for path in (mgmt, shared):
        if path.is_symlink() or not path.is_file() or stat.S_IMODE(path.stat().st_mode) != 0o600:
            raise LiveCapabilityBoundaryError("unsafe kubeconfig")
    if output.exists() or output.is_symlink():
        raise LiveCapabilityBoundaryError("exclusive output exists")

    amendment = json.loads((SPIKE / spec["amendmentPath"]).read_text())["spec"]
    old = amendment["base"]
    old_platform = amendment["basePlatform"]
    new = amendment["identities"]
    new_source = amendment["platform"]["sourceCommit"]
    desired_apps = desired_applications(amendment)
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
            raise LiveCapabilityBoundaryError("lifecycle base identity mismatch")
        replacement = BASE.clean(current)
        replacement["metadata"].setdefault("annotations", {}).update(annotations)
        prepared.append((mgmt, "lifecycle", raw_uri, current, replacement))

    hcp_uri = BASE.uri("addons.cluster.x-k8s.io", "v1alpha1", "disposable-ok141", "helmchartproxies", "disposable-ok141-cilium")
    hcp = BASE.raw(client, mgmt, "get", hcp_uri)
    hcp_annotations = hcp.get("metadata", {}).get("annotations", {})
    if (
        hcp_annotations.get("openkubes.io/intent-revision") != old["R"]
        or hcp_annotations.get("openkubes.io/execution-fixture") != old["fixtureDigest"]
    ):
        raise LiveCapabilityBoundaryError("HCP base identity mismatch")
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
        raise LiveCapabilityBoundaryError("registration base identity mismatch")
    registration_replacement = BASE.clean(registration)
    registration_replacement["metadata"].setdefault("annotations", {}).update({
        **annotations, "openkubes.io/platform-revision": new["P"]
    })
    prepared.append((shared, "registration", registration_uri, registration, registration_replacement))

    for name in (
        "disposable-ok141-observability-alerting",
        "disposable-ok141-observability-dashboards",
        "disposable-ok141-observability-core",
    ):
        raw_uri = BASE.uri("argoproj.io", "v1alpha1", "argocd", "applications", name)
        current = BASE.raw(client, shared, "get", raw_uri)
        current_annotations = current.get("metadata", {}).get("annotations", {})
        if any((
            current_annotations.get("openkubes.io/intent-revision") != old["R"],
            current_annotations.get("openkubes.io/platform-revision") != old["P"],
            current_annotations.get("openkubes.io/execution-fixture") != old["fixtureDigest"],
        )):
            raise LiveCapabilityBoundaryError("Application base identity mismatch")
        if current.get("spec", {}).get("source", {}).get("targetRevision") != old_platform["sourceCommit"]:
            raise LiveCapabilityBoundaryError("Application base source mismatch")
        replacement = BASE.clean(current)
        replacement["metadata"].setdefault("annotations", {}).update({
            **annotations, "openkubes.io/platform-revision": new["P"]
        })
        replacement["spec"]["source"]["targetRevision"] = new_source
        expected = copy.deepcopy(desired_apps[name])
        if normalized_application_spec(replacement["spec"]) != normalized_application_spec(expected["spec"]):
            raise LiveCapabilityBoundaryError("Application delta exceeds metadata and targetRevision")
        prepared.append((shared, "application", raw_uri, current, replacement))

    if len(prepared) != 13 or prepared[-1][2].split("/")[-1] != "disposable-ok141-observability-core":
        raise LiveCapabilityBoundaryError("prepared set or Core-last ordering mismatch")

    evidence: dict[str, Any] = {
        "apiVersion": "evidence.openkubes.io/v1alpha1",
        "kind": "OK141LiveCapabilityNameBoundaryAmendmentEvidence",
        "candidateDigest": digest_file(candidate_path),
        "amendmentDigest": spec["amendmentDigest"],
        "identities": new,
        "preflightObjectCount": 13,
        "updatedObjectCount": 0,
        "updates": [],
        "coreUpdatedLast": True,
        "automaticArgoReconciliationAcknowledged": True,
        "explicitArgoSyncSubmitted": False,
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
                raise LiveCapabilityBoundaryError("prepared object lacks UID/resourceVersion")
            returned = BASE.raw(
                client, kubeconfig, "replace", raw_uri,
                json.dumps(replacement, sort_keys=True, separators=(",", ":")).encode(),
            )
            if returned.get("metadata", {}).get("uid") != uid or returned.get("metadata", {}).get("resourceVersion") == resource_version:
                raise LiveCapabilityBoundaryError("optimistic-concurrency postcondition failed")
            evidence["updates"].append({"category": category, "uidPreserved": True, "resourceVersionAdvanced": True})
            evidence["updatedObjectCount"] = len(evidence["updates"])
            write_private(output, evidence)
    except Exception:
        evidence["state"] = "STOP-PARTIAL-STATE-PRESERVED"
        write_private(output, evidence)
        raise

    observations: list[dict[str, Any]] = []
    final: dict[str, dict[str, Any]] = {}
    for iteration in range(spec["observation"]["maxIterations"]):
        final = {}
        for name in sorted(desired_apps):
            raw_uri = BASE.uri("argoproj.io", "v1alpha1", "argocd", "applications", name)
            final[name] = app_summary(BASE.raw(client, shared, "get", raw_uri), new_source)
        observations.append({"iteration": iteration + 1, "applications": final})
        if all(
            item["desiredRevisionCurrent"]
            and item["appliedRevisionCurrent"]
            and item["sync"] == "Synced"
            and item["health"] == "Healthy"
            for item in final.values()
        ):
            break
        if iteration + 1 < spec["observation"]["maxIterations"]:
            time.sleep(spec["observation"]["intervalSeconds"])
    converged = all(
        item["desiredRevisionCurrent"]
        and item["appliedRevisionCurrent"]
        and item["sync"] == "Synced"
        and item["health"] == "Healthy"
        for item in final.values()
    )
    evidence.update({
        "state": "PASS-PLATFORM-V9-CONVERGED" if converged else "STOP-PLATFORM-V9-NOT-CONVERGED",
        "observationIterations": len(observations),
        "observationDigest": BASE.digest_bytes(json.dumps(observations, sort_keys=True, separators=(",", ":")).encode()),
        "finalApplications": final,
        "allApplicationsCurrentSyncedHealthy": converged,
    })
    evidence["semanticDigest"] = BASE.digest_bytes(json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode())
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
                raise LiveCapabilityBoundaryError("amend requires --execute")
            print(json.dumps(execute(args.candidate.resolve()), sort_keys=True))
        return 0
    except Exception as error:
        print(f"ERROR: {type(error).__name__}: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
