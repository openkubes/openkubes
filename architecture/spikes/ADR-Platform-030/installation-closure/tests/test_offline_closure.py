import copy
import importlib.util
import sys
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "offline_closure_test", HERE / "verify_offline_closure.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class OfflineClosureTests(unittest.TestCase):
    def setUp(self):
        self.path = HERE / "offline-closure-results-v1.yaml"
        self.document = MODULE.V1.read_yaml_or_json(self.path)

    def test_complete_offline_evaluation_verifies(self):
        digest = MODULE.validate(self.document, self.path)
        self.assertTrue(digest.startswith("sha256:"))

    def test_authorization_or_mutation_is_rejected(self):
        for field, value in (
            ("decision", "GO"),
            ("mutationAuthorized", True),
            ("m0aInstallationGranted", True),
            ("m0bInstallationGranted", True),
            ("go1Granted", True),
        ):
            with self.subTest(field=field):
                changed = copy.deepcopy(self.document)
                changed["spec"]["authorization"][field] = value
                with self.assertRaises(MODULE.INSTALLER.InstallerError):
                    MODULE.validate(changed, self.path)

    def test_missing_result_is_rejected(self):
        changed = copy.deepcopy(self.document)
        changed["spec"]["results"].pop()
        with self.assertRaises((MODULE.INSTALLER.InstallerError, ValueError)):
            MODULE.validate(changed, self.path)

    def test_caaph_partial_result_cannot_be_overclaimed(self):
        changed = copy.deepcopy(self.document)
        result = next(
            item
            for item in changed["spec"]["results"]
            if item["id"] == "M0AI-COMPATIBILITY-EVIDENCE"
        )
        result["result"] = "PROVEN-OFFLINE"
        with self.assertRaises(MODULE.INSTALLER.InstallerError):
            MODULE.validate(changed, self.path)

    def test_repeatable_materialization_cannot_be_claimed_permanent(self):
        changed = copy.deepcopy(self.document)
        result = next(
            item
            for item in changed["spec"]["results"]
            if item["id"] == "M0BI-SOURCE-MATERIALIZATION-VERIFY"
        )
        result["result"] = "PROVEN-OFFLINE"
        with self.assertRaises(MODULE.INSTALLER.InstallerError):
            MODULE.validate(changed, self.path)

    def test_atomic_results_cannot_close_source_blocker(self):
        changed = copy.deepcopy(self.document)
        changed["spec"]["summary"]["sourceBlockersClosed"] = 1
        with self.assertRaises(MODULE.INSTALLER.InstallerError):
            MODULE.validate(changed, self.path)

    def test_artifact_digest_tampering_is_rejected(self):
        changed = copy.deepcopy(self.document)
        changed["spec"]["artifacts"]["boundedInstaller"]["digest"] = "sha256:" + "0" * 64
        with self.assertRaises(MODULE.INSTALLER.InstallerError):
            MODULE.validate(changed, self.path)

    def test_unknown_evidence_reference_is_rejected(self):
        changed = copy.deepcopy(self.document)
        changed["spec"]["results"][0]["evidence"] = ["missing"]
        with self.assertRaises(MODULE.INSTALLER.InstallerError):
            MODULE.validate(changed, self.path)

    def test_current_protocol_remains_no_go(self):
        protocol_path = HERE.parent / "m0a-installation" / "m0a-installation-v1.yaml"
        protocol = MODULE.V1.read_yaml_or_json(protocol_path)
        reviewed = MODULE.INSTALLER.verify_reviewed_object_set(protocol, protocol_path)
        with self.assertRaises(MODULE.INSTALLER.InstallerError):
            MODULE.INSTALLER._authorization_plan(protocol, protocol_path, reviewed)


if __name__ == "__main__":
    unittest.main()
