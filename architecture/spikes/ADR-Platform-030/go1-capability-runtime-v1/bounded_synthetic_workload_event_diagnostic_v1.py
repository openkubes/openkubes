#!/usr/bin/env python3
"""Read-only normalized Event diagnosis for the failed synthetic workload."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

MGMT = Path("/private/tmp/ok141-kubectl-v1.34.1-darwin-amd64")
TARGET = Path("/usr/local/bin/kubectl")
MGMT_KUBECONFIG = Path("/Users/arash/.kube/ok-mgmt.yaml")
EPHEMERAL = Path("/private/tmp/ok141-synthetic-workload-event-diagnostic-v1-kubeconfig.yaml")
OUTPUT = Path("/private/tmp/ok141-synthetic-workload-event-diagnostic-v2-evidence.json")
RUN_NAME = "ok-observability-contract-test-ok141-happy-capability-20260815-v2"
RUN_PREFIX = "ok-observability-contract-test"


def sha(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def write_exclusive(path: Path, value: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(value)


def get(client: Path, kubeconfig: Path, uri: str) -> dict[str, Any]:
    completed = subprocess.run([str(client), "--kubeconfig", str(kubeconfig), "get", "--raw", uri], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=30)
    if completed.returncode != 0:
        raise RuntimeError("bounded GET failed; output suppressed")
    value = json.loads(completed.stdout)
    if not isinstance(value, dict):
        raise RuntimeError("GET returned non-object")
    return value


def main() -> int:
    if OUTPUT.exists() or EPHEMERAL.exists():
        raise RuntimeError("exclusive output exists")
    secret = get(MGMT, MGMT_KUBECONFIG, "/api/v1/namespaces/disposable-ok141/secrets/disposable-ok141-kubeconfig")
    write_exclusive(EPHEMERAL, base64.b64decode(secret["data"]["value"], validate=True))
    try:
        events = get(TARGET, EPHEMERAL, "/api/v1/namespaces/ok-observability/events")
        selected = []
        for item in events.get("items", []):
            involved = item.get("involvedObject", {})
            name = str(involved.get("name", ""))
            message = str(item.get("message", "")).lower()
            if RUN_PREFIX not in name and RUN_PREFIX not in message:
                continue
            selected.append({
                "type": item.get("type"),
                "reason": item.get("reason"),
                "involvedKind": involved.get("kind"),
                "count": item.get("count", 1),
                "messageDigest": sha(str(item.get("message", "")).encode()),
            })
        result = {
            "runIdentityDigest": sha(RUN_NAME.encode()),
            "matchingEventCount": len(selected),
            "events": selected,
            "rawMessagesRetained": False,
            "objectNamesRetained": False,
            "secretBytesRetained": False,
        }
    finally:
        EPHEMERAL.unlink(missing_ok=True)
    result["ephemeralKubeconfigRemoved"] = not EPHEMERAL.exists()
    result["semanticDigest"] = sha(json.dumps(result, sort_keys=True, separators=(",", ":")).encode())
    write_exclusive(OUTPUT, (json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n").encode())
    print(json.dumps({"evidencePath": str(OUTPUT), "evidenceDigest": sha(OUTPUT.read_bytes()), "semanticDigest": result["semanticDigest"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
