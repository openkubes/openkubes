"""Offline contract checks for human-reviewed read-only QA evaluation cases.

No model is invoked. Passing these tests is NOT evidence of factual grounding.
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from public_beta.gateway_context import MAX_QUESTION_CHARS
from public_beta.structured_answer import ContractRejected, validate_and_render
from tests.test_private_context_gateway_probe import fixture, SID, QUESTION

FILE = ROOT / "public_beta" / "golden_eval_cases.json"


class ReadonlyGoldenEvalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = json.loads(FILE.read_text(encoding="utf-8"))
        cls.cases = cls.spec["cases"]

    def test_case_catalog_version_and_review_status(self):
        self.assertEqual(self.spec["version"], "0.1")
        self.assertEqual(self.spec["status"], "human_review_required")
        self.assertEqual(self.spec["scope"], "read_only_documentation_qa")
        self.assertGreaterEqual(len(self.cases), 8)

    def test_unique_bounded_questions_and_manual_review_rubrics(self):
        ids = set()
        for case in self.cases:
            with self.subTest(case=case["id"]):
                self.assertNotIn(case["id"], ids)
                ids.add(case["id"])
                self.assertIn(case["kind"],
                              {"factual", "architecture", "command_request",
                               "unsupported", "adversarial"})
                question = case["question"]
                self.assertEqual(question, question.strip())
                self.assertTrue(1 <= len(question) <= MAX_QUESTION_CHARS)
                self.assertFalse(any(ord(char) < 32 or ord(char) == 127
                                     for char in question))
                self.assertTrue(case["human_review"])

    def test_core_negative_case_categories_are_present(self):
        kinds = {case["kind"] for case in self.cases}
        self.assertTrue({"factual", "architecture", "command_request",
                         "unsupported", "adversarial"} <= kinds)

    def test_no_preapproved_grounding_or_commands(self):
        self.assertIn("reviewer_fields", self.spec)
        self.assertIn("supported_claims", self.spec["reviewer_fields"])
        self.assertIn("citation_correct", self.spec["reviewer_fields"])
        self.assertNotIn("answers", self.spec)
        self.assertNotIn("semantic_grounding_pass", self.spec)

    def test_model_authored_commands_are_rejected_by_existing_contract(self):
        # Synthetic model response and synthetic trusted index; no live model.
        from docs_mcp import DocsRetriever
        index = fixture()
        hits = DocsRetriever(index).docs_search(QUESTION, limit=8)
        response = json.dumps({
            "version": "0.1",
            "steps": [{"text": "Run kubectl get pods.", "source_ids": [SID]}],
        })
        with self.assertRaises(ContractRejected):
            validate_and_render(response, hits, index)

    def test_forged_citations_are_rejected_by_existing_contract(self):
        from docs_mcp import DocsRetriever
        index = fixture()
        hits = DocsRetriever(index).docs_search(QUESTION, limit=8)
        response = json.dumps({
            "version": "0.1",
            "steps": [{"text": "Read the documentation.",
                       "source_ids": ["f" * 16]}],
        })
        with self.assertRaises(ContractRejected):
            validate_and_render(response, hits, index)


if __name__ == "__main__":
    unittest.main()
