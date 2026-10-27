import copy
import importlib.util
import sys
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("hcp_phase_r_v5_amendment_test", HERE / "verify_hcp_phase_r_v5_amendment_v1.py")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class HCPPhaseRV5AmendmentTests(unittest.TestCase):
    def setUp(self):
        self.path = HERE / "hcp-phase-r-v5-amendment-v1.yaml"
        self.value = MODULE.V1.read_yaml_or_json(self.path)

    def assert_rejected(self, value):
        with self.assertRaises((MODULE.AmendmentError, MODULE.V1.HarnessError)):
            MODULE.validate(value, self.path)

    def test_current_hcp_is_carrier_only_amendment(self):
        current = MODULE.validate(self.value, self.path)
        annotations = current["metadata"]["annotations"]
        self.assertEqual(annotations["openkubes.io/intent-revision"], self.value["spec"]["fixture"]["R"])
        self.assertEqual(annotations["openkubes.io/execution-fixture"], self.value["spec"]["fixture"]["fixtureDigest"])

    def test_any_authority_fails_closed(self):
        changed = copy.deepcopy(self.value)
        changed["spec"]["authorization"]["hcpSubmissionGranted"] = True
        self.assert_rejected(changed)

    def test_fixture_tampering_fails_closed(self):
        changed = copy.deepcopy(self.value)
        changed["spec"]["fixture"]["R"] = "sha256:" + "0" * 64
        self.assert_rejected(changed)

    def test_hcp_digest_tampering_fails_closed(self):
        changed = copy.deepcopy(self.value)
        changed["spec"]["currentHCP"]["rawDigest"] = "sha256:" + "0" * 64
        self.assert_rejected(changed)

    def test_false_equivalence_claim_fails_closed(self):
        changed = copy.deepcopy(self.value)
        changed["spec"]["currentHCP"]["desiredHelmSemanticsEqualHistorical"] = False
        self.assert_rejected(changed)

    def test_historical_hcp_cannot_be_enabled(self):
        changed = copy.deepcopy(self.value)
        changed["spec"]["historicalHCP"]["allowedForFutureSubmission"] = True
        self.assert_rejected(changed)

    def test_current_hcp_cannot_be_enabled_in_checkpoint(self):
        changed = copy.deepcopy(self.value)
        changed["spec"]["currentHCP"]["submissionEnabled"] = True
        self.assert_rejected(changed)

    def test_submitter_v2_remains_historical_hcp_blocked(self):
        changed = copy.deepcopy(self.value)
        changed["spec"]["submitterCheckpoint"]["historicalHCPOperationRuntimeEligible"] = True
        self.assert_rejected(changed)


if __name__ == "__main__":
    unittest.main()
