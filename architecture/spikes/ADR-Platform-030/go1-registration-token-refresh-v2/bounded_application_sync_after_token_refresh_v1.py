#!/usr/bin/env python3
"""Submit and observe one exact Argo sync after a proven token refresh."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent


class SyncError(RuntimeError):
    pass


def digest_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def digest_file(path: Path) -> str:
    return digest_bytes(path.read_bytes())


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise SyncError(f"expected mapping: {path}")
    return value


def exact(
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
        raise SyncError(f"exact {verb} failed; output suppressed")
    value = json.loads(completed.stdout)
    if not isinstance(value, dict):
        raise SyncError("API response is not an object")
    return value


def write_exclusive(path: Path, value: dict[str, Any]) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as output:
        json.dump(value, output, sort_keys=True, separators=(",", ":"))
        output.write("\n")


def app_summary(value: dict[str, Any]) -> dict[str, Any]:
    status = value.get("status", {})
    operation = status.get("operationState", {}) or {}
    return {
        "sync": status.get("sync", {}).get("status", "Unknown"),
        "health": status.get("health", {}).get("status", "Unknown"),
        "operationPhase": operation.get("phase", "Unknown"),
        "operationRevisionCurrent": operation.get("syncResult", {}).get("revision")
        in (None, value.get("spec", {}).get("source", {}).get("targetRevision")),
        "conditionTypes": sorted(
            item.get("type", "") for item in status.get("conditions", []) if item.get("type")
        ),
    }


def validate(path: Path) -> dict[str, Any]:
    candidate = read_json(path)
    if candidate.get("kind") != "OK141ApplicationSyncAfterTokenRefreshCandidate":
        raise SyncError("candidate kind mismatch")
    spec = candidate.get("spec", {})
    if spec.get("state") != "LIVE-AUTHORIZED-ONCE" or not spec.get("standingGrantAcknowledged"):
        raise SyncError("candidate is not authorized")
    tool = Path(spec["toolPath"])
    if not tool.is_absolute():
        tool = HERE / tool
    if digest_file(tool) != spec.get("toolDigest"):
        raise SyncError("tool digest mismatch")
    predecessor = Path(spec["predecessor"]["path"])
    if digest_file(predecessor) != spec["predecessor"]["digest"]:
        raise SyncError("token refresh evidence digest mismatch")
    evidence = read_json(predecessor)
    if not all(
        evidence.get(key) is True
        for key in (
            "targetIdentityMatched",
            "targetProbeSucceeded",
            "registrationSecretReplaced",
            "uidPreserved",
            "resourceVersionAdvanced",
        )
    ):
        raise SyncError("token refresh evidence is incomplete")
    return candidate


def execute(path: Path) -> dict[str, Any]:
    candidate = validate(path)
    spec = candidate["spec"]
    client = Path(spec["clientPath"])
    kubeconfig = Path(spec["kubeconfigPath"])
    if digest_file(client) != spec["clientDigest"]:
        raise SyncError("client digest mismatch")
    if (
        kubeconfig.is_symlink()
        or not kubeconfig.is_file()
        or stat.S_IMODE(kubeconfig.stat().st_mode) != 0o600
    ):
        raise SyncError("unsafe kubeconfig")
    output = Path(spec["outputPath"])
    if output.exists() or output.is_symlink():
        raise SyncError("exclusive output exists")

    app = spec["application"]
    current = exact(client, kubeconfig, "get", app["uri"])
    metadata = current.get("metadata", {})
    if (metadata.get("namespace"), metadata.get("name")) != (
        app["namespace"],
        app["name"],
    ):
        raise SyncError("application identity mismatch")
    uid = str(metadata.get("uid", ""))
    resource_version = str(metadata.get("resourceVersion", ""))
    if not uid or not resource_version:
        raise SyncError("application lacks optimistic-concurrency identity")
    if current.get("operation") is not None:
        raise SyncError("application already has a requested operation")
    operation_state = current.get("status", {}).get("operationState", {}) or {}
    if (
        operation_state.get("phase") != "Failed"
        or operation_state.get("finishedAt") != app["expectedPriorOperationFinishedAt"]
    ):
        raise SyncError("prior failed operation boundary changed")
    annotations = metadata.get("annotations", {})
    for key, expected in app["identityAnnotations"].items():
        if annotations.get(key) != expected:
            raise SyncError(f"application identity annotation mismatch: {key}")
    if current.get("spec", {}).get("source", {}).get("targetRevision") != app["sourceRevision"]:
        raise SyncError("application source revision mismatch")

    replacement = copy.deepcopy(current)
    replacement["metadata"].pop("managedFields", None)
    replacement["metadata"].pop("selfLink", None)
    replacement["operation"] = copy.deepcopy(app["operation"])
    returned = exact(
        client,
        kubeconfig,
        "replace",
        app["uri"],
        json.dumps(replacement, sort_keys=True, separators=(",", ":")).encode(),
    )
    returned_meta = returned.get("metadata", {})
    if returned_meta.get("uid") != uid:
        raise SyncError("application UID changed")
    if str(returned_meta.get("resourceVersion", "")) == resource_version:
        raise SyncError("application resourceVersion did not advance")
    if returned.get("operation") != app["operation"]:
        raise SyncError("requested operation was not retained")

    observations: list[dict[str, Any]] = []
    final: dict[str, Any] = {}
    for iteration in range(spec["observation"]["maxIterations"]):
        value = exact(client, kubeconfig, "get", app["uri"])
        final = app_summary(value)
        observations.append({"iteration": iteration + 1, "status": final})
        if final["sync"] == "Synced" and final["health"] == "Healthy" and final["operationPhase"] == "Succeeded":
            break
        if final["operationPhase"] in ("Failed", "Error"):
            break
        if iteration + 1 < spec["observation"]["maxIterations"]:
            time.sleep(spec["observation"]["intervalSeconds"])

    succeeded = (
        final.get("sync") == "Synced"
        and final.get("health") == "Healthy"
        and final.get("operationPhase") == "Succeeded"
    )
    evidence = {
        "apiVersion": "evidence.openkubes.io/v1alpha1",
        "kind": "OK141ApplicationSyncAfterTokenRefreshEvidence",
        "candidateDigest": digest_file(path),
        "predecessorDigest": spec["predecessor"]["digest"],
        "application": app["name"],
        "sourceRevision": app["sourceRevision"],
        "uidPreserved": True,
        "resourceVersionAdvanced": True,
        "exactOperationSubmitted": True,
        "observationIterations": len(observations),
        "finalStatus": final,
        "succeeded": succeeded,
        "specChanged": False,
        "credentialChanged": False,
        "rbacChanged": False,
        "deletePerformed": False,
        "rollbackOrCleanupPerformed": False,
        "failureInjectionPerformed": False,
        "rawObjectRetained": False,
        "observationDigest": digest_bytes(
            json.dumps(observations, sort_keys=True, separators=(",", ":")).encode()
        ),
        "state": "PASS-SYNC-CONVERGED" if succeeded else "STOP-SYNC-NOT-CONVERGED",
    }
    evidence["semanticDigest"] = digest_bytes(
        json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
    )
    write_exclusive(output, evidence)
    return {
        "state": evidence["state"],
        "evidenceDigest": digest_file(output),
        "finalStatus": final,
        "observationIterations": evidence["observationIterations"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "sync"))
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "verify":
            validate(args.candidate.resolve())
            print(digest_file(args.candidate.resolve()))
        else:
            if not args.execute:
                raise SyncError("sync requires --execute")
            print(json.dumps(execute(args.candidate.resolve()), sort_keys=True))
        return 0
    except Exception as error:
        print(f"ERROR: {type(error).__name__}: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
