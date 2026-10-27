import copy
import importlib.util
import sys
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("go1_protocol_v6_test", HERE / "verify_go1_protocol_v6.py")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class GO1ProtocolV6Tests(unittest.TestCase):
    def setUp(self):
        self.path = HERE / "go1-protocol-v6.yaml"
        self.value = MODULE.V1.read_yaml_or_json(self.path)

    def assert_rejected(self, value):
        with self.assertRaises((MODULE.ProtocolError, MODULE.SUBMITTER.SubmitterError, MODULE.MATERIALIZER.MaterializerError, MODULE.V2.SubmitterError, MODULE.V1.HarnessError)):
            MODULE.validate(value, self.path)

    def test_protocol_reproduces_and_is_fully_disabled(self):
        spec = MODULE.validate(self.value, self.path)
        self.assertEqual(len(spec["lifecycleSubmission"]["groups"]), 5)
        self.assertFalse(any(item["enabled"] for item in spec["phases"]))

    def test_any_authority_fails_closed(self):
        changed = copy.deepcopy(self.value)
        changed["spec"]["authorization"]["go1LifecycleEnablementGranted"] = True
        self.assert_rejected(changed)

    def test_historical_protocol_cannot_be_reenabled(self):
        changed = copy.deepcopy(self.value)
        changed["spec"]["supersedesForFutureExecution"]["allowedForFutureExecution"] = True
        self.assert_rejected(changed)

    def test_fixture_tampering_fails_closed(self):
        changed = copy.deepcopy(self.value)
        changed["spec"]["fixture"]["R"] = "sha256:" + "0" * 64
        self.assert_rejected(changed)

    def test_group_reordering_fails_closed(self):
        changed = copy.deepcopy(self.value)
        changed["spec"]["lifecycleSubmission"]["groups"][2], changed["spec"]["lifecycleSubmission"]["groups"][3] = changed["spec"]["lifecycleSubmission"]["groups"][3], changed["spec"]["lifecycleSubmission"]["groups"][2]
        self.assert_rejected(changed)

    def test_secret_materializer_tampering_fails_closed(self):
        changed = copy.deepcopy(self.value)
        changed["spec"]["mechanisms"]["providerAccessMaterializer"]["digest"] = "sha256:" + "0" * 64
        self.assert_rejected(changed)

    def test_secret_bytes_cannot_be_allowed(self):
        changed = copy.deepcopy(self.value)
        changed["spec"]["lifecycleSubmission"]["groups"][2]["secretBytesInProtocolOrEvidenceAllowed"] = True
        self.assert_rejected(changed)

    def test_inherited_later_stage_tampering_fails_closed(self):
        changed = copy.deepcopy(self.value)
        changed["spec"]["inheritedLaterStages"]["sections"]["platform"] = "sha256:" + "0" * 64
        self.assert_rejected(changed)

    def test_phase_enablement_fails_closed(self):
        changed = copy.deepcopy(self.value)
        changed["spec"]["phases"][1]["enabled"] = True
        self.assert_rejected(changed)

    def test_lifecycle_object_total_tampering_fails_closed(self):
        changed = copy.deepcopy(self.value)
        changed["spec"]["scope"]["maximumBoundary"]["lifecycleSubmissionObjects"] = 11
        self.assert_rejected(changed)


if __name__ == "__main__":
    unittest.main()
