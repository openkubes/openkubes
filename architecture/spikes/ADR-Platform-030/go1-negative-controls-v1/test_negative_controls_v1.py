#!/usr/bin/env python3
"""Negative controls for the negative-control candidate itself."""

from __future__ import annotations

import copy
import json
import unittest

from verify_negative_controls_v1 import CANDIDATE, VerificationError, verify


class CandidateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.value = json.loads(CANDIDATE.read_text())

    def test_candidate(self) -> None:
        self.assertEqual(verify(self.value), self.value["candidateDigest"])

    def test_critical_mutations_fail_closed(self) -> None:
        mutations = {
            "wrong_r": lambda value: value["bindings"].__setitem__("R", "sha256:" + "0" * 64),
            "missing_receipt": lambda value: value["receiptPrefix"].pop(),
            "reordered_receipt": lambda value: value["receiptPrefix"].reverse(),
            "mutation_enabled": lambda value: value["liveBoundary"].__setitem__("mutationAllowed", True),
            "delete_allowed": lambda value: value["liveBoundary"]["allowedOperations"].append("DELETE"),
            "forbidden_removed": lambda value: value["liveBoundary"]["forbiddenOperations"].remove("DELETE"),
            "resume_not_terminal": lambda value: value["resumeProof"].__setitem__("state", "NEXT"),
            "test_failed": lambda value: value["implementation"].__setitem__("targetedTestResult", "FAIL"),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                changed = copy.deepcopy(self.value)
                mutate(changed)
                with self.assertRaises(VerificationError):
                    verify(changed)


if __name__ == "__main__":
    unittest.main()
