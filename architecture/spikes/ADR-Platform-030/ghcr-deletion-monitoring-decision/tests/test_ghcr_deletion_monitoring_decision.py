import copy
import importlib.util
import sys
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("ghcr_deletion_monitoring_decision_test", HERE / "verify_ghcr_deletion_monitoring_decision.py")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class GHCRDeletionMonitoringDecisionTests(unittest.TestCase):
    def setUp(self):
        self.path = HERE / "ghcr-deletion-monitoring-decision-v1.yaml"
        self.decision = MODULE.V1.read_yaml_or_json(self.path)

    def assert_rejected(self, changed):
        with self.assertRaises(MODULE.V1.HarnessError):
            MODULE.validate(changed, self.path)

    def test_decision_and_source_verify(self):
        self.assertTrue(MODULE.validate(self.decision, self.path).startswith("sha256:"))

    def test_interval_is_exactly_bound(self):
        for field, value in (("targetInterval", "PT12H"), ("intervalHours", 12)):
            changed = copy.deepcopy(self.decision)
            changed["spec"]["monitoringPolicy"][field] = value
            with self.subTest(field=field):
                self.assert_rejected(changed)

    def test_detection_cannot_be_claimed_guaranteed(self):
        changed = copy.deepcopy(self.decision)
        changed["spec"]["monitoringPolicy"]["detectionDeadlineGuaranteed"] = True
        self.assert_rejected(changed)
        changed = copy.deepcopy(self.decision)
        changed["spec"]["monitoringPolicy"]["continuousAvailabilityGuaranteed"] = True
        self.assert_rejected(changed)

    def test_missing_and_unavailable_observer_fail_closed(self):
        changed = copy.deepcopy(self.decision)
        changed["spec"]["monitoringPolicy"]["outcomeWhenMissing"] = "IGNORE"
        self.assert_rejected(changed)
        changed = copy.deepcopy(self.decision)
        changed["spec"]["monitoringPolicy"]["outcomeWhenObserverLateOrUnavailable"] = "PASS"
        self.assert_rejected(changed)

    def test_observer_cannot_gain_package_mutation(self):
        for field in ("automaticRepairAllowed", "automaticRestoreAllowed", "automaticRepublishAllowed", "deletePermissionAllowed", "packageWritePermissionAllowed"):
            changed = copy.deepcopy(self.decision)
            changed["spec"]["monitoringPolicy"][field] = True
            with self.subTest(field=field):
                self.assert_rejected(changed)

    def test_any_authorization_fails_closed(self):
        for field in self.decision["spec"]["authorization"]:
            if field == "decision":
                continue
            changed = copy.deepcopy(self.decision)
            changed["spec"]["authorization"][field] = True
            with self.subTest(field=field):
                self.assert_rejected(changed)

    def test_implementation_cannot_be_preclaimed(self):
        for field in self.decision["spec"]["operationalState"]:
            changed = copy.deepcopy(self.decision)
            changed["spec"]["operationalState"][field] = True
            with self.subTest(field=field):
                self.assert_rejected(changed)

    def test_acceptance_identity_is_bound(self):
        changed = copy.deepcopy(self.decision)
        changed["spec"]["decision"]["acceptedBy"] = "github:someone-else"
        self.assert_rejected(changed)
        changed = copy.deepcopy(self.decision)
        changed["spec"]["decision"]["acceptanceInput"] = "different"
        self.assert_rejected(changed)

    def test_source_digest_tampering_fails_closed(self):
        changed = copy.deepcopy(self.decision)
        changed["spec"]["sourceRetentionDecision"]["digest"] = "sha256:" + "0" * 64
        self.assert_rejected(changed)


if __name__ == "__main__":
    unittest.main()
