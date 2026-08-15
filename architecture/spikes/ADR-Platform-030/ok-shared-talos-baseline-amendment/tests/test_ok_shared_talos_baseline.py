from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest

import yaml


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("baseline", HERE / "verify_ok_shared_talos_baseline.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class BaselineTest(unittest.TestCase):
    def test_checkpoint_passes(self) -> None:
        self.assertTrue(MODULE.verify().startswith("sha256:"))

    def _verify_changed(self, changed: dict) -> str:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = root / MODULE.RECORD.name
            digest = root / MODULE.DIGEST.name
            raw = yaml.safe_dump(changed, sort_keys=False).encode()
            record.write_bytes(raw)
            import hashlib
            digest.write_text("sha256:" + hashlib.sha256(raw).hexdigest() + "\n", encoding="utf-8")
            old_record, old_digest = MODULE.RECORD, MODULE.DIGEST
            MODULE.RECORD, MODULE.DIGEST = record, digest
            try:
                with self.assertRaises(MODULE.VerificationError) as error:
                    MODULE.verify()
                return str(error.exception)
            finally:
                MODULE.RECORD, MODULE.DIGEST = old_record, old_digest

    def test_mutation_grant_fails_closed(self) -> None:
        changed = copy.deepcopy(yaml.safe_load(MODULE.RECORD.read_text()))
        changed["spec"]["authorization"]["mutationAuthorized"] = True
        self.assertIn("mutationAuthorized", self._verify_changed(changed))

    def test_replacement_inheritance_claim_fails_closed(self) -> None:
        changed = copy.deepcopy(yaml.safe_load(MODULE.RECORD.read_text()))
        changed["spec"]["recovery"]["replacementMachineInheritance"] = "AUTOMATIC"
        self.assertIn("replacement inheritance", self._verify_changed(changed))

    def test_jira_report_cannot_be_promoted_to_live_observation(self) -> None:
        changed = copy.deepcopy(yaml.safe_load(MODULE.RECORD.read_text()))
        changed["spec"]["source"]["jira"]["independentlyReobservedByOk141"] = True
        self.assertIn("live observation boundary", self._verify_changed(changed))

    def test_ok_shared_self_management_fails_closed(self) -> None:
        changed = copy.deepcopy(yaml.safe_load(MODULE.RECORD.read_text()))
        changed["spec"]["ok141Impact"]["okSharedSelfManagementAllowed"] = True
        self.assertIn("self-management boundary", self._verify_changed(changed))


if __name__ == "__main__":
    unittest.main()
