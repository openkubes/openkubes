#!/usr/bin/env python3
import tempfile
import unittest
from pathlib import Path

import yaml

from verify_delete_d4_d5_closure_v1 import ClosureError, digest, verify


HERE = Path(__file__).resolve().parent
CLOSURE = HERE / "delete-d4-d5-closure-evidence-v1.yaml"


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
        self.assertTrue(verify(CLOSURE)["spec"]["d5"]["allBoundProviderResidualsAbsent"])

    def test_d4_incomplete_fails(self):
        with self.assertRaisesRegex(ClosureError, "D4 absence"):
            verify(self.changed(lambda v: v["spec"]["d4"].update(confirmedAbsentControllerOwnedIdentities=23)))

    def test_d5_partial_fails(self):
        with self.assertRaisesRegex(ClosureError, "D5 delete"):
            verify(self.changed(lambda v: v["spec"]["d5"].update(completedDeletes=6)))

    def test_retry_fails(self):
        with self.assertRaisesRegex(ClosureError, "retryPerformed"):
            verify(self.changed(lambda v: v["spec"]["d5"].update(retryPerformed=True)))

    def test_d6_authority_fails(self):
        with self.assertRaisesRegex(ClosureError, "grants authority"):
            verify(self.changed(lambda v: v["spec"]["authorization"].update(d6Granted=True)))

    def test_publication_bound(self):
        publication = yaml.safe_load(
            (HERE / "delete-d4-d5-closure-publication-candidate-v1.yaml").read_text()
        )["spec"]
        self.assertEqual(digest(CLOSURE), publication["bindings"]["closureDigest"])
        self.assertEqual(6, publication["bindings"]["offlineTestsPassed"])


if __name__ == "__main__":
    unittest.main()
