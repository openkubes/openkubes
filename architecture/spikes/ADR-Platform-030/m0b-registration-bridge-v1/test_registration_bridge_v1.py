#!/usr/bin/env python3
from __future__ import annotations

import base64
import copy
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml


HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "registration_bridge_v1.py"
module_spec = importlib.util.spec_from_file_location("registration_bridge", SCRIPT)
bridge = importlib.util.module_from_spec(module_spec)
assert module_spec.loader is not None
module_spec.loader.exec_module(bridge)
CANDIDATE = "sha256:" + "d" * 64
AUDIENCE = "https://kubernetes.default.svc.cluster.local"
TOKEN = "synthetic-registration-bridge-token-never-real"
CA = b"synthetic-bridge-ca-not-a-real-certificate"
CAPI_UID = "11111111-1111-4111-8111-111111111111"
WORKLOAD_UID = "22222222-2222-4222-8222-222222222222"
CA_HASH = "sha256:" + hashlib.sha256(CA).hexdigest()


def grants(now: datetime) -> tuple[dict, dict]:
    common = {
        "decision": "GO",
        "candidateDigest": CANDIDATE,
        "maximumRuns": 1,
        "validFrom": (now - timedelta(minutes=1)).isoformat(),
        "validUntil": (now + timedelta(minutes=30)).isoformat(),
    }
    token = {
        **common,
        "grantID": "ok141-m0b-tr1-synthetic-bridge",
        "pairedGrantID": "ok141-m0b-rm1-synthetic-bridge",
        "tokenRequestGranted": True,
        "antiReplayReceiptGranted": True,
        "serviceAccount": "kube-system/ok141-argocd-manager",
        "audience": AUDIENCE,
        "expirationSeconds": 10800,
        "capiClusterUID": CAPI_UID,
        "workloadKubeSystemUID": WORKLOAD_UID,
        "workloadAPICAFingerprint": CA_HASH,
    }
    materializer = {
        **common,
        "grantID": "ok141-m0b-rm1-synthetic-bridge",
        "pairedGrantID": "ok141-m0b-tr1-synthetic-bridge",
        "materializerGranted": True,
    }
    return token, materializer


def runtime() -> dict:
    return {
        "name": "disposable-ok141",
        "server": "https://203.0.113.10:6443",
        "namespaces": "ok-observability,kube-system",
        "project": "openkubes-disposable",
        "clusterResources": True,
        "caData": base64.b64encode(CA).decode(),
        "capiClusterUID": CAPI_UID,
        "workloadKubeSystemUID": WORKLOAD_UID,
        "workloadAPICAFingerprint": CA_HASH,
        "R": "sha256:636fe23404ac53109f44d6346534dcf1367ae91c572d5e18bd32cd0a3128a16e",
        "P": "sha256:b0f25c639a45d895b889997f5ecc2325db45dd5d51b0684998c94d5e17bd47bf",
        "fixtureDigest": "sha256:a2ae3437645db5a83426b89d36d00693d2600e4ef20dc1aba2650dcda7f936f6",
    }


def must_fail(name: str, function) -> None:
    try:
        function()
    except bridge.BridgeError:
        return
    raise AssertionError(f"negative control did not fail closed: {name}")


def main() -> int:
    now = datetime.now(timezone.utc)
    token_grant, materializer_grant = grants(now)
    bridge.validate_pair(token_grant, materializer_grant, CANDIDATE, now)
    bridge.validate_runtime(runtime(), token_grant)
    changed = copy.deepcopy(materializer_grant)
    changed["pairedGrantID"] = "wrong"
    must_fail("unpaired-grant", lambda: bridge.validate_pair(token_grant, changed, CANDIDATE, now))
    changed_runtime = runtime()
    changed_runtime["capiClusterUID"] = "33333333-3333-4333-8333-333333333333"
    must_fail("runtime-correlation", lambda: bridge.validate_runtime(changed_runtime, token_grant))

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        expiration = (datetime.now(timezone.utc) + timedelta(hours=2, minutes=30)).isoformat().replace("+00:00", "Z")
        token_response = json.dumps({"status": {"token": TOKEN, "expirationTimestamp": expiration}})
        fake = root / "kubectl"
        fake.write_text(
            "#!/bin/sh\n"
            "case \" $* \" in\n"
            f"  *\" --raw \"*) cat >/dev/null; printf '%s' '{token_response}'; printf '%s' '{TOKEN}' >&2 ;;\n"
            f"  *) input=$(cat); printf '%s' \"$input\" >&2; printf 'created'; printf '%s' '{TOKEN}' >&2 ;;\n"
            "esac\n"
        )
        fake.chmod(0o700)
        token_path = root / "token-grant.yaml"
        materializer_path = root / "materializer-grant.yaml"
        token_path.write_text(yaml.safe_dump({"spec": token_grant}))
        materializer_path.write_text(yaml.safe_dump({"spec": materializer_grant}))
        target_kubeconfig = root / "target-kubeconfig"
        shared_kubeconfig = root / "shared-kubeconfig"
        target_kubeconfig.write_text("synthetic-target-kubeconfig")
        shared_kubeconfig.write_text("synthetic-shared-kubeconfig")
        receipt = root / "receipt.json"
        completed = subprocess.run(
            [
                sys.executable, str(SCRIPT), "--execute",
                "--token-grant-file", str(token_path),
                "--materializer-grant-file", str(materializer_path),
                "--candidate-digest", CANDIDATE,
                "--receipt", str(receipt),
                "--target-kubectl", str(fake),
                "--target-kubeconfig", str(target_kubeconfig),
                "--shared-kubectl", str(fake),
                "--shared-kubeconfig", str(shared_kubeconfig),
            ],
            input=json.dumps(runtime()),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        assert completed.returncode == 0, completed.stderr
        combined = completed.stdout + completed.stderr + receipt.read_text()
        assert TOKEN not in combined
        assert base64.b64encode(CA).decode() not in combined
        result = json.loads(completed.stdout)
        assert result["state"] == "REGISTRATION-CREATED"
        assert result["submittedObjectCount"] == 2
        assert result["credentialPrinted"] is False
        assert result["credentialRetainedByBridge"] is False

        replay = subprocess.run(
            [
                sys.executable, str(SCRIPT), "--execute",
                "--token-grant-file", str(token_path),
                "--materializer-grant-file", str(materializer_path),
                "--candidate-digest", CANDIDATE,
                "--receipt", str(receipt),
                "--target-kubectl", str(fake),
                "--target-kubeconfig", str(target_kubeconfig),
                "--shared-kubectl", str(fake),
                "--shared-kubeconfig", str(shared_kubeconfig),
            ],
            input=json.dumps(runtime()),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        assert replay.returncode == 2
        assert TOKEN not in replay.stdout + replay.stderr
        assert "TokenRequest child failed" in replay.stderr

    source = SCRIPT.read_text()
    assert "shell=False" in source
    assert "tempfile" not in source
    assert "stdout=subprocess.PIPE" in source
    assert "stderr=subprocess.PIPE" in source
    assert "bearerToken" in source
    print("PASS: 10 bridge checks; synthetic token crossed child boundaries without output or file persistence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
