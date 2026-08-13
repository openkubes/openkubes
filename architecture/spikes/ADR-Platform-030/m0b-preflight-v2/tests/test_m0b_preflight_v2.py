from __future__ import annotations

import copy
import importlib.util
import tempfile
import unittest
from pathlib import Path

import yaml


HERE = Path(__file__).resolve().parent
MODULE_PATH = HERE.parent / "verify_m0b_preflight_v2.py"
SPEC = importlib.util.spec_from_file_location("verify_m0b_preflight_v2", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class M0bPreflightV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.document = yaml.safe_load(MODULE.PREFLIGHT.read_text())

    def verify_modified(self, document: dict) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "preflight.yaml"
            path.write_text(yaml.safe_dump(document, sort_keys=False))
            with self.assertRaises(MODULE.VerificationError):
                MODULE.verify(path)

    def test_checkpoint_verifies(self) -> None:
        self.assertTrue(MODULE.verify().startswith("sha256:"))

    def test_ha_profile_fails_closed(self) -> None:
        changed = copy.deepcopy(self.document)
        changed["spec"]["candidate"]["installationProfile"] = "ha-namespace-install"
        self.verify_modified(changed)

    def test_missing_namespace_transport_fails_closed(self) -> None:
        changed = copy.deepcopy(self.document)
        changed["spec"]["candidate"]["futureTransportPrefix"] = ["kubectl", "apply"]
        self.verify_modified(changed)

    def test_local_self_management_fails_closed(self) -> None:
        changed = copy.deepcopy(self.document)
        changed["spec"]["acceptedBoundaries"]["selfManagementAllowed"] = True
        self.verify_modified(changed)

    def test_changed_incarnation_fails_closed(self) -> None:
        changed = copy.deepcopy(self.document)
        changed["spec"]["liveTarget"]["kubeSystemNamespaceUID"] = "replacement"
        self.verify_modified(changed)

    def test_grant_fails_closed(self) -> None:
        changed = copy.deepcopy(self.document)
        changed["spec"]["authorization"]["m0bInstallationGranted"] = True
        self.verify_modified(changed)

    def test_rbac_understatement_fails_closed(self) -> None:
        changed = copy.deepcopy(self.document)
        changed["spec"]["rbacObservation"]["findings"]["SECRET-WRITE"] = 0
        self.verify_modified(changed)


if __name__ == "__main__":
    unittest.main()
