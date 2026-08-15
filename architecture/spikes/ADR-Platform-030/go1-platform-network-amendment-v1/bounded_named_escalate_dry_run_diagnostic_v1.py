#!/usr/bin/env python3
"""Prove named ClusterRole update authorization with a non-persisting API dry-run."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
CANDIDATE = HERE / "named-escalate-dry-run-diagnostic-v1.yaml"
CLIENT = Path("/private/tmp/ok141-kubectl-v1.34.1-darwin-amd64")
SHARED = Path("/Users/arash/.kube/ok-shared.yaml")
EPHEMERAL = Path("/private/tmp/ok141-named-escalate-dry-run-target.yaml")
EXPECTED_CLIENT = "sha256:bb211f2b31f2b3bc60562b44cc1e3b712a16a98e9072968ba255beb04cefcfdf"


def sha(path: str | Path) -> str:
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def exact(config: Path, verb: str, uri: str, payload: bytes | None = None) -> tuple[int, bytes]:
    command = [str(CLIENT), "--kubeconfig", str(config), verb, "--raw", uri]
    if payload is not None:
        command.extend(["--filename", "-"])
    result = subprocess.run(command, input=payload, capture_output=True, check=False)
    return result.returncode, result.stdout + result.stderr


def decode(secret: dict, name: str) -> str:
    return base64.b64decode(secret["data"][name], validate=True).decode()


def main() -> int:
    spec = yaml.safe_load(CANDIDATE.read_text())["spec"]
    predecessor = Path(spec["predecessor"]["path"])
    output = Path(spec["outputPath"])
    if sha(predecessor) != spec["predecessor"]["digest"]:
        raise RuntimeError("predecessor mismatch")
    if sha(CLIENT) != EXPECTED_CLIENT or SHARED.is_symlink() or (SHARED.stat().st_mode & 0o777) != 0o600:
        raise RuntimeError("local identity mismatch")
    if output.exists() or EPHEMERAL.exists():
        raise RuntimeError("exclusive output exists")

    result = {
        "apiVersion": "evidence.openkubes.io/v1alpha1",
        "kind": "GO1NamedEscalateDryRunDiagnosticEvidence",
        "candidateDigest": sha(CANDIDATE),
        "predecessorDigest": spec["predecessor"]["digest"],
        "exactClusterRoleName": spec["exactClusterRoleName"],
        "registrationSecretReadPerformed": False,
        "dryRunUpdateAttempted": False,
        "dryRunAccepted": False,
        "resourceVersionUnchanged": False,
        "uidUnchanged": False,
        "persistentMutationPerformed": False,
        "credentialPayloadRetained": False,
        "rawObjectRetained": False,
        "rawErrorRetained": False,
        "syncRetryPerformed": False,
        "cleanupPerformed": False,
        "failureInjectionPerformed": False,
        "state": "STARTED",
    }
    try:
        code, raw = exact(SHARED, "get", spec["registrationSecretURI"])
        if code:
            raise RuntimeError("registration secret read failed")
        secret = json.loads(raw)
        result["registrationSecretReadPerformed"] = True
        server = decode(secret, "server")
        config = json.loads(decode(secret, "config"))
        token = config["bearerToken"]
        ca = config["tlsClientConfig"]["caData"]
        kubeconfig = {
            "apiVersion": "v1",
            "kind": "Config",
            "clusters": [{"name": "target", "cluster": {"server": server, "certificate-authority-data": ca}}],
            "users": [{"name": "argo", "user": {"token": token}}],
            "contexts": [{"name": "target", "context": {"cluster": "target", "user": "argo"}}],
            "current-context": "target",
        }
        fd = os.open(EPHEMERAL, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as handle:
            yaml.safe_dump(kubeconfig, handle, sort_keys=True)
        secret = config = kubeconfig = {}
        server = token = ca = ""

        name = spec["exactClusterRoleName"]
        uri = f"/apis/rbac.authorization.k8s.io/v1/clusterroles/{name}"
        code, raw = exact(EPHEMERAL, "get", uri)
        if code:
            raise RuntimeError("exact role read failed")
        before = json.loads(raw)
        uid = before["metadata"]["uid"]
        resource_version = before["metadata"]["resourceVersion"]
        before["metadata"].pop("managedFields", None)
        before["metadata"].pop("selfLink", None)

        result["dryRunUpdateAttempted"] = True
        dry_uri = f"{uri}?{spec['dryRunQuery']}"
        code, raw = exact(EPHEMERAL, "replace", dry_uri, json.dumps(before, sort_keys=True, separators=(",", ":")).encode())
        result["dryRunAccepted"] = code == 0
        result["responseCategory"] = "SUCCESS" if code == 0 else (
            "PRIVILEGE-ESCALATION" if b"attempting to grant RBAC permissions not currently held" in raw else "FORBIDDEN" if b"forbidden" in raw.lower() else "OTHER"
        )

        code, raw = exact(EPHEMERAL, "get", uri)
        if code:
            raise RuntimeError("post-dry-run exact role read failed")
        after = json.loads(raw)
        result["uidUnchanged"] = after["metadata"]["uid"] == uid
        result["resourceVersionUnchanged"] = after["metadata"]["resourceVersion"] == resource_version
        result["persistentMutationPerformed"] = not (result["uidUnchanged"] and result["resourceVersionUnchanged"])
        result["state"] = "PASS-NAMED-ESCALATE-DRY-RUN" if result["dryRunAccepted"] and not result["persistentMutationPerformed"] else "FAIL-CLOSED"
    finally:
        EPHEMERAL.unlink(missing_ok=True)

    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(result, handle, sort_keys=True, separators=(",", ":"))
        handle.write("\n")
    print(json.dumps({
        "state": result["state"],
        "dryRunAccepted": result["dryRunAccepted"],
        "responseCategory": result.get("responseCategory"),
        "resourceVersionUnchanged": result["resourceVersionUnchanged"],
        "evidenceDigest": sha(output),
    }, sort_keys=True))
    return 0 if result["state"].startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
