import copy
import importlib.util
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("go1_v3_verify_test", HERE / "verify_go1_protocol_v3.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class GO1ProtocolV3Tests(unittest.TestCase):
    def setUp(self):
        self.path = HERE / "go1-protocol-v3.yaml"
        self.protocol = MODULE.V1.read_yaml_or_json(self.path)

    def test_protocol_reproduces_bound_draft(self):
        digest = MODULE.validate(self.protocol, self.path)
        self.assertTrue(digest.startswith("sha256:"))

    def test_historical_fixture_or_revision_fails_closed(self):
        for field, value in {
            "fixtureDigest": "sha256:67fa2e63bba98d8cc70f680e8df56dea5803c0a0d8c5db81ab78578daacebd9f",
            "R": "sha256:62e4d20fdd352474f4a5d2ea6639d7d63fa494af58b9b4532169bd96437d9f78",
            "P": "sha256:0dcfbe10f271aeb7e82d94fbad0ff2691dec67f69c7452578662df09a650439b",
        }.items():
            changed = copy.deepcopy(self.protocol)
            changed["spec"]["fixture"][field] = value
            with self.subTest(field=field), self.assertRaises(MODULE.V1.HarnessError):
                MODULE.validate(changed, self.path)

    def test_authorization_or_phase_enablement_fails_closed(self):
        changed = copy.deepcopy(self.protocol)
        changed["spec"]["authorization"]["goGranted"] = True
        with self.assertRaises(MODULE.V1.HarnessError):
            MODULE.validate(changed, self.path)
        changed = copy.deepcopy(self.protocol)
        changed["spec"]["phases"][0]["enabled"] = True
        with self.assertRaises(MODULE.V1.HarnessError):
            MODULE.validate(changed, self.path)

    def test_missing_blocker_or_wrong_target_fails_closed(self):
        changed = copy.deepcopy(self.protocol)
        changed["spec"]["blockers"].pop()
        with self.assertRaises(MODULE.V1.HarnessError):
            MODULE.validate(changed, self.path)

    def test_platform_source_or_closure_tampering_fails_closed(self):
        for field in ("sourceCommit", "sourceClosureLockDigest"):
            changed = copy.deepcopy(self.protocol)
            changed["spec"]["mechanisms"]["platform"][field] = "sha256:" + "0" * 64
            with self.subTest(field=field), self.assertRaises(MODULE.V1.HarnessError):
                MODULE.validate(changed, self.path)
        changed = copy.deepcopy(self.protocol)
        changed["spec"]["submission"]["groups"][0]["targetPlane"] = "ok-mgmt"
        with self.assertRaises(MODULE.V1.HarnessError):
            MODULE.validate(changed, self.path)


if __name__ == "__main__":
    unittest.main()
