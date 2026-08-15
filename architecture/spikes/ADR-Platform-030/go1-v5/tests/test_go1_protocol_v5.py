import copy
import importlib.util
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "go1_v5_verify_test", HERE / "verify_go1_protocol_v5.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class GO1ProtocolV5Tests(unittest.TestCase):
    def setUp(self):
        self.path = HERE / "go1-protocol-v5.yaml"
        self.protocol = MODULE.V1.read_yaml_or_json(self.path)

    def assert_rejected(self, changed):
        with self.assertRaises((MODULE.VerificationError, MODULE.V1.HarnessError)):
            MODULE.validate(changed, self.path)

    def test_protocol_reproduces_bound_checkpoint(self):
        self.assertTrue(MODULE.validate(self.protocol, self.path).startswith("sha256:"))

    def test_authorization_tampering_fails_closed(self):
        changed = copy.deepcopy(self.protocol)
        changed["spec"]["authorization"]["go1LifecycleEnablementGranted"] = True
        self.assert_rejected(changed)

    def test_automatic_runtime_advance_fails_closed(self):
        changed = copy.deepcopy(self.protocol)
        changed["spec"]["runtimePause"]["automaticAdvanceAllowed"] = True
        self.assert_rejected(changed)

    def test_premature_runtime_binding_fails_closed(self):
        changed = copy.deepcopy(self.protocol)
        changed["spec"]["runtimePause"]["runtimeBinding"]["completedArtifactDigest"] = "sha256:" + "0" * 64
        self.assert_rejected(changed)

    def test_historical_non_executable_hcp_fails_closed(self):
        changed = copy.deepcopy(self.protocol)
        changed["spec"]["enablement"]["hcpCandidate"]["path"] = "../harness/candidates/caaph-v0.6.4/helmchartproxy-candidate.yaml"
        self.assert_rejected(changed)

    def test_granted_stage_gate_fails_closed(self):
        changed = copy.deepcopy(self.protocol)
        changed["spec"]["stageGates"][0]["state"] = "GRANTED"
        self.assert_rejected(changed)

    def test_enabled_mutating_phase_fails_closed(self):
        changed = copy.deepcopy(self.protocol)
        changed["spec"]["phases"][7]["enabled"] = True
        self.assert_rejected(changed)

    def test_excess_wall_clock_budget_fails_closed(self):
        changed = copy.deepcopy(self.protocol)
        changed["spec"]["scope"]["maximumBoundary"]["wallClockMinutes"] = 121
        self.assert_rejected(changed)

    def test_application_submission_fails_closed(self):
        changed = copy.deepcopy(self.protocol)
        changed["spec"]["platform"]["applications"]["submitEnabled"] = True
        self.assert_rejected(changed)

    def test_missing_blocker_fails_closed(self):
        changed = copy.deepcopy(self.protocol)
        changed["spec"]["blockers"].pop()
        self.assert_rejected(changed)

    def test_runtime_blocker_bypass_fails_closed(self):
        changed = copy.deepcopy(self.protocol)
        changed["spec"]["acceptance"]["allRuntimeBlockersMustCloseBeforePauseRelease"] = False
        self.assert_rejected(changed)

    def test_prior_v4_binding_tampering_fails_closed(self):
        changed = copy.deepcopy(self.protocol)
        changed["spec"]["supersedesForFutureExecution"]["digest"] = "sha256:" + "0" * 64
        self.assert_rejected(changed)


if __name__ == "__main__":
    unittest.main()
