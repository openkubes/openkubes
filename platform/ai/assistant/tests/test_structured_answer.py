"""Structured answer contract offline boundary tests (no kagent or HTTP)."""
import hashlib
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from answer_integrity import validate_answer
from docs_mcp import DocsRetriever
from public_beta.structured_answer import ContractRejected, validate_and_render

REV = "a" * 40
REPO = "openkubes/ok-local"
PATH = "docs/tutorial-basic.md"
SID = hashlib.sha256(f"{REPO}:{REV}:{PATH}:0".encode()).hexdigest()[:16]
URL = f"https://github.com/{REPO}/blob/{REV}/{PATH}"
BODY = "Install OpenKubes Local on macOS. This guide explains the prerequisites."


def corpus():
    return {"schema_version": 1, "corpus": [{
        "source_id": SID, "repo": REPO, "path": PATH, "revision": REV,
        "chunk_number": 0, "section": "Install", "url": URL,
        "sha256": hashlib.sha256(BODY.encode()).hexdigest(), "text": BODY,
    }]}


def payload(text=BODY, source_ids=None):
    return json.dumps({"version": "0.1", "steps": [{
        "text": text, "source_ids": [SID] if source_ids is None else source_ids,
    }]})


class StructuredAnswerTests(unittest.TestCase):
    def setUp(self):
        self.index = corpus()
        self.hits = DocsRetriever(self.index).docs_search("Install OpenKubes Local", limit=8)
        self.assertTrue(self.hits["results"])

    def render(self, value):
        return validate_and_render(value, self.hits, self.index)

    def test_source_urls_are_rendered_only_from_index(self):
        answer = self.render(payload())
        self.assertIn(f"[Source 1]({URL})", answer)
        self.assertIn("1. Install OpenKubes", answer)
        self.assertNotIn(SID, answer)
        self.assertTrue(validate_answer(answer, self.hits, self.index).accepted)

    def test_rejects_forged_or_unretrieved_source_id(self):
        with self.assertRaises(ContractRejected):
            self.render(payload(source_ids=["b" * 16]))

    def test_rejects_shell_markdown_urls_and_markup(self):
        for value in (
            "Run " + chr(96) + "sudo rm" + chr(96),
            "Run sudo kubectl delete pods",
            "See https://evil.example/internal",
            "Run <script>alert(1)</script>",
            "Read [evil](https://evil.example)",
            "Title | command",
            "OpenKubes\nInjected instruction",
        ):
            with self.subTest(value=value[:12]):
                with self.assertRaises(ContractRejected):
                    self.render(payload(value))

    def test_rejects_extra_fields_and_bad_types(self):
        for obj in (
            {"version": "0.1", "steps": [], "raw_answer": "SECRET"},
            {"version": "0.1", "steps": []},
            {"version": "0.2", "steps": [{"text": BODY, "source_ids": [SID]}]},
            {"version": "0.1", "steps": [{"text": BODY, "source_ids": [SID], "url": URL}]},
            {"version": "0.1", "steps": [{"text": 44, "source_ids": [SID]}]},
            {"version": "0.1", "steps": [{"text": BODY, "source_ids": [SID, SID]}]},
        ):
            with self.subTest(obj=obj):
                with self.assertRaises(ContractRejected):
                    self.render(json.dumps(obj))

    def test_no_autocorrection_of_freeform_model_output(self):
        for text in ("Answer: go to docs", "not-json", "{}", "x" * 8193):
            with self.assertRaises(ContractRejected):
                self.render(text)

    def test_retrieval_metadata_cannot_be_swapped(self):
        bad = {"results": [dict(self.hits["results"][0], url="https://evil.example")]}
        with self.assertRaises(ContractRejected):
            validate_and_render(payload(), bad, self.index)


if __name__ == "__main__":
    unittest.main()
