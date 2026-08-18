from __future__ import annotations

import json
import unittest

import generate_authorization_candidate_v1 as generator
import verify_authorization_candidate_v1 as verifier


class FreshAuthorizationCandidateTest(unittest.TestCase):
    def test_candidate_verifies(self) -> None:
        self.assertTrue(verifier.verify().startswith("sha256:"))

    def test_candidate_cannot_be_executed(self) -> None:
        candidate = json.loads(generator.OUTPUT.read_text())
        self.assertFalse(candidate["authorization"]["privateKeyMaterialized"])
        self.assertFalse(candidate["authorization"]["grantSigned"])
        self.assertFalse(candidate["authorization"]["mutationGranted"])
        self.assertTrue(candidate["unsignedGrantTemplate"]["signature"]["value"].startswith("RUNTIME-"))


if __name__ == "__main__":
    unittest.main()
