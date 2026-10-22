"""Offline, fail-closed review record tests."""
import hashlib
import unittest

from public_beta.source_bound_command_reference import build_command_references
from public_beta.command_display_review import new_review_record, validate_review_record

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


class ReviewRecordTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = index("```bash\ngit status\n```\n\n```sh\nbrew install multipass\n```\n")
        self.references = build_command_references(self.snapshot)
        self.record = new_review_record(
            self.snapshot, self.references[0], decision="approve_for_review",
            reviewer="security.reviewer", ticket="OK-202",
            rationale="Reviewed source-bound documentation reference manually.",
            reviewed_at="2026-10-22T15:00:00Z")

    def test_valid_review_is_never_display_permission(self):
        self.assertEqual(self.record["decision"], "approve_for_review")
        self.assertIs(self.record["display_allowed"], False)
        self.assertEqual(validate_review_record(self.snapshot, self.references[0], self.record), self.record)
        self.assertNotIn("body", self.record)

    def test_reject_wrong_block_even_same_chunk(self):
        with self.assertRaises(ValueError):
            validate_review_record(self.snapshot, self.references[1], self.record)

    def test_reject_changed_snapshot(self):
        other = index("```bash\ngit status --short\n```\n\n```sh\nbrew install multipass\n```\n")
        with self.assertRaises(ValueError):
            validate_review_record(other, self.references[0], self.record)

    def test_reject_display_authorization(self):
        with self.assertRaises(ValueError):
            validate_review_record(self.snapshot, self.references[0], dict(self.record, display_allowed=True))

    def test_reject_forged_digest(self):
        with self.assertRaises(ValueError):
            validate_review_record(self.snapshot, self.references[0], dict(self.record, reference_sha256="0"*64))

    def test_reject_extra_field(self):
        with self.assertRaises(ValueError):
            validate_review_record(self.snapshot, self.references[0], dict(self.record, command="git status"))

    def test_reject_invalid_decision(self):
        with self.assertRaises(ValueError):
            new_review_record(self.snapshot, self.references[0], decision="approved",
                reviewer="security.reviewer", ticket="OK-202",
                rationale="A sufficiently long reviewer rationale.",
                reviewed_at="2026-10-22T15:00:00Z")

    def test_reject_weak_rationale(self):
        with self.assertRaises(ValueError):
            validate_review_record(self.snapshot, self.references[0], dict(self.record, rationale="OK"))

    def test_reject_invalid_timestamp(self):
        for value in ("2026-02-30T15:00:00Z", "yesterday", "2026-10-22T15:00:00+02:00"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_review_record(self.snapshot, self.references[0], dict(self.record, reviewed_at=value))

    def test_reject_invalid_reviewer_and_ticket(self):
        for field, value in (("reviewer", ""), ("ticket", "SEC-3")):
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_review_record(self.snapshot, self.references[0], dict(self.record, **{field:value}))

    def test_reject_modified_index_digest(self):
        broken = index("```bash\ngit status\n```\n")
        broken["corpus"][0]["sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            validate_review_record(broken, self.references[0], self.record)


if __name__ == "__main__":
    unittest.main()
