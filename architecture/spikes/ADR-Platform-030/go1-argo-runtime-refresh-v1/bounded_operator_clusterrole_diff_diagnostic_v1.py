#!/usr/bin/env python3
"""Classify the exact live-vs-rendered operator ClusterRole difference."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
CANDIDATE = HERE / "operator-clusterrole-diff-diagnostic-v1.yaml"
CLIENT = Path("/private/tmp/ok141-kubectl-v1.34.1-darwin-amd64")
SHARED = Path("/Users/arash/.kube/ok-shared.yaml")
EPHEMERAL = Path("/private/tmp/ok141-operator-clusterrole-diff-target.yaml")
EXPECTED_CLIENT = "sha256:bb211f2b31f2b3bc60562b44cc1e3b712a16a98e9072968ba255beb04cefcfdf"


def sha(path: str | Path) -> str:
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(value) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def exact(config: Path, uri: str) -> dict:
    result = subprocess.run([str(CLIENT), "--kubeconfig", str(config), "get", "--raw", uri], capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError("exact GET failed")
    return json.loads(result.stdout)


def decode(secret: dict, name: str) -> str:
    return base64.b64decode(secret["data"][name], validate=True).decode()


def rule_set(value: dict) -> dict[str, dict]:
    result = {}
    for rule in value.get("rules") or []:
        canonical = {
            "apiGroups": sorted(rule.get("apiGroups") or []),
            "resources": sorted(rule.get("resources") or []),
            "resourceNames": sorted(rule.get("resourceNames") or []),
            "verbs": sorted(rule.get("verbs") or []),
            "nonResourceURLs": sorted(rule.get("nonResourceURLs") or []),
        }
        result[digest(canonical)] = canonical
    return result


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
        "kind": "GO1OperatorClusterRoleDiffDiagnosticEvidence",
        "candidateDigest": sha(CANDIDATE),
        "predecessorDigest": spec["predecessor"]["digest"],
        "exactClusterRoleName": spec["exactClusterRole"]["name"],
        "registrationSecretReadPerformed": False,
        "rawObjectRetained": False,
        "rawRulesRetained": False,
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

        live = exact(EPHEMERAL, spec["exactClusterRole"]["uri"])
        desired = yaml.safe_load(desired_path.read_text())
        if live.get("metadata", {}).get("name") != spec["exactClusterRole"]["name"] or desired.get("metadata", {}).get("name") != spec["exactClusterRole"]["name"]:
            raise RuntimeError("role identity mismatch")
        live_rules, desired_rules = rule_set(live), rule_set(desired)
        live_labels = live.get("metadata", {}).get("labels") or {}
        desired_labels = desired.get("metadata", {}).get("labels") or {}
        live_annotations = live.get("metadata", {}).get("annotations") or {}
        desired_annotations = desired.get("metadata", {}).get("annotations") or {}
        evidence.update({
            "liveRuleCount": len(live_rules),
            "desiredRuleCount": len(desired_rules),
            "missingRuleDigests": sorted(set(desired_rules) - set(live_rules)),
            "extraRuleDigests": sorted(set(live_rules) - set(desired_rules)),
            "rulesEquivalent": set(live_rules) == set(desired_rules),
            "aggregationRuleEquivalent": live.get("aggregationRule") == desired.get("aggregationRule"),
            "labelKeySetsEquivalent": set(live_labels) == set(desired_labels),
            "labelValuesEquivalent": live_labels == desired_labels,
            "extraAnnotationKeys": sorted(set(live_annotations) - set(desired_annotations)),
            "missingAnnotationKeys": sorted(set(desired_annotations) - set(live_annotations)),
            "desiredAnnotationValuesEquivalent": all(live_annotations.get(key) == value for key, value in desired_annotations.items()),
            "ownerReferencePresent": bool(live.get("metadata", {}).get("ownerReferences")),
            "finalizerPresent": bool(live.get("metadata", {}).get("finalizers")),
        })
        evidence["state"] = "PASS-DIFF-CLASSIFIED"
    finally:
        EPHEMERAL.unlink(missing_ok=True)

    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(evidence, handle, sort_keys=True, separators=(",", ":"))
        handle.write("\n")
    print(json.dumps({
        "state": evidence["state"],
        "rulesEquivalent": evidence["rulesEquivalent"],
        "missingRuleCount": len(evidence["missingRuleDigests"]),
        "extraRuleCount": len(evidence["extraRuleDigests"]),
        "labelValuesEquivalent": evidence["labelValuesEquivalent"],
        "extraAnnotationKeys": evidence["extraAnnotationKeys"],
        "evidenceDigest": sha(output),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
