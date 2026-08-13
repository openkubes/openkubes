from __future__ import annotations
import sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import verify_m0a_v7_1_live_preflight as module
class Tests(unittest.TestCase):
    def test_live_preflight_is_read_only_and_bound(self):
        r=module.verify();self.assertEqual(r["exactIdentityAbsence"],19);self.assertEqual(r["bootstrapAbsence"],7);self.assertFalse(r["mutationPerformed"])
if __name__=="__main__":unittest.main()
