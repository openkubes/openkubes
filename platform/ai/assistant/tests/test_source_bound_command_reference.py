"""Source-bound metadata contract regression tests (offline only)."""
import hashlib
import unittest

from public_beta.source_bound_command_reference import (
    build_command_references, validate_command_reference,
)

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


class ReferenceContractTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = index("~~~bash\ngit status\n~~~\n\n```sh\nbrew install multipass\n```\n")
        self.refs = build_command_references(self.snapshot)

    def test_exact_provenance_and_no_command_body(self):
        self.assertEqual(len(self.refs), 2)
        self.assertEqual([r["block_ordinal"] for r in self.refs], [0, 1])
        self.assertEqual([r["review"] for r in self.refs], ["manual_review", "quarantine"])
        self.assertTrue(all(r["display_allowed"] is False for r in self.refs))
        self.assertTrue(all("body" not in r and "command" not in r for r in self.refs))
        for ref in self.refs:
            self.assertEqual(validate_command_reference(self.snapshot, ref), ref)

    def test_reject_tampered_revision(self):
        forged = dict(self.refs[0], commit_sha="b" * 40)
        with self.assertRaises(ValueError):
            validate_command_reference(self.snapshot, forged)

    def test_reject_tampered_block_hash_and_ordinal(self):
        for forged in (dict(self.refs[0], block_sha256="0" * 64),
                       dict(self.refs[0], block_ordinal=3)):
            with self.assertRaises(ValueError):
                validate_command_reference(self.snapshot, forged)

    def test_reject_display_authorization(self):
        with self.assertRaises(ValueError):
            validate_command_reference(self.snapshot, dict(self.refs[0], display_allowed=True))

    def test_reject_unrecognized_field(self):
        with self.assertRaises(ValueError):
            validate_command_reference(self.snapshot, dict(self.refs[0], shell="danger"))

    def test_reject_modified_index(self):
        modified = index("~~~bash\ngit status --short\n~~~\n\n```sh\nbrew install multipass\n```\n")
        with self.assertRaises(ValueError):
            validate_command_reference(modified, self.refs[0])

    def test_reject_invalid_index_integrity(self):
        altered = index("~~~bash\ngit status\n~~~\n")
        altered["corpus"][0]["sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            build_command_references(altered)

    def test_reject_non_integer_ordinal(self):
        for value in (True, "0", -1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_command_reference(self.snapshot, dict(self.refs[0], block_ordinal=value))


if __name__ == "__main__":
    unittest.main()
