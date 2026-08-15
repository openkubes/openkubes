from __future__ import annotations

import copy
import importlib.util
import tempfile
import unittest
from pathlib import Path

import yaml


HERE = Path(__file__).resolve().parent
MODULE_PATH = HERE.parent / "verify_m0b_security_v2.py"
SPEC = importlib.util.spec_from_file_location("verify_m0b_security_v2", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class M0bSecurityV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.document = yaml.safe_load(MODULE.CANDIDATE.read_text())

    def verify_modified(self, document: dict) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "candidate.yaml"
            path.write_text(yaml.safe_dump(document, sort_keys=False))
            with self.assertRaises(MODULE.VerificationError):
                MODULE.verify(path)

    def test_candidate_verifies(self) -> None:
        self.assertTrue(MODULE.verify().startswith("sha256:"))

    def test_apply_is_rejected(self) -> None:
        changed = copy.deepcopy(self.document)
        changed["spec"]["submissionModel"]["serverSideApplyAllowed"] = True
        self.verify_modified(changed)

    def test_namespace_change_is_rejected(self) -> None:
        changed = copy.deepcopy(self.document)
        changed["spec"]["submissionModel"]["phase2"]["targetNamespace"] = "default"
        self.verify_modified(changed)

    def test_partial_risk_cannot_be_removed(self) -> None:
        changed = copy.deepcopy(self.document)
        changed["spec"]["risksRequiringAcceptance"] = changed["spec"]["risksRequiringAcceptance"][:-1]
        self.verify_modified(changed)

    def test_controller_secret_write_cannot_be_hidden(self) -> None:
        changed = copy.deepcopy(self.document)
        changed["spec"]["controllerBoundary"]["findings"]["SECRET-WRITE"] = 0
        self.verify_modified(changed)

    def test_candidate_cannot_self_authorize(self) -> None:
        changed = copy.deepcopy(self.document)
        changed["spec"]["authorization"]["securityRiskAccepted"] = True
        self.verify_modified(changed)


if __name__ == "__main__":
    unittest.main()
