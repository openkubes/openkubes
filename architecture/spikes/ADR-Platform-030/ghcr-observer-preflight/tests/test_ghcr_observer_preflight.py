import copy
import importlib.util
import sys
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("ghcr_observer_preflight_test", HERE / "verify_ghcr_observer_preflight.py")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class GHCRObserverPreflightTests(unittest.TestCase):
    def setUp(self):
        self.path = HERE / "ghcr-observer-preflight-v1.yaml"
        self.preflight = MODULE.V1.read_yaml_or_json(self.path)

    def assert_rejected(self, changed):
        with self.assertRaises(MODULE.V1.HarnessError):
            MODULE.validate(changed, self.path)

    def test_preflight_and_source_verify(self):
        self.assertTrue(MODULE.validate(self.preflight, self.path).startswith("sha256:"))

    def test_any_write_or_gate_fails_closed(self):
        for field in ("externalWriteAuthorized", "packageCreationAuthorized", "environmentCreationAuthorized", "workflowDeploymentAuthorized", "credentialMutationAuthorized", "infrastructureMutationAuthorized", "m0aInstallationGranted", "m0bInstallationGranted", "go1Granted"):
            changed = copy.deepcopy(self.preflight)
            changed["spec"]["authorization"][field] = True
            with self.subTest(field=field):
                self.assert_rejected(changed)

    def test_missing_package_cannot_be_claimed_present(self):
        changed = copy.deepcopy(self.preflight)
        changed["spec"]["liveObservations"]["package"]["packageCreated"] = True
        self.assert_rejected(changed)

    def test_missing_package_scope_cannot_be_claimed(self):
        changed = copy.deepcopy(self.preflight)
        changed["spec"]["liveObservations"]["packageListing"]["currentTokenProvesPackageRead"] = True
        self.assert_rejected(changed)

    def test_actions_security_posture_cannot_be_overstated(self):
        changed = copy.deepcopy(self.preflight)
        changed["spec"]["liveObservations"]["repositoryActions"]["organizationRequiresActionSHAPinning"] = True
        self.assert_rejected(changed)
        changed = copy.deepcopy(self.preflight)
        changed["spec"]["liveObservations"]["repositoryActions"]["evidencePublishEnvironmentPresent"] = True
        self.assert_rejected(changed)

    def test_deletion_and_restore_cannot_be_overstated(self):
        changed = copy.deepcopy(self.preflight)
        changed["spec"]["officialCapabilityEvidence"]["deletionBoundary"]["administratorDeletionPossible"] = False
        self.assert_rejected(changed)
        changed = copy.deepcopy(self.preflight)
        changed["spec"]["officialCapabilityEvidence"]["deletionBoundary"]["restoreGuaranteed"] = True
        self.assert_rejected(changed)

    def test_attestation_cannot_become_retention_proof(self):
        changed = copy.deepcopy(self.preflight)
        changed["spec"]["officialCapabilityEvidence"]["attestationBoundary"]["attestationIsNotRetentionProof"] = False
        self.assert_rejected(changed)

    def test_cached_clock_result_cannot_be_retained(self):
        changed = copy.deepcopy(self.preflight)
        changed["spec"]["clockObservation"]["rejectedObservation"]["retainedAsClockEvidence"] = True
        self.assert_rejected(changed)

    def test_clock_skew_limit_cannot_be_relaxed_or_preused(self):
        changed = copy.deepcopy(self.preflight)
        changed["spec"]["clockObservation"]["requiredMaximumSkewSeconds"] = 30
        self.assert_rejected(changed)
        changed = copy.deepcopy(self.preflight)
        changed["spec"]["clockObservation"]["result"] = "PROVEN-FOR-FUTURE-GATE"
        self.assert_rejected(changed)

    def test_runtime_cannot_be_precreated_or_deployed(self):
        changed = copy.deepcopy(self.preflight)
        changed["spec"]["proposedObserverRuntime"]["environmentStatus"] = "CREATED"
        self.assert_rejected(changed)
        changed = copy.deepcopy(self.preflight)
        changed["spec"]["proposedObserverRuntime"]["workflowStatus"] = "DEPLOYED"
        self.assert_rejected(changed)

    def test_retention_proposal_cannot_be_preaccepted(self):
        changed = copy.deepcopy(self.preflight)
        changed["spec"]["retentionProposal"]["status"] = "ACCEPTED"
        self.assert_rejected(changed)
        changed = copy.deepcopy(self.preflight)
        changed["spec"]["retentionProposal"]["model"] = "WORM"
        self.assert_rejected(changed)

    def test_source_digest_tampering_fails_closed(self):
        changed = copy.deepcopy(self.preflight)
        changed["spec"]["sourceProtocol"]["digest"] = "sha256:" + "0" * 64
        self.assert_rejected(changed)


if __name__ == "__main__":
    unittest.main()
