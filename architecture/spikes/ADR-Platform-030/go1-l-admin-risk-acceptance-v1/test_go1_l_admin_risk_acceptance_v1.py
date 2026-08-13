import copy
import importlib.util
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("admin_risk_acceptance_test", HERE / "verify_go1_l_admin_risk_acceptance_v1.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class AdminRiskAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.document = MODULE.V1.read_yaml_or_json(MODULE.ACCEPTANCE)

    def assert_rejected(self, changed):
        with self.assertRaises(MODULE.AcceptanceError):
            MODULE.validate(changed)

    def test_acceptance_reproduces_without_authority(self):
        self.assertTrue(MODULE.validate(self.document).startswith("sha256:"))

    def test_candidate_digest_tampering_fails(self):
        changed = copy.deepcopy(self.document)
        changed["spec"]["acceptance"]["acceptedCandidateDigest"] = "sha256:" + "0" * 64
        self.assert_rejected(changed)

    def test_statement_tampering_fails(self):
        changed = copy.deepcopy(self.document)
        changed["spec"]["acceptance"]["exactStatement"] += " GO"
        self.assert_rejected(changed)

    def test_any_grant_fails(self):
        for key in ("credentialUseGranted", "preflightGranted", "submissionGranted", "retryGranted", "rollbackOrCleanupGranted", "go1LGranted", "go1Granted", "failureInjectionGranted"):
            changed = copy.deepcopy(self.document)
            changed["spec"]["authorization"][key] = True
            with self.subTest(key=key):
                self.assert_rejected(changed)

    def test_runtime_readiness_cannot_be_preclaimed(self):
        for key in ("credentialIdentityResolved", "runtimeGrantCandidatesComplete", "credentialUseReadyForDecision", "go1LReadyForDecision", "clusterContacted", "mutationAuthorized"):
            changed = copy.deepcopy(self.document)
            changed["spec"]["conclusions"][key] = True
            with self.subTest(key=key):
                self.assert_rejected(changed)


if __name__ == "__main__":
    unittest.main()
