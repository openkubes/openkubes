#!/usr/bin/env python3
"""Execute one granted graceful Argo controller refresh and bounded Core observation."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
CANDIDATE = HERE / "argo-runtime-refresh-candidate-v1.yaml"
CLIENT = Path("/private/tmp/ok141-kubectl-v1.34.1-darwin-amd64")
KUBECONFIG = Path("/Users/arash/.kube/ok-shared.yaml")
EXPECTED_CANDIDATE = "sha256:89b3ea187a8b4cb25b8e61a37d44ed7bbe3e153580535c962e4a0c97601ec5dd"
EXPECTED_CLIENT = "sha256:bb211f2b31f2b3bc60562b44cc1e3b712a16a98e9072968ba255beb04cefcfdf"
EXPECTED_R = "sha256:89248df8cd908394d2d75c18fbb39d52d84cf181f66480c743bfe9d732a0aaa4"
EXPECTED_P = "sha256:02206b92b487a0f12eee8139d82f9ef150ab9688c7a60687d3f7b6b782266472"
EXPECTED_FIXTURE = "sha256:3aa621cd8f3b21e87a5d7059911d02a4b0f10f2d724df351750787eb274b9ae6"
EXPECTED_REVISION = "b5f7be6a7ddab798f31f32197fcbb9e86a9798b6"


def sha(path: str | Path) -> str:
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def request(verb: str, uri: str, payload: bytes | None = None, allow_not_found: bool = False) -> dict | None:
    command = [str(CLIENT), "--kubeconfig", str(KUBECONFIG), verb, "--raw", uri]
    if payload is not None:
        command.extend(["--filename", "-"])
    result = subprocess.run(command, input=payload, capture_output=True, check=False)
    if result.returncode:
        combined = (result.stdout + result.stderr).lower()
        if allow_not_found and (b'"code": 404' in combined or b"notfound" in combined or b"not found" in combined):
            return None
        raise RuntimeError(f"exact {verb} failed")
    return json.loads(result.stdout)


def pod_ready(pod: dict) -> bool:
    if pod.get("status", {}).get("phase") != "Running":
        return False
    return any(item.get("type") == "Ready" and item.get("status") == "True" for item in pod.get("status", {}).get("conditions") or [])


def app_snapshot(value: dict) -> dict:
    status = value.get("status", {})
    operation = status.get("operationState", {})
    conditions = status.get("conditions") or []
    blocking = sorted({item.get("type") for item in conditions if item.get("type") in {"ComparisonError", "InvalidSpecError", "SyncError", "UnknownError"}})
    advisory = sorted({item.get("type") for item in conditions if item.get("type") not in set(blocking)})
    return {
        "health": status.get("health", {}).get("status"),
        "sync": status.get("sync", {}).get("status"),
        "revisionCurrent": status.get("sync", {}).get("revision") == EXPECTED_REVISION,
        "operationPhase": operation.get("phase"),
        "operationRevisionCurrent": operation.get("syncResult", {}).get("revision") in (None, EXPECTED_REVISION),
        "blockingConditions": blocking,
        "advisoryConditions": advisory,
    }


def app_ready(snapshot: dict) -> bool:
    return (
        snapshot["health"] == "Healthy"
        and snapshot["sync"] == "Synced"
        and snapshot["revisionCurrent"]
        and snapshot["operationRevisionCurrent"]
        and not snapshot["blockingConditions"]
    )


def write_evidence(path: Path, evidence: dict) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(evidence, handle, sort_keys=True, separators=(",", ":"))
        handle.write("\n")


def main() -> int:
    spec = yaml.safe_load(CANDIDATE.read_text())["spec"]
    output = Path(spec["operation"]["outputPath"])
    if sha(CANDIDATE) != EXPECTED_CANDIDATE or sha(CLIENT) != EXPECTED_CLIENT:
        raise RuntimeError("bound identity mismatch")
    if KUBECONFIG.is_symlink() or not KUBECONFIG.is_file() or (KUBECONFIG.stat().st_mode & 0o777) != 0o600:
        raise RuntimeError("unsafe credential path")
    if output.exists() or output.is_symlink():
        raise RuntimeError("exclusive evidence output exists")

    evidence = {
        "apiVersion": "evidence.openkubes.io/v1alpha1",
        "kind": "GO1ArgoRuntimeRefreshEvidence",
        "candidateDigest": EXPECTED_CANDIDATE,
        "controllerRestartPerformed": False,
        "gracefulDelete": True,
        "forceDeletePerformed": False,
        "uidAndResourceVersionPreconditionsUsed": False,
        "replacementObserved": False,
        "replacementUIDChanged": False,
        "replacementRunningAndReady": False,
        "explicitApplicationOperationSubmitted": False,
        "applicationChanged": False,
        "credentialReadPerformed": False,
        "targetReadPerformed": False,
        "rollbackOrCleanupPerformed": False,
        "failureInjectionPerformed": False,
        "rawObjectsRetained": False,
        "rawMessagesRetained": False,
        "state": "STARTED",
    }
    try:
        cm = request("get", spec["shared"]["configMapURI"])
        if cm.get("data", {}).get("resource.respectRBAC") != "strict":
            raise RuntimeError("required config mismatch")
        statefulset = request("get", spec["shared"]["statefulSetURI"])
        expected_sts = spec["shared"]["requiredStatefulSet"]
        images = [item.get("image") for item in statefulset.get("spec", {}).get("template", {}).get("spec", {}).get("containers") or []]
        if statefulset.get("spec", {}).get("replicas") != expected_sts["replicas"] or statefulset.get("status", {}).get("readyReplicas") != expected_sts["readyReplicas"] or expected_sts["image"] not in images:
            raise RuntimeError("statefulset identity or readiness mismatch")

        pod = request("get", spec["shared"]["podURI"])
        if not pod_ready(pod):
            raise RuntimeError("controller pod not ready")
        metadata = pod.get("metadata", {})
        old_uid, old_rv = metadata.get("uid"), metadata.get("resourceVersion")
        if not old_uid or not old_rv:
            raise RuntimeError("controller concurrency identity missing")

        application = request("get", spec["shared"]["applicationURI"])
        annotations = application.get("metadata", {}).get("annotations", {})
        if annotations.get("openkubes.io/intent-revision") != EXPECTED_R or annotations.get("openkubes.io/platform-revision") != EXPECTED_P or annotations.get("openkubes.io/execution-fixture") != EXPECTED_FIXTURE:
            raise RuntimeError("application identity mismatch")
        automated = application.get("spec", {}).get("syncPolicy", {}).get("automated", {})
        if automated.get("enabled") is not True or automated.get("selfHeal") is not True:
            raise RuntimeError("automatic reconciliation boundary mismatch")
        evidence["initialApplication"] = app_snapshot(application)

        delete_options = {
            "apiVersion": "v1",
            "kind": "DeleteOptions",
            "gracePeriodSeconds": 30,
            "propagationPolicy": spec["operation"]["deletePropagation"],
            "preconditions": {"uid": old_uid, "resourceVersion": old_rv},
        }
        evidence["uidAndResourceVersionPreconditionsUsed"] = True
        request("delete", spec["shared"]["podURI"], json.dumps(delete_options, separators=(",", ":")).encode())
        evidence["controllerRestartPerformed"] = True

        for iteration in range(1, spec["operation"]["replacementMaximumIterations"] + 1):
            replacement = request("get", spec["shared"]["podURI"], allow_not_found=True)
            if replacement is not None:
                new_uid = replacement.get("metadata", {}).get("uid")
                if new_uid and new_uid != old_uid and pod_ready(replacement):
                    evidence["replacementObserved"] = True
                    evidence["replacementUIDChanged"] = True
                    evidence["replacementRunningAndReady"] = True
                    evidence["replacementObservationIterations"] = iteration
                    break
            time.sleep(spec["operation"]["replacementPollIntervalSeconds"])
        else:
            raise RuntimeError("replacement not ready within bound")

        history = []
        for iteration in range(1, spec["operation"]["applicationMaximumIterations"] + 1):
            current = request("get", spec["shared"]["applicationURI"])
            snapshot = app_snapshot(current)
            if not history or snapshot != history[-1]:
                history.append(snapshot)
            if app_ready(snapshot):
                evidence["applicationObservationIterations"] = iteration
                evidence["applicationReady"] = True
                evidence["applicationStateHistory"] = history
                evidence["state"] = "PASS-ARGO-RUNTIME-REFRESH-CORE-READY"
                break
            time.sleep(spec["operation"]["applicationPollIntervalSeconds"])
        else:
            evidence["applicationObservationIterations"] = spec["operation"]["applicationMaximumIterations"]
            evidence["applicationReady"] = False
            evidence["applicationStateHistory"] = history
            evidence["state"] = "STOP-PRESERVE-NO-RETRY"
            evidence["failureClass"] = "CORE-NOT-READY-WITHIN-BOUND"
    except Exception as error:
        evidence["state"] = "STOP-PRESERVE-NO-RETRY"
        evidence["failureClass"] = type(error).__name__
    write_evidence(output, evidence)
    print(json.dumps({
        "state": evidence["state"],
        "controllerRestartPerformed": evidence["controllerRestartPerformed"],
        "replacementRunningAndReady": evidence["replacementRunningAndReady"],
        "applicationReady": evidence.get("applicationReady"),
        "evidenceDigest": sha(output),
    }, sort_keys=True))
    return 0 if evidence["state"].startswith("PASS") else 2


if __name__ == "__main__":
    raise SystemExit(main())
