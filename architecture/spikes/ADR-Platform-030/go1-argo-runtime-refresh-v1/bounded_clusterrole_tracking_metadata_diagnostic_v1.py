#!/usr/bin/env python3
"""Compare redacted tracking metadata across the five exact ClusterRoles."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
CANDIDATE = HERE / "clusterrole-tracking-metadata-diagnostic-v1.yaml"
CLIENT = Path("/private/tmp/ok141-kubectl-v1.34.1-darwin-amd64")
SHARED = Path("/Users/arash/.kube/ok-shared.yaml")
EPHEMERAL = Path("/private/tmp/ok141-clusterrole-tracking-metadata-target.yaml")
EXPECTED_CLIENT = "sha256:bb211f2b31f2b3bc60562b44cc1e3b712a16a98e9072968ba255beb04cefcfdf"


def sha(path: str | Path) -> str:
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def exact(config: Path, uri: str) -> dict:
    result = subprocess.run([str(CLIENT), "--kubeconfig", str(config), "get", "--raw", uri], capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError("exact GET failed")
    return json.loads(result.stdout)


def decode(secret: dict, name: str) -> str:
    return base64.b64decode(secret["data"][name], validate=True).decode()


def main() -> int:
    spec = yaml.safe_load(CANDIDATE.read_text())["spec"]
    predecessor = Path(spec["predecessor"]["path"])
    output = Path(spec["outputPath"])
    names = set(spec["exactNames"])
    if sha(predecessor) != spec["predecessor"]["digest"] or len(names) != 5:
        raise RuntimeError("binding mismatch")
    if sha(CLIENT) != EXPECTED_CLIENT or SHARED.is_symlink() or (SHARED.stat().st_mode & 0o777) != 0o600:
        raise RuntimeError("local identity mismatch")
    if output.exists() or EPHEMERAL.exists():
        raise RuntimeError("exclusive output exists")

    evidence = {
        "apiVersion": "evidence.openkubes.io/v1alpha1",
        "kind": "GO1ClusterRoleTrackingMetadataDiagnosticEvidence",
        "candidateDigest": sha(CANDIDATE),
        "predecessorDigest": spec["predecessor"]["digest"],
        "objects": [],
        "registrationSecretReadPerformed": False,
        "rawObjectsRetained": False,
        "annotationValuesRetained": False,
        "credentialPayloadRetained": False,
        "mutationPerformed": False,
        "retryPerformed": False,
        "rollbackOrCleanupPerformed": False,
        "failureInjectionPerformed": False,
    }
    try:
        secret = exact(SHARED, spec["registrationSecretURI"])
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

        for name in sorted(names):
            value = exact(EPHEMERAL, f"/apis/rbac.authorization.k8s.io/v1/clusterroles/{name}")
            annotations = value.get("metadata", {}).get("annotations") or {}
            labels = value.get("metadata", {}).get("labels") or {}
            evidence["objects"].append({
                "name": name,
                "annotationKeys": sorted(annotations),
                "annotationValueDigests": {key: digest_text(value) for key, value in sorted(annotations.items())},
                "labelKeys": sorted(labels),
                "labelMapDigest": digest_text(json.dumps(labels, sort_keys=True, separators=(",", ":"))),
            })
        evidence["distinctAnnotationKeySets"] = len({tuple(item["annotationKeys"]) for item in evidence["objects"]})
        evidence["state"] = "PASS-TRACKING-METADATA-CLASSIFIED"
    finally:
        EPHEMERAL.unlink(missing_ok=True)

    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(evidence, handle, sort_keys=True, separators=(",", ":"))
        handle.write("\n")
    print(json.dumps({
        "state": evidence["state"],
        "distinctAnnotationKeySets": evidence["distinctAnnotationKeySets"],
        "objects": [{"name": item["name"], "annotationKeys": item["annotationKeys"]} for item in evidence["objects"]],
        "evidenceDigest": sha(output),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
