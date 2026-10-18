import hashlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from public_beta.command_security_review import command_security_review
from public_beta.source_bound_command_manifest import source_bound_command_manifest

REV = "e" * 40
REPO = "openkubes/ok-local"
PATH = "docs/tutorial-basic.md"
F = chr(96) * 3


def fixture():
    docs = []
    for n, title in enumerate(["Overview", "Prerequisites"] +
                              [f"Step {step} — Test" for step in range(1, 9)]):
        text = ("Intro\n" + F + "bash\necho example\n" + F + "\n") if n >= 2 else "Intro"
        sid = hashlib.sha256(f"{REPO}:{REV}:{PATH}:{n}".encode()).hexdigest()[:16]
        docs.append({
            "source_id": sid, "repo": REPO, "path": PATH,
            "revision": REV, "chunk_number": n, "section": title,
            "url": f"https://github.com/{REPO}/blob/{REV}/{PATH}",
            "sha256": hashlib.sha256(text.encode()).hexdigest(),
            "text": text
        })
    index = {"schema_version": 1, "corpus": docs}
    hits = {"results": [{
        "source_id": doc["source_id"], "title": doc["section"],
        "repo": doc["repo"], "path": doc["path"],
        "commit_sha": doc["revision"], "url": doc["url"],
        "snippet": doc["text"]
    } for doc in docs[:2]]}
    return hits, index


def review_entry(hits, index, *, step=1, category="diagnostic"):
    m = source_bound_command_manifest(hits, index, step=step)
    block = m["blocks"][0]
    return {key: value for key, value in {
        "step": step, "source_id": block["source_id"],
        "fence_ordinal": block["fence_ordinal"],
        "sha256": block["sha256"], "revision": block["revision"],
        "category": category,
    }.items()}


class CommandSecurityReviewTests(unittest.TestCase):
    def setUp(self):
        self.hits, self.index = fixture()

    def test_default_pending_does_not_authorize(self):
        result = command_security_review(self.hits, self.index)
        self.assertEqual(result["status"], "REVIEW_INCOMPLETE")
        self.assertEqual(result["total_blocks"], 8)
        self.assertEqual(result["pending_blocks"], 8)
        self.assertFalse(result["display_authorized"])
        self.assertFalse(result["execution_authorized"])
        self.assertNotIn("echo example", str(result))

    def test_partial_manual_classification(self):
        result = command_security_review(
            self.hits, self.index, [review_entry(self.hits, self.index)])
        self.assertEqual(result["reviewed_blocks"], 1)
        self.assertEqual(result["pending_blocks"], 7)
        self.assertEqual(result["category_counts"]["diagnostic"], 1)

    def test_all_reviewed_still_not_authorized(self):
        entries = [review_entry(self.hits, self.index, step=n,
                                category="required") for n in range(1, 9)]
        result = command_security_review(self.hits, self.index, entries)
        self.assertEqual(result["status"], "REVIEW_RECORDED")
        self.assertFalse(result["display_authorized"])
        self.assertFalse(result["execution_authorized"])

    def test_rejects_fake_digest(self):
        entry = review_entry(self.hits, self.index)
        entry["sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            command_security_review(self.hits, self.index, [entry])

    def test_rejects_duplicate_reviews(self):
        entry = review_entry(self.hits, self.index)
        with self.assertRaises(ValueError):
            command_security_review(self.hits, self.index, [entry, entry])

    def test_rejects_unknown_category_or_extra_field(self):
        entry = review_entry(self.hits, self.index)
        entry["category"] = "auto_approved"
        with self.assertRaises(ValueError):
            command_security_review(self.hits, self.index, [entry])
        entry["category"] = "required"
        entry["approved"] = True
        with self.assertRaises(ValueError):
            command_security_review(self.hits, self.index, [entry])

    def test_rejects_changed_source(self):
        entry = review_entry(self.hits, self.index)
        altered_hits, altered_index = fixture()
        doc = altered_index["corpus"][2]
        doc["text"] = doc["text"].replace("echo example", "echo changed")
        doc["sha256"] = hashlib.sha256(doc["text"].encode()).hexdigest()
        with self.assertRaises(ValueError):
            command_security_review(altered_hits, altered_index, [entry])

    def test_rejects_invalid_step_type(self):
        entry = review_entry(self.hits, self.index)
        entry["step"] = True
        with self.assertRaises(ValueError):
            command_security_review(self.hits, self.index, [entry])


if __name__ == "__main__":
    unittest.main()
