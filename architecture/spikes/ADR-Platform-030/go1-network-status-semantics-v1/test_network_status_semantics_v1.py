import copy
import datetime as dt
import importlib.util
import sys
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("ok141_network_status_semantics_test", HERE / "network_status_semantics_v1.py")
SEM = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = SEM
assert SPEC.loader is not None
SPEC.loader.exec_module(SEM)


class NetworkStatusSemanticsTests(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime(2026, 8, 14, 15, 30, 30, tzinfo=dt.timezone.utc)

    def probe(self, status_marker="omitted", timestamp="2026-08-14T15:30:00Z"):
        def protocol():
            value = {"lastProbed": timestamp, "latency": 10}
            if status_marker != "omitted":
                value["status"] = status_marker
            return value

        path = {"http": protocol(), "icmp": protocol()}
        return {
            "timestamp": timestamp,
            "nodes": [
                {
                    "name": name,
                    "host": {"primary-address": copy.deepcopy(path)},
                    "health-endpoint": {"primary-address": copy.deepcopy(path)},
                }
                for name in ("node-0", "node-1")
            ],
        }

    def test_candidate_is_inert_and_source_locked(self):
        candidate = SEM.validate_candidate()
        self.assertEqual(candidate["spec"]["authorization"]["decision"], "NO-GO")
        self.assertTrue(all(not value for key, value in candidate["spec"]["authorization"].items() if key.endswith("Granted")))
        self.assertEqual(SEM.validate_source_lock()["spec"]["commit"], SEM.CILIUM_COMMIT)

    def test_omitted_status_passes_with_exact_current_coverage(self):
        state, details = SEM.evaluate_probe(self.probe(), ["node-0", "node-1"], self.now, 120)
        self.assertEqual(state, "PASS-FUNCTIONAL-NETWORK-PROBE")
        self.assertEqual(details["successfulPathCount"], 8)

    def test_present_empty_string_remains_compatible(self):
        self.assertEqual(SEM.evaluate_probe(self.probe(""), ["node-0", "node-1"], self.now, 120)[0], "PASS-FUNCTIONAL-NETWORK-PROBE")

    def test_present_null_fails_closed(self):
        self.assertEqual(SEM.evaluate_probe(self.probe(None), ["node-0", "node-1"], self.now, 120)[0], "FAIL-FUNCTIONAL-CONNECTIVITY")

    def test_nonempty_error_fails_closed(self):
        self.assertEqual(SEM.evaluate_probe(self.probe("Connection timed out"), ["node-0", "node-1"], self.now, 120)[0], "FAIL-FUNCTIONAL-CONNECTIVITY")

    def test_missing_protocol_or_timestamp_fails_closed(self):
        missing_protocol = self.probe()
        del missing_protocol["nodes"][0]["host"]["primary-address"]["http"]
        self.assertEqual(SEM.evaluate_probe(missing_protocol, ["node-0", "node-1"], self.now, 120)[0], "FAIL-FUNCTIONAL-CONNECTIVITY")
        missing_timestamp = self.probe()
        del missing_timestamp["nodes"][0]["host"]["primary-address"]["http"]["lastProbed"]
        self.assertEqual(SEM.evaluate_probe(missing_timestamp, ["node-0", "node-1"], self.now, 120)[0], "FAIL-FUNCTIONAL-CONNECTIVITY")

    def test_stale_probe_and_path_fail_closed(self):
        stale = self.probe(timestamp="2026-08-14T15:20:00Z")
        self.assertEqual(SEM.evaluate_probe(stale, ["node-0", "node-1"], self.now, 120)[0], "FAIL-STALE-FUNCTIONAL-PROBE")
        stale_path = self.probe()
        stale_path["nodes"][0]["host"]["primary-address"]["http"]["lastProbed"] = "2026-08-14T15:20:00Z"
        self.assertEqual(SEM.evaluate_probe(stale_path, ["node-0", "node-1"], self.now, 120)[0], "FAIL-STALE-FUNCTIONAL-PATH")

    def test_wrong_node_coverage_fails_closed(self):
        self.assertEqual(SEM.evaluate_probe(self.probe(), ["node-0"], self.now, 120)[0], "FAIL-PROBE-NODE-COVERAGE")


if __name__ == "__main__":
    unittest.main()

