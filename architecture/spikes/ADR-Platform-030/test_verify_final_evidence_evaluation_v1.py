#!/usr/bin/env python3
import tempfile
import unittest
from pathlib import Path

from verify_final_evidence_evaluation_v1 import EvaluationError, digest, verify


HERE = Path(__file__).resolve().parent
EVALUATION = HERE / "final-evidence-evaluation-v1.md"
PUBLICATION = HERE / "final-evidence-evaluation-publication-candidate-v1.json"


class TestEvaluation(unittest.TestCase):
    def changed(self, old, new):
        temporary = tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False)
        temporary.write(EVALUATION.read_text().replace(old, new))
        temporary.close()
        self.addCleanup(Path(temporary.name).unlink)
        return Path(temporary.name)

    def test_pass(self):
        self.assertIn("Outcome A selected", verify(EVALUATION))

    def test_unclassified_fails(self):
        with self.assertRaisesRegex(EvaluationError, "missing"):
            verify(self.changed("Overall OK-141 A/B/C/D:        A", "Overall OK-141 A/B/C/D:        unclassified"))

    def test_accepted_adr_fails(self):
        with self.assertRaisesRegex(EvaluationError, "forbidden"):
            verify(self.changed("ADR-030:                       Proposed; amendment required before acceptance", "ADR-030:                       Accepted"))

    def test_outage_pass_fails(self):
        with self.assertRaisesRegex(EvaluationError, "forbidden"):
            verify(self.changed("Delete scenario:               PASS / terminally closed", "Management outage:             PASS"))

    def test_required_reconciler_fails(self):
        with self.assertRaisesRegex(EvaluationError, "missing"):
            verify(self.changed("RequiresReconciler:            No", "RequiresReconciler:            Proven"))

    def test_publication_bound(self):
        import json
        publication = json.loads(PUBLICATION.read_text())
        self.assertEqual(digest(EVALUATION), publication["bindings"]["evaluationDigest"])
        self.assertEqual(6, publication["bindings"]["offlineTestsPassed"])


if __name__ == "__main__":
    unittest.main()
