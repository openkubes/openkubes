import copy
import importlib.util
import sys
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("ghcr_alert_destination_decision_test", HERE / "verify_ghcr_alert_destination_decision.py")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class GHCRAlertDestinationDecisionTests(unittest.TestCase):
    def setUp(self):
        self.path = HERE / "ghcr-alert-destination-decision-v1.yaml"
        self.decision = MODULE.V1.read_yaml_or_json(self.path)

    def assert_rejected(self, changed):
        with self.assertRaises(MODULE.V1.HarnessError):
            MODULE.validate(changed, self.path)

    def test_decision_and_source_verify(self):
        self.assertTrue(MODULE.validate(self.decision, self.path).startswith("sha256:"))

    def test_alert_surface_is_exactly_bound(self):
        for field, value in (("primarySignal", "ISSUE"), ("detailSurface", "WEBHOOK"), ("accountableRecipient", "github:someone-else")):
            changed = copy.deepcopy(self.decision)
            changed["spec"]["alertPolicy"][field] = value
            with self.subTest(field=field):
                self.assert_rejected(changed)

    def test_delivery_and_missed_run_cannot_be_overclaimed(self):
        changed = copy.deepcopy(self.decision)
        changed["spec"]["alertPolicy"]["notificationDeliveryGuaranteed"] = True
        self.assert_rejected(changed)
        changed = copy.deepcopy(self.decision)
        changed["spec"]["alertPolicy"]["missedOrNeverStartedRunCoverage"] = True
        self.assert_rejected(changed)

    def test_no_additional_write_integration_can_be_selected(self):
        for field in ("issueCreationAllowed", "pullRequestCreationAllowed", "externalWebhookAllowed", "emailIntegrationClaimAllowed", "packageWritePermissionAllowed", "packageDeletePermissionAllowed", "additionalAPIMutationRequired"):
            changed = copy.deepcopy(self.decision)
            changed["spec"]["alertPolicy"][field] = True
            with self.subTest(field=field):
                self.assert_rejected(changed)

    def test_fail_closed_outcomes_cannot_be_weakened(self):
        for field in self.decision["spec"]["failClosedOutcomes"]:
            changed = copy.deepcopy(self.decision)
            changed["spec"]["failClosedOutcomes"][field] = "PASS"
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

    def test_acceptance_input_is_bound(self):
        changed = copy.deepcopy(self.decision)
        changed["spec"]["decision"]["acceptanceInput"] = "different"
        self.assert_rejected(changed)

    def test_source_digest_tampering_fails_closed(self):
        changed = copy.deepcopy(self.decision)
        changed["spec"]["sourceMonitoringDecision"]["digest"] = "sha256:" + "0" * 64
        self.assert_rejected(changed)


if __name__ == "__main__":
    unittest.main()
