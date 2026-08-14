import copy
import datetime as dt
import importlib.util
import sys
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("ok141_network_cache_timing_test", HERE / "bounded_network_cache_timing_diagnostic_v1.py")
DIAG = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = DIAG
assert SPEC.loader is not None
SPEC.loader.exec_module(DIAG)


class TimingDiagnosticTests(unittest.TestCase):
    def payload(self, status_marker="omitted"):
        def protocol(seconds):
            item = {"lastProbed": f"2026-08-14T15:2{seconds}:00Z", "latency": 10}
            if status_marker != "omitted":
                item["status"] = status_marker
            return item
        path = {"http": protocol(8), "icmp": protocol(9)}
        return {"timestamp": "2026-08-14T15:28:00Z", "probeInterval": "1m36.566s", "nodes": [{"name": name, "host": {"primary-address": copy.deepcopy(path)}, "health-endpoint": {"primary-address": copy.deepcopy(path)}} for name in ("node-0", "node-1")]}

    def test_candidate_is_inert_and_source_locked(self):
        candidate = DIAG.validate_candidate()
        self.assertEqual(candidate["spec"]["authorization"]["decision"], "NO-GO")
        self.assertTrue(all(not value for key, value in candidate["spec"]["authorization"].items() if key.endswith("Granted")))

    def test_go_duration_parser(self):
        self.assertAlmostEqual(DIAG.parse_duration("1m36.566s"), 96.566)
        self.assertAlmostEqual(DIAG.parse_duration("2h1m1.5s"), 7261.5)

    def test_timing_summary_is_redacted_and_complete(self):
        now = dt.datetime(2026, 8, 14, 15, 31, tzinfo=dt.timezone.utc)
        state, details = DIAG.timing_summary(self.payload(), ["node-0", "node-1"], now)
        self.assertEqual(state, "PASS-CACHED-HEALTH-TIMING-OBSERVED")
        self.assertEqual(details["probeIntervalSeconds"], 96.566)
        self.assertEqual(details["pathCount"], 8)
        self.assertEqual(details["statusCategoryCounts"], {"success": 8, "failure": 0, "invalid": 0})
        self.assertNotIn("nodes", details)

    def test_nonempty_status_is_counted_without_retaining_text(self):
        now = dt.datetime(2026, 8, 14, 15, 31, tzinfo=dt.timezone.utc)
        state, details = DIAG.timing_summary(self.payload("Connection timed out"), ["node-0", "node-1"], now)
        self.assertEqual(state, "OBSERVED-NON-SUCCESS-STATUS")
        self.assertEqual(details["statusCategoryCounts"]["failure"], 8)
        self.assertNotIn("Connection timed out", str(details))

    def test_wrong_coverage_fails_closed(self):
        now = dt.datetime(2026, 8, 14, 15, 31, tzinfo=dt.timezone.utc)
        self.assertEqual(DIAG.timing_summary(self.payload(), ["node-0"], now)[0], "FAIL-NODE-COVERAGE")


if __name__ == "__main__":
    unittest.main()

