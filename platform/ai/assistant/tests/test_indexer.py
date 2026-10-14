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

    def test_install_intent_prefers_tutorial_over_long_architecture(self):
        # The original scorer ranked generic architecture prose first.
        index = {"corpus": [
            {"source_id": "arch", "repo": "openkubes/openkubes",
             "path": "docs/agentic-operations-reference-architecture.md",
             "revision": SHA1, "section": "How should we measure success?",
             "url": "https://github.com/openkubes/openkubes/blob/" + SHA1 + "/docs/agentic-operations-reference-architecture.md",
             "text": "How do I install platform operations? How do I measure success?"},
            {"source_id": "guide", "repo": "openkubes/ok-local",
             "path": "docs/tutorial-basic.md", "revision": SHA2,
             "section": "Step 2 — Install K3s",
             "url": "https://github.com/openkubes/ok-local/blob/" + SHA2 + "/docs/tutorial-basic.md",
             "text": "Install K3s inside the VM before installing KubeVirt."},
        ]}
        hits = indexer.search(index, "How do I install ok-local?")
        self.assertEqual(hits[0]["source_id"], "guide")

    def test_document_path_boosts_specific_topic(self):
        hits = indexer.search(self.index, "ok-local install")
        self.assertEqual(hits[0]["repo"], "openkubes/ok-local")

    def test_broad_install_starts_at_beginning_of_tutorial(self):
        docs = []
        for ident, section in [
            ("entry", "Overview"), ("step1", "Step 1 — Prepare VM"),
            ("step2", "Step 2 — Install K3s"),
            ("step6", "Step 6 — Install virtctl"),
        ]:
            docs.append({
                "source_id": ident,
                "repo": "openkubes/ok-local",
                "path": "docs/tutorial-basic.md",
                "revision": SHA2,
                "section": section,
                "url": "https://github.com/openkubes/ok-local/blob/" + SHA2
                       + "/docs/tutorial-basic.md",
                "text": "Install ok-local " + section
                        + (" install install install" if ident == "step6" else ""),
            })
        hits = indexer.search(
            {"corpus": docs}, "How do I install ok-local?", limit=3
        )
        self.assertEqual([hit["source_id"] for hit in hits],
                         ["entry", "step1", "step2"])

    def test_specific_install_question_preserves_relevance(self):
        docs = []
        for ident, section, body in [
            ("first", "Overview", "Install ok-local"),
            ("virtctl", "Install virtctl", "Install virtctl for ok-local"),
        ]:
            docs.append({
                "source_id": ident, "repo": "openkubes/ok-local",
                "path": "docs/tutorial-basic.md", "revision": SHA2,
                "section": section,
                "url": "https://github.com/openkubes/ok-local/blob/" + SHA2
                       + "/docs/tutorial-basic.md",
                "text": body,
            })
        hits = indexer.search(
            {"corpus": docs}, "How do I install virtctl on ok-local?"
        )
        self.assertEqual(hits[0]["source_id"], "virtctl")

    def test_stopwords_only_produce_no_results(self):
        self.assertEqual(indexer.search(self.index, "how do I"), [])

    def test_fenced_shell_block_stays_intact(self):
        command = "echo a long command\n" * 100
        markdown = "# Install\nBefore\n\n```bash\n" + command + "```\n\nAfter"
        sections = indexer.split_markdown(markdown)
        containing = [text for _, text in sections if "echo a long command" in text]
        self.assertEqual(len(containing), 1)
        self.assertIn("```bash", containing[0])
        self.assertIn("echo a long command\n```", containing[0])
        self.assertEqual(containing[0].count("echo a long command"), 100)

    def test_heading_inside_code_is_not_a_section(self):
        sections = indexer.split_markdown(
            "# Install\n```sh\n# shell comment\necho hello\n```\n\nDone"
        )
        self.assertEqual({name for name, _ in sections}, {"Install"})
        self.assertIn("# shell comment", sections[0][1])

    def test_oversize_code_block_fails_closed(self):
        with self.assertRaises(ValueError):
            indexer.split_markdown("# Install\n```sh\n" + "x" * 2700 + "\n```")

    def test_unclosed_fence_fails_closed(self):
        with self.assertRaises(ValueError):
            indexer.split_markdown("# Install\n```sh\necho unfinished")

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
