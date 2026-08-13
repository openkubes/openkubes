from __future__ import annotations
import sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import verify_m0a_v7_1_risk_acceptance as module
class Tests(unittest.TestCase):
    def test_exact_non_authorizing_record(self):
        r=module.verify();self.assertEqual(r["acceptedRisks"],5);self.assertFalse(r["mutationAuthorized"]);self.assertFalse(r["clusterContacted"])
if __name__=="__main__":unittest.main()
