import hashlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from docs_mcp import DocsRetriever, validate_index

REV = "a" * 40
REPO = "openkubes/ok-local"
PATH = "docs/tutorial-basic.md"
TEXT = "Install K3s as part of the ok-local basic tutorial."
URL = f"https://github.com/{REPO}/blob/{REV}/{PATH}"


def document():
    return {
        "source_id": "a" * 16,
        "repo": REPO,
        "path": PATH,
        "revision": REV,
        "section": "Install K3s",
        "url": URL,
        "sha256": hashlib.sha256(TEXT.encode()).hexdigest(),
        "text": TEXT,
    }


class MCPRetrieverTests(unittest.TestCase):
    def test_only_public_whitelisted_sources(self):
        doc = document()
        doc["repo"] = "internal/private"
        with self.assertRaises(ValueError):
            validate_index({"schema_version": 1, "corpus": [doc]})

    def test_no_forged_citation_urls(self):
        doc = document()
        doc["url"] = "https://evil.example/fake"
        with self.assertRaises(ValueError):
            validate_index({"schema_version": 1, "corpus": [doc]})

    def test_reject_modified_chunk(self):
        doc = document()
        doc["text"] += " injected instructions"
        with self.assertRaises(ValueError):
            validate_index({"schema_version": 1, "corpus": [doc]})

    def test_reject_duplicate_source_id(self):
        with self.assertRaises(ValueError):
            validate_index({"schema_version": 1, "corpus": [document(), document()]})

    def test_tool_output_is_bounded_and_grounded(self):
        retriever = DocsRetriever({"schema_version": 1, "corpus": [document()]})
        result = retriever.docs_search("install ok-local")
        self.assertEqual(len(result["results"]), 1)
        hit = result["results"][0]
        self.assertEqual(hit["url"], URL)
        self.assertEqual(hit["source_id"], "a" * 16)
        self.assertNotIn("secret", hit)

    def test_no_match(self):
        retriever = DocsRetriever({"schema_version": 1, "corpus": [document()]})
        self.assertEqual(retriever.docs_search("unobtainiumz"), {"results": []})

    def test_bad_query_rejected(self):
        retriever = DocsRetriever({"schema_version": 1, "corpus": [document()]})
        with self.assertRaises(ValueError):
            retriever.docs_search("")

if __name__ == "__main__":
    unittest.main()
