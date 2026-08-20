#!/usr/bin/env python3
import tempfile
import unittest
from pathlib import Path

import yaml

from verify_delete_d6_d7_closure_v1 import ClosureError, digest, verify


HERE = Path(__file__).resolve().parent
CLOSURE = HERE / "delete-d6-d7-closure-evidence-v1.yaml"


class TestClosure(unittest.TestCase):
    def changed(self, update):
        value = yaml.safe_load(CLOSURE.read_text())
        update(value)
        temporary = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
        yaml.safe_dump(value, temporary, sort_keys=False)
        temporary.close()
        self.addCleanup(Path(temporary.name).unlink)
        return Path(temporary.name)

    def test_pass(self):
        self.assertTrue(verify(CLOSURE)["spec"]["conclusion"]["deleteScenarioComplete"])

    def test_partial_d6_fails(self):
        with self.assertRaisesRegex(ClosureError, "D6 delete"):
            verify(self.changed(lambda v: v["spec"]["d6"].update(completedDeletes=1)))

    def test_remaining_identity_fails(self):
        with self.assertRaisesRegex(ClosureError, "D7 absence"):
            verify(self.changed(lambda v: v["spec"]["d7"].update(confirmedAbsentUniqueIdentities=38)))

    def test_force_delete_fails(self):
        with self.assertRaisesRegex(ClosureError, "forceDeletePerformed"):
            verify(self.changed(lambda v: v["spec"]["d6"].update(forceDeletePerformed=True)))

    def test_further_delete_authority_fails(self):
        with self.assertRaisesRegex(ClosureError, "grants authority"):
            verify(self.changed(lambda v: v["spec"]["authorization"].update(furtherDeleteGranted=True)))

    def test_publication_bound(self):
        publication = yaml.safe_load(
            (HERE / "delete-d6-d7-closure-publication-candidate-v1.yaml").read_text()
        )["spec"]
        self.assertEqual(digest(CLOSURE), publication["bindings"]["closureDigest"])
        self.assertEqual(6, publication["bindings"]["offlineTestsPassed"])


if __name__ == "__main__":
    unittest.main()
