"""Guard the docs-only agent's strict, temporary answer-format profile."""
from pathlib import Path
import unittest

AGENT = Path(__file__).resolve().parents[1] / "kagent" / "openkubes-docs-agent.yaml"


class DocsAgentFormatContractTests(unittest.TestCase):
    def setUp(self):
        manifest = AGENT.read_text(encoding="utf-8")
        self.prompt = manifest.split("    systemMessage: |", 1)[1].split("\n    tools:", 1)[0]
        self.assertIn("name: openkubes-docs-agent", manifest)
        self.assertIn("namespace: openkubes-assistant", manifest)

    def test_output_constraints_are_explicit(self):
        for required in (
            "Do NOT create Markdown tables",
            "inline backticks",
            "bare URLs",
            "source_id tokens",
            "DO NOT output any shell commands",
            "or fenced code blocks",
            "docs_search",
            "EXACT",
            "GitHub URL and title returned by docs_search",
        ):
            with self.subTest(requirement=required):
                self.assertIn(required, self.prompt)

    def test_no_live_kubernetes_tools_are_attached(self):
        manifest = AGENT.read_text(encoding="utf-8")
        attached = manifest.split("\n    tools:\n", 1)[1].split("\n---", 1)[0]
        self.assertIn("name: openkubes-docs-search", attached)
        self.assertIn("- docs_search", attached)
        self.assertNotIn("kubectl", attached)
        self.assertNotIn("kagent-tool-server", attached)


if __name__ == "__main__":
    unittest.main()
