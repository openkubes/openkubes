#!/usr/bin/env python3
"""Fail-closed offline verifier for the OK-141 delete-test preparation."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import yaml


PASS = "PASS-DELETE-PREPARATION-OFFLINE-NO-GO"
EXPECTED_STAGES = ["D0", "D1", "D2", "D3", "D4", "D5", "D6", "D7"]


def canonical_digest(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def load_yaml(path: Path) -> dict:
    value = yaml.safe_load(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected one YAML object")
    return value


def verify(protocol_path: Path, observation_path: Path, publication_path: Path) -> dict:
    protocol = load_yaml(protocol_path)
    observation = load_yaml(observation_path)
    publication = load_yaml(publication_path)
    spec = protocol.get("spec", {})
    observed = observation.get("spec", {})
    errors: list[str] = []

    if spec.get("state") != "OFFLINE-PREPARED-BLOCKED-NO-GO":
        errors.append("protocol state is not fail-closed NO-GO")
    if observed.get("state") != "PASS-READ-ONLY-INVENTORY-NO-GO":
        errors.append("read-only observation state is not accepted")

    stages = spec.get("stages", [])
    if [stage.get("id") for stage in stages] != EXPECTED_STAGES:
        errors.append("stage order must be D0 through D7")
    if any(stage.get("enabled") is not False for stage in stages):
        errors.append("every stage must remain disabled")

    by_id = {stage.get("id"): stage for stage in stages}
    d1_order = by_id.get("D1", {}).get("order", [])
    if len(d1_order) != 5 or "Secret|argocd|disposable-ok141-cluster" not in d1_order[3]:
        errors.append("D1 must quiesce three Applications before registration")
    if by_id.get("D2", {}).get("target", "").split("|")[1:3] != ["HelmChartProxy", "disposable-ok141"]:
        errors.append("D2 must target the exact HelmChartProxy")
    if by_id.get("D3", {}).get("target") != "cluster.x-k8s.io/v1beta2|Cluster|disposable-ok141|disposable-ok141":
        errors.append("D3 must delete only the authoritative CAPI Cluster")
    if "external-infra-kubeconfig-disposable-ok141" not in " ".join(by_id.get("D3", {}).get("retainedDuringStage", [])):
        errors.append("provider credential must be retained during CAPI deletion")

    d5 = by_id.get("D5", {})
    if "both exact Released provider PersistentVolumes" not in d5.get("order", []):
        errors.append("D5 must close Retain-policy PVs")
    if "both exact detached correlated Longhorn Volumes" not in d5.get("order", []):
        errors.append("D5 must close correlated Longhorn volumes")
    d6_order = by_id.get("D6", {}).get("order", [])
    if not d6_order or "external-infra-kubeconfig-disposable-ok141" not in d6_order[0]:
        errors.append("provider credential must be removed only in D6")

    auth = spec.get("authorization", {})
    if auth.get("decision") != "NO-GO":
        errors.append("authorization decision must remain NO-GO")
    if any(value is not False for key, value in auth.items() if key.endswith("Granted")):
        errors.append("no permission may be granted by the preparation")

    exclusions = " ".join(spec.get("exclusions", [])).lower()
    if "force deletion" not in exclusions or "finalizer manipulation" not in exclusions:
        errors.append("force delete and finalizer mutation must be excluded")
    if spec.get("excludedSharedInfrastructure", {}).get("deletionAllowed") is not False:
        errors.append("shared ok147 infrastructure must be preserved")

    gitops = observed.get("gitOpsPlane", {})
    if gitops.get("applicationCount") != 3 or gitops.get("allDeletionFinalizersAbsent") is not True:
        errors.append("the exact three finalizer-free Applications are required")
    if gitops.get("exclusiveAppProjectMembership") is not True:
        errors.append("the disposable AppProject must have exclusive membership")
    storage = observed.get("infrastructurePlane", {}).get("retainedProviderStorage", {})
    if storage.get("persistentVolumes") != 2 or storage.get("reclaimPolicy") != "Retain":
        errors.append("the two Retain-policy provider PVs must be modeled")
    if storage.get("longhornVolumes") != 2:
        errors.append("the two correlated Longhorn volumes must be modeled")

    publication_spec = publication.get("spec", {})
    if publication_spec.get("state") != "PREPARED-NOT-AUTHORIZED":
        errors.append("publication candidate must remain not authorized")
    bindings = publication_spec.get("bindings", {})
    if bindings.get("protocolSemanticDigest") != canonical_digest(protocol):
        errors.append("publication protocol binding does not match")
    if bindings.get("protocolFileDigest") != file_digest(protocol_path):
        errors.append("publication protocol file binding does not match")
    if bindings.get("observationSemanticDigest") != canonical_digest(observation):
        errors.append("publication observation binding does not match")
    if bindings.get("observationFileDigest") != file_digest(observation_path):
        errors.append("publication observation file binding does not match")
    if bindings.get("offlineTestsPassed") != 11:
        errors.append("publication candidate must bind eleven offline tests")
    publication_auth = publication_spec.get("authorization", {})
    if any(value is not False for key, value in publication_auth.items() if key.endswith("Granted")):
        errors.append("publication candidate grants authority")

    if errors:
        raise ValueError("; ".join(errors))
    return {
        "state": PASS,
        "protocolDigest": canonical_digest(protocol),
        "observationDigest": canonical_digest(observation),
        "publicationCandidateDigest": canonical_digest(publication),
        "stageCount": len(stages),
        "mutationAuthorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--observation", type=Path, required=True)
    parser.add_argument("--publication-candidate", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            verify(args.protocol, args.observation, args.publication_candidate),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
