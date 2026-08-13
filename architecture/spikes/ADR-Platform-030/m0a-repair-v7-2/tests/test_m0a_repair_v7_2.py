from __future__ import annotations
import importlib.util,json,sys,unittest
from pathlib import Path
import yaml

HERE=Path(__file__).resolve().parents[1]
SPIKE=HERE.parent
def load():
    spec=importlib.util.spec_from_file_location("ok141_m0a_repair_v72_test",HERE/"controlled_m0a_repair_v7_2.py")
    module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module
    assert spec.loader is not None;spec.loader.exec_module(module);return module
M=load()

class RepairCandidateTests(unittest.TestCase):
    def setUp(self):
        self.path=HERE/"m0a-repair-candidate-v7-2.yaml"
        self.document,self.refs,_,_=M.verify_candidate(self.path)
        self.spec=self.document["spec"]
        self.patch=json.loads(self.refs["jsonPatch"].read_text())
    def test_candidate_is_no_go(self):
        self.assertEqual(self.spec["authorization"]["decision"],"NO-GO")
        self.assertFalse(any(v for k,v in self.spec["authorization"].items() if k!="decision"))
    def test_patch_is_one_exact_replace(self):
        self.assertEqual([x["op"] for x in self.patch],["test","test","test","replace"])
        self.assertEqual(self.patch[0]["value"],self.spec["target"]["deploymentUID"])
        self.assertEqual(self.patch[2]["value"],self.spec["repair"]["oldArguments"])
        self.assertEqual(self.patch[3]["value"],self.spec["repair"]["newArguments"])
    def test_all_provider_variables_are_resolved(self):
        self.assertEqual(self.spec["repair"]["newArguments"],["--leader-elect","--diagnostics-address=:8443","--insecure-diagnostics=false","--sync-period=10m","--v=2"])
        self.assertFalse(any("${" in value for value in self.spec["repair"]["newArguments"]))
    def test_historical_source_contains_exact_three_variables(self):
        source=SPIKE/"m0a-installation"/"caaph-v0.6.4-addon-components.yaml"
        self.assertEqual(source.read_text().count("${CAAPH_"),3)
    def test_grant_template_cannot_authorize(self):
        grant=yaml.safe_load((HERE/"m0a-repair-grant-v7-2.template.yaml").read_text())["spec"]
        self.assertEqual(grant["decision"],"NO-GO");self.assertFalse(grant["repairAuthorized"]);self.assertEqual(grant["maximumRuns"],0)
    def test_grant_candidate_remains_no_go(self):
        grant=yaml.safe_load((HERE/"m0a-repair-grant-candidate-v7-2.yaml").read_text())["spec"]
        self.assertEqual(grant["state"],"AWAITING-EXPLICIT-RISK-ACCEPTANCE-AND-REPAIR-GRANT")
        self.assertEqual(grant["repairCandidateDigest"],M.sha(self.path))
        self.assertEqual(grant["proposedGrant"]["maximumRuns"],1)
        self.assertEqual(grant["authorization"]["decision"],"NO-GO")
        self.assertFalse(any(v for k,v in grant["authorization"].items() if k!="decision"))
    def test_runtime_is_partial_not_success(self):
        runtime=yaml.safe_load(self.refs["v71RuntimeEvidence"].read_text())["spec"]
        self.assertEqual(runtime["state"],"PARTIAL-STATE-RETAINED")
        self.assertEqual(runtime["execution"]["result"],"STOP-NOT-SUCCESS")
        self.assertFalse(runtime["conclusion"]["grantsReusable"])

if __name__=="__main__":unittest.main()
