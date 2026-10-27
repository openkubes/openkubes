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


class AdapterIngressTests(unittest.TestCase):
    """The adapter must not be reachable by everything in the cluster.

    Removing the consumer's RBAC and ServiceAccount token is the visible half of
    the ADR-021 boundary. The invisible half is that the adapter sits in front of
    the provider holding its credential: if any pod can reach it, the credential
    is effectively shared with the whole cluster and the consumer hardening buys
    nothing.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.documents = [
            document
            for document in yaml.safe_load_all(
                (ADAPTER_DIR / "deploy.yaml").read_text()
            )
            if isinstance(document, dict)
        ]

    def policy(self) -> dict:
        policies = [
            document
            for document in self.documents
            if document.get("kind") == "NetworkPolicy"
        ]
        self.assertEqual(
            1, len(policies), "the adapter must ship exactly one ingress policy"
        )
        return policies[0]

    def test_ingress_policy_selects_the_adapter(self) -> None:
        deployment = next(
            document for document in self.documents if document["kind"] == "Deployment"
        )
        selector = deployment["spec"]["selector"]["matchLabels"]
        policy = self.policy()
        self.assertEqual(selector, policy["spec"]["podSelector"]["matchLabels"])
        self.assertEqual(
            deployment["metadata"]["namespace"], policy["metadata"]["namespace"]
        )
        self.assertIn("Ingress", policy["spec"]["policyTypes"])

    def test_ingress_is_restricted_to_declared_consumers(self) -> None:
        rules = self.policy()["spec"]["ingress"]
        self.assertTrue(rules, "an empty ingress list would deny the consumer too")
        for rule in rules:
            sources = rule.get("from")
            self.assertTrue(
                sources,
                "a rule without 'from' admits every source, which is the state "
                "this policy exists to end",
            )
            for source in sources:
                self.assertTrue(
                    source.get("namespaceSelector", {}).get("matchLabels")
                    or source.get("podSelector", {}).get("matchLabels"),
                    f"unrestricted ingress source: {source}",
                )

    def test_ingress_port_matches_the_served_port(self) -> None:
        deployment = next(
            document for document in self.documents if document["kind"] == "Deployment"
        )
        container = deployment["spec"]["template"]["spec"]["containers"][0]
        served = container["ports"][0]["containerPort"]
        allowed = [
            port["port"]
            for rule in self.policy()["spec"]["ingress"]
            for port in rule.get("ports", [])
        ]
        self.assertEqual([served], allowed)


if __name__ == "__main__":
    unittest.main()
