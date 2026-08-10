import copy
import importlib.util
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "go1_v4_verify_test", HERE / "verify_go1_protocol_v4.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class GO1ProtocolV4Tests(unittest.TestCase):
    def setUp(self):
        self.path = HERE / "go1-protocol-v4.yaml"
        self.protocol = MODULE.V1.read_yaml_or_json(self.path)

    def assert_rejected(self, changed):
        with self.assertRaises(MODULE.V1.HarnessError):
            MODULE.validate(changed, self.path)

    def test_protocol_reproduces_bound_draft(self):
        digest = MODULE.validate(self.protocol, self.path)
        self.assertTrue(digest.startswith("sha256:"))

    def test_gate_partition_tampering_fails_closed(self):
        changed = copy.deepcopy(self.protocol)
        changed["spec"]["gatePartition"]["digest"] = "sha256:" + "0" * 64
        self.assert_rejected(changed)

    def test_historical_protocol_tampering_fails_closed(self):
        changed = copy.deepcopy(self.protocol)
        changed["spec"]["historicalProtocol"]["draftDigest"] = "sha256:" + "0" * 64
        self.assert_rejected(changed)

    def test_mutation_or_go_authority_fails_closed(self):
        for field in ("mutationAuthorized", "goGranted"):
            changed = copy.deepcopy(self.protocol)
            changed["spec"]["authorization"][field] = True
            with self.subTest(field=field):
                self.assert_rejected(changed)

    def test_installation_gate_cannot_authorize_target_or_go1(self):
        for field in ("mayAuthorizeTargetConvergence", "mayAuthorizeGO1"):
            changed = copy.deepcopy(self.protocol)
            changed["spec"]["installationGates"][0][field] = True
            with self.subTest(field=field):
                self.assert_rejected(changed)

    def test_pre_go_requirement_cannot_be_missing_or_preclosed(self):
        changed = copy.deepcopy(self.protocol)
        changed["spec"]["preGoRequirements"].pop()
        self.assert_rejected(changed)
        changed = copy.deepcopy(self.protocol)
        changed["spec"]["preGoRequirements"][0]["status"] = "CLOSED"
        self.assert_rejected(changed)

    def test_runtime_obligation_cannot_be_preclosed(self):
        changed = copy.deepcopy(self.protocol)
        changed["spec"]["runtimeObligations"][0]["status"] = "CLOSED"
        self.assert_rejected(changed)

    def test_runtime_obligation_cannot_move_to_g1(self):
        changed = copy.deepcopy(self.protocol)
        changed["spec"]["runtimeObligations"][0]["phase"] = "G1"
        self.assert_rejected(changed)

    def test_runtime_obligation_must_stop_on_failure(self):
        changed = copy.deepcopy(self.protocol)
        changed["spec"]["runtimeObligations"][0]["onFailure"] = "CONTINUE"
        self.assert_rejected(changed)

    def test_deferred_scenario_cannot_enter_go1(self):
        changed = copy.deepcopy(self.protocol)
        changed["spec"]["deferredScenarios"][0]["includedInGO1"] = True
        self.assert_rejected(changed)

    def test_submission_and_all_phases_remain_disabled(self):
        changed = copy.deepcopy(self.protocol)
        changed["spec"]["submission"]["enabled"] = True
        self.assert_rejected(changed)
        changed = copy.deepcopy(self.protocol)
        changed["spec"]["phases"][1]["enabled"] = True
        self.assert_rejected(changed)

    def test_authority_domains_cannot_be_swapped(self):
        changed = copy.deepcopy(self.protocol)
        changed["spec"]["submission"]["groups"][0]["targetPlane"] = "ok-mgmt"
        self.assert_rejected(changed)

    def test_historical_all_blockers_rule_cannot_return(self):
        changed = copy.deepcopy(self.protocol)
        changed["spec"]["acceptance"]["allHistoricalBlockersMustBeClosedBeforeGoDecision"] = True
        self.assert_rejected(changed)
        changed = copy.deepcopy(self.protocol)
        changed["spec"]["preconditions"].append("all blockers are CLOSED before GO")
        self.assert_rejected(changed)

    def test_fixture_identity_tampering_fails_closed(self):
        changed = copy.deepcopy(self.protocol)
        changed["spec"]["fixture"]["fixtureDigest"] = "sha256:" + "0" * 64
        self.assert_rejected(changed)


if __name__ == "__main__":
    unittest.main()
