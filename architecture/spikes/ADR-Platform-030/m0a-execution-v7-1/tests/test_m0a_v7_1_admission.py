from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import verify_m0a_v7_1_admission as module  # noqa: E402


class AdmissionCorrectionTests(unittest.TestCase):
    def test_v7_is_invalidated_and_v71_is_fail_closed(self) -> None:
        result = module.verify()
        self.assertEqual(result["state"], "CORRECTED-OFFLINE-NO-GO")
        self.assertEqual(result["oldValidationEntries"], 2)
        self.assertEqual(result["correctedValidationEntries"], 1)
        self.assertEqual(result["clusterScopedIdentities"], 4)
        self.assertEqual(result["namespacedIdentities"], 7)
        self.assertFalse(result["mutationAuthorized"])
        self.assertFalse(result["clusterContacted"])


if __name__ == "__main__":
    unittest.main()
