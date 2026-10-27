#!/usr/bin/env python3
"""Propagate the exact OK-141 SSA Platform amendment with optimistic concurrency."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
import stat
import subprocess
import sys
import time
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


VERIFY = load_module("ok141_ssa_amendment_verifier", HERE / "verify_platform_ssa_amendment_v1.py")


class LiveAmendmentError(RuntimeError):
    pass


def digest_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def digest_file(path: Path) -> str:
    return digest_bytes(path.read_bytes())


def raw(
    client: Path,
    kubeconfig: Path,
    verb: str,
    uri: str,
    payload: bytes | None = None,
) -> dict[str, Any]:
    command = [str(client), "--kubeconfig", str(kubeconfig), verb, "--raw", uri]
    if payload is not None:
        command += ["--filename", "-"]
    completed = subprocess.run(
        command,
        input=payload,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        raise LiveAmendmentError(f"exact {verb} failed for bound object; output suppressed")
    value = json.loads(completed.stdout)
    if not isinstance(value, dict):
        raise LiveAmendmentError("API returned non-object")
    return value


def uri(group: str, version: str, namespace: str | None, plural: str, name: str) -> str:
    prefix = f"/apis/{group}/{version}" if group else f"/api/{version}"
    scope = f"/namespaces/{namespace}" if namespace else ""
    return f"{prefix}{scope}/{plural}/{name}"


def clean(current: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(current)
    result.setdefault("metadata", {}).pop("managedFields", None)
    result["metadata"].pop("selfLink", None)
    return result


def summary(value: dict[str, Any]) -> dict[str, Any]:
    status = value.get("status", {})
    operation = status.get("operationState", {}) or {}
    return {
        "sync": status.get("sync", {}).get("status", "Unknown"),
        "health": status.get("health", {}).get("status", "Unknown"),
        "operationPhase": operation.get("phase", "Unknown"),
        "conditionTypes": sorted(
            item.get("type", "") for item in status.get("conditions", []) if item.get("type")
        ),
    }


def validate_candidate(path: Path) -> dict[str, Any]:
    candidate = json.loads(path.read_text())
    if candidate.get("kind") != "OK141LivePlatformSSAAmendmentCandidate":
        raise LiveAmendmentError("candidate kind mismatch")
    spec = candidate["spec"]
    if spec.get("state") != "LIVE-AUTHORIZED-ONCE" or not spec.get("standingGrantAcknowledged"):
        raise LiveAmendmentError("candidate authorization mismatch")
    amendment_path = SPIKE / spec["amendmentPath"]
    if digest_file(amendment_path) != spec["amendmentDigest"]:
        raise LiveAmendmentError("amendment artifact digest mismatch")
    if VERIFY.validate(amendment_path) != spec["identities"]["FixtureDigest"]:
        raise LiveAmendmentError("offline amendment verification failed")
    tool = HERE / spec["toolPath"]
    if digest_file(tool) != spec["toolDigest"]:
        raise LiveAmendmentError("tool digest mismatch")
    return candidate


def execute(candidate_path: Path) -> dict[str, Any]:
    candidate = validate_candidate(candidate_path)
    spec = candidate["spec"]
    client = Path(spec["clientPath"])
    mgmt = Path(spec["managementKubeconfigPath"])
    shared = Path(spec["sharedKubeconfigPath"])
    if digest_file(client) != spec["clientDigest"]:
        raise LiveAmendmentError("client digest mismatch")
    for path in (mgmt, shared):
        if path.is_symlink() or not path.is_file() or stat.S_IMODE(path.stat().st_mode) != 0o600:
            raise LiveAmendmentError("unsafe Kubeconfig")
    output = Path(spec["outputPath"])
    if output.exists() or output.is_symlink():
        raise LiveAmendmentError("exclusive output exists")
    amendment_path = SPIKE / spec["amendmentPath"]
    amendment = json.loads(amendment_path.read_text())["spec"]
    old = amendment["base"]
    new = amendment["identities"]
    apps_path = SPIKE / amendment["platform"]["applicationsPath"]
    desired_apps = {
        item["metadata"]["name"]: item
        for item in yaml.safe_load_all(apps_path.read_text())
        if item
    }
    annotations = {
        "openkubes.io/intent-revision": new["R"],
        "openkubes.io/execution-fixture": new["FixtureDigest"],
    }
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
    prepared: list[tuple[Path, str, str, dict[str, Any], dict[str, Any]]] = []
    for item in lifecycle:
        raw_uri = uri(*item)
        current = raw(client, mgmt, "get", raw_uri)
        existing = current.get("metadata", {}).get("annotations", {})
        if existing.get("openkubes.io/intent-revision") != old["R"]:
            raise LiveAmendmentError("lifecycle old R precondition failed")
        replacement = clean(current)
        replacement["metadata"].setdefault("annotations", {}).update(annotations)
        prepared.append((mgmt, "lifecycle", raw_uri, current, replacement))

    hcp_uri = uri(
        "addons.cluster.x-k8s.io", "v1alpha1", "disposable-ok141",
        "helmchartproxies", "disposable-ok141-cilium",
    )
    hcp = raw(client, mgmt, "get", hcp_uri)
    hcp_annotations = hcp.get("metadata", {}).get("annotations", {})
    if (
        hcp_annotations.get("openkubes.io/intent-revision") != old["R"]
        or hcp_annotations.get("openkubes.io/execution-fixture") != old["fixtureDigest"]
    ):
        raise LiveAmendmentError("HCP old identity precondition failed")
    hcp_replacement = clean(hcp)
    hcp_replacement["metadata"].setdefault("annotations", {}).update(annotations)
    prepared.append((mgmt, "enablement", hcp_uri, hcp, hcp_replacement))

    registration_uri = uri("", "v1", "argocd", "secrets", "disposable-ok141-cluster")
    registration = raw(client, shared, "get", registration_uri)
    registration_annotations = registration.get("metadata", {}).get("annotations", {})
    if (
        registration_annotations.get("openkubes.io/intent-revision") != old["R"]
        or registration_annotations.get("openkubes.io/platform-revision") != old["P"]
        or registration_annotations.get("openkubes.io/execution-fixture") != old["fixtureDigest"]
    ):
        raise LiveAmendmentError("registration old identity precondition failed")
    registration_replacement = clean(registration)
    registration_replacement["metadata"].setdefault("annotations", {}).update({
        **annotations, "openkubes.io/platform-revision": new["P"]
    })
    prepared.append((shared, "registration", registration_uri, registration, registration_replacement))

    for name in (
        "disposable-ok141-observability-core",
        "disposable-ok141-observability-alerting",
        "disposable-ok141-observability-dashboards",
    ):
        app_uri = uri("argoproj.io", "v1alpha1", "argocd", "applications", name)
        current = raw(client, shared, "get", app_uri)
        current_annotations = current.get("metadata", {}).get("annotations", {})
        if (
            current_annotations.get("openkubes.io/intent-revision") != old["R"]
            or current_annotations.get("openkubes.io/platform-revision") != old["P"]
            or current_annotations.get("openkubes.io/execution-fixture") != old["fixtureDigest"]
        ):
            raise LiveAmendmentError("Application old identity precondition failed")
        if current.get("spec", {}).get("source", {}).get("targetRevision") != amendment["platform"]["sourceCommit"]:
            raise LiveAmendmentError("Application source revision changed")
        replacement = clean(current)
        replacement["metadata"].setdefault("annotations", {}).update({
            **annotations, "openkubes.io/platform-revision": new["P"]
        })
        if name.endswith("-core"):
            wanted = desired_apps[name]["spec"]["syncPolicy"]["syncOptions"]
            current_options = current.get("spec", {}).get("syncPolicy", {}).get("syncOptions", [])
            if "ServerSideApply=true" in current_options:
                raise LiveAmendmentError("SSA option already present")
            if sorted(current_options + ["ServerSideApply=true"]) != sorted(wanted):
                raise LiveAmendmentError("core sync-option delta is not exact")
            if current.get("spec", {}).get("source", {}).get("helm", {}).get("valuesObject") != desired_apps[name]["spec"]["source"]["helm"]["valuesObject"]:
                raise LiveAmendmentError("core Provider Values differ from amended profile")
            replacement["spec"]["syncPolicy"]["syncOptions"] = copy.deepcopy(wanted)
        prepared.append((shared, "application", app_uri, current, replacement))

    if len(prepared) != 13:
        raise LiveAmendmentError("prepared object count mismatch")
    evidence = {
        "apiVersion": "evidence.openkubes.io/v1alpha1",
        "kind": "OK141LivePlatformSSAAmendmentEvidence",
        "candidateDigest": digest_file(candidate_path),
        "amendmentDigest": spec["amendmentDigest"],
        "identities": new,
        "preflightObjectCount": len(prepared),
        "updates": [],
        "state": "STARTED",
        "credentialPayloadRetained": False,
        "rawObjectsRetained": False,
        "retryPerformed": False,
        "rollbackOrCleanupPerformed": False,
        "failureInjectionPerformed": False,
    }
    try:
        for kubeconfig, category, raw_uri, current, replacement in prepared:
            uid = current.get("metadata", {}).get("uid")
            resource_version = current.get("metadata", {}).get("resourceVersion")
            if not uid or not resource_version:
                raise LiveAmendmentError("prepared object lacks UID/resourceVersion")
            returned = raw(
                client, kubeconfig, "replace", raw_uri,
                json.dumps(replacement, sort_keys=True, separators=(",", ":")).encode(),
            )
            returned_meta = returned.get("metadata", {})
            if returned_meta.get("uid") != uid or returned_meta.get("resourceVersion") == resource_version:
                raise LiveAmendmentError("optimistic-concurrency postcondition failed")
            evidence["updates"].append({
                "category": category,
                "kindAndName": raw_uri.rsplit("/", 2)[-2] + "/" + raw_uri.rsplit("/", 1)[-1],
                "uidPreserved": True,
                "resourceVersionAdvanced": True,
            })
        evidence["state"] = "PASS-AMENDED"
    except Exception:
        evidence["state"] = "STOP-PARTIAL-STATE-PRESERVED"
        evidence["updatedObjectCount"] = len(evidence["updates"])
        write_evidence = copy.deepcopy(evidence)
        descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as handle:
            json.dump(write_evidence, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
        raise

    observations: list[dict[str, Any]] = []
    final: dict[str, dict[str, Any]] = {}
    app_uris = {
        name: uri("argoproj.io", "v1alpha1", "argocd", "applications", name)
        for name in (
            "disposable-ok141-observability-core",
            "disposable-ok141-observability-alerting",
            "disposable-ok141-observability-dashboards",
        )
    }
    for iteration in range(spec["observation"]["maxIterations"]):
        current = {name: summary(raw(client, shared, "get", app_uri)) for name, app_uri in app_uris.items()}
        observations.append({"iteration": iteration + 1, "applications": current})
        final = current
        if all(item["sync"] == "Synced" and item["health"] == "Healthy" for item in current.values()):
            break
        if iteration + 1 < spec["observation"]["maxIterations"]:
            time.sleep(spec["observation"]["intervalSeconds"])
    converged = all(
        item["sync"] == "Synced" and item["health"] == "Healthy"
        for item in final.values()
    )
    evidence.update({
        "updatedObjectCount": len(evidence["updates"]),
        "coreServerSideApplyConfigured": True,
        "automaticArgoReconciliationAcknowledged": True,
        "observationIterations": len(observations),
        "observationDigest": digest_bytes(
            json.dumps(observations, sort_keys=True, separators=(",", ":")).encode()
        ),
        "finalApplications": final,
        "allApplicationsSyncedHealthy": converged,
        "state": "PASS-PLATFORM-CONVERGED" if converged else "STOP-PLATFORM-NOT-CONVERGED",
    })
    evidence["semanticDigest"] = digest_bytes(
        json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
    )
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        json.dump(evidence, handle, sort_keys=True, separators=(",", ":"))
        handle.write("\n")
    return {
        "state": evidence["state"],
        "evidenceDigest": digest_file(output),
        "updatedObjectCount": evidence["updatedObjectCount"],
        "observationIterations": evidence["observationIterations"],
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
                raise LiveAmendmentError("amend requires --execute")
            print(json.dumps(execute(args.candidate.resolve()), sort_keys=True))
        return 0
    except Exception as error:
        print(f"ERROR: {type(error).__name__}: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
