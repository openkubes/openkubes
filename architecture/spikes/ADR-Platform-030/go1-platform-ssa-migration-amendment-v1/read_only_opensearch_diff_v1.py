#!/usr/bin/env python3
"""Render the bound Core source and report only redacted live/desired diff paths."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile

import yaml


SPIKE = Path(__file__).resolve().parents[1]
SOURCE_REPO = Path("/Users/arash/temp/kubernauts/ok/ok-observability")
SOURCE_COMMIT = "b5f7be6a7ddab798f31f32197fcbb9e86a9798b6"
APPLICATIONS = SPIKE / "harness/profiles/platform/minimal-observability-v7/applications.yaml"
CLIENT = Path("/private/tmp/ok141-kubectl-v1.34.1-darwin-amd64")
MGMT_KUBECONFIG = Path("/Users/arash/.kube/ok-mgmt.yaml")
EPHEMERAL = Path("/private/tmp/ok141-opensearch-diff-workload-kubeconfig.yaml")
SECRET_URI = "/api/v1/namespaces/disposable-ok141/secrets/disposable-ok141-kubeconfig"
LIVE_URI = "/apis/apps/v1/namespaces/ok-observability/statefulsets/ok-observability-opensearch"


def request(kubeconfig: Path, uri: str) -> dict:
    completed = subprocess.run(
        [str(CLIENT), "--kubeconfig", str(kubeconfig), "get", "--raw", uri],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode:
        raise RuntimeError(f"bounded exact GET failed: exit={completed.returncode}")
    return json.loads(completed.stdout)


def value_digest(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def walk(desired: object, live: object, path: str = "") -> list[dict]:
    if type(desired) is not type(live):
        return [{"path": path or "/", "class": "type", "desiredDigest": value_digest(desired), "liveDigest": value_digest(live)}]
    if isinstance(desired, dict):
        result = []
        for key in sorted(set(desired) | set(live)):
            child = f"{path}/{key}"
            if key not in desired:
                result.append({"path": child, "class": "live-only", "liveDigest": value_digest(live[key])})
            elif key not in live:
                result.append({"path": child, "class": "desired-only", "desiredDigest": value_digest(desired[key])})
            else:
                result.extend(walk(desired[key], live[key], child))
        return result
    if isinstance(desired, list):
        if desired == live:
            return []
        def item_name(item: object) -> str | None:
            if not isinstance(item, dict):
                return None
            if isinstance(item.get("name"), str):
                return item["name"]
            metadata = item.get("metadata")
            return metadata.get("name") if isinstance(metadata, dict) and isinstance(metadata.get("name"), str) else None

        if all(item_name(item) is not None for item in desired + live):
            desired_by_name = {item_name(item): item for item in desired}
            live_by_name = {item_name(item): item for item in live}
            if len(desired_by_name) == len(desired) and len(live_by_name) == len(live):
                result = []
                for name in sorted(set(desired_by_name) | set(live_by_name)):
                    child = f"{path}[name={name}]"
                    if name not in desired_by_name:
                        result.append({"path": child, "class": "live-only", "liveDigest": value_digest(live_by_name[name])})
                    elif name not in live_by_name:
                        result.append({"path": child, "class": "desired-only", "desiredDigest": value_digest(desired_by_name[name])})
                    else:
                        result.extend(walk(desired_by_name[name], live_by_name[name], child))
                return result
        return [{"path": path or "/", "class": "list", "desiredDigest": value_digest(desired), "liveDigest": value_digest(live)}]
    if desired != live:
        return [{"path": path or "/", "class": "value", "desiredDigest": value_digest(desired), "liveDigest": value_digest(live)}]
    return []


def main() -> None:
    app = next(
        item
        for item in yaml.safe_load_all(APPLICATIONS.read_text())
        if item and item.get("metadata", {}).get("name") == "disposable-ok141-observability-core"
    )
    values = app["spec"]["source"]["helm"]["valuesObject"]
    with tempfile.TemporaryDirectory(prefix="ok141-opensearch-diff-") as directory:
        root = Path(directory)
        archive = root / "source.tar"
        subprocess.run(
            ["git", "-C", str(SOURCE_REPO), "archive", "--format=tar", f"--output={archive}", SOURCE_COMMIT],
            check=True,
        )
        source = root / "source"
        source.mkdir()
        with tarfile.open(archive, "r") as handle:
            handle.extractall(source, filter="data")
        values_path = root / "values.yaml"
        values_path.write_text(yaml.safe_dump(values, sort_keys=True))
        rendered = subprocess.run(
            [
                "helm", "template", "disposable-ok141-observability-core",
                str(source / "profiles/ok-observability-standard"),
                "--namespace", "ok-observability", "--kube-version", "1.36.2",
                "--include-crds", "--values", str(values_path),
            ],
            check=True,
            stdout=subprocess.PIPE,
        ).stdout.decode()
    selected = subprocess.run(
        [
            "yq", "eval-all", "--output-format=json",
            'select(.kind == "StatefulSet" and .metadata.name == "ok-observability-opensearch")',
            "-",
        ],
        input=rendered.encode(),
        check=True,
        stdout=subprocess.PIPE,
    ).stdout
    desired = json.loads(selected)

    secret = request(MGMT_KUBECONFIG, SECRET_URI)
    EPHEMERAL.write_bytes(base64.b64decode(secret["data"]["value"], validate=True))
    os.chmod(EPHEMERAL, 0o600)
    try:
        live = request(EPHEMERAL, LIVE_URI)
    finally:
        EPHEMERAL.unlink(missing_ok=True)

    managers = sorted(
        {
            (
                item.get("manager"),
                item.get("operation"),
                item.get("subresource"),
            )
            for item in live.get("metadata", {}).get("managedFields", [])
        }
    )
    for obj in (desired, live):
        obj.pop("status", None)
        metadata = obj.get("metadata", {})
        for key in ("creationTimestamp", "generation", "managedFields", "resourceVersion", "uid"):
            metadata.pop(key, None)
    differences = walk(desired, live)
    print(
        json.dumps(
            {
                "desiredDigest": value_digest(desired),
                "liveDigest": value_digest(live),
                "differenceCount": len(differences),
                "differences": differences,
                "managedFieldManagers": [
                    {"manager": item[0], "operation": item[1], "subresource": item[2]}
                    for item in managers
                ],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
