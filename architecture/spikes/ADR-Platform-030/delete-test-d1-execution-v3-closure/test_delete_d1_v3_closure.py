#!/usr/bin/env python3

import tempfile
import unittest
from pathlib import Path

import yaml

from verify_delete_d1_v3_closure import ClosureError, digest, verify


HERE = Path(__file__).resolve().parent
CLOSURE = HERE / "delete-d1-v3-closure-evidence.yaml"


class DeleteD1V3ClosureTest(unittest.TestCase):
    def changed(self, mutate) -> Path:
        temp = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
        value = yaml.safe_load(CLOSURE.read_text())
        mutate(value)
        yaml.safe_dump(value, temp, sort_keys=False)
        temp.close()
        self.addCleanup(Path(temp.name).unlink)
        return Path(temp.name)

    def test_closure_passes(self):
        self.assertEqual("PASS-D1-GITOPS-QUIESCED-REDACTED", verify(CLOSURE)["spec"]["state"])

    def test_partial_delete_fails(self):
        with self.assertRaisesRegex(ClosureError, "count"):
            verify(self.changed(lambda v: v["spec"]["execution"].update(completedDeleteCount=4)))

    def test_order_change_fails(self):
        with self.assertRaisesRegex(ClosureError, "ordered"):
            verify(self.changed(lambda v: v["spec"]["execution"]["orderedTargets"].reverse()))

    def test_force_delete_fails(self):
        with self.assertRaisesRegex(ClosureError, "forceDelete"):
            verify(self.changed(lambda v: v["spec"]["execution"].update(forceDeletePerformed=True)))

    def test_d2_authority_fails(self):
        with self.assertRaisesRegex(ClosureError, "grants authority"):
            verify(self.changed(lambda v: v["spec"]["authorization"].update(d2Granted=True)))

    def test_publication_candidate_bound(self):
        publication = yaml.safe_load((HERE / "delete-d1-v3-closure-publication-candidate.yaml").read_text())["spec"]
        self.assertEqual(digest(CLOSURE), publication["bindings"]["closureDigest"])
        self.assertEqual(6, publication["bindings"]["offlineTestsPassed"])


if __name__ == "__main__":
    unittest.main()
