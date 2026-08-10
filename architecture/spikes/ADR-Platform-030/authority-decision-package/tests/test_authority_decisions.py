import copy
import importlib.util
import sys
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "authority_decisions_verify_test", HERE / "verify_authority_decisions.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class AuthorityDecisionTests(unittest.TestCase):
    def setUp(self):
        self.path = HERE / "authority-decisions-v1.yaml"
        self.package = MODULE.V1.read_yaml_or_json(self.path)

    def assert_rejected(self, changed):
        with self.assertRaises(MODULE.V1.HarnessError):
            MODULE.validate(changed, self.path)

    def test_undecided_package_and_sources_verify(self):
        self.assertTrue(MODULE.validate(self.package, self.path).startswith("sha256:"))

    def test_any_grant_or_mutation_fails_closed(self):
        for field in ("mutationAuthorized", "m0aInstallationGranted", "m0bInstallationGranted", "go1Granted"):
            changed = copy.deepcopy(self.package)
            changed["spec"]["authorization"][field] = True
            with self.subTest(field=field):
                self.assert_rejected(changed)

    def test_any_decision_outcome_fails_closed(self):
        for outcome in ("ACCEPT", "REJECT", "DEFER"):
            changed = copy.deepcopy(self.package)
            changed["spec"]["decisions"][0]["outcome"] = outcome
            with self.subTest(outcome=outcome):
                self.assert_rejected(changed)

    def test_authority_or_window_assignment_fails_closed(self):
        mutations = {"authority": "alice", "decidedAt": "2026-08-10T12:00:00Z", "validFrom": "2026-08-11T08:00:00Z", "validUntil": "2026-08-11T09:00:00Z"}
        for field, value in mutations.items():
            changed = copy.deepcopy(self.package)
            changed["spec"]["decisions"][0][field] = value
            with self.subTest(field=field):
                self.assert_rejected(changed)

    def test_missing_or_moved_decision_fails_closed(self):
        changed = copy.deepcopy(self.package)
        changed["spec"]["decisions"].pop()
        self.assert_rejected(changed)
        changed = copy.deepcopy(self.package)
        changed["spec"]["decisions"][0]["gate"] = "M0B-I"
        self.assert_rejected(changed)

    def test_credential_gate_cannot_become_authority_decision(self):
        changed = copy.deepcopy(self.package)
        changed["spec"]["decisions"][0]["id"] = "M0AI-INSTALLER-CREDENTIAL"
        self.assert_rejected(changed)
        changed = copy.deepcopy(self.package)
        changed["spec"]["excludedMutationGates"][0]["status"] = "AUTHORIZED"
        self.assert_rejected(changed)

    def test_development_loss_boundaries_cannot_be_overstated(self):
        forbidden = {
            "highAvailabilityRequired": True,
            "providerSnapshotsRequired": True,
            "totalStateLossAccepted": False,
            "rebuildPathProven": True,
            "automaticAdoptionAllowed": True,
            "productionDRClaimAllowed": True,
            "lifecycleContinuityClaimAllowed": True,
        }
        for field, value in forbidden.items():
            changed = copy.deepcopy(self.package)
            changed["spec"]["developmentRiskProfile"][field] = value
            with self.subTest(field=field):
                self.assert_rejected(changed)

    def test_target_identity_tampering_fails_closed(self):
        for field in ("kubeSystemNamespaceUID", "apiServer", "kubernetesVersion", "platform"):
            changed = copy.deepcopy(self.package)
            changed["spec"]["targetIncarnations"]["ok-shared"][field] = "tampered"
            with self.subTest(field=field):
                self.assert_rejected(changed)

    def test_source_digest_tampering_fails_closed(self):
        changed = copy.deepcopy(self.package)
        changed["spec"]["sources"]["liveResults"]["digest"] = "sha256:" + "0" * 64
        self.assert_rejected(changed)

    def test_rbac_risk_reduction_without_decision_fails_closed(self):
        changed = copy.deepcopy(self.package)
        decision = next(item for item in changed["spec"]["decisions"] if item["id"] == "M0AI-RBAC-SECURITY-DECISION")
        decision["residualRisks"]["SECRET-READ"] = 0
        self.assert_rejected(changed)


if __name__ == "__main__":
    unittest.main()
