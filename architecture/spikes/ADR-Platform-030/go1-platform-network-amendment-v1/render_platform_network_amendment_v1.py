#!/usr/bin/env python3
"""Render and verify the target-network-specific OK-141 Platform amendment."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
BASE_PATH = SPIKE / "m0b-v2/render_platform_inventory_v2.py"
APPLICATIONS = SPIKE / "harness/profiles/platform/minimal-observability-v5/applications.yaml"
BASE_INVENTORY = SPIKE / "m0b-v2/platform-rendered-inventory-v2.json"
EXPECTED_REMOVED = {
    ("monitoring.coreos.com/v1", "PrometheusRule", "ok-observability", "ok-observability-etcd"),
    ("monitoring.coreos.com/v1", "PrometheusRule", "ok-observability", "ok-observability-kube-scheduler.rules"),
    ("monitoring.coreos.com/v1", "PrometheusRule", "ok-observability", "ok-observability-kubernetes-system-controller-manager"),
    ("monitoring.coreos.com/v1", "PrometheusRule", "ok-observability", "ok-observability-kubernetes-system-kube-proxy"),
    ("monitoring.coreos.com/v1", "PrometheusRule", "ok-observability", "ok-observability-kubernetes-system-scheduler"),
    ("monitoring.coreos.com/v1", "ServiceMonitor", "ok-observability", "ok-observability-coredns"),
    ("monitoring.coreos.com/v1", "ServiceMonitor", "ok-observability", "ok-observability-kube-controller-manager"),
    ("monitoring.coreos.com/v1", "ServiceMonitor", "ok-observability", "ok-observability-kube-etcd"),
    ("monitoring.coreos.com/v1", "ServiceMonitor", "ok-observability", "ok-observability-kube-proxy"),
    ("monitoring.coreos.com/v1", "ServiceMonitor", "ok-observability", "ok-observability-kube-scheduler"),
    ("v1", "Service", "kube-system", "ok-observability-coredns"),
    ("v1", "Service", "kube-system", "ok-observability-kube-controller-manager"),
    ("v1", "Service", "kube-system", "ok-observability-kube-etcd"),
    ("v1", "Service", "kube-system", "ok-observability-kube-proxy"),
    ("v1", "Service", "kube-system", "ok-observability-kube-scheduler"),
}


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


BASE = load("ok141_m0b_render_for_network_amendment", BASE_PATH)


def identity(item: dict) -> tuple[str, str, str, str]:
    return (
        item["apiVersion"], item["kind"], item.get("namespace") or "",
        item.get("name") or item.get("generateName") or "",
    )


def render(source_repo: Path) -> dict:
    original = BASE.APPLICATIONS
    try:
        BASE.APPLICATIONS = APPLICATIONS
        result = BASE.render(source_repo)
    finally:
        BASE.APPLICATIONS = original
    base = json.loads(BASE_INVENTORY.read_text(encoding="utf-8"))
    old, new = {identity(x) for x in base["objects"]}, {identity(x) for x in result["objects"]}
    removed, added = old - new, new - old
    if removed != EXPECTED_REMOVED or added:
        raise RuntimeError("render delta is not the exact target-network amendment")
    if any(item.get("namespace") == "kube-system" for item in result["objects"]):
        raise RuntimeError("amended Platform render still targets kube-system")
    result["format"] = "ok141-platform-rendered-inventory/network-amendment-v1"
    result["baseInventoryDigest"] = base["inventoryDigest"]
    result["removedObjects"] = [
        {"apiVersion": x[0], "kind": x[1], "namespace": x[2], "name": x[3]}
        for x in sorted(removed)
    ]
    result["semanticDelta"] = "disable-target-incompatible-control-plane-scrapes"
    result["authorization"] = "NO-GO"
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-repo", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        raw = json.dumps(render(args.source_repo), indent=2, sort_keys=True) + "\n"
        if args.output:
            args.output.write_text(raw, encoding="utf-8")
        else:
            print(raw, end="")
        return 0
    except (OSError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
