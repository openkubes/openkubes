"""Offline source-block inventory checks."""
import hashlib
import unittest

from public_beta.source_command_inventory import inventory_shell_blocks

REPO = "openkubes/ok-local"
PATH = "docs/tutorial-basic.md"
REV = "a" * 40
SID = hashlib.sha256(f"{REPO}:{REV}:{PATH}:0".encode()).hexdigest()[:16]
URL = f"https://github.com/{REPO}/blob/{REV}/{PATH}"


def index(text):
    return {"schema_version": 1, "corpus": [{
        "source_id": SID, "repo": REPO, "path": PATH, "revision": REV,
        "chunk_number": 0, "section": "Basic", "url": URL, "text": text,
        "sha256": hashlib.sha256(text.encode()).hexdigest(),
    }]}


class SourceInventoryTests(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(inventory_shell_blocks(index("text")), [])

    def test_complete_and_classified(self):
        entries = inventory_shell_blocks(index("Intro\n```bash\nkubectl get pods\n```\n"))
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["review"], "manual_review")
        self.assertEqual(entries[0]["url"], URL)
        self.assertNotIn("body", entries[0])

    def test_quarantine_install(self):
        entries = inventory_shell_blocks(index("```sh\nbrew install multipass\n```\n"))
        self.assertEqual(entries[0]["review"], "quarantine")

    def test_fail_invalid_hash(self):
        obj = index("```sh\ngit status\n```\n")
        obj["corpus"][0]["sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            inventory_shell_blocks(obj)

    def test_incomplete(self):
        with self.assertRaises(ValueError):
            inventory_shell_blocks(index("```bash\ngit status\n"))


if __name__ == "__main__":
    unittest.main()
