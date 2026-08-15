from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("ok141_verify_m0b_v2_runtime_closure_test", HERE / "verify_m0b_v2_runtime_closure.py")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class M0bV2RuntimeClosureTests(unittest.TestCase):
    def test_redacted_checkpoint_verifies_without_raw_files(self) -> None:
        self.assertEqual(MODULE.verify(), MODULE.FILES["m0b-v2-runtime-closure-v1.yaml"])

    def test_local_raw_evidence_verifies(self) -> None:
        self.assertEqual(MODULE.verify(with_raw=True), MODULE.FILES["m0b-v2-runtime-closure-v1.yaml"])


if __name__ == "__main__":
    unittest.main()
