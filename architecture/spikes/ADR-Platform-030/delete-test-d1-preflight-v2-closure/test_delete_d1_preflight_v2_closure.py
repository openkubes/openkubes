#!/usr/bin/env python3

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from verify_delete_d1_preflight_v2_closure import ClosureError, canonical_digest, digest, verify_closure


HERE = Path(__file__).resolve().parent
CLOSURE = HERE / "delete-d1-preflight-v2-closure-evidence.yaml"


class DeleteD1PreflightV2ClosureTest(unittest.TestCase):
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
        state = verify_closure(CLOSURE)["spec"]["state"]
        self.assertEqual("PASS-D1-V2-PREFLIGHT-PRIVATE-BOUND-NO-GO", state)

    def test_semantic_match_change_fails(self) -> None:
        path = self.changed(lambda value: value["spec"]["normalization"].update(semanticMatchCount=2))
        with self.assertRaisesRegex(ClosureError, "normalization"):
            verify_closure(path)

    def test_defaulting_change_fails(self) -> None:
        path = self.changed(lambda value: value["spec"]["normalization"]["defaultsApplied"].update({"spec.source.directory.recurse": True}))
        with self.assertRaisesRegex(ClosureError, "normalization"):
            verify_closure(path)

    def test_delete_authority_fails(self) -> None:
        path = self.changed(lambda value: value["spec"]["authorization"].update(deleteGranted=True))
        with self.assertRaisesRegex(ClosureError, "grants authority"):
            verify_closure(path)

    def test_preflight_mutation_claim_fails(self) -> None:
        path = self.changed(lambda value: value["spec"]["execution"].update(d1PreflightMutationPerformed=True))
        with self.assertRaisesRegex(ClosureError, "execution"):
            verify_closure(path)

    def test_refresh_binding_change_fails(self) -> None:
        path = self.changed(lambda value: value["spec"]["bindings"].update(registrationRefreshEvidenceDigest="sha256:bad"))
        with self.assertRaisesRegex(ClosureError, "binding"):
            verify_closure(path)

    def test_publication_candidate_is_bound(self) -> None:
        publication = yaml.safe_load((HERE / "delete-d1-preflight-v2-closure-publication-candidate.yaml").read_text())["spec"]
        closure = yaml.safe_load(CLOSURE.read_text())
        self.assertEqual(digest(CLOSURE), publication["bindings"]["closureFileDigest"])
        self.assertEqual(canonical_digest(closure), publication["bindings"]["closureSemanticDigest"])
        self.assertEqual(7, publication["bindings"]["offlineTestsPassed"])
        self.assertFalse(any(value for key, value in publication["authorization"].items() if key.endswith("Granted")))


if __name__ == "__main__":
    unittest.main()
