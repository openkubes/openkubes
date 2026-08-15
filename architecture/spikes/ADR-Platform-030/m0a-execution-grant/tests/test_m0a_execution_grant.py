from __future__ import annotations

import copy
import importlib.util
import unittest
from pathlib import Path

import yaml


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SPEC = importlib.util.spec_from_file_location("verify_m0a_execution_grant", ROOT / "verify_m0a_execution_grant.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


class ExecutionGrantTests(unittest.TestCase):
    def setUp(self) -> None:
        self.path = ROOT / "m0a-combined-grant-v1.yaml"
        self.document = yaml.safe_load(self.path.read_text())

    def mutate_and_fail(self, update) -> None:
        changed = copy.deepcopy(self.document)
        update(changed)
        temporary = ROOT / ".test-mutated.yaml"
        temporary.write_text(yaml.safe_dump(changed, sort_keys=False))
        try:
            with self.assertRaises((MODULE.VerificationError, MODULE.EXECUTION.ExecutionError)):
                MODULE.verify(temporary)
        finally:
            temporary.unlink(missing_ok=True)

    def test_canonical_grant_verifies(self) -> None:
        self.assertTrue(MODULE.verify(self.path).startswith("sha256:"))

    def test_publication_scope_fails_closed(self) -> None:
        self.mutate_and_fail(lambda d: d["spec"].update({"evidencePublicationGranted": True}))

    def test_candidate_digest_fails_closed(self) -> None:
        self.mutate_and_fail(lambda d: d["spec"].update({"candidateDigest": "sha256:" + "0" * 64}))


if __name__ == "__main__":
    unittest.main()
