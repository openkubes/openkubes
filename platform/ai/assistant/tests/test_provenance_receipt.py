"""Security regression fixtures for offline receipt v0.2; no cluster calls."""
import copy
import hashlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from docs_mcp import DocsRetriever
from public_beta.provenance_receipt import (
    ProvenanceRejected, issue_receipt, verify_receipt,
)

KEY = bytes(range(32))  # Test-only deterministic bytes; NEVER deploy as a key
KEY2 = bytes(reversed(range(32)))
NOW = 1800000000
REQUEST = "1" * 32
EVENT = "2" * 32
QUESTION = "How do I install OpenKubes Local?"
REPO = "openkubes/ok-local"
REV = "a" * 40
PATH = "docs/tutorial-basic.md"
TEXT = "Install OpenKubes Local by reading the installation guide."
SID = hashlib.sha256(f"{REPO}:{REV}:{PATH}:0".encode()).hexdigest()[:16]
ISSUER = "openkubes-docs-mcp"
AUDIENCE = "private-docs-gateway"
AGENT = "openkubes-docs-agent-json"
ARGUMENTS = {"query": QUESTION, "limit": 8}


def fixture(text=TEXT):
    return {"schema_version": 1, "corpus": [{
        "source_id": SID, "repo": REPO, "path": PATH, "revision": REV,
        "chunk_number": 0, "section": "Install",
        "url": f"https://github.com/{REPO}/blob/{REV}/{PATH}",
        "sha256": hashlib.sha256(text.encode()).hexdigest(), "text": text,
    }]}


def consumer():
    used = set()
    def once(issuer, request, event):
        key = (issuer, request, event)
        if key in used:
            return False
        used.add(key)
        return True
    return once


class ProvenanceReceiptTests(unittest.TestCase):
    def setUp(self):
        self.index = fixture()
        self.results = DocsRetriever(self.index).docs_search(QUESTION, limit=8)
        self.assertEqual(len(self.results["results"]), 1)
        self.issue_args = dict(
            key=KEY, key_id="test-key-1", issuer=ISSUER, audience=AUDIENCE,
            agent_id=AGENT, request_id=REQUEST, event_id=EVENT,
            question=QUESTION, arguments=ARGUMENTS,
            results=self.results, index=self.index,
            issued_at=NOW, expires_at=NOW + 60, now=NOW,
        )
        self.receipt = issue_receipt(**self.issue_args)
        self.verify_args = dict(
            keys={"test-key-1": KEY}, issuer=ISSUER, audience=AUDIENCE,
            agent_id=AGENT, request_id=REQUEST, question=QUESTION,
            arguments=ARGUMENTS, results=self.results, index=self.index,
            receipt=self.receipt, cited_source_ids=[SID],
            consume=consumer(), now=NOW,
        )

    def verify(self, **kwargs):
        args = dict(self.verify_args)
        args.update(kwargs)
        return verify_receipt(**args)

    def test_signed_matching_request_accepted_once(self):
        self.assertIsNone(self.verify())
        with self.assertRaisesRegex(ProvenanceRejected, "receipt_replayed"):
            self.verify()

    def test_other_request_or_question_rejected(self):
        for change in ({"request_id": "3"*32}, {"question": "Different question"},
                       {"agent_id": "different-agent"},
                       {"audience": "public-gateway"}, {"issuer": "rogue-mcp"}):
            with self.subTest(change=change), self.assertRaises(ProvenanceRejected):
                self.verify(**change)

    def test_tampered_ids_or_signature_rejected(self):
        for field, value in (("source_ids", ["f"*16]), ("signature", "f"*64)):
            bad = dict(self.receipt, **{field: value})
            with self.subTest(field=field), self.assertRaises(ProvenanceRejected):
                self.verify(receipt=bad)

    def test_absent_or_injected_fields_rejected(self):
        for bad in ({}, dict(self.receipt, model_claim=True)):
            with self.assertRaisesRegex(ProvenanceRejected, "invalid_receipt_shape"):
                self.verify(receipt=bad)

    def test_changed_tool_text_with_same_source_id_rejected(self):
        bad = copy.deepcopy(self.results)
        bad["results"][0]["snippet"] = "Untrusted malicious content"
        with self.assertRaises(ProvenanceRejected):
            self.verify(results=bad)

    def test_swapped_valid_index_snapshot_rejected(self):
        # Same ID, different validated content/hash: fixture metadata is unchanged.
        modified = fixture(text="Different content for same document chunk.")
        with self.assertRaises(ProvenanceRejected):
            self.verify(index=modified)

    def test_altered_tool_query_or_limit_rejected(self):
        for value in ({"query": QUESTION, "limit": 7},
                      {"query": "other question", "limit": 8}):
            with self.subTest(value=value), self.assertRaises(ProvenanceRejected):
                self.verify(arguments=value)

    def test_expired_or_future_receipts_rejected(self):
        for when in (NOW + 60, NOW - 6):
            with self.subTest(when=when), self.assertRaises(ProvenanceRejected):
                self.verify(now=when)

    def test_invalid_time_window_rejected_at_signing(self):
        for expires in (NOW, NOW + 301):
            with self.assertRaises(ProvenanceRejected):
                issue_receipt(**dict(self.issue_args, expires_at=expires))

    def test_unknown_or_rotated_key_rejected(self):
        with self.assertRaisesRegex(ProvenanceRejected, "unknown_key"):
            self.verify(keys={"other-key": KEY2})
        with self.assertRaisesRegex(ProvenanceRejected, "signature_mismatch"):
            self.verify(keys={"test-key-1": KEY2})
        # Verifier can accept multiple active keys during planned rotation.
        self.assertIsNone(self.verify(keys={"test-key-1": KEY, "new-key": KEY2}))

    def test_missing_or_unavailable_replay_guard_rejected(self):
        with self.assertRaisesRegex(ProvenanceRejected, "missing_replay_guard"):
            self.verify(consume=None)
        def broken(*_):
            raise RuntimeError("ledger down")
        with self.assertRaisesRegex(ProvenanceRejected, "replay_guard_unavailable"):
            self.verify(consume=broken)

    def test_citation_not_in_actual_results_rejected(self):
        with self.assertRaisesRegex(ProvenanceRejected, "unattested_citation"):
            self.verify(cited_source_ids=["f"*16])

    def test_forged_results_cannot_be_signed_against_snapshot(self):
        forged = copy.deepcopy(self.results)
        forged["results"][0]["snippet"] = "not in index"
        with self.assertRaises(ProvenanceRejected):
            issue_receipt(**dict(self.issue_args, results=forged))

    def test_duplicate_ids_rejected_at_signing(self):
        bad = {"results": [self.results["results"][0]] * 2}
        with self.assertRaises(ProvenanceRejected):
            issue_receipt(**dict(self.issue_args, results=bad))

    def test_empty_results_rejected(self):
        with self.assertRaises(ProvenanceRejected):
            issue_receipt(**dict(self.issue_args, results={"results": []}))

    def test_invalid_key_or_context_rejected(self):
        for change in ({"key": b"short"}, {"request_id": "../other"},
                       {"event_id": "wrong"}, {"key_id": " "},
                       {"arguments": {"query": QUESTION, "limit": True}}):
            with self.subTest(change=change), self.assertRaises(ProvenanceRejected):
                issue_receipt(**dict(self.issue_args, **change))


if __name__ == "__main__":
    unittest.main()
