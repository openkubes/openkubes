"""Offline receipt verification tests; no kagent, cluster, or network I/O."""
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

KEY = b"a-fixture-key-for-testing-only-not-production-1234567890"
REQUEST = "0" * 32
QUESTION = "How do I install OpenKubes Local?"
REPO = "openkubes/ok-local"
REV = "a" * 40
PATH = "docs/tutorial-basic.md"
TEXT = "Install OpenKubes Local by reading the installation guide."
SID = hashlib.sha256(f"{REPO}:{REV}:{PATH}:0".encode()).hexdigest()[:16]


def fixture():
    return {"schema_version": 1, "corpus": [{
        "source_id": SID, "repo": REPO, "path": PATH, "revision": REV,
        "chunk_number": 0, "section": "Install",
        "url": f"https://github.com/{REPO}/blob/{REV}/{PATH}",
        "sha256": hashlib.sha256(TEXT.encode()).hexdigest(), "text": TEXT,
    }]}


class ProvenanceReceiptTests(unittest.TestCase):
    def setUp(self):
        self.index = fixture()
        self.results = DocsRetriever(self.index).docs_search(QUESTION, limit=8)
        self.assertEqual(len(self.results["results"]), 1)
        self.receipt = issue_receipt(
            key=KEY, request_id=REQUEST, question=QUESTION, results=self.results)

    def verify(self, receipt=None, **kwargs):
        return verify_receipt(
            key=kwargs.get("key", KEY),
            request_id=kwargs.get("request_id", REQUEST),
            question=kwargs.get("question", QUESTION),
            receipt=self.receipt if receipt is None else receipt,
            index=kwargs.get("index", self.index),
            rendered_source_ids=kwargs.get("rendered_source_ids", [SID]),
        )

    def test_signed_matching_request_is_accepted(self):
        self.assertIsNone(self.verify())

    def test_other_request_id_is_rejected(self):
        with self.assertRaises(ProvenanceRejected):
            self.verify(request_id="1" * 32)

    def test_other_question_is_rejected(self):
        with self.assertRaises(ProvenanceRejected):
            self.verify(question="Different question")

    def test_tampered_source_ids_are_rejected(self):
        receipt = copy.deepcopy(self.receipt)
        receipt["source_ids"] = ["f" * 16]
        with self.assertRaises(ProvenanceRejected):
            self.verify(receipt)

    def test_tampered_signature_is_rejected(self):
        receipt = copy.deepcopy(self.receipt)
        receipt["signature"] = "f" * 64
        with self.assertRaises(ProvenanceRejected):
            self.verify(receipt)

    def test_unattested_citation_is_rejected(self):
        with self.assertRaises(ProvenanceRejected):
            self.verify(rendered_source_ids=["f" * 16])

    def test_absent_receipt_is_rejected(self):
        with self.assertRaises(ProvenanceRejected):
            self.verify({})

    def test_duplicate_ids_and_model_injected_properties_are_rejected(self):
        for edit in ({"source_ids": [SID, SID]}, {"model_claim": True}):
            receipt = dict(self.receipt)
            receipt.update(edit)
            with self.subTest(edit=edit):
                with self.assertRaises(ProvenanceRejected):
                    self.verify(receipt)

    def test_empty_results_cannot_create_receipt(self):
        with self.assertRaises(ProvenanceRejected):
            issue_receipt(key=KEY, request_id=REQUEST, question=QUESTION,
                          results={"results": []})

    def test_weak_key_rejected(self):
        with self.assertRaises(ProvenanceRejected):
            issue_receipt(key=b"bad", request_id=REQUEST, question=QUESTION,
                          results=self.results)

    def test_unknown_corpus_source_is_rejected(self):
        changed = fixture()
        changed["corpus"] = []
        with self.assertRaises(ProvenanceRejected):
            self.verify(index=changed)

    def test_malformed_request_id_is_rejected(self):
        with self.assertRaises(ProvenanceRejected):
            self.verify(request_id="../other-request")


if __name__ == "__main__":
    unittest.main()
