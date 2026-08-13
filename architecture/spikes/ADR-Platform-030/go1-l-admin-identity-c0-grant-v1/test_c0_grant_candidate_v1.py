import copy
import importlib.util
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("c0_grant_candidate_test", HERE / "verify_c0_grant_candidate_v1.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class C0GrantCandidateTests(unittest.TestCase):
    def setUp(self):
        self.document = MODULE.V1.read_yaml_or_json(MODULE.CANDIDATE)

    def assert_rejected(self, changed):
        with self.assertRaises(MODULE.GrantCandidateError):
            MODULE.validate(changed)

    def test_candidate_reproduces_without_authority(self):
        self.assertTrue(MODULE.validate(self.document).startswith("sha256:"))

    def test_window_must_be_exactly_ten_minutes(self):
        changed = copy.deepcopy(self.document)
        changed["spec"]["requestedGrant"]["expiresAt"] = "2026-08-13T16:11:00Z"
        self.assert_rejected(changed)

    def test_grant_identity_is_bound(self):
        changed = copy.deepcopy(self.document)
        changed["spec"]["requestedGrant"]["grantID"] = "ok141-c0-unbound"
        self.assert_rejected(changed)

    def test_cluster_contact_or_mutation_fails(self):
        for key in ("kubectlOrKubernetesClientAllowed", "networkDNSOrTCPContactAllowed", "preflightOrSubmissionAllowed", "mutationAllowed"):
            changed = copy.deepcopy(self.document)
            changed["spec"]["executionBoundary"][key] = True
            with self.subTest(key=key):
                self.assert_rejected(changed)

    def test_candidate_cannot_self_authorize(self):
        for key in ("c0Granted", "credentialInspectionGranted", "clusterContactGranted", "preflightGranted", "submissionGranted", "go1LGranted", "go1Granted"):
            changed = copy.deepcopy(self.document)
            changed["spec"]["authorization"][key] = True
            with self.subTest(key=key):
                self.assert_rejected(changed)

    def test_execution_claim_fails(self):
        for key in ("credentialInspected", "clusterContacted", "mutationAuthorized"):
            changed = copy.deepcopy(self.document)
            changed["spec"]["conclusions"][key] = True
            with self.subTest(key=key):
                self.assert_rejected(changed)


if __name__ == "__main__":
    unittest.main()
