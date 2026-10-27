#!/usr/bin/env python3
"""Restart the exact disposable Prometheus operator once and observe existing work."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time


HERE = Path(__file__).resolve().parent
CANDIDATE = HERE / "prometheus-operator-api-refresh-candidate-v1.json"
EXPECTED_CANDIDATE = "sha256:b62bb500f53c1c2883b11c44391582bdfc5e346601fe292e4ec35865b6bf24ad"
CLIENT = Path("/private/tmp/ok141-kubectl-v1.34.1-darwin-amd64")
EXPECTED_CLIENT = "sha256:bb211f2b31f2b3bc60562b44cc1e3b712a16a98e9072968ba255beb04cefcfdf"
MGMT_KUBECONFIG = Path("/Users/arash/.kube/ok-mgmt.yaml")
SHARED_KUBECONFIG = Path("/Users/arash/.kube/ok-shared.yaml")
EPHEMERAL = Path("/private/tmp/ok141-prometheus-operator-api-refresh-workload-kubeconfig.yaml")


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def request(kubeconfig: Path, verb: str, uri: str, payload: bytes | None = None) -> dict:
    command = [str(CLIENT), "--kubeconfig", str(kubeconfig), verb, "--raw", uri]
    if payload is not None:
        command.extend(["--filename", "-"])
    result = subprocess.run(
        command,
        input=payload,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise RuntimeError(f"bounded exact {verb} failed: exit={result.returncode}")
    return json.loads(result.stdout)


def pod_ready(pod: dict) -> bool:
    return pod.get("status", {}).get("phase") == "Running" and any(
        item.get("type") == "Ready" and item.get("status") == "True"
        for item in pod.get("status", {}).get("conditions", [])
    )


def application_snapshot(app: dict) -> dict:
    status = app.get("status", {})
    operation = status.get("operationState", {})
    blocking = sorted(
        {
            item.get("type")
            for item in status.get("conditions", [])
            if item.get("type") in {"ComparisonError", "InvalidSpecError", "SyncError", "UnknownError"}
        }
    )
    return {
        "sync": status.get("sync", {}).get("status"),
        "health": status.get("health", {}).get("status"),
        "operationPhase": operation.get("phase"),
        "operationStartedAt": operation.get("startedAt"),
        "operationFinished": bool(operation.get("finishedAt")),
        "blockingConditions": blocking,
    }


def write_exclusive(path: Path, value: dict) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(value, handle, sort_keys=True, separators=(",", ":"))
        handle.write("\n")


def main() -> int:
    candidate = json.loads(CANDIDATE.read_text())
    spec = candidate["spec"]
    output = Path(spec["operation"]["privateEvidencePath"])
    if digest(CANDIDATE) != EXPECTED_CANDIDATE or digest(CLIENT) != EXPECTED_CLIENT:
        raise RuntimeError("bound candidate or client identity mismatch")
    for kubeconfig in (MGMT_KUBECONFIG, SHARED_KUBECONFIG):
        if kubeconfig.is_symlink() or not kubeconfig.is_file() or (kubeconfig.stat().st_mode & 0o777) != 0o600:
            raise RuntimeError("unsafe bound kubeconfig")
    if output.exists() or output.is_symlink() or EPHEMERAL.exists():
        raise RuntimeError("exclusive output already exists")

    evidence = {
        "apiVersion": "evidence.openkubes.io/v1alpha1",
        "kind": "OK141PrometheusOperatorAPIRefreshEvidence",
        "candidateDigest": EXPECTED_CANDIDATE,
        "controllerRestartPerformed": False,
        "uidAndResourceVersionPreconditionsUsed": False,
        "forceDeletePerformed": False,
        "explicitArgoSyncSubmitted": False,
        "applicationMutationPerformed": False,
        "replacementObserved": False,
        "replacementReady": False,
        "prometheusStatusObserved": False,
        "rawCredentialRetained": False,
        "retryPerformed": False,
        "rollbackOrCleanupPerformed": False,
        "failureInjectionPerformed": False,
        "state": "STARTED",
    }
    try:
        app = request(SHARED_KUBECONFIG, "get", spec["shared"]["coreApplicationURI"])
        initial_app = application_snapshot(app)
        evidence["initialApplication"] = initial_app
        if initial_app["operationPhase"] != "Running" or initial_app["operationStartedAt"] != spec["shared"]["requiredOperationStartedAt"]:
            raise RuntimeError("bound existing Core operation is not running")

        secret = request(MGMT_KUBECONFIG, "get", spec["management"]["workloadKubeconfigSecretURI"])
        raw = base64.b64decode(secret["data"][spec["management"]["dataKey"]], validate=True)
        EPHEMERAL.write_bytes(raw)
        os.chmod(EPHEMERAL, 0o600)

        pod = request(EPHEMERAL, "get", spec["target"]["podURI"])
        if not pod_ready(pod):
            raise RuntimeError("bound operator pod is not ready")
        if [item.get("name") for item in pod["spec"].get("containers", [])] != [spec["target"]["expectedContainer"]]:
            raise RuntimeError("operator container identity mismatch")
        old_uid = pod["metadata"].get("uid")
        old_rv = pod["metadata"].get("resourceVersion")
        if not old_uid or not old_rv:
            raise RuntimeError("operator concurrency identity missing")

        prometheus = request(EPHEMERAL, "get", spec["target"]["prometheusURI"])
        if prometheus.get("status"):
            raise RuntimeError("Prometheus is no longer in the bound status-absent state")

        delete_options = {
            "apiVersion": "v1",
            "kind": "DeleteOptions",
            "gracePeriodSeconds": spec["operation"]["gracePeriodSeconds"],
            "propagationPolicy": "Background",
            "preconditions": {"uid": old_uid, "resourceVersion": old_rv},
        }
        evidence["uidAndResourceVersionPreconditionsUsed"] = True
        request(
            EPHEMERAL,
            "delete",
            spec["target"]["podURI"],
            json.dumps(delete_options, sort_keys=True, separators=(",", ":")).encode(),
        )
        evidence["controllerRestartPerformed"] = True

        for iteration in range(1, spec["operation"]["replacementMaximumIterations"] + 1):
            collection = request(EPHEMERAL, "get", spec["target"]["replacementCollectionURI"])
            replacements = [
                item
                for item in collection.get("items", [])
                if item.get("metadata", {}).get("uid") != old_uid and pod_ready(item)
            ]
            if len(replacements) == 1:
                evidence["replacementObserved"] = True
                evidence["replacementReady"] = True
                evidence["replacementObservationIterations"] = iteration
                break
            if len(replacements) > 1:
                raise RuntimeError("more than one replacement operator pod observed")
            time.sleep(spec["operation"]["replacementPollIntervalSeconds"])
        else:
            raise RuntimeError("replacement operator did not become ready within bound")

        history: list[dict] = []
        for iteration in range(1, spec["operation"]["coreMaximumIterations"] + 1):
            prometheus = request(EPHEMERAL, "get", spec["target"]["prometheusURI"])
            if prometheus.get("status"):
                evidence["prometheusStatusObserved"] = True
            current = application_snapshot(
                request(SHARED_KUBECONFIG, "get", spec["shared"]["coreApplicationURI"])
            )
            if not history or current != history[-1]:
                history.append(current)
            if current["operationPhase"] in {"Succeeded", "Failed", "Error"}:
                evidence["coreObservationIterations"] = iteration
                break
            time.sleep(spec["operation"]["corePollIntervalSeconds"])
        else:
            evidence["coreObservationIterations"] = spec["operation"]["coreMaximumIterations"]

        evidence["applicationHistory"] = history
        final_app = history[-1]
        if (
            evidence["prometheusStatusObserved"]
            and final_app["operationPhase"] == "Succeeded"
            and final_app["sync"] == "Synced"
            and final_app["health"] == "Healthy"
            and not final_app["blockingConditions"]
        ):
            evidence["state"] = "PASS-EXISTING-CORE-SYNC-CONVERGED"
        else:
            evidence["state"] = "STOP-PRESERVE-NO-RETRY"
            evidence["failureClass"] = (
                "CORE-OPERATION-TERMINATED-NON-SUCCESS"
                if final_app["operationPhase"] in {"Failed", "Error"}
                else "CORE-NOT-CONVERGED-WITHIN-BOUND"
            )
    except Exception as error:
        evidence["state"] = "STOP-PRESERVE-NO-RETRY"
        evidence["failureClass"] = type(error).__name__
    finally:
        EPHEMERAL.unlink(missing_ok=True)

    write_exclusive(output, evidence)
    print(
        json.dumps(
            {
                "state": evidence["state"],
                "controllerRestartPerformed": evidence["controllerRestartPerformed"],
                "replacementReady": evidence["replacementReady"],
                "prometheusStatusObserved": evidence["prometheusStatusObserved"],
                "finalApplication": evidence.get("applicationHistory", [None])[-1],
                "evidenceDigest": digest(output),
            },
            sort_keys=True,
        )
    )
    return 0 if evidence["state"].startswith("PASS") else 2


if __name__ == "__main__":
    raise SystemExit(main())
