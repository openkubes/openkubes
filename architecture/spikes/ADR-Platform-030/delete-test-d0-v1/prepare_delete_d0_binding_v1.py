#!/usr/bin/env python3
"""Prepare a private, time-bounded D0 runtime binding for OK-141 deletion."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any
import yaml


class BindingError(ValueError):
    pass


EXPECTED_QUERY_IDS = {
    "ok-shared": (
        "application-core",
        "application-alerting",
        "application-dashboards",
        "registration-secret",
        "app-project",
        "project-applications",
    ),
    "ok-mgmt": (
        "management-namespace",
        "provider-access-secret",
        "capi-cluster",
        "kubevirt-cluster",
        "talos-control-plane",
        "talos-worker-template",
        "machine-deployment",
        "control-plane-machine-template",
        "worker-machine-template",
        "helm-chart-proxy",
        "helm-release-proxy",
        "machines",
        "machine-sets",
        "kubevirt-machines",
        "talos-configs",
    ),
    "ok-infra": (
        "provider-namespace",
        "golden-image-role",
        "golden-image-role-binding",
        "load-balancer-service",
        "virtual-machines",
        "virtual-machine-instances",
        "data-volumes",
        "provider-pvcs",
        "provider-pvs",
        "provider-longhorn-volumes",
    ),
    "workload": (
        "platform-namespace",
        "target-cluster-role",
        "target-cluster-role-binding",
        "platform-pvcs",
        "platform-pvs",
    ),
}
EXPECTED_QUERY_PROFILE_DIGEST = "sha256:21175b2a181e05019eea8024240b6f6c7ee0ba86c9ab0c8d6f3bc0b8eaa0670c"


def sha256_bytes(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def file_digest(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_digest(value: object) -> str:
    return sha256_bytes(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def read_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text())
    if not isinstance(value, dict):
        raise BindingError(f"{path}: expected one YAML object")
    return value


def parse_time(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise BindingError("timestamp lacks timezone")
    return parsed.astimezone(dt.timezone.utc)


def verify_candidate(path: Path) -> dict[str, Any]:
    candidate = read_yaml(path)
    spec = candidate.get("spec", {})
    errors: list[str] = []
    if spec.get("version") != "ok141-delete-d0-binding/v1":
        errors.append("candidate version mismatch")
    if spec.get("state") != "READY-FOR-EXPLICIT-READ-ONLY-GRANT":
        errors.append("candidate is not fail-closed")
    protocol = spec.get("protocol", {})
    if protocol.get("semanticDigest") != "sha256:4cd457c5f40bdf3ae871cbe56ba7c151f7ac3242bd73129557f25cf620a2d0bc":
        errors.append("delete protocol semantic digest mismatch")
    if protocol.get("fileDigest") != "sha256:f63a9a1fd2f46d7f8995f95e6ba75138053f9cc9b4c93467184510ec5899b989":
        errors.append("delete protocol file digest mismatch")
    tool = spec.get("tool", {})
    if tool.get("executorDigest") != file_digest(Path(__file__).resolve()):
        errors.append("executor digest mismatch")
    if tool.get("kubectlDigest") != "sha256:bb211f2b31f2b3bc60562b44cc1e3b712a16a98e9072968ba255beb04cefcfdf":
        errors.append("kubectl digest mismatch")
    if tool.get("queryProfileDigest") != EXPECTED_QUERY_PROFILE_DIGEST:
        errors.append("declared query profile digest mismatch")
    if tool.get("discoveryAllowed") or tool.get("watchAllowed") or tool.get("mutationAllowed"):
        errors.append("tool grants forbidden behavior")

    planes = spec.get("planes", {})
    if set(planes) != set(EXPECTED_QUERY_IDS):
        errors.append("plane set mismatch")
    for plane, ids in EXPECTED_QUERY_IDS.items():
        plane_spec = planes.get(plane, {})
        kubeconfig = plane_spec.get("kubeconfigPath", "")
        if not kubeconfig.startswith("/Users/arash/.kube/"):
            errors.append(f"{plane}: unexpected kubeconfig path")
        queries = plane_spec.get("queries", [])
        if tuple(query.get("id") for query in queries) != ids:
            errors.append(f"{plane}: query profile mismatch")
        for query in queries:
            uri = query.get("rawURI", "")
            if not uri.startswith(("/api/", "/apis/")):
                errors.append(f"{plane}/{query.get('id')}: invalid raw URI")
            if query.get("method") != "GET":
                errors.append(f"{plane}/{query.get('id')}: non-GET method")
            if query.get("expectedCount", -1) < 0:
                errors.append(f"{plane}/{query.get('id')}: expected count missing")
            if query.get("collection") and not query.get("postFilter") and "labelSelector=" not in uri:
                errors.append(f"{plane}/{query.get('id')}: unbounded collection")
    query_profile = {plane: plane_spec.get("queries", []) for plane, plane_spec in planes.items()}
    if canonical_digest(query_profile) != EXPECTED_QUERY_PROFILE_DIGEST:
        errors.append("query profile content digest mismatch")

    evidence = spec.get("privateOutputs", {})
    if evidence.get("bindingPath") != "/private/tmp/ok141-delete-d0-runtime-binding-v1.json":
        errors.append("private binding path mismatch")
    if evidence.get("evidencePath") != "/private/tmp/ok141-delete-d0-evidence-v1.json":
        errors.append("private evidence path mismatch")
    if evidence.get("mode") != "0600" or evidence.get("maximumBindingAgeMinutes") != 10:
        errors.append("private output boundary mismatch")

    auth = spec.get("authorization", {})
    if auth.get("decision") != "NO-GO":
        errors.append("candidate authorization is not NO-GO")
    if any(value is not False for key, value in auth.items() if key.endswith("Granted")):
        errors.append("candidate grants authority")
    if errors:
        raise BindingError("; ".join(errors))
    return candidate


def verify_grant(candidate_path: Path, grant_path: Path, now: dt.datetime | None = None) -> dict[str, Any]:
    candidate = verify_candidate(candidate_path)
    grant = read_yaml(grant_path)
    spec = grant.get("spec", {})
    errors: list[str] = []
    if spec.get("state") != "GRANTED":
        errors.append("grant state mismatch")
    if spec.get("candidateDigest") != file_digest(candidate_path):
        errors.append("grant candidate digest mismatch")
    if spec.get("maximumRuns") != 1 or spec.get("consumed") is not False:
        errors.append("grant is not fresh and single-use")
    for key in ("readOnlyAuthorized", "credentialUseAuthorized", "secretMetadataReadAuthorized"):
        if spec.get(key) is not True:
            errors.append(f"{key} is required")
    for key in (
        "mutationAuthorized",
        "deleteAuthorized",
        "cleanupAuthorized",
        "retryAuthorized",
        "rollbackAuthorized",
        "outageAuthorized",
        "failureInjectionAuthorized",
        "publicationAuthorized",
    ):
        if spec.get(key) is not False:
            errors.append(f"{key} must be false")
    current = now or dt.datetime.now(dt.timezone.utc)
    start = parse_time(spec.get("notBefore", ""))
    end = parse_time(spec.get("notAfter", ""))
    if not start <= current <= end or (end - start).total_seconds() > 1200:
        errors.append("grant window is inactive or exceeds twenty minutes")
    outputs = candidate["spec"]["privateOutputs"]
    if spec.get("bindingPath") != outputs["bindingPath"] or spec.get("evidencePath") != outputs["evidencePath"]:
        errors.append("grant output paths differ")
    if errors:
        raise BindingError("; ".join(errors))
    return grant


def safe_metadata(item: dict[str, Any]) -> dict[str, Any]:
    metadata = item.get("metadata", {})
    retained = {
        "apiVersion": item.get("apiVersion"),
        "kind": item.get("kind"),
        "name": metadata.get("name"),
        "namespace": metadata.get("namespace"),
        "uid": metadata.get("uid"),
        "resourceVersion": metadata.get("resourceVersion"),
        "generation": metadata.get("generation"),
        "deletionTimestamp": metadata.get("deletionTimestamp"),
        "finalizers": metadata.get("finalizers", []),
        "ownerReferences": [
            {"apiVersion": owner.get("apiVersion"), "kind": owner.get("kind"), "name": owner.get("name"), "uid": owner.get("uid")}
            for owner in metadata.get("ownerReferences", [])
        ],
    }
    if item.get("kind") == "Secret":
        retained["dataKeys"] = sorted((item.get("data") or {}).keys())
    if item.get("kind") == "PersistentVolume":
        spec = item.get("spec", {})
        retained["storage"] = {
            "claimRef": {key: spec.get("claimRef", {}).get(key) for key in ("namespace", "name", "uid")},
            "reclaimPolicy": spec.get("persistentVolumeReclaimPolicy"),
            "storageClassName": spec.get("storageClassName"),
            "volumeHandle": spec.get("csi", {}).get("volumeHandle"),
            "phase": item.get("status", {}).get("phase"),
        }
    if item.get("kind") == "Volume" and item.get("apiVersion", "").startswith("longhorn.io/"):
        retained["longhorn"] = {
            "state": item.get("status", {}).get("state"),
            "robustness": item.get("status", {}).get("robustness"),
            "fromBackup": item.get("spec", {}).get("fromBackup"),
        }
    if item.get("kind") == "Application":
        retained["application"] = {
            "project": item.get("spec", {}).get("project"),
            "sync": item.get("status", {}).get("sync", {}).get("status"),
            "health": item.get("status", {}).get("health", {}).get("status"),
            "automated": item.get("spec", {}).get("syncPolicy", {}).get("automated") is not None,
        }
    return retained


def apply_post_filter(items: list[dict[str, Any]], query: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
    rule = query.get("postFilter")
    if not rule:
        return items
    if rule == "application-project:openkubes-disposable":
        return [item for item in items if item.get("spec", {}).get("project") == "openkubes-disposable"]
    if rule == "claim-namespace:disposable-ok141":
        return [item for item in items if item.get("spec", {}).get("claimRef", {}).get("namespace") == "disposable-ok141"]
    if rule == "claim-namespace:ok-observability":
        return [item for item in items if item.get("spec", {}).get("claimRef", {}).get("namespace") == "ok-observability"]
    if rule == "metadata-namespace:disposable-ok141":
        return [item for item in items if item.get("metadata", {}).get("namespace") == "disposable-ok141"]
    if rule == "metadata-namespace:ok-observability":
        return [item for item in items if item.get("metadata", {}).get("namespace") == "ok-observability"]
    if rule == "derived:provider-pv-volume-handles":
        handles = context.get("providerVolumeHandles", set())
        return [item for item in items if item.get("metadata", {}).get("name") in handles]
    raise BindingError(f"unsupported post-filter {rule}")


def run_query(kubectl: Path, kubeconfig: Path, query: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
    command = [str(kubectl), "--kubeconfig", str(kubeconfig), "get", "--raw", query["rawURI"]]
    completed = subprocess.run(command, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
    if completed.returncode != 0:
        raise BindingError(f"{query['id']}: exact GET failed")
    if len(completed.stdout) > 5 * 1024 * 1024:
        raise BindingError(f"{query['id']}: response exceeds bound")
    value = json.loads(completed.stdout)
    items = value.get("items") if query.get("collection") else [value]
    if not isinstance(items, list):
        raise BindingError(f"{query['id']}: invalid response shape")
    items = apply_post_filter(items, query, context)
    if len(items) != query["expectedCount"]:
        raise BindingError(f"{query['id']}: expected {query['expectedCount']} objects, got {len(items)}")
    retained = [safe_metadata(item) for item in items]
    if query["id"] == "provider-pvs":
        context["providerVolumeHandles"] = {
            item.get("storage", {}).get("volumeHandle") for item in retained if item.get("storage", {}).get("volumeHandle")
        }
    return retained


def write_exclusive_json(path: Path, value: object) -> None:
    if path.parent != Path("/private/tmp") or path.exists():
        raise BindingError(f"unsafe or existing private output: {path}")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(value, stream, sort_keys=True, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        if path.exists():
            path.chmod(0o600)


def snapshot(candidate_path: Path, grant_path: Path, kubectl: Path) -> dict[str, Any]:
    candidate = verify_candidate(candidate_path)
    grant = verify_grant(candidate_path, grant_path)
    if file_digest(kubectl) != candidate["spec"]["tool"]["kubectlDigest"]:
        raise BindingError("kubectl binary digest mismatch")
    context: dict[str, Any] = {}
    started = dt.datetime.now(dt.timezone.utc)
    planes: dict[str, Any] = {}
    for plane, plane_spec in candidate["spec"]["planes"].items():
        kubeconfig = Path(plane_spec["kubeconfigPath"])
        if kubeconfig.is_symlink() or not kubeconfig.is_file() or stat.S_IMODE(kubeconfig.stat().st_mode) != 0o600:
            raise BindingError(f"{plane}: unsafe kubeconfig")
        planes[plane] = {
            query["id"]: run_query(kubectl, kubeconfig, query, context)
            for query in plane_spec["queries"]
        }
    completed = dt.datetime.now(dt.timezone.utc)
    binding = {
        "format": "ok141-delete-d0-runtime-binding/v1",
        "state": "CURRENT-PRIVATE-BOUND-NO-GO",
        "candidateDigest": file_digest(candidate_path),
        "grantID": grant["spec"]["grantID"],
        "observedAt": completed.isoformat(),
        "expiresAt": (completed + dt.timedelta(minutes=10)).isoformat(),
        "planes": planes,
        "credentialContentRetained": False,
        "mutationPerformed": False,
        "deletePerformed": False,
    }
    binding_path = Path(candidate["spec"]["privateOutputs"]["bindingPath"])
    write_exclusive_json(binding_path, binding)
    evidence = {
        "format": "ok141-delete-d0-private-evidence/v1",
        "state": "PASS-D0-PRIVATE-BOUND-NO-GO",
        "candidateDigest": file_digest(candidate_path),
        "grantID": grant["spec"]["grantID"],
        "startedAt": started.isoformat(),
        "completedAt": completed.isoformat(),
        "bindingDigest": file_digest(binding_path),
        "planeCounts": {plane: sum(len(items) for items in queries.values()) for plane, queries in planes.items()},
        "secretValuesRetained": False,
        "rawResponsesRetained": False,
        "mutationPerformed": False,
        "deletePerformed": False,
    }
    write_exclusive_json(Path(candidate["spec"]["privateOutputs"]["evidencePath"]), evidence)
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "verify-grant", "snapshot"))
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--grant", type=Path)
    parser.add_argument("--kubectl", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "verify":
            candidate = verify_candidate(args.candidate.resolve())
            print(json.dumps({"state": "PASS-D0-CANDIDATE-OFFLINE-NO-GO", "candidateDigest": file_digest(args.candidate.resolve()), "semanticDigest": canonical_digest(candidate)}, sort_keys=True))
        elif args.command == "verify-grant":
            if args.grant is None:
                raise BindingError("grant is required")
            verify_grant(args.candidate.resolve(), args.grant.resolve())
            print(file_digest(args.grant.resolve()))
        else:
            if not args.execute or args.grant is None or args.kubectl is None:
                raise BindingError("snapshot requires --execute, --grant and --kubectl")
            print(json.dumps(snapshot(args.candidate.resolve(), args.grant.resolve(), args.kubectl.resolve()), sort_keys=True))
        return 0
    except (BindingError, OSError, ValueError, json.JSONDecodeError, subprocess.SubprocessError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
