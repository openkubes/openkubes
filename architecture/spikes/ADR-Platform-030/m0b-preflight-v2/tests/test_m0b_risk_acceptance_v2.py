from __future__ import annotations

import copy
import importlib.util
import tempfile
import unittest
from pathlib import Path

import yaml


HERE = Path(__file__).resolve().parent
MODULE_PATH = HERE.parent / "verify_m0b_risk_acceptance_v2.py"
SPEC = importlib.util.spec_from_file_location("verify_m0b_risk_acceptance_v2", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class M0bRiskAcceptanceV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.document = yaml.safe_load(MODULE.ACCEPTANCE.read_text())

    def verify_modified(self, document: dict) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "acceptance.yaml"
            path.write_text(yaml.safe_dump(document, sort_keys=False))
            with self.assertRaises(MODULE.VerificationError):
                MODULE.verify(path)

    def test_acceptance_verifies(self) -> None:
        self.assertTrue(MODULE.verify().startswith("sha256:"))

    def test_text_change_fails_closed(self) -> None:
        changed = copy.deepcopy(self.document)
        changed["spec"]["decision"]["exactStatement"] += " erweitert"
        self.verify_modified(changed)

    def test_authority_change_fails_closed(self) -> None:
        changed = copy.deepcopy(self.document)
        changed["spec"]["decision"]["acceptedBy"] = "unknown"
        self.verify_modified(changed)

    def test_installation_grant_fails_closed(self) -> None:
        changed = copy.deepcopy(self.document)
        changed["spec"]["effects"]["grantsM0bInstallation"] = True
        self.verify_modified(changed)


if __name__ == "__main__":
    unittest.main()
