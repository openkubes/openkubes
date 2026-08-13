from __future__ import annotations
import importlib.util,sys,unittest
from pathlib import Path

HERE=Path(__file__).resolve().parents[1]
def load():
    spec=importlib.util.spec_from_file_location("ok141_m0a_readiness_v73_test",HERE/"evaluate_m0a_readiness_v7_3.py")
    module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module
    assert spec.loader is not None;spec.loader.exec_module(module);return module
M=load()

class ReadinessCandidateTests(unittest.TestCase):
    def setUp(self):self.document,self.refs=M.verify_candidate(HERE/"m0a-readiness-candidate-v7-3.yaml");self.spec=self.document["spec"]
    def test_is_read_only(self):self.assertEqual(self.spec["state"],"READY-READ-ONLY");self.assertFalse(any(self.spec["authorization"].values()))
    def test_index_and_platform_identities_are_distinct(self):
        image=self.spec["imageIdentity"]
        self.assertNotEqual(image["indexDigest"],image["linuxAmd64ChildManifestDigest"])
        self.assertTrue(image["expectedRuntimeImageID"].endswith("@"+image["indexDigest"]))
        self.assertEqual(image["claimBoundary"]["runtimeImageIDEqualsPlatformChild"],"not-required-and-not-claimed")
    def test_repair_state_is_bound(self):self.assertEqual(self.spec["sourceEvidence"]["v72RawLocalEvidenceDigest"],"sha256:128b03c32ed4d278d83ebbde7cfd555b69160e6e8bf4f904a55d4d737479adc4")
    def test_no_target_state_expected(self):self.assertEqual(self.spec["assertions"]["caaphCustomResources"],0);self.assertEqual(self.spec["assertions"]["capiLifecycleInventory"],{"clusters":0,"machines":0,"machineDeployments":0})

if __name__=="__main__":unittest.main()
