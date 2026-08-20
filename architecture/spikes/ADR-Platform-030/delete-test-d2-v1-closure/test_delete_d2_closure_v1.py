#!/usr/bin/env python3

import tempfile
import unittest
from pathlib import Path
import yaml
from verify_delete_d2_closure_v1 import ClosureError, digest, verify

HERE = Path(__file__).resolve().parent
CLOSURE = HERE / "delete-d2-closure-evidence-v1.yaml"

class TestClosure(unittest.TestCase):
    def changed(self, mutate):
        value = yaml.safe_load(CLOSURE.read_text()); mutate(value)
        temp = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
        yaml.safe_dump(value, temp, sort_keys=False); temp.close(); self.addCleanup(Path(temp.name).unlink)
        return Path(temp.name)
    def test_pass(self): self.assertEqual("PASS-D2-ENABLEMENT-QUIESCED-REDACTED", verify(CLOSURE)["spec"]["state"])
    def test_hrp_direct_delete_fails(self):
        with self.assertRaisesRegex(ClosureError, "hrpDelete"):
            verify(self.changed(lambda v: v["spec"]["result"].update(hrpDeleteRequestedByRunner=True)))
    def test_finalizer_mutation_fails(self):
        with self.assertRaisesRegex(ClosureError, "finalizer"):
            verify(self.changed(lambda v: v["spec"]["result"].update(finalizerMutationPerformed=True)))
    def test_d3_authority_fails(self):
        with self.assertRaisesRegex(ClosureError, "grants authority"):
            verify(self.changed(lambda v: v["spec"]["authorization"].update(d3Granted=True)))
    def test_publication_bound(self):
        p = yaml.safe_load((HERE / "delete-d2-closure-publication-candidate-v1.yaml").read_text())["spec"]
        self.assertEqual(digest(CLOSURE), p["bindings"]["closureDigest"]); self.assertEqual(5, p["bindings"]["offlineTestsPassed"])

if __name__ == "__main__": unittest.main()
