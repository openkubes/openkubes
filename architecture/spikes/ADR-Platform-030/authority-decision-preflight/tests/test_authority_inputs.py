import copy
import importlib.util
import sys
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("authority_inputs_test", HERE / "verify_authority_inputs.py")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class AuthorityInputTests(unittest.TestCase):
    def setUp(self):
        self.path = HERE / "authority-inputs-v1.yaml"
        self.inputs = MODULE.V1.read_yaml_or_json(self.path)

    def assert_rejected(self, changed):
        with self.assertRaises(MODULE.V1.HarnessError):
            MODULE.validate(changed, self.path)

    def test_inputs_and_source_verify(self):
        self.assertTrue(MODULE.validate(self.inputs, self.path).startswith("sha256:"))

    def test_grant_or_mutation_fails_closed(self):
        for field in ("mutationAuthorized", "m0aInstallationGranted", "m0bInstallationGranted", "go1Granted"):
            changed = copy.deepcopy(self.inputs)
            changed["spec"]["authorization"][field] = True
            with self.subTest(field=field):
                self.assert_rejected(changed)

    def test_principal_or_role_tampering_fails_closed(self):
        changed = copy.deepcopy(self.inputs)
        changed["spec"]["authorityPrincipal"]["principal"] = "github:someone-else"
        self.assert_rejected(changed)
        changed = copy.deepcopy(self.inputs)
        changed["spec"]["authorityPrincipal"]["roles"].pop()
        self.assert_rejected(changed)

    def test_solo_model_cannot_claim_independent_review(self):
        changed = copy.deepcopy(self.inputs)
        changed["spec"]["governanceException"]["independentHumanSecurityReview"] = True
        self.assert_rejected(changed)
        changed = copy.deepcopy(self.inputs)
        changed["spec"]["governanceException"]["claimBoundaries"]["independentHumanReviewClaimAllowed"] = True
        self.assert_rejected(changed)

    def test_solo_model_cannot_gain_production_claims(self):
        for field in ("productionUseAllowed", "highAvailabilityClaimAllowed", "disasterRecoveryClaimAllowed", "lifecycleContinuityClaimAllowed", "automaticAdoptionClaimAllowed"):
            changed = copy.deepcopy(self.inputs)
            changed["spec"]["governanceException"]["claimBoundaries"][field] = True
            with self.subTest(field=field):
                self.assert_rejected(changed)

    def test_placement_cannot_expand_to_local_or_self_management(self):
        for field in ("manageLocalOkSharedResources", "selfManagementAllowed"):
            changed = copy.deepcopy(self.inputs)
            changed["spec"]["gitOpsPlacementBoundary"][field] = True
            with self.subTest(field=field):
                self.assert_rejected(changed)
        changed = copy.deepcopy(self.inputs)
        changed["spec"]["gitOpsPlacementBoundary"]["externalWorkloadClustersOnly"] = False
        self.assert_rejected(changed)

    def test_placement_identity_tampering_fails_closed(self):
        changed = copy.deepcopy(self.inputs)
        changed["spec"]["gitOpsPlacementBoundary"]["boundIncarnation"]["kubeSystemNamespaceUID"] = "tampered"
        self.assert_rejected(changed)

    def test_proposals_cannot_become_bound_inputs(self):
        changed = copy.deepcopy(self.inputs)
        changed["spec"]["unresolvedInputs"]["evidenceDestination"]["status"] = "APPROVED"
        self.assert_rejected(changed)
        changed = copy.deepcopy(self.inputs)
        changed["spec"]["unresolvedInputs"]["executionWindow"]["validFrom"] = "2026-08-10T17:00:00Z"
        self.assert_rejected(changed)

    def test_rbac_or_credentials_cannot_be_preaccepted(self):
        changed = copy.deepcopy(self.inputs)
        changed["spec"]["unresolvedInputs"]["rbacSecurityDecisions"]["m0a"] = "ACCEPTED"
        self.assert_rejected(changed)
        changed = copy.deepcopy(self.inputs)
        changed["spec"]["unresolvedInputs"]["installerCredentials"]["m0b"] = "AUTHORIZED"
        self.assert_rejected(changed)

    def test_source_digest_tampering_fails_closed(self):
        changed = copy.deepcopy(self.inputs)
        changed["spec"]["sourcePackage"]["digest"] = "sha256:" + "0" * 64
        self.assert_rejected(changed)


if __name__ == "__main__":
    unittest.main()
