#!/usr/bin/env python3
"""Fail-closed mutations for the redacted closure."""

from __future__ import annotations

import copy
import json
import unittest

from verify_closure_v1 import CANDIDATE, CLOSURE, ClosureVerificationError, verify_closure


class ClosureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.candidate = json.loads(CANDIDATE.read_text())
        self.closure = json.loads(CLOSURE.read_text())

    def test_closure(self) -> None:
        self.assertEqual(verify_closure(self.closure, self.candidate), self.closure["evidenceDigest"])

    def test_critical_mutations_fail_closed(self) -> None:
        mutations = {
            "snapshot_changed": lambda value: value.__setitem__("afterSnapshotDigest", "sha256:" + "0" * 64),
            "mutation_reported": lambda value: value.__setitem__("clusterMutationPerformed", True),
            "wrong_r_accepted": lambda value: value["terminalReplay"].__setitem__("wrongRRejected", False),
            "replay_next": lambda value: value["terminalReplay"].__setitem__("state", "NEXT"),
            "mutation_allowed": lambda value: value["terminalReplay"].__setitem__("mutationAllowed", True),
            "node_not_ready": lambda value: value["health"].__setitem__("nodesReady", 1),
            "cilium_not_ready": lambda value: value["health"].__setitem__("ciliumReady", 1),
            "credential_retained": lambda value: value.__setitem__("credentialContentRetained", True),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                changed = copy.deepcopy(self.closure)
                mutate(changed)
                with self.assertRaises(ClosureVerificationError):
                    verify_closure(changed, self.candidate)


if __name__ == "__main__":
    unittest.main()
