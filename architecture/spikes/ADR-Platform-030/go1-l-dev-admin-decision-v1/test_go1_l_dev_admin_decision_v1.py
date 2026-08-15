import copy
import importlib.util
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("dev_admin_decision_test", HERE / "verify_go1_l_dev_admin_decision_v1.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class DevAdminDecisionTests(unittest.TestCase):
    def setUp(self):
        self.decision = MODULE.V1.read_yaml_or_json(MODULE.DECISION)

    def assert_rejected(self, changed):
        with self.assertRaises(MODULE.DecisionError):
            MODULE.validate(changed)

    def test_selection_reproduces_without_authority(self):
        self.assertTrue(MODULE.validate(self.decision).startswith("sha256:"))

    def test_different_model_fails(self):
        changed = copy.deepcopy(self.decision)
        changed["spec"]["selection"]["model"] = "TEMPORARY-ADMISSION-PLUS-SCOPED-CREATE"
        self.assert_rejected(changed)

    def test_statement_tampering_fails(self):
        changed = copy.deepcopy(self.decision)
        changed["spec"]["selection"]["exactStatement"] += " GO"
        self.assert_rejected(changed)

    def test_execution_risk_cannot_be_preaccepted(self):
        changed = copy.deepcopy(self.decision)
        changed["spec"]["selection"]["executionRiskAccepted"] = True
        self.assert_rejected(changed)

    def test_credential_cannot_be_prebound(self):
        changed = copy.deepcopy(self.decision)
        changed["spec"]["futureCredentialRequirements"]["credentialMaterial"] = "admin.kubeconfig"
        self.assert_rejected(changed)

    def test_any_grant_fails(self):
        for key in ("credentialIssuanceGranted", "administratorCredentialUseGranted", "operationGrantIssued", "admissionInstallationGranted", "go1LGranted", "go1Granted", "retryGranted", "rollbackOrCleanupGranted", "failureInjectionGranted"):
            changed = copy.deepcopy(self.decision)
            changed["spec"]["authorization"][key] = True
            with self.subTest(key=key):
                self.assert_rejected(changed)

    def test_ready_conclusion_fails(self):
        for key in ("credentialMaterialReady", "submitterReadyForExecution", "go1LReadyForDecision", "infrastructureMutationAuthorized"):
            changed = copy.deepcopy(self.decision)
            changed["spec"]["conclusions"][key] = True
            with self.subTest(key=key):
                self.assert_rejected(changed)


if __name__ == "__main__":
    unittest.main()
