import copy
import importlib.util
from pathlib import Path
import unittest

import yaml


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("network_amendment", HERE / "verify_platform_network_amendment_v1.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PlatformNetworkAmendmentTests(unittest.TestCase):
    def setUp(self):
        self.candidate = yaml.safe_load((HERE / "platform-network-amendment-v1.yaml").read_text())

    def test_candidate_reproduces(self):
        self.assertEqual(
            MODULE.validate(self.candidate),
            self.candidate["spec"]["fixture"]["fixtureDigest"],
        )

    def test_old_identity_fails_closed(self):
        changed = copy.deepcopy(self.candidate)
        changed["spec"]["fixture"]["P"] = changed["spec"]["base"]["P"]
        with self.assertRaises(MODULE.V1.HarnessError):
            MODULE.validate(changed)

    def test_render_or_fixture_tampering_fails_closed(self):
        for field in ("renderInventoryDigest", "fixtureDigest"):
            with self.subTest(field=field):
                changed = copy.deepcopy(self.candidate)
                changed["spec"]["fixture"][field] = "sha256:" + "0" * 64
                with self.assertRaises(MODULE.V1.HarnessError):
                    MODULE.validate(changed)


if __name__ == "__main__":
    unittest.main()
