#!/usr/bin/env python3
"""Bounded exact-GET observer after the OK-141 exact RBAC remediation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path

import yaml


CLIENT = Path("/private/tmp/ok141-kubectl-v1.34.1-darwin-amd64")
KUBECONFIG = Path("/Users/arash/.kube/ok-shared.yaml")


class ObserverError(RuntimeError):
    pass


def sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def get(uri: str) -> dict:
    result = subprocess.run(
        [str(CLIENT), "--kubeconfig", str(KUBECONFIG), "get", "--raw", uri],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise ObserverError("exact Application GET failed")
    return json.loads(result.stdout)


def summary(value: dict, spec: dict) -> dict:
    expected = spec["expected"]
    metadata, status = value.get("metadata", {}), value.get("status", {})
    annotations = metadata.get("annotations", {})
    sync, health = status.get("sync", {}), status.get("health", {})
    reconciled = status.get("reconciledAt")
    condition_types = sorted({item.get("type", "UNKNOWN") for item in status.get("conditions") or []})
    blocking = sorted(set(condition_types) & set(spec["blockingConditionTypes"]))
    advisory = sorted(set(condition_types) & set(spec["advisoryConditionTypes"]))
    unclassified = sorted(set(condition_types) - set(blocking) - set(advisory))
    identity_current = (
        annotations.get("openkubes.io/intent-revision") == expected["R"]
        and annotations.get("openkubes.io/platform-revision") == expected["P"]
        and annotations.get("openkubes.io/execution-fixture") == expected["fixtureDigest"]
    )
    fresh = bool(reconciled and parse_time(reconciled) >= parse_time(expected["minimumReconciledAt"]))
    ready = (
        identity_current
        and fresh
        and sync.get("status") == "Synced"
        and sync.get("revision") == expected["sourceRevision"]
        and health.get("status") == "Healthy"
        and not blocking
        and not unclassified
    )
    return {
        "name": metadata.get("name"),
        "identityCurrent": identity_current,
        "fresh": fresh,
        "sync": sync.get("status", "Unknown"),
        "sourceRevisionCurrent": sync.get("revision") == expected["sourceRevision"],
        "health": health.get("status", "Unknown"),
        "blockingConditionTypes": blocking,
        "advisoryConditionTypes": advisory,
        "unclassifiedConditionTypes": unclassified,
        "ready": ready,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, required=True)
    args = parser.parse_args()
    candidate = yaml.safe_load(args.candidate.read_text())
    spec = candidate["spec"]
    output = Path(spec["outputPath"])
    try:
        allowed_sources = {"standing-dev-execution-envelope-v1", "explicit-user-grant-and-standing-dev-envelope"}
        if spec["authorization"].get("state") != "GRANTED" or spec["authorization"].get("source") not in allowed_sources or spec["authorization"].get("envelopeDigest") != "sha256:85e997df331d2ced4ea147c32cc4a94a419e9efdba6de17d8a8ef3cb1dbeac93":
            raise ObserverError("authorization mismatch")
        predecessor = Path(spec["predecessor"]["path"])
        predecessor_value = json.loads(predecessor.read_text())
        if sha(predecessor) != spec["predecessor"]["digest"] or predecessor_value.get("state") != spec["predecessor"]["state"]:
            raise ObserverError("predecessor mismatch")
        if sha(CLIENT) != "sha256:bb211f2b31f2b3bc60562b44cc1e3b712a16a98e9072968ba255beb04cefcfdf":
            raise ObserverError("client mismatch")
        if KUBECONFIG.is_symlink() or not KUBECONFIG.is_file() or (KUBECONFIG.stat().st_mode & 0o777) != 0o600:
            raise ObserverError("unsafe kubeconfig")
        if output.exists() or output.is_symlink():
            raise ObserverError("exclusive output exists")
        history, final = [], []
        for iteration in range(1, spec["polling"]["maxIterations"] + 1):
            final = [
                summary(
                    get(f"/apis/argoproj.io/v1alpha1/namespaces/argocd/applications/{name}"),
                    spec,
                )
                for name in spec["applications"]
            ]
            history.append(sum(item["ready"] for item in final))
            if all(item["ready"] for item in final):
                break
            if iteration < spec["polling"]["maxIterations"]:
                time.sleep(spec["polling"]["intervalSeconds"])
        evidence = {
            "apiVersion": "evidence.openkubes.io/v1alpha1",
            "kind": "GO1PostExactRBACObserverEvidence",
            "candidateDigest": sha(args.candidate),
            "predecessorDigest": spec["predecessor"]["digest"],
            "applications": final,
            "readyCount": sum(item["ready"] for item in final),
            "allReady": all(item["ready"] for item in final),
            "iterations": len(history),
            "readyCountHistory": history,
            "queryCount": len(history) * len(spec["applications"]),
            "secretOrTargetReadPerformed": False,
            "mutationPerformed": False,
            "capabilityTestPerformed": False,
            "retryPerformed": False,
            "cleanupPerformed": False,
            "rawObjectsRetained": False,
            "rawMessagesRetained": False,
            "failureInjectionPerformed": False,
        }
        descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            json.dump(evidence, stream, sort_keys=True, separators=(",", ":"))
            stream.write("\n")
        print(json.dumps({
            "allReady": evidence["allReady"],
            "readyCount": evidence["readyCount"],
            "iterations": evidence["iterations"],
            "evidenceDigest": sha(output),
        }, sort_keys=True))
        return 0
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
