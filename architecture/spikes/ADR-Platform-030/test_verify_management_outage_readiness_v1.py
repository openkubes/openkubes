#!/usr/bin/env python3
import json
import tempfile
import unittest
from pathlib import Path

from verify_management_outage_readiness_v1 import ReadinessError, digest, verify


HERE = Path(__file__).resolve().parent
ASSESSMENT = HERE / "management-outage-readiness-v1.md"
PUBLICATION = HERE / "management-outage-readiness-publication-candidate-v1.json"


class TestReadiness(unittest.TestCase):
    def changed(self, old, new):
        temporary = tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False)
        temporary.write(ASSESSMENT.read_text().replace(old, new))
        temporary.close()
        self.addCleanup(Path(temporary.name).unlink)
        return Path(temporary.name)

    def test_pass(self):
        self.assertIn("NO-GO", verify(ASSESSMENT))

    def test_safety_go_fails(self):
        with self.assertRaisesRegex(ReadinessError, "missing"):
            verify(self.changed("Gate A — Safety: BLOCKED", "Gate A — Safety: GO"))

    def test_outage_go_fails(self):
        with self.assertRaisesRegex(ReadinessError, "forbidden"):
            verify(self.changed("Outage / worker failure:               NO-GO", "Outage / worker failure:               GO"))

    def test_done_fails(self):
        with self.assertRaisesRegex(ReadinessError, "forbidden"):
            verify(self.changed("OK-141 Jira completion:                BLOCKED by current acceptance text", "OK-141 Jira completion:                DONE"))

    def test_worker_budget_retained(self):
        self.assertIn("workers:                    at least 2", verify(ASSESSMENT))

    def test_publication_bound(self):
        publication = json.loads(PUBLICATION.read_text())
        self.assertEqual(digest(ASSESSMENT), publication["bindings"]["assessmentDigest"])
        self.assertEqual(6, publication["bindings"]["offlineTestsPassed"])


if __name__ == "__main__":
    unittest.main()
