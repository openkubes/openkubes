"""Regression evidence for cross-subject attribution; offline only.

This test explicitly shows that structural source-ID validation can ACCEPT
an unsupported semantic claim. It is NOT an automated semantic filter.
"""
import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from docs_mcp import DocsRetriever
from public_beta.structured_answer import validate_and_render

REPO = "openkubes/ok-local"
PATH = "docs/tutorial-basic.md"
REV = "a" * 40
SOURCE = (
    "This tutorial runs KubeVirt on a single node. "
    "For a more complete local setup that mirrors a production Kubernetes "
    "infrastructure, see the OpenKubes project. "
    "OpenKubes provides a fully automated local dev environment (ok-local) "
    "and a production-ready stack on Hetzner bare metal (ok-rke2)."
)
SID = hashlib.sha256(f"{REPO}:{REV}:{PATH}:0".encode()).hexdigest()[:16]


def index_fixture():
    return {"schema_version": 1, "corpus": [{
        "source_id": SID, "repo": REPO, "path": PATH, "revision": REV,
        "chunk_number": 0, "section": "Overview",
        "url": f"https://github.com/{REPO}/blob/{REV}/{PATH}",
        "text": SOURCE, "sha256": hashlib.sha256(SOURCE.encode()).hexdigest(),
    }]}


class SubjectAttributionEvidenceTests(unittest.TestCase):
    def test_existing_contract_accepts_wrongly_attributed_single_node_claim(self):
        index = index_fixture()
        hits = DocsRetriever(index).docs_search("What is OpenKubes Local?", limit=8)
        self.assertEqual(len(hits["results"]), 1)
        answer = json.dumps({"version": "0.1", "steps": [{
            "text": ("OpenKubes Local provides a fully automated single-node "
                     "Kubernetes environment similar to production."),
            "source_ids": [SID],
        }]})
        rendered = validate_and_render(answer, hits, index)
        self.assertIn("single-node Kubernetes environment", rendered)
        # EXPECTED DOCUMENTED GAP: structure passes, semantic human review FAILS.
        # Never interpret the accepted response as a correct answer.

    def test_prompt_explicitly_prohibits_cross_subject_claim_transfer(self):
        manifest = (
            ROOT / "kagent" / "openkubes-docs-agent-context.lab.yaml"
        ).read_text(encoding="utf-8")
        self.assertIn("Attribute each claim to the EXACT subject", manifest)
        self.assertIn("does NOT establish", manifest)
        self.assertIn("prefer a narrower supported answer", manifest)

    def test_grounded_narrow_statement_passes_structure(self):
        index = index_fixture()
        hits = DocsRetriever(index).docs_search("What is OpenKubes Local?", limit=8)
        answer = json.dumps({"version": "0.1", "steps": [{
            "text": "OpenKubes provides a fully automated local development environment called ok-local.",
            "source_ids": [SID],
        }]})
        self.assertIn("ok-local", validate_and_render(answer, hits, index))


if __name__ == "__main__":
    unittest.main()
