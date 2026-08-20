#!/usr/bin/env python3
import tempfile,unittest
from pathlib import Path
import yaml
from verify_delete_d3_closure_v1 import ClosureError,digest,verify
HERE=Path(__file__).resolve().parent; CLOSURE=HERE/"delete-d3-closure-evidence-v1.yaml"
class TestClosure(unittest.TestCase):
    def changed(self,fn):
        v=yaml.safe_load(CLOSURE.read_text()); fn(v); f=tempfile.NamedTemporaryFile(mode="w",suffix=".yaml",delete=False); yaml.safe_dump(v,f,sort_keys=False); f.close(); self.addCleanup(Path(f.name).unlink); return Path(f.name)
    def test_pass(self): self.assertTrue(verify(CLOSURE)["spec"]["result"]["clusterAbsent"])
    def test_child_delete_fails(self):
        with self.assertRaisesRegex(ClosureError,"childDelete"): verify(self.changed(lambda v:v["spec"]["result"].update(childDeleteRequestedByRunner=True)))
    def test_d4_claim_fails(self):
        with self.assertRaisesRegex(ClosureError,"D4"): verify(self.changed(lambda v:v["spec"]["conclusion"].update(detailedControllerGraphClosureProven=True)))
    def test_d5_authority_fails(self):
        with self.assertRaisesRegex(ClosureError,"grants authority"): verify(self.changed(lambda v:v["spec"]["authorization"].update(d5Granted=True)))
    def test_publication_bound(self):
        p=yaml.safe_load((HERE/"delete-d3-closure-publication-candidate-v1.yaml").read_text())["spec"]; self.assertEqual(digest(CLOSURE),p["bindings"]["closureDigest"]); self.assertEqual(5,p["bindings"]["offlineTestsPassed"])
if __name__=="__main__": unittest.main()
