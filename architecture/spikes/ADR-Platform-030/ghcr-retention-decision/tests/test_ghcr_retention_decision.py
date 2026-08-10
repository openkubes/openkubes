import copy
import importlib.util
import sys
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("ghcr_retention_decision_test", HERE / "verify_ghcr_retention_decision.py")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class GHCRRetentionDecisionTests(unittest.TestCase):
    def setUp(self):
        self.path = HERE / "ghcr-retention-decision-v1.yaml"
        self.decision = MODULE.V1.read_yaml_or_json(self.path)

    def assert_rejected(self, changed):
        with self.assertRaises(MODULE.V1.HarnessError):
            MODULE.validate(changed, self.path)

    def test_decision_and_source_verify(self):
        self.assertTrue(MODULE.validate(self.decision, self.path).startswith("sha256:"))

    def test_any_write_or_gate_fails_closed(self):
        for field in ("externalWriteAuthorized", "packageCreationAuthorized", "environmentCreationAuthorized", "workflowDeploymentAuthorized", "credentialMutationAuthorized", "infrastructureMutationAuthorized", "m0aInstallationGranted", "m0bInstallationGranted", "go1Granted"):
            changed = copy.deepcopy(self.decision)
            changed["spec"]["authorization"][field] = True
            with self.subTest(field=field):
                self.assert_rejected(changed)

    def test_statement_and_principal_are_bound(self):
        changed = copy.deepcopy(self.decision)
        changed["spec"]["decision"]["statement"] += " Extra"
        self.assert_rejected(changed)
        changed = copy.deepcopy(self.decision)
        changed["spec"]["decision"]["acceptedBy"] = "github:someone-else"
        self.assert_rejected(changed)

    def test_minimum_retention_cannot_be_shortened(self):
        changed = copy.deepcopy(self.decision)
        changed["spec"]["retentionPolicy"]["minimumRetentionDaysAfterOK141Closure"] = 89
        self.assert_rejected(changed)

    def test_worm_availability_and_restore_cannot_be_overstated(self):
        for field, value in (("immutabilityClaim", "WORM"), ("availabilityClaim", "GUARANTEED"), ("restoreGuaranteed", True), ("administratorDeletionPossible", False)):
            changed = copy.deepcopy(self.decision)
            changed["spec"]["retentionPolicy"][field] = value
            with self.subTest(field=field):
                self.assert_rejected(changed)

    def test_monitoring_cannot_be_preimplemented_or_prescheduled(self):
        changed = copy.deepcopy(self.decision)
        changed["spec"]["deletionMonitoring"]["status"] = "IMPLEMENTED"
        self.assert_rejected(changed)
        changed = copy.deepcopy(self.decision)
        changed["spec"]["deletionMonitoring"]["interval"] = "PT1H"
        self.assert_rejected(changed)

    def test_monitoring_cannot_gain_mutation_authority(self):
        for field in ("automaticRepairAllowed", "automaticRepublishAllowed", "deletePermissionAllowed"):
            changed = copy.deepcopy(self.decision)
            changed["spec"]["deletionMonitoring"][field] = True
            with self.subTest(field=field):
                self.assert_rejected(changed)

    def test_operational_state_cannot_be_preclosed(self):
        for field in self.decision["spec"]["operationalState"]:
            changed = copy.deepcopy(self.decision)
            changed["spec"]["operationalState"][field] = True
            with self.subTest(field=field):
                self.assert_rejected(changed)

    def test_expiry_cannot_allow_early_or_mandatory_deletion(self):
        changed = copy.deepcopy(self.decision)
        changed["spec"]["expirySemantics"]["earlyDeletionAllowed"] = True
        self.assert_rejected(changed)
        changed = copy.deepcopy(self.decision)
        changed["spec"]["expirySemantics"]["deletionAtExpiryRequired"] = True
        self.assert_rejected(changed)

    def test_source_digest_tampering_fails_closed(self):
        changed = copy.deepcopy(self.decision)
        changed["spec"]["sourcePreflight"]["digest"] = "sha256:" + "0" * 64
        self.assert_rejected(changed)


if __name__ == "__main__":
    unittest.main()
