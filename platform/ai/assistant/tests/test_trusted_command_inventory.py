import hashlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from docs_mcp import DocsRetriever
from public_beta.trusted_command_inventory import inventory_trusted_fences

REV = "a" * 40
REPO = "openkubes/ok-local"
PATH = "docs/tutorial-basic.md"
F = "`" * 3


def make_doc(n, passage):
    sid = hashlib.sha256(f"{REPO}:{REV}:{PATH}:{n}".encode()).hexdigest()[:16]
    return {
        "source_id": sid, "repo": REPO, "path": PATH,
        "revision": REV, "chunk_number": n, "section": "Install",
        "url": f"https://github.com/{REPO}/blob/{REV}/{PATH}",
        "sha256": hashlib.sha256(passage.encode()).hexdigest(),
        "text": passage,
    }


class TrustedCommandInventoryTests(unittest.TestCase):
    def setUp(self):
        self.docs = [
            make_doc(0, "Setup\n" + F + "bash\necho hello\n" + F + "\n"),
            make_doc(1, "Other\n" + F + "bash\necho second\n" + F + "\n"),
        ]
        self.index = {"schema_version": 1, "corpus": self.docs}
        self.retrieval = DocsRetriever(self.index).docs_search("install", limit=2)

    def test_counts_source_fences_not_model_commands(self):
        result = inventory_trusted_fences(self.retrieval, self.index)
        self.assertEqual(result["status"], "INVENTORY_ONLY")
        self.assertEqual(result["eligible_shell_fences"], 2)
        self.assertEqual(result["retrieved_sources"], 2)
        self.assertFalse(result["display_authorized"])
        self.assertFalse(result["execution_authorized"])
        self.assertNotIn("echo", str(result))

    def test_fails_closed_for_modified_snippet(self):
        changed = {"results": [dict(self.retrieval["results"][0])]}
        changed["results"][0]["snippet"] += " changed"
        with self.assertRaises(ValueError):
            inventory_trusted_fences(changed, self.index)

    def test_rejects_duplicate_hit(self):
        duplicate = {"results": [self.retrieval["results"][0]] * 2}
        with self.assertRaises(ValueError):
            inventory_trusted_fences(duplicate, self.index)

    def test_non_shell_fences_are_not_counted(self):
        doc = make_doc(0, "data\n" + F + "json\n{\"ok\":true}\n" + F + "\n")
        index = {"schema_version": 1, "corpus": [doc]}
        result = inventory_trusted_fences(DocsRetriever(index).docs_search("install"), index)
        self.assertEqual(result["eligible_shell_fences"], 0)

    def test_unclosed_fence_not_counted(self):
        doc = make_doc(0, "setup\n" + F + "bash\necho incomplete\n")
        index = {"schema_version": 1, "corpus": [doc]}
        result = inventory_trusted_fences(DocsRetriever(index).docs_search("install"), index)
        self.assertEqual(result["eligible_shell_fences"], 0)

    def test_many_fences_report_capped_overflow_without_authorizing(self):
        text = "setup\n" + (F + "bash\necho example\n" + F + "\n") * 17
        doc = make_doc(0, text)
        index = {"schema_version": 1, "corpus": [doc]}
        retrieval = DocsRetriever(index).docs_search("install", limit=1)
        result = inventory_trusted_fences(retrieval, index)
        self.assertEqual(result["status"], "OVER_LIMIT")
        self.assertTrue(result["count_is_capped"])
        self.assertEqual(result["max_blocks"], 16)
        self.assertEqual(result["eligible_shell_fences"], 17)
        self.assertFalse(result["display_authorized"])
        self.assertFalse(result["execution_authorized"])
        self.assertNotIn("echo example", str(result))

    def test_no_hits_fail_closed(self):
        with self.assertRaises(ValueError):
            inventory_trusted_fences({"results": []}, self.index)

    def test_oversize_block_not_counted(self):
        doc = make_doc(0, F + "bash\n" + "x" * 1300 + "\n" + F + "\n")
        index = {"schema_version": 1, "corpus": [doc]}
        result = inventory_trusted_fences(DocsRetriever(index).docs_search("install"), index)
        self.assertEqual(result["eligible_shell_fences"], 0)


if __name__ == "__main__":
    unittest.main()
