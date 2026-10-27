import copy
import datetime as dt
import importlib.util
import sys
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("ok141_cache_freshness_test", HERE / "network_cache_freshness_v1.py")
FRESH = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = FRESH
assert SPEC.loader is not None
SPEC.loader.exec_module(FRESH)


class CacheFreshnessTests(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime(2026, 8, 14, 16, 0, tzinfo=dt.timezone.utc)

    def payload(self, age=150, interval="1m36.566s", status="omitted"):
        timestamp = self.now - dt.timedelta(seconds=age)
        def item():
            value = {"lastProbed": timestamp.isoformat().replace("+00:00", "Z")}
            if status != "omitted":
                value["status"] = status
            return value
        path = {"http": item(), "icmp": item()}
        return {"timestamp": timestamp.isoformat().replace("+00:00", "Z"), "probeInterval": interval, "nodes": [{"name": name, "host": {"primary-address": copy.deepcopy(path)}, "health-endpoint": {"primary-address": copy.deepcopy(path)}} for name in ("node-0", "node-1")]}

    def test_candidate_is_inert(self):
        candidate = FRESH.validate_candidate()
        self.assertEqual(candidate["spec"]["authorization"]["decision"], "NO-GO")

    def test_source_derived_bound_accepts_age_above_historical_120(self):
        state, details = FRESH.evaluate_probe(self.payload(150), ["node-0", "node-1"], self.now)
        self.assertEqual(state, "PASS-FUNCTIONAL-NETWORK-PROBE")
        self.assertEqual(details["maximumAcceptedAgeSeconds"], 166.566)

    def test_age_above_dynamic_bound_fails(self):
        self.assertEqual(FRESH.evaluate_probe(self.payload(170), ["node-0", "node-1"], self.now)[0], "FAIL-STALE-CACHED-HEALTH-RESPONSE")

    def test_nonempty_and_null_status_fail(self):
        self.assertEqual(FRESH.evaluate_probe(self.payload(10, status="timeout"), ["node-0", "node-1"], self.now)[0], "FAIL-FUNCTIONAL-CONNECTIVITY")
        self.assertEqual(FRESH.evaluate_probe(self.payload(10, status=None), ["node-0", "node-1"], self.now)[0], "FAIL-FUNCTIONAL-CONNECTIVITY")

    def test_unbounded_or_invalid_interval_fails(self):
        self.assertEqual(FRESH.evaluate_probe(self.payload(10, interval="301s"), ["node-0", "node-1"], self.now)[0], "FAIL-CACHED-HEALTH-PROBE-INTERVAL")
        self.assertEqual(FRESH.evaluate_probe(self.payload(10, interval="invalid"), ["node-0", "node-1"], self.now)[0], "FAIL-CACHED-HEALTH-TIMING-METADATA")

    def test_future_timestamp_fails(self):
        self.assertEqual(FRESH.evaluate_probe(self.payload(-20), ["node-0", "node-1"], self.now)[0], "FAIL-STALE-CACHED-HEALTH-RESPONSE")


if __name__ == "__main__":
    unittest.main()

