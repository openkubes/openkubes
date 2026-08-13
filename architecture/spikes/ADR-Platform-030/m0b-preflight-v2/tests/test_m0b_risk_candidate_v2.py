from __future__ import annotations

import copy
import importlib.util
import tempfile
import unittest
from pathlib import Path

import yaml


HERE = Path(__file__).resolve().parent
MODULE_PATH = HERE.parent / "verify_m0b_risk_candidate_v2.py"
SPEC = importlib.util.spec_from_file_location("verify_m0b_risk_candidate_v2", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class M0bRiskCandidateV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.document = yaml.safe_load(MODULE.CANDIDATE.read_text())

    def verify_modified(self, document: dict) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "risk.yaml"
            path.write_text(yaml.safe_dump(document, sort_keys=False))
            with self.assertRaises(MODULE.VerificationError):
                MODULE.verify(path)

    def test_candidate_verifies(self) -> None:
        self.assertTrue(MODULE.verify().startswith("sha256:"))

    def test_missing_risk_fails_closed(self) -> None:
        changed = copy.deepcopy(self.document)
        changed["spec"]["acceptanceText"] = "Ich akzeptiere den Kandidaten."
        self.verify_modified(changed)

    def test_candidate_cannot_record_acceptance(self) -> None:
        changed = copy.deepcopy(self.document)
        changed["spec"]["decision"]["accepted"] = True
        self.verify_modified(changed)

    def test_candidate_cannot_grant_installation(self) -> None:
        changed = copy.deepcopy(self.document)
        changed["spec"]["effects"]["grantsM0bInstallation"] = True
        self.verify_modified(changed)


if __name__ == "__main__":
    unittest.main()
