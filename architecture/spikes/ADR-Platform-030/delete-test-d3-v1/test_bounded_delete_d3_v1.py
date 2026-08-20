#!/usr/bin/env python3

import tempfile, unittest
from pathlib import Path
import yaml
import bounded_delete_d3_v1 as runner

HERE=Path(__file__).resolve().parent; CANDIDATE=HERE/"delete-d3-candidate-v1.yaml"

class TestD3(unittest.TestCase):
    def changed(self, mutate):
        value=yaml.safe_load(CANDIDATE.read_text()); mutate(value)
        temp=tempfile.NamedTemporaryFile(mode="w",suffix=".yaml",delete=False); yaml.safe_dump(value,temp,sort_keys=False); temp.close(); self.addCleanup(Path(temp.name).unlink); return Path(temp.name)
    def test_candidate_passes(self): self.assertEqual("OFFLINE-PREPARED-BLOCKED-NO-GO",runner.verify_candidate(CANDIDATE)["spec"]["state"])
    def test_delete_authority_fails(self):
        with self.assertRaisesRegex(runner.D3Error,"grants authority"): runner.verify_candidate(self.changed(lambda v:v["spec"]["authorization"].update(deleteGranted=True)))
    def test_target_change_fails(self):
        with self.assertRaisesRegex(runner.D3Error,"target mismatch"): runner.verify_candidate(self.changed(lambda v:v["spec"]["target"].update(name="wrong")))
    def test_child_delete_fails(self):
        with self.assertRaisesRegex(runner.D3Error,"ownership boundary"): runner.verify_candidate(self.changed(lambda v:v["spec"]["operation"].update(childDelete=True)))
    def test_live_resource_version(self):
        bound={"name":"c","namespace":"n","uid":"u","resourceVersion":"1"}; current={"metadata":{"name":"c","namespace":"n","uid":"u","resourceVersion":"2"}}
        self.assertEqual("2",runner.live_cluster(current,bound)["resourceVersion"])
    def test_uid_change_fails(self):
        bound={"name":"c","namespace":"n","uid":"u","resourceVersion":"1"}; current={"metadata":{"name":"c","namespace":"n","uid":"x","resourceVersion":"2"}}
        with self.assertRaisesRegex(runner.D3Error,"immutable"): runner.live_cluster(current,bound)
    def test_publication_non_authorizing(self):
        p=yaml.safe_load((HERE/"delete-d3-publication-candidate-v1.yaml").read_text())["spec"]
        self.assertEqual(runner.file_digest(CANDIDATE),p["bindings"]["candidateDigest"]); self.assertEqual(7,p["bindings"]["offlineTestsPassed"]); self.assertFalse(any(v for k,v in p["authorization"].items() if k.endswith("Granted")))

if __name__=="__main__": unittest.main()
