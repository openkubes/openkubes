#!/usr/bin/env python3
"""Bounded OK-141 capability execution after Platform v8 convergence."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


class CapabilityRuntimeError(ValueError):
    pass


def sha_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def digest(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise CapabilityRuntimeError(f"expected mapping: {path}")
    return value


def expect(actual: Any, expected: Any, context: str) -> None:
    if actual != expected:
        raise CapabilityRuntimeError(f"{context} mismatch")


def safe_file(path: Path, expected_digest: str, mode: int | None = None) -> None:
    if path.is_symlink() or not path.is_file():
        raise CapabilityRuntimeError(f"unsafe or missing file: {path}")
    expect(digest(path), expected_digest, f"file digest {path}")
    if mode is not None and (path.stat().st_mode & 0o777) != mode:
        raise CapabilityRuntimeError(f"unsafe mode for {path}")


def write_exclusive(path: Path, payload: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(payload)


def raw_get(client: Path, kubeconfig: Path, uri: str) -> dict[str, Any]:
    completed = subprocess.run(
        [str(client), "--kubeconfig", str(kubeconfig), "get", "--raw", uri],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=30,
    )
    if completed.returncode != 0:
        raise CapabilityRuntimeError("bounded exact GET failed; output suppressed")
    value = json.loads(completed.stdout)
    if not isinstance(value, dict):
        raise CapabilityRuntimeError("bounded exact GET returned non-object")
    return value


def validate_candidate(path: Path) -> dict[str, Any]:
    candidate = read_json(path)
    expect(candidate.get("kind"), "OK141CapabilityRuntimeCandidate", "kind")
    spec = candidate["spec"]
    expect(spec.get("version"), "ok141-capability-runtime/v1", "version")
    expect(spec.get("state"), "AUTHORIZED-BY-CONTINUOUS-DEV-GRANT", "state")
    tool_path = (path.parent / spec["tool"]["path"]).resolve()
    safe_file(tool_path, spec["tool"]["digest"])
    safe_file(Path(spec["tools"]["sharedAndManagementKubectl"]["path"]), spec["tools"]["sharedAndManagementKubectl"]["digest"])
    safe_file(Path(spec["tools"]["workloadKubectl"]["path"]), spec["tools"]["workloadKubectl"]["digest"])
    safe_file(Path(spec["capability"]["scriptPath"]), spec["capability"]["scriptDigest"])
    safe_file(Path(spec["tools"]["bash"]["path"]), spec["tools"]["bash"]["digest"])
    safe_file(Path(spec["tools"]["curl"]["path"]), spec["tools"]["curl"]["digest"])
    safe_file(Path(spec["tools"]["jq"]["path"]), spec["tools"]["jq"]["digest"])
    for key in ("sharedKubeconfig", "managementKubeconfig"):
        safe_file(Path(spec["credentials"][key]), spec["credentials"][key + "Digest"], 0o600)
    if len(spec["applications"]) != 3 or len(set(spec["applications"])) != 3:
        raise CapabilityRuntimeError("exactly three unique Applications required")
    if spec["capability"].get("syntheticMutationAndCleanupOwnedByScript") is not True:
        raise CapabilityRuntimeError("synthetic cleanup boundary missing")
    forbidden = spec["authorization"]["forbidden"]
    for required in ("arbitraryMutation", "failureInjection", "broadCleanup", "rawEvidencePublication"):
        if required not in forbidden:
            raise CapabilityRuntimeError("authorization boundary incomplete")
    return candidate


def application_status(obj: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    name = obj.get("metadata", {}).get("name")
    if name not in spec["applications"]:
        raise CapabilityRuntimeError("unexpected Application identity")
    annotations = obj.get("metadata", {}).get("annotations", {})
    identities = spec["identities"]
    for annotation, key in (
        ("openkubes.io/intent-revision", "R"),
        ("openkubes.io/platform-revision", "P"),
        ("openkubes.io/execution-fixture", "FixtureDigest"),
    ):
        expect(annotations.get(annotation), identities[key], f"{name} {annotation}")
    status = obj.get("status", {})
    sync = status.get("sync", {})
    health = status.get("health", {})
    expect(sync.get("revision"), spec["sourceRevision"], f"{name} source revision")
    expect(sync.get("status"), "Synced", f"{name} sync")
    expect(health.get("status"), "Healthy", f"{name} health")
    return {
        "name": name,
        "uidDigest": sha_bytes(str(obj["metadata"].get("uid", "")).encode()),
        "generation": obj["metadata"].get("generation"),
        "sync": "Synced",
        "health": "Healthy",
        "revision": sync.get("revision"),
    }


def execute(path: Path) -> dict[str, Any]:
    candidate = validate_candidate(path)
    spec = candidate["spec"]
    output = Path(spec["outputPath"])
    ephemeral = Path(spec["runtime"]["ephemeralKubeconfigPath"])
    tool_dir = Path(spec["runtime"]["ephemeralToolDirectory"])
    if any(item.exists() or item.is_symlink() for item in (output, ephemeral, tool_dir)):
        raise CapabilityRuntimeError("exclusive runtime path already exists")

    shared_client = Path(spec["tools"]["sharedAndManagementKubectl"]["path"])
    workload_client = Path(spec["tools"]["workloadKubectl"]["path"])
    shared_kubeconfig = Path(spec["credentials"]["sharedKubeconfig"])
    management_kubeconfig = Path(spec["credentials"]["managementKubeconfig"])

    applications = []
    for name in spec["applications"]:
        uri = f"/apis/argoproj.io/v1alpha1/namespaces/argocd/applications/{name}"
        applications.append(application_status(raw_get(shared_client, shared_kubeconfig, uri), spec))

    workload_secret = raw_get(shared_client, management_kubeconfig, spec["workload"]["kubeconfigSecretURI"])
    try:
        raw_kubeconfig = base64.b64decode(workload_secret["data"]["value"], validate=True)
    except (KeyError, ValueError) as error:
        raise CapabilityRuntimeError("invalid workload kubeconfig Secret shape") from error
    write_exclusive(ephemeral, raw_kubeconfig)
    raw_kubeconfig = b""

    completed: subprocess.CompletedProcess[bytes] | None = None
    secret_shape: dict[str, Any] = {}
    run_id = spec["capability"]["runID"]
    try:
        credential_secret = raw_get(workload_client, ephemeral, spec["workload"]["credentialSecretURI"])
        keys = spec["workload"]["credentialKeys"]
        data = credential_secret.get("data", {})
        if not isinstance(data, dict) or any(key not in data for key in keys):
            raise CapabilityRuntimeError("credential Secret lacks required keys")
        credentials: dict[str, str] = {}
        for key in keys:
            value = base64.b64decode(data[key], validate=True).decode()
            if len(value) < 16:
                raise CapabilityRuntimeError("credential value violates minimum length")
            credentials[key] = value
        secret_shape = {
            "name": credential_secret.get("metadata", {}).get("name"),
            "namespace": credential_secret.get("metadata", {}).get("namespace"),
            "uidDigest": sha_bytes(str(credential_secret.get("metadata", {}).get("uid", "")).encode()),
            "requiredKeysPresent": True,
            "credentialBytesRetained": False,
        }

        tool_dir.mkdir(mode=0o700)
        os.symlink(workload_client, tool_dir / "kubectl")
        env = os.environ.copy()
        env.update(
            {
                "PATH": f"{tool_dir}:/usr/local/bin:/usr/bin:/bin",
                "KUBECONFIG": str(ephemeral),
                "CONTRACT_TEST_NAMESPACE": spec["capability"]["namespace"],
                "CONTRACT_TEST_RUN_ID": run_id,
                "CONTRACT_TEST_TIMEOUT": str(spec["capability"]["asyncTimeoutSeconds"]),
                "GRAFANA_USER": credentials["grafana-admin-user"],
                "GRAFANA_PASSWORD": credentials["grafana-admin-password"],
                "OPENSEARCH_USER": "admin",
                "OPENSEARCH_PASSWORD": credentials["opensearch-admin-password"],
                "CONTRACT_TEST_RECEIVER_CAPTURE_URL": "",
            }
        )
        completed = subprocess.run(
            [spec["tools"]["bash"]["path"], spec["capability"]["scriptPath"]],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            env=env,
            timeout=spec["capability"]["overallTimeoutSeconds"],
        )
        for key in list(credentials):
            credentials[key] = ""
        data = {}
    finally:
        ephemeral.unlink(missing_ok=True)
        (tool_dir / "kubectl").unlink(missing_ok=True)
        try:
            tool_dir.rmdir()
        except FileNotFoundError:
            pass
        for log_path in Path("/tmp").glob(f"pf-*-{run_id}.log"):
            if log_path.is_file() and not log_path.is_symlink():
                log_path.unlink()

    if completed is None:
        raise CapabilityRuntimeError("capability test did not start")
    state = "PASS-CAPABILITY" if completed.returncode == 0 else "FAIL-CAPABILITY"
    evidence = {
        "apiVersion": "evidence.openkubes.io/v1alpha1",
        "kind": "OK141CapabilityRuntimeEvidence",
        "state": state,
        "candidateDigest": digest(path),
        "identities": spec["identities"],
        "sourceRevision": spec["sourceRevision"],
        "applications": applications,
        "credentialSecret": secret_shape,
        "capability": {
            "contractDigest": spec["capability"]["contractDigest"],
            "scriptDigest": spec["capability"]["scriptDigest"],
            "exitCode": completed.returncode,
            "stdoutDigest": sha_bytes(completed.stdout),
            "stderrDigest": sha_bytes(completed.stderr),
            "alertAcceptance": "firing-only",
            "syntheticCleanupOwnedByScript": True,
            "rawOutputRetained": False,
        },
        "cleanup": {
            "ephemeralKubeconfigRemoved": not ephemeral.exists(),
            "ephemeralToolDirectoryRemoved": not tool_dir.exists(),
            "portForwardLogsRemoved": not any(Path("/tmp").glob(f"pf-*-{run_id}.log")),
        },
        "secretBytesRetained": False,
    }
    evidence["semanticDigest"] = sha_bytes(json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode())
    write_exclusive(output, (json.dumps(evidence, sort_keys=True, separators=(",", ":")) + "\n").encode())
    if completed.returncode != 0:
        raise CapabilityRuntimeError("exact capability test failed; raw output suppressed")
    return {"state": state, "evidencePath": str(output), "evidenceDigest": digest(output), "semanticDigest": evidence["semanticDigest"]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "execute"))
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "verify":
            validate_candidate(args.candidate.resolve())
            print(digest(args.candidate.resolve()))
        else:
            if not args.execute:
                raise CapabilityRuntimeError("execution flag required")
            print(json.dumps(execute(args.candidate.resolve()), sort_keys=True))
        return 0
    except (CapabilityRuntimeError, KeyError, OSError, TypeError, ValueError, json.JSONDecodeError, subprocess.SubprocessError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
