#!/usr/bin/env python3
"""Render and inventory the exact OK-141 Platform P-double-prime source offline."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import yaml


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
APPLICATIONS = SPIKE / "harness/profiles/platform/minimal-observability-v3/applications.yaml"
SOURCE_COMMIT = "fe394da8875adecc3b497137e546cecabd710d1d"
DESTINATION_NAMESPACE = "ok-observability"
KUBE_VERSION = "1.36.2"
CLUSTER_SCOPED = {
    ("apiextensions.k8s.io", "CustomResourceDefinition"),
    ("rbac.authorization.k8s.io", "ClusterRole"),
    ("rbac.authorization.k8s.io", "ClusterRoleBinding"),
    ("admissionregistration.k8s.io", "MutatingWebhookConfiguration"),
    ("admissionregistration.k8s.io", "ValidatingWebhookConfiguration"),
}
VENDORED_DEPENDENCIES = [
    "implementations/prometheus/charts/kube-prometheus-stack-62.7.0.tgz",
    "implementations/grafana/charts/grafana-8.6.4.tgz",
    "implementations/opensearch/charts/opensearch-2.30.1.tgz",
    "implementations/opensearch/charts/fluent-bit-0.48.6.tgz",
    "profiles/ok-observability-standard/charts/ok-observability-prometheus-0.1.0.tgz",
    "profiles/ok-observability-standard/charts/ok-observability-grafana-0.1.0.tgz",
    "profiles/ok-observability-standard/charts/ok-observability-opensearch-0.1.0.tgz",
]


def _sha256(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _documents(raw: bytes) -> list[dict[str, Any]]:
    # Helm can emit unquoted YAML 1.1 scalar tokens such as "=" in probe args.
    # BaseLoader is sufficient here because the inventory reads identity fields
    # only and must not reinterpret application values.
    return [item for item in yaml.load_all(raw, Loader=yaml.BaseLoader) if item]


def _git_bytes(repo: Path, path: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(repo), "show", f"{SOURCE_COMMIT}:{path}"],
        check=True,
        capture_output=True,
    ).stdout


def _api_group(api_version: str) -> str:
    return api_version.split("/", 1)[0] if "/" in api_version else ""


def _entry(document: dict[str, Any], source: str) -> dict[str, Any]:
    api_version = document["apiVersion"]
    kind = document["kind"]
    metadata = document.get("metadata", {})
    cluster_scoped = (_api_group(api_version), kind) in CLUSTER_SCOPED
    namespace = None if cluster_scoped else metadata.get("namespace", DESTINATION_NAMESPACE)
    return {
        "source": source,
        "apiVersion": api_version,
        "kind": kind,
        "namespace": namespace,
        "name": metadata.get("name"),
        "generateName": metadata.get("generateName"),
    }


def render(source_repo: Path) -> dict[str, Any]:
    applications = {
        item["metadata"]["name"]: item
        for item in yaml.safe_load_all(APPLICATIONS.read_text())
        if item
    }
    core = applications["disposable-ok141-observability-core"]
    values = yaml.safe_dump(
        core["spec"]["source"]["helm"]["valuesObject"],
        sort_keys=True,
    ).encode()

    with tempfile.TemporaryDirectory(prefix="ok141-m0b-") as directory:
        root = Path(directory)
        values_path = root / "provider-values.yaml"
        values_path.write_bytes(values)
        chart = source_repo / "profiles/ok-observability-standard"
        rendered = subprocess.run(
            [
                "helm", "template", "disposable-ok141-observability-core", str(chart),
                "--namespace", DESTINATION_NAMESPACE,
                "--kube-version", KUBE_VERSION,
                "--include-crds", "--values", str(values_path),
            ],
            check=True,
            capture_output=True,
        ).stdout

    source_documents = {
        "core": _documents(rendered),
        "alerting": _documents(_git_bytes(source_repo, "alerting/prometheus-rules.yaml")),
        "dashboards": _documents(_git_bytes(source_repo, "dashboards/platform-overview-configmap.yaml")),
    }
    inventory = sorted(
        (_entry(document, source) for source, docs in source_documents.items() for document in docs),
        key=lambda item: (
            item["source"], item["apiVersion"], item["kind"],
            item["namespace"] or "", item["name"] or "", item["generateName"] or "",
        ),
    )
    canonical = json.dumps(inventory, sort_keys=True, separators=(",", ":")).encode()
    dependencies = []
    for relative in VENDORED_DEPENDENCIES:
        artifact = source_repo / relative
        if not artifact.is_file():
            raise FileNotFoundError(f"missing local dependency artifact: {relative}")
        tracked = subprocess.run(
            ["git", "-C", str(source_repo), "ls-files", "--error-unmatch", relative],
            capture_output=True,
        ).returncode == 0
        dependencies.append(
            {"path": relative, "digest": _sha256(artifact.read_bytes()), "trackedAtSourceCommit": tracked}
        )
    return {
        "format": "ok141-platform-rendered-inventory/v1",
        "sourceCommit": SOURCE_COMMIT,
        "renderer": {
            "helmVersion": subprocess.run(
                ["helm", "version", "--short"], check=True, capture_output=True, text=True
            ).stdout.strip(),
            "kubernetesVersion": "v" + KUBE_VERSION,
            "includeCRDs": True,
        },
        "coreRenderedRawDigest": _sha256(rendered),
        "inventoryDigest": _sha256(canonical),
        "objectCount": len(inventory),
        "objects": inventory,
        "dependencyArtifacts": dependencies,
        "sourceProvenance": "LOCAL-IGNORED-DEPENDENCIES-NOT-AUTHORITATIVE",
        "authorization": "NO-GO",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-repo", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = json.dumps(render(args.source_repo), indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(result)
    else:
        print(result, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
