from __future__ import annotations

import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml


ADAPTER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ADAPTER_DIR))
os.environ.setdefault("DIAGNOSTICS_BEARER_TOKEN", "test-consumer-token")

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
            headers = {"X-Invocation-Id": "inv-test-1"}

            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict[str, str]:
                return {"invocation_id": "inv-test-1"}

        class Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, traceback):
                return None

            async def post(self, url, json, headers):
                calls.append((url, json, headers))
                return Response()

        with (
            patch.object(server.httpx, "AsyncClient", return_value=Client()),
            patch.object(server.uuid, "uuid4") as uuid4,
        ):
            uuid4.return_value.hex = "request123"
            result = asyncio.run(
                server._call("/v1/get_platform_health", {"clusters": ["ok-ai"]})
            )

        self.assertEqual({"invocation_id": "inv-test-1"}, result)
        self.assertEqual(
            [
                (
                    f"{server.FACADE_URL}/v1/get_platform_health",
                    {"clusters": ["ok-ai"]},
                    {
                        "Authorization": "Bearer test-consumer-token",
                        "X-Request-Id": "mcp-request123",
                    },
                )
            ],
            calls,
        )

    def test_http_forwarder_rejects_missing_invocation_header(self) -> None:
        class Response:
            headers = {}

            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict[str, str]:
                return {"invocation_id": "inv-test-1"}

        class Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, traceback):
                return None

            async def post(self, url, json, headers):
                return Response()

        with patch.object(server.httpx, "AsyncClient", return_value=Client()):
            with self.assertRaisesRegex(RuntimeError, "missing required"):
                asyncio.run(server._call("/v1/get_platform_health", {}))

    def test_deployment_uses_consumer_secret_without_kubernetes_token(self) -> None:
        documents = list(
            yaml.safe_load_all((ADAPTER_DIR / "deploy.yaml").read_text())
        )
        deployment = next(item for item in documents if item["kind"] == "Deployment")
        pod_spec = deployment["spec"]["template"]["spec"]
        self.assertIs(pod_spec["automountServiceAccountToken"], False)
        container = pod_spec["containers"][0]
        env = {item["name"]: item for item in container["env"]}
        token = env["DIAGNOSTICS_BEARER_TOKEN"]
        self.assertNotIn("value", token)
        self.assertEqual(
            {
                "name": "platform-diagnostics-mcp-consumer",
                "key": "token",
            },
            token["valueFrom"]["secretKeyRef"],
        )


if __name__ == "__main__":
    unittest.main()
