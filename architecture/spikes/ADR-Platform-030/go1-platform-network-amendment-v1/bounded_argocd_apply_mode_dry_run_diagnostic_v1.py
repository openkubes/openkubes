#!/usr/bin/env python3
"""Exercise client-side apply in server dry-run mode under Argo's target identity."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
CANDIDATE = HERE / "argocd-apply-mode-dry-run-diagnostic-v1.yaml"
CLIENT = Path("/private/tmp/ok141-kubectl-v1.34.1-darwin-amd64")
SHARED = Path("/Users/arash/.kube/ok-shared.yaml")
EPHEMERAL = Path("/private/tmp/ok141-argocd-apply-mode-dry-run-target.yaml")
EXPECTED_CLIENT = "sha256:bb211f2b31f2b3bc60562b44cc1e3b712a16a98e9072968ba255beb04cefcfdf"


def sha(path: str | Path) -> str:
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def exact(config: Path, verb: str, uri: str) -> dict:
    result = subprocess.run([str(CLIENT), "--kubeconfig", str(config), verb, "--raw", uri], capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError(f"exact {verb} failed")
    return json.loads(result.stdout)


def decode(secret: dict, name: str) -> str:
    return base64.b64decode(secret["data"][name], validate=True).decode()


def main() -> int:
    spec = yaml.safe_load(CANDIDATE.read_text())["spec"]
    predecessor = Path(spec["predecessor"]["path"])
    manifest = Path(spec["exactClusterRole"]["manifestPath"])
    output = Path(spec["outputPath"])
    if sha(predecessor) != spec["predecessor"]["digest"] or sha(manifest) != spec["exactClusterRole"]["manifestDigest"]:
        raise RuntimeError("binding mismatch")
    if sha(CLIENT) != EXPECTED_CLIENT or SHARED.is_symlink() or (SHARED.stat().st_mode & 0o777) != 0o600:
        raise RuntimeError("local identity mismatch")
    if output.exists() or EPHEMERAL.exists():
        raise RuntimeError("exclusive output exists")

    evidence = {
        "apiVersion": "evidence.openkubes.io/v1alpha1",
        "kind": "GO1ArgoApplyModeDryRunDiagnosticEvidence",
        "candidateDigest": sha(CANDIDATE),
        "predecessorDigest": spec["predecessor"]["digest"],
        "manifestDigest": spec["exactClusterRole"]["manifestDigest"],
        "exactClusterRoleName": spec["exactClusterRole"]["name"],
        "registrationSecretReadPerformed": False,
        "serverDryRunApplyAttempted": False,
        "serverDryRunApplyAccepted": False,
        "uidUnchanged": False,
        "resourceVersionUnchanged": False,
        "persistentMutationPerformed": False,
        "credentialPayloadRetained": False,
        "rawOutputRetained": False,
        "syncRetryPerformed": False,
        "cleanupPerformed": False,
        "failureInjectionPerformed": False,
        "state": "STARTED",
    }
    try:
        secret = exact(SHARED, "get", spec["registrationSecretURI"])
        evidence["registrationSecretReadPerformed"] = True
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

        name = spec["exactClusterRole"]["name"]
        uri = f"/apis/rbac.authorization.k8s.io/v1/clusterroles/{name}"
        before = exact(EPHEMERAL, "get", uri)
        uid = before["metadata"]["uid"]
        resource_version = before["metadata"]["resourceVersion"]

        evidence["serverDryRunApplyAttempted"] = True
        result = subprocess.run([
            str(CLIENT), "--kubeconfig", str(EPHEMERAL), "apply", "--dry-run=server", "--validate=true", "-f", str(manifest), "-o", "name"
        ], capture_output=True, check=False)
        combined = result.stdout + result.stderr
        evidence["serverDryRunApplyAccepted"] = result.returncode == 0
        evidence["responseCategory"] = "SUCCESS" if result.returncode == 0 else (
            "PRIVILEGE-ESCALATION" if b"attempting to grant RBAC permissions not currently held" in combined else "FORBIDDEN" if b"forbidden" in combined.lower() else "OTHER"
        )

        after = exact(EPHEMERAL, "get", uri)
        evidence["uidUnchanged"] = after["metadata"]["uid"] == uid
        evidence["resourceVersionUnchanged"] = after["metadata"]["resourceVersion"] == resource_version
        evidence["persistentMutationPerformed"] = not (evidence["uidUnchanged"] and evidence["resourceVersionUnchanged"])
        evidence["state"] = "PASS-ARGO-APPLY-MODE-DRY-RUN" if evidence["serverDryRunApplyAccepted"] and not evidence["persistentMutationPerformed"] else "FAIL-CLOSED"
    finally:
        EPHEMERAL.unlink(missing_ok=True)

    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(evidence, handle, sort_keys=True, separators=(",", ":"))
        handle.write("\n")
    print(json.dumps({
        "state": evidence["state"],
        "serverDryRunApplyAccepted": evidence["serverDryRunApplyAccepted"],
        "responseCategory": evidence.get("responseCategory"),
        "resourceVersionUnchanged": evidence["resourceVersionUnchanged"],
        "evidenceDigest": sha(output),
    }, sort_keys=True))
    return 0 if evidence["state"].startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
