"""Isolated JSON agent fixture tests; no network and no cluster mutations."""
import hashlib
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from public_beta.private_a2a_probe import A2A_URL, LAB_A2A_URL, query_agent
from public_beta.private_structured_a2a_probe import run_structured_probe

REV = "a" * 40
REPO = "openkubes/ok-local"
PATH = "docs/tutorial-basic.md"
SID = hashlib.sha256(f"{REPO}:{REV}:{PATH}:0".encode()).hexdigest()[:16]
TEXT = "Install OpenKubes Local by reading the installation guide."


def fixture():
    return {"schema_version": 1, "corpus": [{
        "source_id": SID, "repo": REPO, "path": PATH, "revision": REV,
        "chunk_number": 0, "section": "Install",
        "url": f"https://github.com/{REPO}/blob/{REV}/{PATH}",
        "sha256": hashlib.sha256(TEXT.encode()).hexdigest(), "text": TEXT,
    }]}


def answer(text=TEXT, ids=None):
    return json.dumps({"version": "0.1", "steps": [
        {"text": text, "source_ids": [SID] if ids is None else ids}
    ]})


class PrivateStructuredA2ATests(unittest.TestCase):
    def test_isolated_agent_resource_has_only_docs_search(self):
        file = Path(__file__).resolve().parents[1] / "kagent" / "openkubes-docs-agent-json.lab.yaml"
        data = file.read_text(encoding="utf-8")
        self.assertIn("name: openkubes-docs-agent-json", data)
        self.assertIn("namespace: openkubes-assistant", data)
        self.assertIn("modelConfig: docs-ollama", data)
        self.assertIn("runtime: go", data)
        self.assertIn("name: openkubes-docs-search", data)
        self.assertIn("- docs_search", data)
        self.assertNotIn("kind: ModelConfig", data)
        self.assertNotIn("kagent-tool-server", data)

    def test_valid_json_is_rendered_without_raw_text_leak(self):
        result = run_structured_probe(fixture(), "Install OpenKubes Local",
                                      ask=lambda _: answer())
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["accepted"])
        self.assertNotIn(TEXT, str(result))
        self.assertNotIn(SID, str(result))

    def test_invalid_json_is_rejected_without_echo(self):
        result = run_structured_probe(fixture(), "Install OpenKubes Local",
                                      ask=lambda _: "SECRET malformed JSON")
        self.assertEqual(result["status"], "REJECT")
        self.assertEqual(result["reason"], "invalid_json")
        self.assertNotIn("SECRET", str(result))

    def test_untrusted_source_id_is_rejected(self):
        result = run_structured_probe(fixture(), "Install OpenKubes Local",
                                      ask=lambda _: answer(ids=["b" * 16]))
        self.assertEqual(result["status"], "REJECT")
        self.assertEqual(result["reason"], "invalid_sources")

    def test_no_source_never_invokes_agent(self):
        def forbidden(_):
            self.fail("Agent should not be called")
        result = run_structured_probe(fixture(), "zzzzunmatched", ask=forbidden)
        self.assertEqual(result["status"], "NO_SOURCES")

    def test_only_two_loopback_paths_are_allowed(self):
        self.assertTrue(A2A_URL.startswith("http://127.0.0.1:8083/"))
        self.assertTrue(LAB_A2A_URL.startswith("http://127.0.0.1:8083/"))
        self.assertNotEqual(A2A_URL, LAB_A2A_URL)
        with self.assertRaisesRegex(ValueError, "Unapproved A2A endpoint"):
            query_agent("test", agent_url="https://untrusted.example/")

if __name__ == "__main__":
    unittest.main()
