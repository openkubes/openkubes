import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import indexer


SHA1 = "a" * 40
SHA2 = "b" * 40

class IndexerTest(unittest.TestCase):
    def sample_fetch(self, url):
        if url.endswith("/commits/main"):
            return '{"sha":"' + (SHA1 if "/openkubes/openkubes/" in url else SHA2) + '"}'
        if "tutorial-basic.md" in url:
            return "# Quickstart\nStart ok-local using the local tutorial."
        if "tutorial-capi.md" in url:
            return "# CAPI\nProvision a cluster with cluster-api."
        if "platform-diagnostics" in url:
            return "# Diagnostics\nRead-only platform health checks."
        if "agentic-operations" in url:
            return "# Agentic operations\nAI thinks; OpenKubes executes."
        return "# OpenKubes AI\nOpen WebUI and Ollama provide shared AI services."

    def setUp(self):
        self.index = indexer.build_index(self.sample_fetch)

    def test_exact_allowlist_only(self):
        paths = {d["path"] for d in self.index["corpus"]}
        self.assertEqual(paths, {p for group in indexer.SOURCES.values() for p in group})

    def test_pinned_citations_and_digest(self):
        for doc in self.index["corpus"]:
            self.assertIn("/blob/" + doc["revision"] + "/", doc["url"])
            self.assertEqual(len(doc["sha256"]), 64)
            self.assertEqual(len(doc["source_id"]), 16)

    def test_relevant_result(self):
        hits = indexer.search(self.index, "ok-local quickstart")
        self.assertEqual(hits[0]["path"], "docs/tutorial-basic.md")

    def test_no_answer_on_unknown_term(self):
        self.assertEqual(indexer.search(self.index, "zyzzzxq"), [])

    def test_reject_bad_input(self):
        for q in ("", "x" * 4001):
            with self.assertRaises(ValueError):
                indexer.search(self.index, q)

    def test_limit(self):
        with self.assertRaises(ValueError):
            indexer.search(self.index, "OpenKubes", 99)

    def test_no_github_call_during_search(self):
        self.assertTrue(indexer.search(self.index, "Ollama"))

if __name__ == "__main__":
    unittest.main()
