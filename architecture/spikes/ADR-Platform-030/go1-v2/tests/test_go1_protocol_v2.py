import copy
import importlib.util
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("go1_v2_verify_test", HERE / "verify_go1_protocol_v2.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class GO1ProtocolV2Tests(unittest.TestCase):
    def setUp(self):
        self.path = HERE / "go1-protocol-v2.yaml"
        self.protocol = MODULE.V1.read_yaml_or_json(self.path)

    def test_protocol_reproduces_bound_draft(self):
        digest = MODULE.validate(self.protocol, self.path)
        self.assertTrue(digest.startswith("sha256:"))

    def test_historical_fixture_or_revision_fails_closed(self):
        for field, value in {
            "fixtureDigest": "sha256:b27bb7c8e959e2c1028fcc0822755caa795ce21432344a64a62474abeb7f9f2b",
            "R": "sha256:d49e844113bdd96868eb9dec2d6672dfcc98ccb7a0bd43f2c6b53aabc2adda62",
            "P": "sha256:b46911c06ac31ed4755ffa83b0c960fafa0a23cab8442dc9eb1945df927b0665",
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
        changed = copy.deepcopy(self.protocol)
        changed["spec"]["submission"]["groups"][0]["targetPlane"] = "ok-mgmt"
        with self.assertRaises(MODULE.V1.HarnessError):
            MODULE.validate(changed, self.path)


if __name__ == "__main__":
    unittest.main()
