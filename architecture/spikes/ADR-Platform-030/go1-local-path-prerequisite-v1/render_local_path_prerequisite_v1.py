#!/usr/bin/env python3
"""Render the exact OK-141 local-path prerequisite from the pinned upstream source."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml


HERE = Path(__file__).resolve().parent
SOURCE = HERE / "upstream-local-path-storage-v0.0.30.yaml"
OUTPUT = HERE / "local-path-storage-ok141-v1.yaml"
SOURCE_DIGEST = "sha256:fe682186b00400fe7e2b72bae16f63e47a56a6dcc677938c6642139ef670045e"
PROVISIONER_IMAGE = "rancher/local-path-provisioner@sha256:9b914881170048f80ae9302f36e5b99b4a6b18af73a38adc1c66d12f65d360be"
HELPER_IMAGE = "busybox@sha256:dc2d74b28e4cf8984fa52af1f39bc7c3d9c73760b41a74d629f5d11b1ab28616"
PSA = {
    "pod-security.kubernetes.io/enforce": "privileged",
    "pod-security.kubernetes.io/warn": "privileged",
    "pod-security.kubernetes.io/audit": "privileged",
}
DEFAULT_SC = {"storageclass.kubernetes.io/is-default-class": "true"}


class RenderError(ValueError):
    pass


def sha_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def sha(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def identity(value: dict[str, Any]) -> str:
    metadata = value.get("metadata", {})
    return "|".join((value.get("apiVersion", ""), value.get("kind", ""), metadata.get("namespace", ""), metadata.get("name", "")))


def canonical_digest(values: list[dict[str, Any]]) -> str:
    return sha_bytes(json.dumps(values, sort_keys=True, separators=(",", ":")).encode())


def source_objects(path: Path = SOURCE) -> list[dict[str, Any]]:
    if sha(path) != SOURCE_DIGEST:
        raise RenderError("upstream source digest mismatch")
    values = list(yaml.safe_load_all(path.read_text()))
    if len(values) != 9 or any(not isinstance(value, dict) for value in values):
        raise RenderError("unexpected upstream object set")
    return values


def render(path: Path = SOURCE) -> list[dict[str, Any]]:
    values = copy.deepcopy(source_objects(path))
    by_kind = {value["kind"]: value for value in values}
    by_kind["Namespace"].setdefault("metadata", {}).setdefault("labels", {}).update(PSA)
    by_kind["StorageClass"].setdefault("metadata", {}).setdefault("annotations", {}).update(DEFAULT_SC)
    deployment = by_kind["Deployment"]
    deployment["spec"]["template"]["spec"]["containers"][0]["image"] = PROVISIONER_IMAGE
    config = by_kind["ConfigMap"]
    helper = yaml.safe_load(config["data"]["helperPod.yaml"])
    helper["spec"]["containers"][0]["image"] = HELPER_IMAGE
    config["data"]["helperPod.yaml"] = yaml.safe_dump(helper, sort_keys=False).rstrip()
    expected = {
        "v1|Namespace||local-path-storage",
        "v1|ServiceAccount|local-path-storage|local-path-provisioner-service-account",
        "rbac.authorization.k8s.io/v1|Role|local-path-storage|local-path-provisioner-role",
        "rbac.authorization.k8s.io/v1|ClusterRole||local-path-provisioner-role",
        "rbac.authorization.k8s.io/v1|RoleBinding|local-path-storage|local-path-provisioner-bind",
        "rbac.authorization.k8s.io/v1|ClusterRoleBinding||local-path-provisioner-bind",
        "apps/v1|Deployment|local-path-storage|local-path-provisioner",
        "storage.k8s.io/v1|StorageClass||local-path",
        "v1|ConfigMap|local-path-storage|local-path-config",
    }
    if {identity(value) for value in values} != expected:
        raise RenderError("projected identity set mismatch")
    return values


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "render"))
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    values = render()
    raw = yaml.safe_dump_all(values, sort_keys=False, explicit_start=True).encode()
    if args.command == "render":
        args.output.write_bytes(raw)
    print(json.dumps({"sourceDigest": sha(SOURCE), "semanticDigest": canonical_digest(values), "renderedDigest": sha_bytes(raw), "objects": len(values)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
