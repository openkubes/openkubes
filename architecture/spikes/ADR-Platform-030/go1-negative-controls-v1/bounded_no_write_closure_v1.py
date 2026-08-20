#!/usr/bin/env python3
"""Execute the exact-GET and local-only OK-141 negative-control closure."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from verify_negative_controls_v1 import verify


MGMT_PATHS = [
    "/api/v1/namespaces/disposable-ok141",
    "/apis/cluster.x-k8s.io/v1beta2/namespaces/disposable-ok141/clusters/disposable-ok141",
    "/apis/infrastructure.cluster.x-k8s.io/v1alpha1/namespaces/disposable-ok141/kubevirtclusters/disposable-ok141",
    "/apis/controlplane.cluster.x-k8s.io/v1alpha3/namespaces/disposable-ok141/taloscontrolplanes/disposable-ok141-cp",
    "/apis/bootstrap.cluster.x-k8s.io/v1alpha3/namespaces/disposable-ok141/talosconfigtemplates/disposable-ok141-workers-v1-9-6",
    "/apis/cluster.x-k8s.io/v1beta2/namespaces/disposable-ok141/machinedeployments/disposable-ok141-workers",
    "/apis/infrastructure.cluster.x-k8s.io/v1alpha1/namespaces/disposable-ok141/kubevirtmachinetemplates/disposable-ok141-cp-7f5dd4276432",
    "/apis/infrastructure.cluster.x-k8s.io/v1alpha1/namespaces/disposable-ok141/kubevirtmachinetemplates/disposable-ok141-workers-7f5dd4276432",
]

INFRA_PATHS = [
    "/api/v1/namespaces/disposable-ok141",
    "/apis/rbac.authorization.k8s.io/v1/namespaces/ok-images/roles/disposable-ok141-talos-golden-image-cloner",
    "/apis/rbac.authorization.k8s.io/v1/namespaces/ok-images/rolebindings/disposable-ok141-talos-golden-image-cloner",
]


class ClosureError(RuntimeError):
    pass


def digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ClosureError(message)


def require_private(path: Path) -> None:
    mode = stat.S_IMODE(path.stat().st_mode)
    require(mode == 0o600, f"credential file mode is not 0600: {path.name}")


def exact_get(kubectl: Path, kubeconfig: Path, path: str) -> dict[str, Any]:
    completed = subprocess.run(
        [str(kubectl), "--kubeconfig", str(kubeconfig), "get", "--raw", path],
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )
    return json.loads(completed.stdout)


def stable_object(value: dict[str, Any]) -> dict[str, Any]:
    metadata = value.get("metadata", {})
    result: dict[str, Any] = {
        "apiVersion": value.get("apiVersion"),
        "kind": value.get("kind"),
        "name": metadata.get("name"),
        "namespace": metadata.get("namespace", ""),
        "uid": metadata.get("uid"),
        "generation": metadata.get("generation", 0),
    }
    for field in ("spec", "rules", "roleRef", "subjects"):
        if field in value:
            result[field] = value[field]
    return result


def snapshot(kubectl: Path, mgmt: Path, infra: Path) -> str:
    values = [stable_object(exact_get(kubectl, mgmt, path)) for path in MGMT_PATHS]
    values.extend(stable_object(exact_get(kubectl, infra, path)) for path in INFRA_PATHS)
    values.sort(key=lambda item: (item["apiVersion"], item["kind"], item["namespace"], item["name"]))
    require(len(values) == 11, "projected object snapshot count differs")
    require(all(item.get("uid") for item in values), "projected object UID missing")
    return digest(values)


def ready_condition(node: dict[str, Any]) -> bool:
    return any(
        item.get("type") == "Ready" and item.get("status") == "True"
        for item in node.get("status", {}).get("conditions", [])
    )


def health(kubectl: Path, workload: Path, nodes: list[str]) -> dict[str, Any]:
    require(len(nodes) == 2 and len(set(nodes)) == 2, "exactly two distinct Node names are required")
    node_values = [exact_get(kubectl, workload, "/api/v1/nodes/" + name) for name in nodes]
    daemonset = exact_get(kubectl, workload, "/apis/apps/v1/namespaces/kube-system/daemonsets/cilium")
    operator = exact_get(kubectl, workload, "/apis/apps/v1/namespaces/kube-system/deployments/cilium-operator")
    storage = exact_get(kubectl, workload, "/apis/storage.k8s.io/v1/storageclasses/local-path")
    ds_status = daemonset.get("status", {})
    op_status = operator.get("status", {})
    result = {
        "nodesReady": sum(1 for item in node_values if ready_condition(item)),
        "nodesExpected": 2,
        "ciliumDesired": ds_status.get("desiredNumberScheduled", 0),
        "ciliumReady": ds_status.get("numberReady", 0),
        "operatorAvailable": op_status.get("availableReplicas", 0),
        "storageClassPresent": storage.get("metadata", {}).get("name") == "local-path",
    }
    require(result["nodesReady"] == 2, "Node readiness changed")
    require(result["ciliumDesired"] == 2 and result["ciliumReady"] == 2, "Cilium readiness changed")
    require(result["operatorAvailable"] >= 1, "Cilium operator unavailable")
    require(result["storageClassPresent"], "local-path StorageClass missing")
    return result


def resume_args(args: argparse.Namespace, candidate: dict[str, Any], intent_revision: str) -> list[str]:
    bindings = candidate["bindings"]
    command = [
        str(args.runner),
        "cluster", "stage", "resume",
        "--plan", str(args.plan),
        "--contract-namespace", "disposable-ok141",
        "--contract-name", "disposable-ok141",
        "--intent-revision", intent_revision,
        "--enablement-revision", bindings["E"],
        "--platform-revision", bindings["P"],
        "--execution-fixture", bindings["fixtureDigest"],
        "--infrastructure-authority", "ok-infra",
        "--management-authority", "ok-mgmt",
        "--gitops-authority", "ok-shared",
    ]
    for receipt in args.receipt:
        command.extend(["--receipt", receipt])
    return command


def terminal_replay(args: argparse.Namespace, candidate: dict[str, Any]) -> dict[str, Any]:
    wrong = subprocess.run(
        resume_args(args, candidate, "sha256:" + "0" * 64),
        capture_output=True,
        text=True,
        timeout=20,
    )
    require(wrong.returncode != 0, "wrong R was accepted")

    completed = subprocess.run(
        resume_args(args, candidate, candidate["bindings"]["R"]),
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )
    value = json.loads(completed.stdout)
    decision = value.get("decision", {})
    require(decision.get("state") == "COMPLETED", "terminal replay did not complete")
    require(decision.get("completedStages") == 12, "terminal replay stage count differs")
    require(value.get("mutationAllowed") is False, "terminal replay allowed mutation")
    return {
        "wrongRRejected": True,
        "state": decision["state"],
        "completedStages": decision["completedStages"],
        "requiresAuthorization": decision.get("requiresAuthorization"),
        "mutationAllowed": value["mutationAllowed"],
        "decisionDigest": digest(value),
    }


def write_private(path: Path, value: dict[str, Any]) -> None:
    raw = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(descriptor, raw)
    finally:
        os.close(descriptor)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--runner", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--kubectl", type=Path, required=True)
    parser.add_argument("--management-kubeconfig", type=Path, required=True)
    parser.add_argument("--infrastructure-kubeconfig", type=Path, required=True)
    parser.add_argument("--workload-kubeconfig", type=Path, required=True)
    parser.add_argument("--node", action="append", default=[])
    parser.add_argument("--receipt", action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    try:
        candidate = json.loads(args.candidate.read_text())
        candidate_digest = verify(candidate)
        require(len(args.receipt) == 12, "exactly twelve receipt bindings are required")
        require(not args.output.exists(), "output already exists")
        for path in (args.management_kubeconfig, args.infrastructure_kubeconfig, args.workload_kubeconfig):
            require_private(path)

        before = snapshot(args.kubectl, args.management_kubeconfig, args.infrastructure_kubeconfig)
        replay = terminal_replay(args, candidate)
        after = snapshot(args.kubectl, args.management_kubeconfig, args.infrastructure_kubeconfig)
        require(before == after, "projected object snapshot changed")
        health_result = health(args.kubectl, args.workload_kubeconfig, args.node)

        evidence: dict[str, Any] = {
            "format": "ok141-nondestructive-negative-controls-closure/v1",
            "candidateDigest": candidate_digest,
            "state": "PASS",
            "projectedObjectCount": 11,
            "beforeSnapshotDigest": before,
            "afterSnapshotDigest": after,
            "snapshotsEqual": True,
            "terminalReplay": replay,
            "health": health_result,
            "clusterMutationPerformed": False,
            "credentialContentRetained": False,
            "completedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        evidence["evidenceDigest"] = digest(evidence)
        write_private(args.output, evidence)
        print(evidence["evidenceDigest"])
        return 0
    except (ClosureError, OSError, json.JSONDecodeError, subprocess.SubprocessError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
