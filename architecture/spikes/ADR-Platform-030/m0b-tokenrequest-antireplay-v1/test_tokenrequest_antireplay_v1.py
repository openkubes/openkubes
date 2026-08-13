#!/usr/bin/env python3
from __future__ import annotations

import copy
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
SCRIPT = HERE / "tokenrequest_antireplay_v1.py"
module_spec = importlib.util.spec_from_file_location("tokenrequest_antireplay", SCRIPT)
gate = importlib.util.module_from_spec(module_spec)
assert module_spec.loader is not None
module_spec.loader.exec_module(gate)
TOKEN = "synthetic-tokenrequest-token-never-real"
CANDIDATE = "sha256:" + "b" * 64
AUDIENCE = "https://kubernetes.default.svc.cluster.local"


def grant(now: datetime) -> dict:
    return {
        "apiVersion": "authorization.openkubes.io/v1alpha1",
        "kind": "SingleRunGrant",
        "spec": {
            "decision": "GO",
            "tokenRequestGranted": True,
            "antiReplayReceiptGranted": True,
            "candidateDigest": CANDIDATE,
            "maximumRuns": 1,
            "grantID": "ok141-m0b-tr1-synthetic-test",
            "serviceAccount": "kube-system/ok141-argocd-manager",
            "audience": AUDIENCE,
            "expirationSeconds": 10800,
            "validFrom": (now - timedelta(minutes=1)).isoformat(),
            "validUntil": (now + timedelta(minutes=30)).isoformat(),
            "capiClusterUID": "11111111-1111-4111-8111-111111111111",
            "workloadKubeSystemUID": "22222222-2222-4222-8222-222222222222",
            "workloadAPICAFingerprint": "sha256:" + "c" * 64,
        },
    }


def must_fail(name: str, function) -> None:
    try:
        function()
    except gate.GateError:
        return
    raise AssertionError(f"negative control did not fail closed: {name}")


def main() -> int:
    now = datetime.now(timezone.utc)
    value = grant(now)
    spec = gate.validate_grant(value, CANDIDATE, AUDIENCE, now)
    changed = copy.deepcopy(value)
    changed["spec"]["maximumRuns"] = 2
    must_fail("multi-run-grant", lambda: gate.validate_grant(changed, CANDIDATE, AUDIENCE, now))
    changed = copy.deepcopy(value)
    changed["spec"]["workloadKubeSystemUID"] = "RUNTIME-UNBOUND"
    must_fail("unbound-runtime-identity", lambda: gate.validate_grant(changed, CANDIDATE, AUDIENCE, now))
    changed = copy.deepcopy(value)
    changed["spec"]["audience"] = "wrong"
    must_fail("wrong-audience", lambda: gate.validate_grant(changed, CANDIDATE, AUDIENCE, now))

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        receipt = root / "consumed.json"
        receipt_digest = gate.consume_once(receipt, spec, CANDIDATE, now)
        assert receipt_digest.startswith("sha256:")
        assert receipt.stat().st_mode & 0o777 == 0o600
        content = receipt.read_text()
        assert TOKEN not in content
        must_fail("receipt-replay", lambda: gate.consume_once(receipt, spec, CANDIDATE, now))

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        expiration = (datetime.now(timezone.utc) + timedelta(hours=2, minutes=30)).isoformat().replace("+00:00", "Z")
        response = json.dumps({"status": {"token": TOKEN, "expirationTimestamp": expiration}})
        fake = root / "kubectl"
        fake.write_text(f"#!/bin/sh\ncat >/dev/null\nprintf '%s' '{response}'\nprintf '%s' '{TOKEN}' >&2\n")
        fake.chmod(0o700)
        grant_path = root / "grant.yaml"
        grant_path.write_text(yaml.safe_dump(value))
        kubeconfig = root / "synthetic-kubeconfig"
        kubeconfig.write_text("synthetic-not-a-real-kubeconfig")
        receipt = root / "receipt.json"
        read_fd, write_fd = os.pipe()
        completed = subprocess.run(
            [
                sys.executable, str(SCRIPT), "--execute", "--grant-file", str(grant_path),
                "--candidate-digest", CANDIDATE, "--receipt", str(receipt),
                "--token-sink-fd", str(write_fd), "--audience", AUDIENCE,
                "--kubectl", str(fake), "--kubeconfig", str(kubeconfig),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            pass_fds=(write_fd,),
        )
        os.close(write_fd)
        piped_token = os.read(read_fd, 65536).decode()
        os.close(read_fd)
        assert completed.returncode == 0, completed.stderr
        assert piped_token == TOKEN
        combined = completed.stdout + completed.stderr + receipt.read_text()
        assert TOKEN not in combined
        result = json.loads(completed.stdout)
        assert result["credentialPrinted"] is False
        assert result["credentialRetainedByUtility"] is False
        assert result["state"] == "TOKEN-ISSUED-TO-PIPE"

        replay_read, replay_write = os.pipe()
        replay = subprocess.run(
            [
                sys.executable, str(SCRIPT), "--execute", "--grant-file", str(grant_path),
                "--candidate-digest", CANDIDATE, "--receipt", str(receipt),
                "--token-sink-fd", str(replay_write), "--audience", AUDIENCE,
                "--kubectl", str(fake), "--kubeconfig", str(kubeconfig),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            pass_fds=(replay_write,),
        )
        os.close(replay_write)
        assert os.read(replay_read, 65536) == b""
        os.close(replay_read)
        assert replay.returncode == 2
        assert "already exists" in replay.stderr
        assert TOKEN not in replay.stdout + replay.stderr

    source = SCRIPT.read_text()
    assert "shell=False" in source
    assert "O_EXCL" in source
    assert "stdout=subprocess.PIPE" in source
    assert "stderr=subprocess.PIPE" in source
    assert "tokenDigest" not in source
    print("PASS: 12 TokenRequest/anti-replay checks; synthetic token only traversed anonymous pipe")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
