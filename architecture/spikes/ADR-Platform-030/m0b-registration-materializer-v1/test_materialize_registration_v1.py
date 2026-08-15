#!/usr/bin/env python3
from __future__ import annotations

import base64
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
SCRIPT = HERE / "materialize_registration_v1.py"
spec = importlib.util.spec_from_file_location("materializer", SCRIPT)
materializer = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(materializer)
TOKEN = "synthetic-test-token-never-a-real-credential"
CA_BYTES = b"synthetic-test-ca-not-a-real-certificate"


def runtime(now: datetime) -> dict:
    return {
        "name": "disposable-ok141",
        "server": "https://203.0.113.10:6443",
        "namespaces": "ok-observability,kube-system",
        "project": "openkubes-disposable",
        "clusterResources": True,
        "bearerToken": TOKEN,
        "caData": base64.b64encode(CA_BYTES).decode(),
        "capiClusterUID": "11111111-1111-4111-8111-111111111111",
        "workloadKubeSystemUID": "22222222-2222-4222-8222-222222222222",
        "workloadAPICAFingerprint": materializer.sha256_bytes(CA_BYTES),
        "tokenExpiration": (now + timedelta(hours=2, minutes=30)).isoformat().replace("+00:00", "Z"),
        "R": materializer.EXPECTED["R"],
        "P": materializer.EXPECTED["P"],
        "fixtureDigest": materializer.EXPECTED["fixtureDigest"],
    }


def must_fail(name: str, function) -> None:
    try:
        function()
    except materializer.MaterializerError:
        return
    raise AssertionError(f"negative control did not fail closed: {name}")


def main() -> int:
    now = datetime.now(timezone.utc)
    value = runtime(now)
    materializer.validate_runtime(value, now)
    documents = materializer.build_documents(value)
    assert len(documents) == 2
    assert documents[0]["kind"] == "AppProject"
    assert documents[0]["spec"]["permitOnlyProjectScopedClusters"] is True
    assert documents[1]["kind"] == "Secret"
    assert documents[1]["stringData"]["project"] == "openkubes-disposable"
    config = json.loads(documents[1]["stringData"]["config"])
    assert config["bearerToken"] == TOKEN
    assert config["tlsClientConfig"]["caData"] == value["caData"]

    changed = copy.deepcopy(value)
    changed["project"] = "default"
    must_fail("default-project", lambda: materializer.validate_runtime(changed, now))
    changed = copy.deepcopy(value)
    changed["workloadAPICAFingerprint"] = "sha256:" + "0" * 64
    must_fail("wrong-ca", lambda: materializer.validate_runtime(changed, now))
    changed = copy.deepcopy(value)
    changed["tokenExpiration"] = (now + timedelta(hours=4)).isoformat()
    must_fail("excessive-token-lifetime", lambda: materializer.validate_runtime(changed, now))

    candidate_digest = "sha256:" + "a" * 64
    grant = {
        "spec": {
            "decision": "GO",
            "materializerGranted": True,
            "candidateDigest": candidate_digest,
            "maximumRuns": 1,
            "grantID": "ok141-m0b-rm1-synthetic-test",
            "validFrom": (now - timedelta(minutes=1)).isoformat(),
            "validUntil": (now + timedelta(minutes=30)).isoformat(),
        }
    }
    materializer.validate_grant(grant, candidate_digest, now)
    changed_grant = copy.deepcopy(grant)
    changed_grant["spec"]["maximumRuns"] = 2
    must_fail("multi-run-grant", lambda: materializer.validate_grant(changed_grant, candidate_digest, now))

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        fake = root / "kubectl"
        fake.write_text("#!/bin/sh\ninput=$(cat)\nprintf '%s' \"$input\" >&2\nprintf 'created synthetic objects'\n")
        fake.chmod(0o700)
        grant_path = root / "grant.yaml"
        grant_path.write_text(yaml.safe_dump(grant))
        kubeconfig = root / "kubeconfig"
        kubeconfig.write_text("synthetic-not-a-real-kubeconfig")
        completed = subprocess.run(
            [
                sys.executable, str(SCRIPT), "--execute", "--grant-file", str(grant_path),
                "--candidate-digest", candidate_digest, "--kubectl", str(fake),
                "--kubeconfig", str(kubeconfig),
            ],
            input=json.dumps(value),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            env=os.environ.copy(),
        )
        assert completed.returncode == 0, completed.stderr
        combined = completed.stdout + completed.stderr
        assert TOKEN not in combined
        assert value["caData"] not in combined
        result = json.loads(completed.stdout)
        assert result["credentialPrinted"] is False
        assert result["credentialRetained"] is False
        assert result["submittedObjectCount"] == 2

    source = SCRIPT.read_text()
    assert "shell=False" in source
    assert "tempfile" not in source
    assert "bearerToken=\"" not in source
    print("PASS: 9 materializer checks; synthetic credentials absent from stdout/stderr")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
