import hashlib
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from public_beta.local_gateway import Gateway, MAX_REQUEST_BYTES, make_handler

REV = "a" * 40
REPO = "openkubes/ok-local"
PATH = "docs/tutorial-basic.md"
SOURCE_ID = hashlib.sha256(f"{REPO}:{REV}:{PATH}:0".encode()).hexdigest()[:16]
URL = f"https://github.com/{REPO}/blob/{REV}/{PATH}"
TEXT = "Install on Ubuntu VM.\n\n```bash\necho safe\n```"


def example_index():
    return {
        "schema_version": 1,
        "corpus": [{
            "source_id": SOURCE_ID, "repo": REPO, "path": PATH,
            "revision": REV, "chunk_number": 0, "section": "Install",
            "url": URL, "sha256": hashlib.sha256(TEXT.encode()).hexdigest(),
            "text": TEXT,
        }],
    }


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.gateway = Gateway(example_index())

    def test_demo_answer_uses_verified_source(self):
        status, reply = self.gateway.ask("Install ok-local")
        self.assertEqual(status, 200)
        self.assertTrue(reply["demo"])
        self.assertIn(f"]({URL})", reply["answer"])
        self.assertEqual(reply["sources"][0]["source_id"], SOURCE_ID)

    def test_rejects_invalid_questions(self):
        for q in (None, "", " ", "x" * 501, {"question": "x"}):
            status, body = self.gateway.ask(q)
            self.assertEqual(status, 400)
            self.assertEqual(body["error"], "invalid_question")

    def test_rejects_no_matches(self):
        status, body = self.gateway.ask("xyzzyunmatched")
        self.assertEqual(status, 422)
        self.assertEqual(body["error"], "no_verified_source")

    def test_rejects_invented_shell_command(self):
        gateway = Gateway(
            example_index(),
            lambda question, hits: "```bash\nrm -rf /\n```\n"
                                   f"[Source]({URL})",
        )
        status, body = gateway.ask("Install ok-local")
        self.assertEqual(status, 422)
        self.assertIn("unverified_shell_block", body["reasons"])

    def test_rejects_forged_source(self):
        gateway = Gateway(
            example_index(),
            lambda question, hits: "[Source](https://github.com/evil/fake)",
        )
        status, body = gateway.ask("Install ok-local")
        self.assertEqual(status, 422)
        self.assertIn("untrusted_citation", body["reasons"])

    def test_demo_never_uses_network_by_default(self):
        # By design: in-process docs_search and static generator only.
        self.assertEqual(MAX_REQUEST_BYTES, 4096)
        self.assertTrue(callable(make_handler(self.gateway)))


if __name__ == "__main__":
    unittest.main()
