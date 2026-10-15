#!/usr/bin/env python3
"""Read-only ok-kagent preflight and local CRD-schema validation.

The only cluster requests made by this program are version discovery and GETs
for the three kagent CRDs.  Manifest validation happens locally against the
OpenAPI schemas returned by those CRDs; this script never calls apply, create,
patch, delete, diff, or a server-side dry-run endpoint.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml


EXPECTED_CLUSTER = "ok-kagent"
EXPECTED_NAMESPACE = "openkubes-assistant"
CRDS = {
    "Agent": "agents.kagent.dev",
    "ModelConfig": "modelconfigs.kagent.dev",
    "RemoteMCPServer": "remotemcpservers.kagent.dev",
}
ALLOWED_KINDS = {*CRDS, "Service"}


class PreflightError(RuntimeError):
    pass


def run_kubectl(kubeconfig: Path, context: str, *args: str) -> str:
    safe = (
        args == ("config", "view", "--minify", "-o", "json")
        or args == ("version", "-o", "json")
        or (
            len(args) == 5
            and args[:2] == ("get", "crd")
            and args[2] in CRDS.values()
            and args[3:] == ("-o", "json")
        )
    )
    if not safe:
        raise PreflightError(f"refusing non-allowlisted kubectl arguments: {args!r}")
    command = [
        "kubectl",
        "--kubeconfig",
        str(kubeconfig),
        "--context",
        context,
        *args,
    ]
    try:
        completed = subprocess.run(
            command, check=True, capture_output=True, text=True, timeout=30
        )
    except FileNotFoundError as exc:
        raise PreflightError("kubectl was not found in PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise PreflightError(f"kubectl timed out: {' '.join(command)}") from exc
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() or exc.stdout.strip() or f"exit {exc.returncode}"
        raise PreflightError(f"kubectl failed: {detail}") from exc
    return completed.stdout


def assert_lab_identity(config: dict[str, Any], requested_context: str) -> str:
    contexts = config.get("contexts", [])
    if len(contexts) != 1:
        raise PreflightError("minified kubeconfig did not resolve exactly one context")
    selected = contexts[0]
    context_name = selected.get("name")
    cluster_name = selected.get("context", {}).get("cluster")
    if context_name != requested_context:
        raise PreflightError(
            f"kubectl resolved context {context_name!r}, not {requested_context!r}"
        )
    forbidden = f"{context_name} {cluster_name}".lower()
    if "ok-ai" in forbidden or "prod" in forbidden or "production" in forbidden:
        raise PreflightError("refusing forbidden ok-ai/production target")
    if cluster_name != EXPECTED_CLUSTER:
        raise PreflightError(
            f"refusing cluster {cluster_name!r}; only {EXPECTED_CLUSTER!r} is allowed"
        )
    return str(context_name)


def crd_schema(crd: dict[str, Any], api_version: str, kind: str) -> dict[str, Any]:
    expected_name = CRDS[kind]
    if crd.get("metadata", {}).get("name") != expected_name:
        raise PreflightError(f"unexpected CRD returned for {kind}")
    version_name = api_version.split("/", 1)[-1]
    for version in crd.get("spec", {}).get("versions", []):
        if version.get("name") == version_name and version.get("served") is True:
            schema = version.get("schema", {}).get("openAPIV3Schema")
            if not isinstance(schema, dict):
                break
            return schema
    raise PreflightError(f"{expected_name} does not serve {version_name} with a schema")


def _matches(value: Any, schema: dict[str, Any], path: str) -> bool:
    try:
        validate_openapi(value, schema, path)
    except PreflightError:
        return False
    return True


def validate_openapi(value: Any, schema: dict[str, Any], path: str = "$") -> None:
    """Validate the structural OpenAPI subset emitted by Kubernetes CRDs."""
    if value is None and schema.get("nullable"):
        return
    if schema.get("x-kubernetes-int-or-string") and (
        isinstance(value, str) or isinstance(value, int) and not isinstance(value, bool)
    ):
        return

    for subschema in schema.get("allOf", []):
        validate_openapi(value, subschema, path)
    for keyword in ("oneOf", "anyOf"):
        choices = schema.get(keyword)
        if choices:
            matches = sum(_matches(value, choice, path) for choice in choices)
            required_matches = 1 if keyword == "oneOf" else 0
            if (keyword == "oneOf" and matches != required_matches) or (
                keyword == "anyOf" and matches == 0
            ):
                raise PreflightError(f"{path}: does not satisfy {keyword}")

    expected_type = schema.get("type")
    type_ok = {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
    }.get(expected_type, True)
    if not type_ok:
        raise PreflightError(f"{path}: expected {expected_type}, got {type(value).__name__}")
    if "enum" in schema and value not in schema["enum"]:
        raise PreflightError(f"{path}: {value!r} is not in {schema['enum']!r}")

    if expected_type == "object":
        required = schema.get("required", [])
        for name in required:
            if name not in value:
                raise PreflightError(f"{path}: missing required field {name!r}")
        properties = schema.get("properties", {})
        additional = schema.get("additionalProperties", False)
        preserve = schema.get("x-kubernetes-preserve-unknown-fields", False)
        for name, item in value.items():
            child_path = f"{path}.{name}"
            if name in properties:
                validate_openapi(item, properties[name], child_path)
            elif isinstance(additional, dict):
                validate_openapi(item, additional, child_path)
            elif not (additional is True or preserve):
                raise PreflightError(f"{child_path}: field is not present in installed CRD")
    elif expected_type == "array":
        if "minItems" in schema and len(value) < schema["minItems"]:
            raise PreflightError(f"{path}: too few items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            raise PreflightError(f"{path}: too many items")
        item_schema = schema.get("items", {})
        for index, item in enumerate(value):
            validate_openapi(item, item_schema, f"{path}[{index}]")
    elif expected_type == "string":
        if "minLength" in schema and len(value) < schema["minLength"]:
            raise PreflightError(f"{path}: string is too short")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            raise PreflightError(f"{path}: string is too long")
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            raise PreflightError(f"{path}: does not match required pattern")


def load_manifests(paths: list[Path]) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    for path in paths:
        try:
            loaded = yaml.safe_load_all(path.read_text(encoding="utf-8"))
            for index, document in enumerate(loaded, 1):
                if document is None:
                    continue
                if not isinstance(document, dict):
                    raise PreflightError(f"{path}:{index}: expected a YAML object")
                documents.append(document)
        except (OSError, yaml.YAMLError) as exc:
            raise PreflightError(f"cannot read {path}: {exc}") from exc
    return documents


def validate_docs_only_policy(documents: list[dict[str, Any]]) -> None:
    by_kind: dict[str, list[dict[str, Any]]] = {}
    for document in documents:
        kind = document.get("kind")
        if kind not in ALLOWED_KINDS:
            raise PreflightError(f"policy forbids manifest kind {kind!r}")
        namespace = document.get("metadata", {}).get("namespace")
        if namespace != EXPECTED_NAMESPACE:
            raise PreflightError(f"{kind}: namespace must be {EXPECTED_NAMESPACE!r}")
        by_kind.setdefault(str(kind), []).append(document)

    if {kind: len(by_kind.get(kind, [])) for kind in ALLOWED_KINDS} != {
        "Agent": 1,
        "ModelConfig": 1,
        "RemoteMCPServer": 1,
        "Service": 1,
    }:
        raise PreflightError("expected exactly one Agent, ModelConfig, RemoteMCPServer, and Service")

    agent = by_kind["Agent"][0]
    tools = agent.get("spec", {}).get("declarative", {}).get("tools")
    expected_tool = {
        "type": "McpServer",
        "mcpServer": {
            "apiGroup": "kagent.dev",
            "kind": "RemoteMCPServer",
            "name": "openkubes-docs-search",
            "toolNames": ["docs_search"],
        },
    }
    if tools != [expected_tool]:
        raise PreflightError("Agent must expose only docs_search from openkubes-docs-search")

    model = by_kind["ModelConfig"][0]
    if model.get("spec", {}).get("provider") != "Ollama":
        raise PreflightError("ModelConfig must use Ollama")

    remote = by_kind["RemoteMCPServer"][0]
    remote_spec = remote.get("spec", {})
    if remote_spec.get("protocol") != "STREAMABLE_HTTP":
        raise PreflightError("RemoteMCPServer must use STREAMABLE_HTTP")
    if remote_spec.get("url") != (
        "http://openkubes-docs-search.openkubes-assistant.svc.cluster.local:8000/mcp"
    ):
        raise PreflightError("RemoteMCPServer URL must be the internal docs-search Service")
    if remote_spec.get("allowedNamespaces", {}).get("from", "Same") != "Same":
        raise PreflightError("RemoteMCPServer must not allow cross-namespace consumers")
    if "headersFrom" in remote_spec:
        raise PreflightError("RemoteMCPServer must not reference credentials")

    service = by_kind["Service"][0]
    service_spec = service.get("spec", {})
    if service_spec.get("type", "ClusterIP") != "ClusterIP":
        raise PreflightError("docs-search Service must remain cluster-internal")
    for public_field in ("externalIPs", "externalName", "loadBalancerIP"):
        if public_field in service_spec:
            raise PreflightError(f"Service must not set {public_field}")


def validate_cr_manifests(
    documents: list[dict[str, Any]], crds: dict[str, dict[str, Any]]
) -> list[str]:
    results: list[str] = []
    for document in documents:
        kind = document.get("kind")
        if kind not in CRDS:
            continue
        api_version = document.get("apiVersion")
        if not isinstance(api_version, str) or not api_version.startswith("kagent.dev/"):
            raise PreflightError(f"{kind}: expected a kagent.dev API version")
        schema = crd_schema(crds[kind], api_version, kind)
        spec_schema = schema.get("properties", {}).get("spec")
        if not isinstance(spec_schema, dict):
            raise PreflightError(f"{kind}: installed CRD has no spec schema")
        validate_openapi(document.get("spec"), spec_schema, f"{kind}.spec")
        results.append(f"{kind} {api_version}")
    return results


def default_manifests() -> list[Path]:
    directory = Path(__file__).resolve().parent
    return [directory / "openkubes-docs-agent.yaml", directory / "docs-search-mcp.yaml"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kubeconfig", type=Path, required=True)
    parser.add_argument("--context", required=True)
    parser.add_argument("--manifest", action="append", type=Path, dest="manifests")
    args = parser.parse_args(argv)

    try:
        if not args.kubeconfig.is_file():
            raise PreflightError(f"kubeconfig is not a readable file: {args.kubeconfig}")
        config = json.loads(
            run_kubectl(
                args.kubeconfig, args.context, "config", "view", "--minify", "-o", "json"
            )
        )
        context = assert_lab_identity(config, args.context)
        print(f"PASS target guard: context={context} cluster={EXPECTED_CLUSTER}")

        version = json.loads(run_kubectl(args.kubeconfig, args.context, "version", "-o", "json"))
        server_version = version.get("serverVersion", {}).get("gitVersion", "unknown")
        print(f"PASS read-only API discovery: Kubernetes {server_version}")

        crds: dict[str, dict[str, Any]] = {}
        for kind, name in CRDS.items():
            crds[kind] = json.loads(
                run_kubectl(args.kubeconfig, args.context, "get", "crd", name, "-o", "json")
            )
        documents = load_manifests(args.manifests or default_manifests())
        validated = validate_cr_manifests(documents, crds)
        for item in validated:
            print(f"PASS installed CRD schema: {item}")
        validate_docs_only_policy(documents)
        print("PASS docs-only policy: exactly docs_search; no Kubernetes/RBAC/public service")
        print("PASS preflight complete: no cluster resources were created or changed")
        return 0
    except (PreflightError, json.JSONDecodeError) as exc:
        print(f"FAIL preflight: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
