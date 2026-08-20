#!/usr/bin/env python3
import json
import tempfile
import unittest
from pathlib import Path

from verify_adr030_evidence_amendment_v1 import AmendmentError, digest, verify


HERE = Path(__file__).resolve().parent
ADR = HERE.parents[2] / "decisions" / "ADR-Platform-030-control-plane-execution-model.md"
PUBLICATION = HERE / "adr030-evidence-amendment-publication-candidate-v1.json"


class TestAmendment(unittest.TestCase):
    def changed(self, old, new):
        temporary = tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False)
        temporary.write(ADR.read_text().replace(old, new))
        temporary.close()
        self.addCleanup(Path(temporary.name).unlink)
        return Path(temporary.name)

    def test_pass(self):
        self.assertIn("outcome A", verify(ADR))

    def test_acceptance_fails(self):
        with self.assertRaisesRegex(AmendmentError, "forbidden"):
            verify(self.changed("**Status:** Proposed", "**Status:** Accepted"))

    def test_old_condition_fails(self):
        with self.assertRaisesRegex(AmendmentError, "forbidden"):
            verify(self.changed("`ControlPlaneAvailable`", "`ControlPlaneReady`"))

    def test_mandatory_status_loop_fails(self):
        with self.assertRaisesRegex(AmendmentError, "missing"):
            verify(self.changed("A continuously published Kubernetes status surface is optional", "A continuously published Kubernetes status surface is mandatory"))

    def test_acceptance_matrix_retained(self):
        self.assertIn("Create, Scale, Upgrade, Delete, retry, duplicate", verify(ADR))

    def test_publication_bound(self):
        publication = json.loads(PUBLICATION.read_text())
        self.assertEqual(digest(ADR), publication["bindings"]["adrDigest"])
        self.assertEqual(6, publication["bindings"]["offlineTestsPassed"])


if __name__ == "__main__":
    unittest.main()
