#!/usr/bin/env python3
"""Fail-closed verifier for the nine OK-141 live-observation obligations."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import yaml


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


OBSERVER = _load("ok141_live_observer_verify", HERE / "live_observer.py")
INSTALLER = _load(
    "ok141_live_closure_installer",
    SPIKE / "installation-closure" / "bounded_installer.py",
)
V1 = INSTALLER.V1

EXPECTED_RESULTS = {
    "M0AI-BASELINE-LIVE": "OBSERVED-REPEATABLE-PREFLIGHT",
    "M0AI-COMPATIBILITY-CURRENT-TUPLE": "OBSERVED-PARTIAL",
    "M0AI-EVIDENCE-DESTINATION-LIVE": "UNRESOLVED",
    "M0AI-RECOVERY-EVIDENCE-LIVE": "OBSERVED-NO-RECOVERY-EVIDENCE",
    "M0BI-BASELINE-LIVE": "OBSERVED-REPEATABLE-PREFLIGHT",
    "M0BI-CAPACITY-TOPOLOGY-LIVE": "OBSERVED-PARTIAL",
    "M0BI-COMPATIBILITY-CURRENT-TUPLE": "OBSERVED-REPEATABLE-PREFLIGHT",
    "M0BI-EVIDENCE-DESTINATION-LIVE": "UNRESOLVED",
    "M0BI-RECOVERY-EVIDENCE-LIVE": "OBSERVED-NO-RECOVERY-EVIDENCE",
}


def _expect(actual: Any, expected: Any, claim: str) -> None:
    if actual != expected:
        raise OBSERVER.ObservationError(f"live closure {claim} mismatch")


def _resolve(base: Path, requested: str) -> Path:
    candidate = (base.parent / requested).resolve()
    if SPIKE.resolve() not in candidate.parents or not candidate.is_file():
        raise OBSERVER.ObservationError(
            f"live closure reference missing or outside spike root: {requested}"
        )
    return candidate


def _index(items: list[dict[str, Any]], claim: str) -> dict[str, dict[str, Any]]:
    indexed = {item.get("id"): item for item in items}
    if None in indexed or len(indexed) != len(items):
        raise OBSERVER.ObservationError(
            f"live closure {claim} contains missing or duplicate IDs"
        )
    return indexed


def _evidence(path: Path, plane: str) -> dict[str, Any]:
    document = V1.read_yaml_or_json(path)
    _expect(document["kind"], "LivePlaneEvidence", f"{plane} evidence kind")
    spec = document["spec"]
    _expect(spec["plane"], plane, f"{plane} identity")
    _expect(spec["operation"], "READ-ONLY", f"{plane} operation")
    _expect((spec["clusterContacted"], spec["mutationAuthorized"]), (True, False), f"{plane} safety")
    return spec


def validate(document: dict[str, Any], results_path: Path) -> str:
    schema = json.loads((HERE / "live-closure-results-v1.schema.json").read_text())
    V1.normalize(document, schema)
    spec = document["spec"]
    _expect(spec["state"], "EVALUATED-NO-GO", "state")

    authorization = spec["authorization"]
    _expect(authorization["decision"], "NO-GO", "decision")
    for field in (
        "mutationAuthorized",
        "m0aInstallationGranted",
        "m0bInstallationGranted",
        "go1Granted",
    ):
        _expect(authorization[field], False, f"authorization {field}")

    for reference in ("sourceMatrix", "priorOfflineResults"):
        path = _resolve(results_path, spec[reference]["path"])
        _expect(V1.sha256_bytes(path.read_bytes()), spec[reference]["digest"], f"{reference} digest")

    artifacts = spec["artifacts"]
    _expect(set(artifacts), {"observer", "management", "shared", "providerRecovery"}, "artifact membership")
    paths = {}
    for name, claim in artifacts.items():
        path = _resolve(results_path, claim["path"])
        _expect(V1.sha256_bytes(path.read_bytes()), claim["digest"], f"artifact {name}")
        paths[name] = path

    matrix = V1.read_yaml_or_json(
        _resolve(results_path, spec["sourceMatrix"]["path"])
    )
    live_ids = {
        obligation["id"]
        for blocker in matrix["spec"]["blockers"]
        for obligation in blocker["obligations"]
        if obligation["class"] == "LIVE-OBSERVATION"
    }
    _expect(live_ids, set(EXPECTED_RESULTS), "source live-obligation coverage")

    results = _index(spec["results"], "results")
    _expect({item_id: item["result"] for item_id, item in results.items()}, EXPECTED_RESULTS, "result classification")
    for result_id, result in results.items():
        if not result.get("claim") or not result.get("boundary"):
            raise OBSERVER.ObservationError(f"live closure {result_id} lacks claim or boundary")
        if not result.get("evidence") or any(name not in artifacts for name in result["evidence"]):
            raise OBSERVER.ObservationError(f"live closure {result_id} has invalid evidence")

    _expect(spec["summary"]["evaluated"], 9, "evaluated count")
    _expect(
        spec["summary"]["byResult"],
        dict(Counter(EXPECTED_RESULTS.values())),
        "result counts",
    )
    _expect(spec["summary"]["sourceBlockersClosed"], 0, "source blockers closed")
    _expect(spec["summary"]["installationGatesGranted"], 0, "gates granted")

    if set(OBSERVER.PLANES) != {"ok-mgmt", "ok-shared"}:
        raise OBSERVER.ObservationError("live closure observer plane surface changed")
    if not OBSERVER.READS or any(command[0] != "get" for command in OBSERVER.READS.values()):
        raise OBSERVER.ObservationError("live closure observer contains a non-read command")

    management = _evidence(paths["management"], "ok-mgmt")
    _expect(management["identity"]["kubernetesVersion"], "v1.34.1", "management Kubernetes")
    _expect(management["identity"]["platform"], "linux/amd64", "management platform")
    _expect(management["topology"]["controlPlaneNodes"], 1, "management control-plane count")
    _expect(management["topology"]["readyNodes"], 3, "management ready Nodes")
    _expect(management["topology"]["availabilityProfile"], "development-single-control-plane", "management availability profile")
    _expect(management["topology"]["highAvailabilityRequired"], False, "management HA requirement")
    _expect(management["topology"]["totalManagementStateLossAccepted"], True, "management loss acceptance")
    _expect(management["currentTuple"], {
        "capi": "v1.13.4", "capk": "v0.11.2", "talosBootstrapProvider": "v0.6.12",
        "talosControlPlaneProvider": "v0.5.13", "certManager": "v1.20.1", "kubernetes": "v1.34.1"
    }, "management current tuple")
    _expect(
        management["caaphAbsence"],
        {
            "namespacePresent": False,
            "helmChartProxyCRDPresent": False,
            "helmReleaseProxyCRDPresent": False,
            "helmChartProxyAPIQuery": "NO_MATCH",
            "helmReleaseProxyAPIQuery": "NO_MATCH",
            "caaphControllerWorkloads": 0,
        },
        "CAAPH absence",
    )
    _expect(management["recovery"]["result"], "OBSERVED-ABSENT-DEV-RISK-ACCEPTANCE-REQUIRED", "management recovery")
    _expect(management["recovery"]["strategy"], "rebuild-not-restore", "management recovery strategy")
    _expect(management["recovery"]["rebuildPathProven"], False, "management rebuild proof")
    _expect(management["recovery"]["workloadAdoptionClaimAllowed"], False, "management adoption claim")
    _expect(management["evidenceDestination"]["result"], "UNRESOLVED", "management evidence destination")

    shared = _evidence(paths["shared"], "ok-shared")
    _expect(shared["identity"]["kubernetesVersion"], "v1.34.1", "shared Kubernetes")
    _expect(shared["identity"]["platform"], "linux/amd64", "shared platform")
    _expect((shared["topology"]["controlPlaneNodes"], shared["topology"]["workerNodes"]), (1, 3), "shared topology")
    _expect(shared["topology"]["availabilityProfile"], "development-single-control-plane", "shared availability profile")
    _expect(shared["topology"]["highAvailabilityRequired"], False, "shared HA requirement")
    _expect(shared["topology"]["totalClusterStateLossAccepted"], True, "shared loss acceptance")
    _expect(shared["topology"]["productionHAClaimAllowed"], False, "shared production HA")
    _expect(shared["topology"]["etcdMembersDirectlyObserved"], False, "shared etcd evidence")
    _expect(len(shared["capacity"]["nodes"]), 4, "shared capacity node coverage")
    _expect(shared["argocdAbsence"], {"namespacePresent": False, "argoprojCRDs": 0, "argocdControllerWorkloads": 0}, "Argo absence")
    _expect(shared["compatibilityCorrelation"]["upstreamTestedKubernetesVersion"], True, "Argo version correlation")
    _expect(shared["recovery"]["result"], "OBSERVED-ABSENT-DEV-RISK-ACCEPTANCE-REQUIRED", "shared recovery")
    _expect(shared["recovery"]["strategy"], "rebuild-not-restore", "shared recovery strategy")
    _expect(shared["recovery"]["rebuildPathProven"], False, "shared rebuild proof")
    _expect(shared["evidenceDestination"]["result"], "UNRESOLVED", "shared evidence destination")

    provider = V1.read_yaml_or_json(paths["providerRecovery"])["spec"]
    _expect((provider["operation"], provider["mutationAuthorized"]), ("READ-ONLY", False), "provider safety")
    _expect(len(provider["resources"]["ok-mgmt"]["virtualMachines"]), 3, "provider management VM count")
    _expect(len(provider["resources"]["ok-shared"]["virtualMachines"]), 4, "provider shared VM count")
    _expect(provider["snapshotInventory"], {"virtualMachineSnapshots": 0, "virtualMachineRestores": 0, "volumeSnapshots": 0}, "provider snapshot inventory")
    _expect(
        provider["developmentPolicy"],
        {
            "highAvailabilityRequired": False,
            "providerSnapshotsRequired": False,
            "totalStateLossAccepted": True,
            "intendedRecoveryMode": "rebuild-not-restore",
            "rebuildPathProven": False,
        },
        "provider development policy",
    )

    rules = " ".join(spec["rules"]).lower()
    for phrase in (
        "never closes its composite source blocker",
        "refreshed immediately before",
        "remain fail closed",
        "not evidence of backup",
        "development profile may accept total state loss",
        "no observation authorizes installation",
    ):
        if phrase not in rules:
            raise OBSERVER.ObservationError(f"live closure safety rule missing: {phrase}")
    return V1.sha256_bytes(results_path.read_bytes())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--digest-file", type=Path)
    args = parser.parse_args()
    try:
        path = args.results.resolve()
        digest = validate(V1.read_yaml_or_json(path), path)
        if args.digest_file:
            expected = args.digest_file.read_text().split()[0]
            _expect(digest.removeprefix("sha256:"), expected, "raw results digest")
        print(digest)
        return 0
    except (OBSERVER.ObservationError, OSError, ValueError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
