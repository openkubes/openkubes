from __future__ import annotations

import sys
import hashlib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import verify_m0a_v7_risk_acceptance as module  # noqa: E402


class RiskAcceptanceTests(unittest.TestCase):
    def test_record_is_exact_and_non_authorizing(self) -> None:
        result = module.verify()
        self.assertEqual(result["state"], "ACCEPTED-NON-AUTHORIZING")
        self.assertEqual(result["acceptedBy"], "github:arashkaffamanesh")
        self.assertEqual(result["acceptedRisks"], 5)
        self.assertFalse(result["mutationAuthorized"])
        self.assertFalse(result["evidencePublicationGranted"])
        self.assertFalse(result["clusterContacted"])

    def test_record_digest_is_bound(self) -> None:
        actual = "sha256:" + hashlib.sha256(module.RECORD.read_bytes()).hexdigest()
        expected = (module.HERE / "m0a-v7-risk-acceptance-v1.sha256").read_text().strip()
        self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
