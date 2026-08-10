from __future__ import annotations

import asyncio
import inspect
import sys
import unittest
from pathlib import Path
from typing import Any


ADAPTER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ADAPTER_DIR))

import generate  # noqa: E402
import generated_contract  # noqa: E402


class FakeMCP:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self):
        def register(function):
            self.tools[function.__name__] = function
            return function

        return register


class GenerationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.document = generate.load_spec(generate.DEFAULT_SPEC)
        cls.operations = generate.operations(cls.document)

    def test_generated_contract_is_current(self) -> None:
        expected = generate.render(self.document, generate.DEFAULT_SPEC.name)
        actual = generate.DEFAULT_OUTPUT.read_text(encoding="utf-8")
        self.assertEqual(expected, actual)

    def test_every_openapi_operation_is_registered_once(self) -> None:
        mcp = FakeMCP()

        async def invoke(path: str, body: dict[str, Any]) -> dict[str, Any]:
            return {"path": path, "body": body}

        generated_contract.register_tools(mcp, invoke)
        self.assertEqual(
            [operation["id"] for operation in self.operations],
            list(mcp.tools),
        )

    def test_tool_parameters_are_derived_from_request_schemas(self) -> None:
        mcp = FakeMCP()

        async def invoke(path: str, body: dict[str, Any]) -> dict[str, Any]:
            return {"path": path, "body": body}

        generated_contract.register_tools(mcp, invoke)
        for operation in self.operations:
            expected = [parameter["name"] for parameter in operation["parameters"]]
            actual = list(inspect.signature(mcp.tools[operation["id"]]).parameters)
            self.assertEqual(expected, actual, operation["id"])

    def test_generated_tools_forward_contract_paths_and_complete_inputs(self) -> None:
        calls: list[tuple[str, dict[str, Any]]] = []
        mcp = FakeMCP()

        async def invoke(path: str, body: dict[str, Any]) -> dict[str, Any]:
            calls.append((path, body))
            return {"ok": True}

        generated_contract.register_tools(mcp, invoke)
        asyncio.run(mcp.tools["get_platform_health"](clusters=["ok-ai"]))
        asyncio.run(
            mcp.tools["collect_diagnostic_evidence"](
                cluster="ok-ai",
                namespace="payments",
                workload="checkout-api",
                evidence_types=["events", "logs"],
            )
        )
        self.assertEqual(
            [
                ("/v1/get_platform_health", {"clusters": ["ok-ai"]}),
                (
                    "/v1/collect_diagnostic_evidence",
                    {
                        "cluster": "ok-ai",
                        "namespace": "payments",
                        "workload": "checkout-api",
                        "time_range": "PT1H",
                        "evidence_types": ["events", "logs"],
                    },
                ),
            ],
            calls,
        )

    def test_optional_fields_are_omitted_when_not_supplied(self) -> None:
        calls: list[tuple[str, dict[str, Any]]] = []
        mcp = FakeMCP()

        async def invoke(path: str, body: dict[str, Any]) -> dict[str, Any]:
            calls.append((path, body))
            return {"ok": True}

        generated_contract.register_tools(mcp, invoke)
        asyncio.run(mcp.tools["get_platform_health"]())
        self.assertEqual([("/v1/get_platform_health", {})], calls)


class ValidationTests(unittest.TestCase):
    def test_external_schema_references_are_rejected(self) -> None:
        with self.assertRaisesRegex(generate.ContractError, "only local"):
            generate.resolve_ref({}, {"$ref": "https://example.invalid/schema.json"})

    def test_non_post_operations_are_rejected(self) -> None:
        document = {
            "openapi": "3.1.0",
            "paths": {
                "/unsafe": {
                    "delete": {
                        "operationId": "unsafe",
                        "requestBody": {
                            "content": {
                                "application/json": {"schema": {"type": "object"}}
                            }
                        },
                    }
                }
            },
        }
        with self.assertRaisesRegex(generate.ContractError, "only supports JSON POST"):
            generate.operations(document)


if __name__ == "__main__":
    unittest.main()
