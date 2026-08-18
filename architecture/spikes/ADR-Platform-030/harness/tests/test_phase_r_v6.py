import copy
import importlib.util
import json
import unittest
from pathlib import Path


HARNESS = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("ok141_phase_r_v6_test", HARNESS / "ok141_phase_r_v6.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PhaseRV6Tests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads((HARNESS / "fixtures/execution/phase-r-v6.json").read_text())

    def test_v6_reproduces_and_v5_remains_historical(self):
        self.assertEqual(MODULE.validate(self.fixture, HARNESS), self.fixture["fixtureDigest"])
        historical = json.loads((HARNESS / "fixtures/execution/phase-r-v5.json").read_text())
        self.assertEqual(MODULE.V5.validate(historical, HARNESS), MODULE.PHASE_R_V5_DIGEST)

    def test_v6_binds_latest_contract_platform_and_projection(self):
        self.assertEqual(self.fixture["contract"]["R"], MODULE.R9)
        self.assertEqual(self.fixture["platform"]["P"], MODULE.P9)
        self.assertEqual(self.fixture["projection"]["objectSets"]["okMgmtLifecycle"]["count"], 8)
        self.assertEqual(self.fixture["projection"]["objectSets"]["okInfraPrerequisites"]["count"], 3)

    def test_tampering_fails_closed(self):
        mutations = {
            "wrong-r": lambda d: d["contract"].update(R="sha256:" + "1" * 64),
            "wrong-p": lambda d: d["platform"].update(P="sha256:" + "2" * 64),
            "wrong-amendment": lambda d: d["consolidates"][-1].update(fixtureDigest="sha256:" + "3" * 64),
            "wrong-tool": lambda d: d["tools"].update(phaseRV6ToolDigest="sha256:" + "4" * 64),
        }
        for name, mutation in mutations.items():
            with self.subTest(name=name):
                changed = copy.deepcopy(self.fixture)
                mutation(changed)
                with self.assertRaises(MODULE.V1.HarnessError):
                    MODULE.validate(changed, HARNESS)


if __name__ == "__main__":
    unittest.main()
