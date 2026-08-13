from __future__ import annotations
import sys,unittest
from pathlib import Path
import yaml
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import m0a_v7_1_payloads as payloads
import verify_m0a_v7_1_credential as credential
class Tests(unittest.TestCase):
    def test_payloads_derive_from_one_source(self):
        p=payloads.derive();self.assertEqual(len(p["administrator"].documents),8);self.assertEqual(len(p["temporaryInstaller"].documents),11)
        self.assertEqual(len([x for x in yaml.safe_load_all(p["administrator"].raw) if x]),8)
        self.assertEqual(len([x for x in yaml.safe_load_all(p["temporaryInstaller"].raw) if x]),11)
    def test_credential_excludes_privilege_escape(self):
        r=credential.verify();self.assertEqual(r["objects"],5);self.assertFalse(r["bindAllowed"]);self.assertFalse(r["escalateAllowed"])
if __name__=="__main__":unittest.main()
