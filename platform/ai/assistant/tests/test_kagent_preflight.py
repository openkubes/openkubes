import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "kagent"))
from preflight import (
    PreflightError,
    assert_lab_identity,
    load_manifests,
    run_kubectl,
    validate_docs_only_policy,
    validate_openapi,
)


KAGENT_DIR = Path(__file__).resolve().parents[1] / "kagent"


class KagentPreflightTests(unittest.TestCase):
    def test_accepts_only_exact_lab_cluster(self):
        config = {
            "contexts": [
                {
                    "name": "ok-kagent-admin@ok-kagent",
                    "context": {"cluster": "ok-kagent"},
                }
            ]
        }
        self.assertEqual(
            assert_lab_identity(config, "ok-kagent-admin@ok-kagent"),
            "ok-kagent-admin@ok-kagent",
        )

    def test_rejects_ok_ai_even_if_requested(self):
        config = {
            "contexts": [
                {"name": "admin@ok-ai", "context": {"cluster": "ok-ai"}}
            ]
        }
        with self.assertRaises(PreflightError):
            assert_lab_identity(config, "admin@ok-ai")

    def test_kubectl_runner_rejects_mutating_verbs_before_execution(self):
        with self.assertRaises(PreflightError):
            run_kubectl(Path("unused"), "ok-kagent", "apply", "-f", "manifest.yaml")

    def test_openapi_rejects_unknown_or_wrong_type(self):
        schema = {
            "type": "object",
            "required": ["name"],
            "properties": {"name": {"type": "string"}},
        }
        validate_openapi({"name": "docs"}, schema)
        with self.assertRaises(PreflightError):
            validate_openapi({"name": "docs", "unknown": True}, schema)
        with self.assertRaises(PreflightError):
            validate_openapi({"name": 7}, schema)

    def test_checked_in_manifests_preserve_docs_only_boundary(self):
        documents = load_manifests(
            [KAGENT_DIR / "openkubes-docs-agent.yaml", KAGENT_DIR / "docs-search-mcp.yaml"]
        )
        validate_docs_only_policy(documents)

    def test_policy_rejects_kubernetes_tool(self):
        documents = load_manifests(
            [KAGENT_DIR / "openkubes-docs-agent.yaml", KAGENT_DIR / "docs-search-mcp.yaml"]
        )
        poisoned = copy.deepcopy(documents)
        agent = next(document for document in poisoned if document["kind"] == "Agent")
        agent["spec"]["declarative"]["tools"][0]["mcpServer"]["toolNames"].append(
            "k8s_get_resources"
        )
        with self.assertRaises(PreflightError):
            validate_docs_only_policy(poisoned)


if __name__ == "__main__":
    unittest.main()
