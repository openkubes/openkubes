#!/usr/bin/env python3

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from verify_delete_d0_live_grant_candidate_v3 import (
    CandidateError,
    canonical_digest,
    file_digest,
    verify_candidate,
)


HERE = Path(__file__).resolve().parent
CANDIDATE = HERE / "delete-d0-live-grant-candidate-v3.yaml"


class D0V3LiveGrantCandidateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def changed_candidate(self, change) -> Path:
        value = yaml.safe_load(CANDIDATE.read_text())
        change(value)
        path = Path(self.temp.name) / "candidate.yaml"
        path.write_text(yaml.safe_dump(value, sort_keys=False))
        return path

    def test_candidate_passes(self) -> None:
        verified = verify_candidate(CANDIDATE)
        self.assertEqual("NO-GO", verified["spec"]["authorization"]["decision"])

    def test_candidate_grants_nothing(self) -> None:
        path = self.changed_candidate(lambda value: value["spec"]["authorization"].update(liveReadGranted=True))
        with self.assertRaisesRegex(CandidateError, "grants authority"):
            verify_candidate(path)

    def test_candidate_has_no_live_window(self) -> None:
        def mutate(value):
            value["spec"]["requiredGrant"]["notBefore"] = "2026-08-20T16:00:00Z"
        with self.assertRaisesRegex(CandidateError, "live grant values"):
            verify_candidate(self.changed_candidate(mutate))

    def test_delete_authority_remains_required_false(self) -> None:
        def mutate(value):
            value["spec"]["requiredGrant"]["requiredFalse"].remove("deleteAuthorized")
        with self.assertRaisesRegex(CandidateError, "required false"):
            verify_candidate(self.changed_candidate(mutate))

    def test_query_count_change_fails(self) -> None:
        path = self.changed_candidate(lambda value: value["spec"]["scope"].update(sealedGetCount=35))
        with self.assertRaisesRegex(CandidateError, "GET count"):
            verify_candidate(path)

    def test_merged_d0_v3_candidate_is_digest_bound(self) -> None:
        verified = verify_candidate(CANDIDATE)
        bound = (HERE / verified["spec"]["bindings"]["d0CandidatePath"]).resolve()
        self.assertEqual(verified["spec"]["bindings"]["d0CandidateFileDigest"], file_digest(bound))

    def test_private_outputs_are_additive_v3_paths(self) -> None:
        verified = verify_candidate(CANDIDATE)
        outputs = verified["spec"]["privateOutputs"]
        self.assertEqual("/private/tmp/ok141-delete-d0-runtime-binding-v3.json", outputs["bindingPath"])
        self.assertEqual("/private/tmp/ok141-delete-d0-evidence-v3.json", outputs["evidencePath"])

    def test_binding_cannot_be_reused_for_d5(self) -> None:
        verified = verify_candidate(CANDIDATE)
        self.assertTrue(any("D5" in item for item in verified["spec"]["exclusions"]))

    def test_publication_candidate_is_bound_and_not_authorizing(self) -> None:
        publication = yaml.safe_load((HERE / "delete-d0-v3-live-grant-publication-candidate.yaml").read_text())["spec"]
        candidate = yaml.safe_load(CANDIDATE.read_text())
        self.assertEqual(file_digest(CANDIDATE), publication["bindings"]["candidateFileDigest"])
        self.assertEqual(canonical_digest(candidate), publication["bindings"]["candidateSemanticDigest"])
        self.assertEqual(9, publication["bindings"]["offlineTestsPassed"])
        self.assertFalse(any(value for key, value in publication["authorization"].items() if key.endswith("Granted")))


if __name__ == "__main__":
    unittest.main()
