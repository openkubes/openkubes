#!/usr/bin/env python3
"""Review Argo's effective global ClusterRole list/watch permissions."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
CANDIDATE = HERE / "clusterrole-cache-read-review-v1.yaml"
CLIENT = Path("/private/tmp/ok141-kubectl-v1.34.1-darwin-amd64")
SHARED = Path("/Users/arash/.kube/ok-shared.yaml")
EPHEMERAL = Path("/private/tmp/ok141-clusterrole-cache-read-review-target.yaml")
EXPECTED_CLIENT = "sha256:bb211f2b31f2b3bc60562b44cc1e3b712a16a98e9072968ba255beb04cefcfdf"


def sha(path: str | Path) -> str:
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def exact(config: Path, verb: str, uri: str, payload: bytes | None = None) -> dict:
    command = [str(CLIENT), "--kubeconfig", str(config), verb, "--raw", uri]
    if payload is not None:
        command.extend(["--filename", "-"])
    result = subprocess.run(command, input=payload, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError(f"exact {verb} failed")
    return json.loads(result.stdout)


def decode(secret: dict, name: str) -> str:
    return base64.b64decode(secret["data"][name], validate=True).decode()


def main() -> int:
    spec = yaml.safe_load(CANDIDATE.read_text())["spec"]
    predecessor = Path(spec["predecessor"]["path"])
    output = Path(spec["outputPath"])
    resource = spec["resource"]
    if sha(predecessor) != spec["predecessor"]["digest"]:
        raise RuntimeError("predecessor mismatch")
    if set(resource["exactVerbs"]) != {"list", "watch"} or resource["resourceName"] != "":
        raise RuntimeError("scope mismatch")
    if sha(CLIENT) != EXPECTED_CLIENT or SHARED.is_symlink() or (SHARED.stat().st_mode & 0o777) != 0o600:
        raise RuntimeError("local identity mismatch")
    if output.exists() or EPHEMERAL.exists():
        raise RuntimeError("exclusive output exists")

    evidence = {
        "apiVersion": "evidence.openkubes.io/v1alpha1",
        "kind": "GO1ClusterRoleCacheReadReviewEvidence",
        "candidateDigest": sha(CANDIDATE),
        "predecessorDigest": spec["predecessor"]["digest"],
        "reviews": [],
        "registrationSecretReadPerformed": False,
        "temporaryKubeconfigRemoved": False,
        "credentialPayloadRetained": False,
        "rawResponsesRetained": False,
        "mutationPerformed": False,
        "retryPerformed": False,
        "cleanupPerformed": False,
        "failureInjectionPerformed": False,
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

        uri = "/apis/authorization.k8s.io/v1/selfsubjectaccessreviews"
        for verb in sorted(resource["exactVerbs"]):
            body = {
                "apiVersion": "authorization.k8s.io/v1",
                "kind": "SelfSubjectAccessReview",
                "spec": {"resourceAttributes": {
                    "group": resource["apiGroup"],
                    "resource": resource["resource"],
                    "verb": verb,
                }},
            }
            response = exact(EPHEMERAL, "create", uri, json.dumps(body, separators=(",", ":")).encode())
            status = response.get("status", {})
            evidence["reviews"].append({"verb": verb, "allowed": status.get("allowed") is True, "denied": status.get("denied") is True})
        evidence["allDenied"] = all(not item["allowed"] for item in evidence["reviews"])
        evidence["state"] = "PASS-CACHE-READ-GAP-CONFIRMED" if evidence["allDenied"] else "UNEXPECTED-PERMISSION-STATE"
    finally:
        EPHEMERAL.unlink(missing_ok=True)
        evidence["temporaryKubeconfigRemoved"] = not EPHEMERAL.exists()

    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(evidence, handle, sort_keys=True, separators=(",", ":"))
        handle.write("\n")
    print(json.dumps({"state": evidence["state"], "reviews": evidence["reviews"], "evidenceDigest": sha(output)}, sort_keys=True))
    return 0 if evidence["state"].startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
