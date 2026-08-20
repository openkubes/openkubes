#!/usr/bin/env python3

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from verify_delete_longhorn_correlation_closure_v1 import ClosureError, canonical_digest, digest, verify_closure


HERE = Path(__file__).resolve().parent
CLOSURE = HERE / "delete-longhorn-correlation-closure-evidence-v1.yaml"


class LonghornCorrelationClosureTest(unittest.TestCase):
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
        self.assertEqual("PASS-READ-ONLY-DIAGNOSTIC-NO-GO", verify_closure(CLOSURE)["spec"]["state"])

    def test_count_change_fails(self) -> None:
        path = self.changed(lambda value: value["spec"]["observation"].update(providerPVCount=1))
        with self.assertRaisesRegex(ClosureError, "PV count"):
            verify_closure(path)

    def test_root_cause_is_not_overclaimed(self) -> None:
        path = self.changed(lambda value: value["spec"]["conclusions"].update(exactEarlierZeroCause="PROVEN"))
        with self.assertRaisesRegex(ClosureError, "overclaims"):
            verify_closure(path)

    def test_delete_authority_fails(self) -> None:
        path = self.changed(lambda value: value["spec"]["authorization"].update(deleteGranted=True))
        with self.assertRaisesRegex(ClosureError, "grants authority"):
            verify_closure(path)

    def test_publication_candidate_is_bound(self) -> None:
        publication = yaml.safe_load((HERE / "delete-longhorn-correlation-closure-publication-candidate-v1.yaml").read_text())["spec"]
        closure = yaml.safe_load(CLOSURE.read_text())
        self.assertEqual(digest(CLOSURE), publication["bindings"]["closureFileDigest"])
        self.assertEqual(canonical_digest(closure), publication["bindings"]["closureSemanticDigest"])
        self.assertEqual(5, publication["bindings"]["offlineTestsPassed"])
        self.assertFalse(any(value for key, value in publication["authorization"].items() if key.endswith("Granted")))


if __name__ == "__main__":
    unittest.main()
