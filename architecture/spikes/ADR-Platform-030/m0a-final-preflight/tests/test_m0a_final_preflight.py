from __future__ import annotations

import copy
import importlib.util
import unittest
from pathlib import Path

import yaml


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SPEC = importlib.util.spec_from_file_location("verify_m0a_final_preflight", ROOT / "verify_m0a_final_preflight.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


class M0aFinalPreflightTests(unittest.TestCase):
    def setUp(self) -> None:
        self.path = ROOT / "m0a-final-preflight-v1.yaml"
        self.document = yaml.safe_load(self.path.read_text())

    def test_canonical_preflight_verifies(self) -> None:
        self.assertTrue(MODULE.verify(self.path).startswith("sha256:"))

    def test_mutation_authorization_fails_closed(self) -> None:
        changed = copy.deepcopy(self.document)
        changed["spec"]["authorization"]["mutationAuthorized"] = True
        temporary = ROOT / ".test-mutated.yaml"
        temporary.write_text(yaml.safe_dump(changed, sort_keys=False))
        try:
            with self.assertRaises(MODULE.VerificationError):
                MODULE.verify(temporary)
        finally:
            temporary.unlink(missing_ok=True)

    def test_accepting_admin_credential_fails_closed(self) -> None:
        changed = copy.deepcopy(self.document)
        changed["spec"]["currentCredential"]["acceptedForInstallation"] = True
        temporary = ROOT / ".test-credential.yaml"
        temporary.write_text(yaml.safe_dump(changed, sort_keys=False))
        try:
            with self.assertRaises(MODULE.VerificationError):
                MODULE.verify(temporary)
        finally:
            temporary.unlink(missing_ok=True)

    def test_closed_decision_fails_closed(self) -> None:
        changed = copy.deepcopy(self.document)
        changed["spec"]["explicitDecisionsRequired"][0]["state"] = "ACCEPTED"
        temporary = ROOT / ".test-decision.yaml"
        temporary.write_text(yaml.safe_dump(changed, sort_keys=False))
        try:
            with self.assertRaises(MODULE.VerificationError):
                MODULE.verify(temporary)
        finally:
            temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
