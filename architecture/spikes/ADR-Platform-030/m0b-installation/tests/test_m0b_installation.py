import copy
import importlib.util
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "m0b_installation_verify_test", HERE / "verify_m0b_installation.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class M0bInstallationTests(unittest.TestCase):
    def setUp(self):
        self.path = HERE / "m0b-installation-v1.yaml"
        self.protocol = MODULE.V1.read_yaml_or_json(self.path)

    def assert_rejected(self, changed):
        with self.assertRaises(MODULE.V1.HarnessError):
            MODULE.validate(changed, self.path)

    def test_protocol_source_lock_and_namespace_verify(self):
        digest = MODULE.validate(self.protocol, self.path)
        self.assertTrue(digest.startswith("sha256:"))

    def test_reference_tampering_fails_closed(self):
        for reference in ("go1Protocol", "gatePartition", "historicalM0b"):
            changed = copy.deepcopy(self.protocol)
            changed["spec"]["references"][reference]["digest"] = "sha256:" + "0" * 64
            with self.subTest(reference=reference):
                self.assert_rejected(changed)

    def test_authority_cannot_expand_to_target_or_go1(self):
        for field in (
            "mayAuthorizeTargetRegistration",
            "mayAuthorizeTargetConvergence",
            "mayAuthorizeGO1",
            "mayCreateTargetCredentials",
            "maySubmitAppProject",
            "maySubmitApplication",
        ):
            changed = copy.deepcopy(self.protocol)
            changed["spec"]["authorityBoundary"][field] = True
            with self.subTest(field=field):
                self.assert_rejected(changed)

    def test_mutation_or_grant_fails_closed(self):
        for field in (
            "mutationAuthorized",
            "m0bInstallationGranted",
            "m0bTargetRegistrationGranted",
            "m0bTargetConvergenceGranted",
            "go1Granted",
        ):
            changed = copy.deepcopy(self.protocol)
            changed["spec"]["authorization"][field] = True
            with self.subTest(field=field):
                self.assert_rejected(changed)

    def test_placement_cannot_claim_authority_or_production_ha(self):
        changed = copy.deepcopy(self.protocol)
        changed["spec"]["placement"]["productionHAClaimAllowed"] = True
        self.assert_rejected(changed)
        changed = copy.deepcopy(self.protocol)
        changed["spec"]["placement"]["placementAuthority"] = "ACCEPTED"
        self.assert_rejected(changed)

    def test_source_lock_or_namespace_tampering_fails_closed(self):
        changed = copy.deepcopy(self.protocol)
        changed["spec"]["source"]["lockDigest"] = "sha256:" + "0" * 64
        self.assert_rejected(changed)
        changed = copy.deepcopy(self.protocol)
        changed["spec"]["source"]["namespaceRawDigest"] = "sha256:" + "0" * 64
        self.assert_rejected(changed)

    def test_remote_materialization_cannot_be_assumed(self):
        changed = copy.deepcopy(self.protocol)
        changed["spec"]["source"]["remoteContentRetained"] = True
        self.assert_rejected(changed)
        changed = copy.deepcopy(self.protocol)
        changed["spec"]["source"]["materializationRequiredBeforeInstallation"] = False
        self.assert_rejected(changed)

    def test_combined_inventory_tampering_fails_closed(self):
        changed = copy.deepcopy(self.protocol)
        changed["spec"]["source"]["combinedObjectCount"] = 64
        self.assert_rejected(changed)
        changed = copy.deepcopy(self.protocol)
        changed["spec"]["source"]["objectKinds"]["Deployment"] = 7
        self.assert_rejected(changed)

    def test_image_identity_tampering_fails_closed(self):
        changed = copy.deepcopy(self.protocol)
        changed["spec"]["source"]["controllerImages"][0]["linuxAmd64Digest"] = "sha256:" + "0" * 64
        self.assert_rejected(changed)

    def test_submission_must_remain_disabled_and_bounded(self):
        changed = copy.deepcopy(self.protocol)
        changed["spec"]["submission"]["enabled"] = True
        self.assert_rejected(changed)
        changed = copy.deepcopy(self.protocol)
        changed["spec"]["submission"]["targetPlane"] = "ok-mgmt"
        self.assert_rejected(changed)
        changed = copy.deepcopy(self.protocol)
        changed["spec"]["submission"]["freeFormShellEndpoint"] = True
        self.assert_rejected(changed)

    def test_pre_installation_requirement_cannot_be_missing_or_closed(self):
        changed = copy.deepcopy(self.protocol)
        changed["spec"]["preInstallationRequirements"].pop()
        self.assert_rejected(changed)
        changed = copy.deepcopy(self.protocol)
        changed["spec"]["preInstallationRequirements"][0]["status"] = "CLOSED"
        self.assert_rejected(changed)

    def test_runtime_obligation_cannot_be_preclosed_or_moved_to_install(self):
        changed = copy.deepcopy(self.protocol)
        changed["spec"]["runtimeObligations"][0]["status"] = "CLOSED"
        self.assert_rejected(changed)
        changed = copy.deepcopy(self.protocol)
        changed["spec"]["runtimeObligations"][0]["phase"] = "M0BI-G1"
        self.assert_rejected(changed)

    def test_runtime_obligation_must_stop_on_failure(self):
        changed = copy.deepcopy(self.protocol)
        changed["spec"]["runtimeObligations"][0]["onFailure"] = "CONTINUE"
        self.assert_rejected(changed)

    def test_phase_cannot_be_enabled(self):
        changed = copy.deepcopy(self.protocol)
        changed["spec"]["phases"][1]["enabled"] = True
        self.assert_rejected(changed)

    def test_only_installation_phase_may_be_prospectively_mutating(self):
        changed = copy.deepcopy(self.protocol)
        changed["spec"]["phases"][2]["mutating"] = True
        self.assert_rejected(changed)

    def test_rollback_cannot_be_enabled_or_unauthorized(self):
        changed = copy.deepcopy(self.protocol)
        changed["spec"]["rollback"]["enabled"] = True
        self.assert_rejected(changed)
        changed = copy.deepcopy(self.protocol)
        changed["spec"]["rollback"]["authorizationRequired"] = False
        self.assert_rejected(changed)

    def test_target_and_failure_scenarios_remain_excluded(self):
        changed = copy.deepcopy(self.protocol)
        changed["spec"]["excludedScenarios"] = [
            item for item in changed["spec"]["excludedScenarios"] if "restart" not in item
        ]
        self.assert_rejected(changed)


if __name__ == "__main__":
    unittest.main()
