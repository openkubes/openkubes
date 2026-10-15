import hashlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from docs_mcp import DocsRetriever
from public_beta.command_evidence import command_evidence_report

F = chr(96) * 3
REV = "b" * 40
REPO = "openkubes/ok-local"
PATH = "docs/tutorial-basic.md"


def doc(n, text):
    sid = hashlib.sha256(f"{REPO}:{REV}:{PATH}:{n}".encode()).hexdigest()[:16]
    return {
        "source_id": sid, "repo": REPO, "path": PATH,
        "revision": REV, "chunk_number": n, "section": "Setup",
        "url": f"https://github.com/{REPO}/blob/{REV}/{PATH}",
        "sha256": hashlib.sha256(text.encode()).hexdigest(), "text": text,
    }


FIRST = "intro\n" + F + "bash\necho start\n" + F
LATER = "later\n" + F + "bash\necho later\n" + F
INDEX = {"schema_version": 1, "corpus": [doc(0, FIRST), doc(1, LATER)]}


def hits():
    hit = INDEX["corpus"][0]
    return {"results": [{
        "source_id": hit["source_id"], "repo": hit["repo"],
        "path": hit["path"], "commit_sha": hit["revision"],
        "title": hit["section"], "snippet": hit["text"], "url": hit["url"],
    }]}


def answer(command):
    return F + "bash\n" + command + "\n" + F


class CommandEvidenceTests(unittest.TestCase):
    def test_exact_retrieved(self):
        result = command_evidence_report(answer("echo start"), hits(), INDEX)
        self.assertEqual(result["blocks"][0]["evidence"], "exact_retrieved")

    def test_exact_other_index_not_an_acceptance(self):
        result = command_evidence_report(answer("echo later"), hits(), INDEX)
        self.assertEqual(result["blocks"][0]["evidence"], "exact_other_index")

    def test_whitespace_only_other_index(self):
        result = command_evidence_report(answer("echo    later"), hits(), INDEX)
        self.assertEqual(result["blocks"][0]["evidence"], "whitespace_only_other_index")

    def test_whitespace_only_retrieved(self):
        result = command_evidence_report(answer("echo    start"), hits(), INDEX)
        self.assertEqual(result["blocks"][0]["evidence"], "whitespace_only_retrieved")

    def test_not_found_and_no_content_leak(self):
        value = "secret_never_log_7726"
        result = command_evidence_report(answer(value), hits(), INDEX)
        self.assertEqual(result["blocks"][0]["evidence"], "not_found_in_index")
        self.assertNotIn(value, str(result))
        self.assertNotIn(INDEX["corpus"][0]["url"], str(result))

    def test_line_evidence_counts_combined_blocks(self):
        result = command_evidence_report(
            answer("echo start\necho later\necho novel"), hits(), INDEX
        )
        counts = result["blocks"][0]["line_evidence_counts"]
        self.assertEqual(counts["exact_retrieved"], 1)
        self.assertEqual(counts["exact_other_index"], 1)
        self.assertEqual(counts["not_found_in_index"], 1)
        self.assertEqual(result["blocks"][0]["evidence"], "not_found_in_index")
        self.assertNotIn("echo novel", str(result))

    def test_line_evidence_does_not_match_substrings(self):
        result = command_evidence_report(answer("echo star"), hits(), INDEX)
        counts = result["blocks"][0]["line_evidence_counts"]
        self.assertEqual(counts["not_found_in_index"], 1)
        self.assertEqual(counts["exact_retrieved"], 0)

    def test_line_evidence_whitespace_only(self):
        result = command_evidence_report(answer("echo    start"), hits(), INDEX)
        counts = result["blocks"][0]["line_evidence_counts"]
        self.assertEqual(counts["whitespace_only_retrieved"], 1)

    def test_rejects_forged_retrieval(self):
        forged = hits()
        forged["results"][0]["snippet"] = "tampered"
        with self.assertRaises(ValueError):
            command_evidence_report(answer("echo start"), forged, INDEX)

    def test_no_shell_blocks(self):
        result = command_evidence_report("prose", hits(), INDEX)
        self.assertEqual(result["recognized_shell_blocks"], 0)
        self.assertEqual(result["blocks"], [])


if __name__ == "__main__":
    unittest.main()
