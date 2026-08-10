from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ADAPTER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ADAPTER_DIR))

import server  # noqa: E402


class FastMCPRegistrationTests(unittest.TestCase):
    def test_runtime_registers_exact_openapi_tool_surface(self) -> None:
        tools = asyncio.run(server.mcp.list_tools())
        self.assertEqual(
            [
                "get_platform_health",
                "investigate_workload",
                "collect_diagnostic_evidence",
            ],
            [tool.name for tool in tools],
        )

    def test_collect_evidence_exposes_openapi_evidence_types(self) -> None:
        tools = asyncio.run(server.mcp.list_tools())
        collect = next(
            tool for tool in tools if tool.name == "collect_diagnostic_evidence"
        )
        self.assertIn("evidence_types", collect.inputSchema["properties"])

    def test_http_forwarder_uses_generated_contract_path(self) -> None:
        calls = []

        class Response:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict[str, bool]:
                return {"ok": True}

        class Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, traceback):
                return None

            async def post(self, url, json):
                calls.append((url, json))
                return Response()

        with patch.object(server.httpx, "AsyncClient", return_value=Client()):
            result = asyncio.run(
                server._call("/v1/get_platform_health", {"clusters": ["ok-ai"]})
            )

        self.assertEqual({"ok": True}, result)
        self.assertEqual(
            [
                (
                    f"{server.FACADE_URL}/v1/get_platform_health",
                    {"clusters": ["ok-ai"]},
                )
            ],
            calls,
        )


if __name__ == "__main__":
    unittest.main()
