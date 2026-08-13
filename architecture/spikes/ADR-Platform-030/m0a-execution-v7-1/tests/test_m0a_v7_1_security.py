from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import verify_m0a_v7_1_security as module  # noqa: E402


class SecurityCorrectionTests(unittest.TestCase):
    def test_new_security_digest_requires_new_acceptance(self) -> None:
        result = module.verify()
        self.assertEqual(result["state"], "BLOCKED-OFFLINE-CANDIDATE")
        self.assertEqual(result["riskCount"], 5)
        self.assertTrue(result["newAcceptanceRequired"])
        self.assertFalse(result["mutationAuthorized"])
        self.assertFalse(result["clusterContacted"])


if __name__ == "__main__":
    unittest.main()
