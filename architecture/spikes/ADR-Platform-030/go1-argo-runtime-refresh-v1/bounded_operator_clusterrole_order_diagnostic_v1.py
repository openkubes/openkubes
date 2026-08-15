#!/usr/bin/env python3
"""Classify exact and normalized rule ordering for one ClusterRole."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
CANDIDATE = HERE / "operator-clusterrole-order-diagnostic-v1.yaml"
CLIENT = Path("/private/tmp/ok141-kubectl-v1.34.1-darwin-amd64")
SHARED = Path("/Users/arash/.kube/ok-shared.yaml")
EPHEMERAL = Path("/private/tmp/ok141-operator-clusterrole-order-target.yaml")
EXPECTED_CLIENT = "sha256:bb211f2b31f2b3bc60562b44cc1e3b712a16a98e9072968ba255beb04cefcfdf"


def sha(path: str | Path) -> str:
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(value) -> str:
    return "sha256:" + hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def exact(config: Path, uri: str) -> dict:
    result = subprocess.run([str(CLIENT), "--kubeconfig", str(config), "get", "--raw", uri], capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError("exact GET failed")
    return json.loads(result.stdout)


def decode(secret: dict, name: str) -> str:
    return base64.b64decode(secret["data"][name], validate=True).decode()


def normalized_sequence(value: dict) -> list[dict]:
    return [{
        "apiGroups": sorted(rule.get("apiGroups") or []),
        "resources": sorted(rule.get("resources") or []),
        "resourceNames": sorted(rule.get("resourceNames") or []),
        "verbs": sorted(rule.get("verbs") or []),
        "nonResourceURLs": sorted(rule.get("nonResourceURLs") or []),
    } for rule in value.get("rules") or []]


def main() -> int:
    spec = yaml.safe_load(CANDIDATE.read_text())["spec"]
    predecessor = Path(spec["predecessor"]["path"])
    desired_path = Path(spec["exactClusterRole"]["desiredManifestPath"])
    output = Path(spec["outputPath"])
    if sha(predecessor) != spec["predecessor"]["digest"] or sha(desired_path) != spec["exactClusterRole"]["desiredManifestDigest"]:
        raise RuntimeError("binding mismatch")
    if sha(CLIENT) != EXPECTED_CLIENT or SHARED.is_symlink() or (SHARED.stat().st_mode & 0o777) != 0o600:
        raise RuntimeError("local identity mismatch")
    if output.exists() or EPHEMERAL.exists():
        raise RuntimeError("exclusive output exists")

    evidence = {
        "apiVersion": "evidence.openkubes.io/v1alpha1",
        "kind": "GO1OperatorClusterRoleOrderDiagnosticEvidence",
        "candidateDigest": sha(CANDIDATE),
        "predecessorDigest": spec["predecessor"]["digest"],
        "rawObjectsRetained": False,
        "rawRulesRetained": False,
        "credentialPayloadRetained": False,
        "mutationPerformed": False,
        "retryPerformed": False,
        "rollbackOrCleanupPerformed": False,
        "failureInjectionPerformed": False,
    }
    try:
        secret = exact(SHARED, spec["registrationSecretURI"])
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

        live = exact(EPHEMERAL, spec["exactClusterRole"]["uri"])
        desired = yaml.safe_load(desired_path.read_text())
        live_rules = live.get("rules") or []
        desired_rules = desired.get("rules") or []
        live_normalized = normalized_sequence(live)
        desired_normalized = normalized_sequence(desired)
        evidence.update({
            "exactRuleSequenceEquivalent": live_rules == desired_rules,
            "normalizedRuleSequenceEquivalent": live_normalized == desired_normalized,
            "liveExactRuleSequenceDigest": digest(live_rules),
            "desiredExactRuleSequenceDigest": digest(desired_rules),
            "liveNormalizedRuleSequenceDigest": digest(live_normalized),
            "desiredNormalizedRuleSequenceDigest": digest(desired_normalized),
            "typeMetaEquivalent": (live.get("apiVersion"), live.get("kind")) == (desired.get("apiVersion"), desired.get("kind")),
            "nameEquivalent": live.get("metadata", {}).get("name") == desired.get("metadata", {}).get("name"),
            "state": "PASS-ORDER-DIFF-CLASSIFIED",
        })
    finally:
        EPHEMERAL.unlink(missing_ok=True)

    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(evidence, handle, sort_keys=True, separators=(",", ":"))
        handle.write("\n")
    print(json.dumps({
        "state": evidence["state"],
        "exactRuleSequenceEquivalent": evidence["exactRuleSequenceEquivalent"],
        "normalizedRuleSequenceEquivalent": evidence["normalizedRuleSequenceEquivalent"],
        "evidenceDigest": sha(output),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
