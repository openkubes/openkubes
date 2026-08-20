#!/usr/bin/env python3

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from verify_delete_d0_v3_closure import ClosureError, canonical_digest, digest, verify_closure


HERE = Path(__file__).resolve().parent
CLOSURE = HERE / "delete-d0-v3-closure-evidence.yaml"


class DeleteD0V3ClosureTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def changed(self, mutate) -> Path:
        value = yaml.safe_load(CLOSURE.read_text())
        mutate(value)
        path = Path(self.temp.name) / "closure.yaml"
        path.write_text(yaml.safe_dump(value, sort_keys=False))
        return path

    def test_closure_passes(self) -> None:
        self.assertEqual("PASS-D0-V3-PRIVATE-BOUND-NO-GO", verify_closure(CLOSURE)["spec"]["state"])

    def test_count_change_fails(self) -> None:
        path = self.changed(lambda value: value["spec"]["observation"]["retainedObjectCounts"].update(workload=10))
        with self.assertRaisesRegex(ClosureError, "counts"):
            verify_closure(path)

    def test_binding_lifetime_change_fails(self) -> None:
        path = self.changed(lambda value: value["spec"]["observation"].update(bindingLifetimeSeconds=601))
        with self.assertRaisesRegex(ClosureError, "lifetime"):
            verify_closure(path)

    def test_delete_authority_fails(self) -> None:
        path = self.changed(lambda value: value["spec"]["authorization"].update(deleteGranted=True))
        with self.assertRaisesRegex(ClosureError, "grants authority"):
            verify_closure(path)

    def test_d5_reuse_claim_fails(self) -> None:
        path = self.changed(lambda value: value["spec"]["conclusions"].update(bindingReusableForD5=True))
        with self.assertRaisesRegex(ClosureError, "conclusion"):
            verify_closure(path)

    def test_publication_candidate_is_bound(self) -> None:
        publication = yaml.safe_load((HERE / "delete-d0-v3-closure-publication-candidate.yaml").read_text())["spec"]
        closure = yaml.safe_load(CLOSURE.read_text())
        self.assertEqual(digest(CLOSURE), publication["bindings"]["closureFileDigest"])
        self.assertEqual(canonical_digest(closure), publication["bindings"]["closureSemanticDigest"])
        self.assertEqual(6, publication["bindings"]["offlineTestsPassed"])
        self.assertFalse(any(value for key, value in publication["authorization"].items() if key.endswith("Granted")))


if __name__ == "__main__":
    unittest.main()
