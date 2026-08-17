from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

import yaml

import verify_argo_runtime_refresh_candidate_v1 as verifier


class CandidateTests(unittest.TestCase):
    def test_candidate_is_offline_valid_and_blocked(self):
        result = verifier.verify()
        self.assertEqual(result["state"], "PASS-OFFLINE-BLOCKED-CANDIDATE")
        self.assertFalse(result["liveMutationAuthorized"])

    def test_grant_bit_fails_closed(self):
        value = yaml.safe_load(verifier.CANDIDATE.read_text())
        value["spec"]["authorization"]["automaticReconciliationAcknowledged"] = True
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "candidate.yaml"
            path.write_text(yaml.safe_dump(value, sort_keys=False))
            with self.assertRaisesRegex(ValueError, "grants authority"):
                verifier.verify(path)

    def test_explicit_sync_fails_closed(self):
        value = yaml.safe_load(verifier.CANDIDATE.read_text())
        value["spec"]["operation"]["explicitApplicationOperationSubmission"] = True
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "candidate.yaml"
            path.write_text(yaml.safe_dump(value, sort_keys=False))
            with self.assertRaisesRegex(ValueError, "explicit sync"):
                verifier.verify(path)


if __name__ == "__main__":
    unittest.main()
