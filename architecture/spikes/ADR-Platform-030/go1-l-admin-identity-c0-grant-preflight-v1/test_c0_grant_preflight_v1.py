import copy
import importlib.util
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("c0_grant_preflight_test", HERE / "verify_c0_grant_preflight_v1.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class C0GrantPreflightTests(unittest.TestCase):
    def setUp(self):
        self.document = MODULE.V1.read_yaml_or_json(MODULE.PREFLIGHT)

    def assert_rejected(self, changed):
        with self.assertRaises(MODULE.GrantPreflightError):
            MODULE.validate(changed)

    def test_preflight_reproduces_without_authority(self):
        self.assertTrue(MODULE.validate(self.document).startswith("sha256:"))

    def test_window_cannot_be_partially_resolved(self):
        changed = copy.deepcopy(self.document)
        changed["spec"]["requestedAuthority"]["windowStart"] = "2026-08-14T08:00:00Z"
        self.assert_rejected(changed)

    def test_grant_template_cannot_be_finalized_here(self):
        changed = copy.deepcopy(self.document)
        changed["spec"]["runtimeGrantTemplate"]["grantID"] = "ok141-c0-unauthorized"
        self.assert_rejected(changed)

    def test_cluster_contact_or_mutation_fails(self):
        for key in ("kubectlOrKubernetesClientAllowed", "networkDNSOrTCPContactAllowed", "preflightOrSubmissionAllowed", "mutationAllowed"):
            changed = copy.deepcopy(self.document)
            changed["spec"]["executionBoundary"][key] = True
            with self.subTest(key=key):
                self.assert_rejected(changed)

    def test_any_authorization_fails(self):
        for key in ("c0Granted", "credentialInspectionGranted", "preflightGranted", "submissionGranted", "go1LGranted", "go1Granted"):
            changed = copy.deepcopy(self.document)
            changed["spec"]["authorization"][key] = True
            with self.subTest(key=key):
                self.assert_rejected(changed)

    def test_readiness_or_execution_claim_fails(self):
        for key in ("windowResolved", "grantCandidateComplete", "c0ReadyForDecision", "credentialInspected", "clusterContacted", "mutationAuthorized"):
            changed = copy.deepcopy(self.document)
            changed["spec"]["conclusions"][key] = True
            with self.subTest(key=key):
                self.assert_rejected(changed)


if __name__ == "__main__":
    unittest.main()
