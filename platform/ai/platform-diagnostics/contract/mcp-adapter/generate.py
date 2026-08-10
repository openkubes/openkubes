#!/usr/bin/env python3
"""Generate the MCP tool surface from the diagnostics OpenAPI contract."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

import yaml


HERE = Path(__file__).resolve().parent
DEFAULT_SPEC = HERE.parent / "openapi.yaml"
DEFAULT_OUTPUT = HERE / "generated_contract.py"
HTTP_METHODS = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class ContractError(ValueError):
    """Raised when the OpenAPI document cannot be mapped safely to MCP."""


def load_spec(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        document = yaml.safe_load(handle)
    if not isinstance(document, dict) or not str(document.get("openapi", "")).startswith("3."):
        raise ContractError(f"{path} is not an OpenAPI 3 document")
    return document


def resolve_ref(document: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    ref = schema.get("$ref")
    if not ref:
        return schema
    if not isinstance(ref, str) or not ref.startswith("#/"):
        raise ContractError(f"only local OpenAPI references are supported: {ref!r}")
    resolved: Any = document
    for part in ref[2:].split("/"):
        key = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(resolved, dict) or key not in resolved:
            raise ContractError(f"unresolvable OpenAPI reference: {ref}")
        resolved = resolved[key]
    if not isinstance(resolved, dict):
        raise ContractError(f"OpenAPI reference does not resolve to an object: {ref}")
    return resolved


def python_type(document: dict[str, Any], schema: dict[str, Any]) -> str:
    resolved = resolve_ref(document, schema)
    schema_type = resolved.get("type")
    if schema_type == "string":
        return "str"
    if schema_type == "integer":
        return "int"
    if schema_type == "number":
        return "float"
    if schema_type == "boolean":
        return "bool"
    if schema_type == "array":
        items = resolved.get("items", {})
        if not isinstance(items, dict):
            raise ContractError("array items must be an OpenAPI schema object")
        return f"list[{python_type(document, items)}]"
    if schema_type == "object":
        return "dict[str, Any]"
    return "Any"


def operation_description(operation: dict[str, Any]) -> str:
    parts = [operation.get("summary", ""), operation.get("description", "")]
    return " ".join(" ".join(str(part).split()) for part in parts if part).strip()


def operations(document: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    paths = document.get("paths")
    if not isinstance(paths, dict):
        raise ContractError("OpenAPI document has no paths object")

    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method.lower() not in HTTP_METHODS or not isinstance(operation, dict):
                continue
            operation_id = operation.get("operationId")
            if not operation_id:
                continue
            if method.lower() != "post":
                raise ContractError(
                    f"MCP diagnostics adapter only supports JSON POST operations: {operation_id}"
                )
            if not isinstance(operation_id, str) or not IDENTIFIER.match(operation_id):
                raise ContractError(f"operationId is not a valid Python identifier: {operation_id!r}")
            if operation_id in seen:
                raise ContractError(f"duplicate operationId: {operation_id}")
            seen.add(operation_id)

            request_schema = (
                operation.get("requestBody", {})
                .get("content", {})
                .get("application/json", {})
                .get("schema")
            )
            if not isinstance(request_schema, dict):
                raise ContractError(f"{operation_id} has no application/json request schema")
            request_schema = resolve_ref(document, request_schema)
            if request_schema.get("type") != "object":
                raise ContractError(f"{operation_id} request schema must be an object")
            properties = request_schema.get("properties", {})
            if not isinstance(properties, dict):
                raise ContractError(f"{operation_id} properties must be an object")
            required = set(request_schema.get("required", []))

            parameters = []
            for name, schema in properties.items():
                if not isinstance(name, str) or not IDENTIFIER.match(name):
                    raise ContractError(f"request property is not a valid Python identifier: {name!r}")
                if not isinstance(schema, dict):
                    raise ContractError(f"request property {name} must be a schema object")
                resolved = resolve_ref(document, schema)
                is_required = name in required
                has_default = "default" in resolved
                default = resolved.get("default") if has_default else None
                parameters.append(
                    {
                        "name": name,
                        "type": python_type(document, schema),
                        "required": is_required,
                        "has_default": has_default,
                        "default": default,
                    }
                )

            parameters.sort(key=lambda parameter: not parameter["required"])
            result.append(
                {
                    "id": operation_id,
                    "path": path,
                    "description": operation_description(operation),
                    "parameters": parameters,
                }
            )

    if not result:
        raise ContractError("OpenAPI document contains no operations with operationId")
    return result


def render(document: dict[str, Any], source_name: str = "openapi.yaml") -> str:
    lines = [
        '"""Generated from ../openapi.yaml; do not edit by hand."""',
        "",
        "from __future__ import annotations",
        "",
        "from collections.abc import Awaitable, Callable",
        "from typing import Any",
        "",
        "",
        "Invoker = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]",
        "",
        "",
        "def register_tools(mcp: Any, invoke: Invoker) -> None:",
        f"    # Source: {source_name}",
    ]

    for operation in operations(document):
        params = []
        for parameter in operation["parameters"]:
            annotation = parameter["type"]
            if parameter["required"]:
                params.append(f'{parameter["name"]}: {annotation}')
            elif parameter["has_default"]:
                params.append(f'{parameter["name"]}: {annotation} = {parameter["default"]!r}')
            else:
                params.append(f'{parameter["name"]}: {annotation} | None = None')
        signature = ", ".join(params)
        declaration = f'    async def {operation["id"]}({signature}) -> dict[str, Any]:'
        if len(declaration) > 100:
            declaration_lines = [f'    async def {operation["id"]}(']
            declaration_lines.extend(f"        {parameter}," for parameter in params)
            declaration_lines.append("    ) -> dict[str, Any]:")
        else:
            declaration_lines = [declaration]
        description = operation["description"].replace('"""', r'\"\"\"')
        lines.append("    @mcp.tool()")
        lines.extend(declaration_lines)
        lines.extend(
            [f'        """{description}"""', "        body: dict[str, Any] = {}"]
        )
        for parameter in operation["parameters"]:
            name = parameter["name"]
            if parameter["required"] or parameter["has_default"]:
                lines.append(f'        body["{name}"] = {name}')
            else:
                lines.extend(
                    [
                        f"        if {name} is not None:",
                        f'            body["{name}"] = {name}',
                    ]
                )
        lines.extend(
            [
                f'        return await invoke("{operation["path"]}", body)',
                "",
            ]
        )

    return "\n".join(lines).rstrip() + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true", help="fail if generated output is stale")
    parser.add_argument("--stdout", action="store_true", help="print generated output")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    generated = render(load_spec(args.spec), args.spec.name)
    if args.stdout:
        sys.stdout.write(generated)
        return 0
    if args.check:
        current = args.output.read_text(encoding="utf-8") if args.output.exists() else ""
        if current != generated:
            print(f"{args.output} is stale; run {Path(__file__).name}", file=sys.stderr)
            return 1
        return 0
    args.output.write_text(generated, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
