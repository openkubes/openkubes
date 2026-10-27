import copy
import importlib.util
import sys
import unittest
from pathlib import Path

import yaml


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("ok141_network_defaulting_test", HERE / "network_observer_defaulting_v1.py")
FIX = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = FIX
assert SPEC.loader is not None
SPEC.loader.exec_module(FIX)


class NetworkObserverDefaultingTests(unittest.TestCase):
    def setUp(self):
        self.desired = yaml.safe_load(FIX.V1_CANDIDATE.parent.parent.joinpath("go1-l-hcp-v1/helmchartproxy-phase-r-v5-candidate.yaml").read_text())

    def test_candidate_is_inert_and_binds_false_crd_default(self):
        candidate = FIX.validate_candidate()
        self.assertEqual(candidate["spec"]["authorization"]["decision"], "NO-GO")
        self.assertFalse(FIX.hcp_enable_client_cache_default())

    def test_api_defaulted_false_is_semantically_equal(self):
        observed = copy.deepcopy(self.desired)
        observed["spec"]["options"]["enableClientCache"] = False
        self.assertNotEqual(
            {key: self.desired["spec"].get(key) for key in FIX.SEMANTIC_KEYS},
            {key: observed["spec"].get(key) for key in FIX.SEMANTIC_KEYS},
        )
        self.assertTrue(FIX.equivalent(self.desired, observed))

    def test_non_default_true_still_fails(self):
        observed = copy.deepcopy(self.desired)
        observed["spec"]["options"]["enableClientCache"] = True
        self.assertFalse(FIX.equivalent(self.desired, observed))

    def test_unrelated_drift_still_fails(self):
        observed = copy.deepcopy(self.desired)
        observed["spec"]["version"] = "1.19.7"
        self.assertFalse(FIX.equivalent(self.desired, observed))

    def test_unknown_additional_option_still_fails(self):
        observed = copy.deepcopy(self.desired)
        observed["spec"]["options"]["unexpected"] = False
        self.assertFalse(FIX.equivalent(self.desired, observed))


if __name__ == "__main__":
    unittest.main()
