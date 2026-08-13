import copy
import importlib.util
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("admin_risk_test", HERE / "verify_go1_l_admin_risk_v1.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class AdminRiskTests(unittest.TestCase):
    def setUp(self):
        self.candidate = MODULE.V1.read_yaml_or_json(MODULE.CANDIDATE)

    def assert_rejected(self, changed):
        with self.assertRaises(MODULE.RiskError):
            MODULE.validate(changed)

    def test_candidate_reproduces_without_acceptance_or_authority(self):
        self.assertTrue(MODULE.validate(self.candidate).startswith("sha256:"))

    def test_missing_risk_fails_closed(self):
        changed = copy.deepcopy(self.candidate)
        changed["spec"]["riskClaims"].pop("absenceCreateRace")
        self.assert_rejected(changed)

    def test_residual_risk_cannot_be_hidden(self):
        changed = copy.deepcopy(self.candidate)
        changed["spec"]["riskClaims"]["administratorAuthority"]["residualRisk"] = "NONE"
        self.assert_rejected(changed)

    def test_acceptance_cannot_be_preclaimed(self):
        changed = copy.deepcopy(self.candidate)
        changed["spec"]["requiredAcceptance"]["accepted"] = True
        self.assert_rejected(changed)

    def test_acceptance_statement_cannot_grant_execution(self):
        changed = copy.deepcopy(self.candidate)
        changed["spec"]["requiredAcceptance"]["exactStatement"] = "GO1-L ist erteilt"
        self.assert_rejected(changed)

    def test_any_grant_fails_closed(self):
        for key in ("credentialUseGranted", "preflightGranted", "submissionGranted", "retryGranted", "rollbackOrCleanupGranted", "go1LGranted", "go1Granted", "failureInjectionGranted"):
            changed = copy.deepcopy(self.candidate)
            changed["spec"]["authorization"][key] = True
            with self.subTest(key=key):
                self.assert_rejected(changed)

    def test_ready_or_mutation_conclusion_fails(self):
        for key in ("riskAcceptanceComplete", "credentialUseReadyForDecision", "go1LReadyForDecision", "clusterContacted", "mutationAuthorized"):
            changed = copy.deepcopy(self.candidate)
            changed["spec"]["conclusions"][key] = True
            with self.subTest(key=key):
                self.assert_rejected(changed)


if __name__ == "__main__":
    unittest.main()
