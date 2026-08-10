import copy
import importlib.util
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "m0a_installation_verify_test", HERE / "verify_m0a_installation.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class M0aInstallationTests(unittest.TestCase):
    def setUp(self):
        self.path = HERE / "m0a-installation-v1.yaml"
        self.protocol = MODULE.V1.read_yaml_or_json(self.path)

    def assert_rejected(self, changed):
        with self.assertRaises(MODULE.V1.HarnessError):
            MODULE.validate(changed, self.path)

    def test_protocol_and_exact_release_manifest_verify(self):
        digest = MODULE.validate(self.protocol, self.path)
        self.assertTrue(digest.startswith("sha256:"))

    def test_reference_tampering_fails_closed(self):
        for reference in ("go1Protocol", "gatePartition", "historicalM0a"):
            changed = copy.deepcopy(self.protocol)
            changed["spec"]["references"][reference]["digest"] = "sha256:" + "0" * 64
            with self.subTest(reference=reference):
                self.assert_rejected(changed)

    def test_authority_cannot_expand_to_target_or_go1(self):
        for field in (
            "mayAuthorizeTargetConvergence",
            "mayAuthorizeGO1",
            "maySubmitHelmChartProxy",
            "maySubmitHelmReleaseProxy",
            "mayAccessWorkloadCluster",
        ):
            changed = copy.deepcopy(self.protocol)
            changed["spec"]["authorityBoundary"][field] = True
            with self.subTest(field=field):
                self.assert_rejected(changed)

    def test_mutation_or_grant_fails_closed(self):
        for field in (
            "mutationAuthorized",
            "m0aInstallationGranted",
            "m0aTargetConvergenceGranted",
            "go1Granted",
        ):
            changed = copy.deepcopy(self.protocol)
            changed["spec"]["authorization"][field] = True
            with self.subTest(field=field):
                self.assert_rejected(changed)

    def test_wrong_manifest_or_digest_fails_closed(self):
        changed = copy.deepcopy(self.protocol)
        changed["spec"]["source"]["manifestPath"] = "../m0a-v2/helmchartproxy-v4-candidate.yaml"
        self.assert_rejected(changed)
        changed = copy.deepcopy(self.protocol)
        changed["spec"]["source"]["rawDigest"] = "sha256:" + "0" * 64
        self.assert_rejected(changed)

    def test_manifest_inventory_tampering_fails_closed(self):
        changed = copy.deepcopy(self.protocol)
        changed["spec"]["source"]["objectCount"] = 20
        self.assert_rejected(changed)
        changed = copy.deepcopy(self.protocol)
        changed["spec"]["source"]["objectKinds"]["Deployment"] = 2
        self.assert_rejected(changed)

    def test_submission_must_remain_disabled_and_bounded(self):
        changed = copy.deepcopy(self.protocol)
        changed["spec"]["submission"]["enabled"] = True
        self.assert_rejected(changed)
        changed = copy.deepcopy(self.protocol)
        changed["spec"]["submission"]["targetPlane"] = "ok-infra"
        self.assert_rejected(changed)
        changed = copy.deepcopy(self.protocol)
        changed["spec"]["submission"]["freeFormShellEndpoint"] = True
        self.assert_rejected(changed)

    def test_security_acceptance_cannot_be_assumed(self):
        changed = copy.deepcopy(self.protocol)
        changed["spec"]["securityReview"]["status"] = "ACCEPTED"
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
        changed["spec"]["runtimeObligations"][0]["phase"] = "M0AI-G1"
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

    def test_failure_and_target_scenarios_remain_excluded(self):
        changed = copy.deepcopy(self.protocol)
        changed["spec"]["excludedScenarios"] = [
            item for item in changed["spec"]["excludedScenarios"] if "restart" not in item
        ]
        self.assert_rejected(changed)


if __name__ == "__main__":
    unittest.main()
