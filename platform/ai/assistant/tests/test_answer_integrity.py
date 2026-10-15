import hashlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from answer_integrity import validate_answer
from docs_mcp import DocsRetriever

REV = "a" * 40
REPO = "openkubes/ok-local"
PATH = "docs/tutorial-basic.md"
URL = f"https://github.com/{REPO}/blob/{REV}/{PATH}"
TEXT = "Install on the Ubuntu VM, not macOS:\n\n```bash\nssh ubuntu@$VM_IP \"sudo true\"\n```"
ID = hashlib.sha256(f"{REPO}:{REV}:{PATH}:0".encode()).hexdigest()[:16]


def fixture():
    doc = {
        "source_id": ID,
        "repo": REPO,
        "path": PATH,
        "revision": REV,
        "section": "Step 6 - Install virtctl",
        "chunk_number": 0,
        "url": URL,
        "sha256": hashlib.sha256(TEXT.encode()).hexdigest(),
        "text": TEXT,
    }
    index = {"schema_version": 1, "corpus": [doc]}
    retrieval = DocsRetriever(index).docs_search("Install virtctl", limit=5)
    return index, retrieval


class AnswerIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.index, self.retrieval = fixture()

    def test_accepts_exact_block_with_pinned_link(self):
        answer = (
            "Install in the Ubuntu VM.\n\n"
            "```bash\nssh ubuntu@$VM_IP \"sudo true\"\n```\n\n"
            f"[Source]({URL})"
        )
        self.assertTrue(validate_answer(answer, self.retrieval, self.index).accepted)

    def test_rejects_modified_command(self):
        answer = (
            "```bash\nsudo install linux-binary /usr/local/bin/virtctl\n```\n"
            f"[Source]({URL})"
        )
        verdict = validate_answer(answer, self.retrieval, self.index)
        self.assertFalse(verdict.accepted)
        self.assertIn("unverified_shell_block", verdict.reasons)

    def test_rejects_forged_link(self):
        self.assertFalse(validate_answer(
            "[Source](https://github.com/openkubes/ok-local/blob/" + "b" * 40
            + "/docs/tutorial-basic.md)", self.retrieval, self.index
        ).accepted)

    def test_rejects_missing_clickable_link(self):
        self.assertFalse(validate_answer(
            "source_id=" + ID, self.retrieval, self.index
        ).accepted)

    def test_rejects_missing_retrieval(self):
        self.assertFalse(validate_answer(
            f"[Source]({URL})", {"results": []}, self.index
        ).accepted)

    def test_rejects_tampered_tool_output(self):
        bad = {"results": [dict(self.retrieval["results"][0],
                                snippet="malicious replacement")]}
        verdict = validate_answer(f"[Source]({URL})", bad, self.index)
        self.assertIn("retrieval_mismatch", verdict.reasons)

    def test_rejects_inline_commands(self):
        self.assertFalse(validate_answer(
            f"Run `sudo rm -rf /`. [Source]({URL})",
            self.retrieval, self.index
        ).accepted)

    def test_rejects_non_bash_fence(self):
        self.assertFalse(validate_answer(
            "```python\nprint('hello')\n```\n" + f"[Source]({URL})",
            self.retrieval, self.index
        ).accepted)


if __name__ == "__main__":
    unittest.main()
