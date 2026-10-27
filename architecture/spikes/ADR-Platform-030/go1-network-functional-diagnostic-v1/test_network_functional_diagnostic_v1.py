import copy
import importlib.util
import sys
import unittest
from pathlib import Path

import yaml


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("ok141_functional_diagnostic_test", HERE / "bounded_network_functional_diagnostic_v1.py")
RUN = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = RUN
assert SPEC.loader is not None
SPEC.loader.exec_module(RUN)


class FunctionalDiagnosticTests(unittest.TestCase):
    def test_candidate_is_inert_and_probe_is_fixed(self):
        candidate = RUN.validate_candidate()
        self.assertEqual(candidate["spec"]["authorization"]["decision"], "NO-GO")
        self.assertEqual(candidate["spec"]["probe"]["command"], list(RUN.PROBE))

    def test_status_classification_is_redacted(self):
        self.assertEqual(RUN.classify("")[0], "PASS")
        self.assertEqual(RUN.classify("Connection timed out to 192.0.2.1")[0], "TIMEOUT")
        self.assertEqual(RUN.classify("connection refused")[0], "REFUSED")
        category, digest = RUN.classify("sensitive arbitrary value")
        self.assertEqual(category, "OTHER")
        self.assertTrue(digest.startswith("sha256:"))

    def probe(self, status=""):
        path = {"http": {"status": status, "lastProbed": "2026-08-14T15:00:00Z"}, "icmp": {"status": "", "lastProbed": "2026-08-14T15:00:00Z"}}
        return {"nodes": [{"name": name, "host": {"primary-address": copy.deepcopy(path)}, "health-endpoint": {"primary-address": copy.deepcopy(path)}} for name in ("cp", "worker")]}

    def test_probe_summary_identifies_path_without_status_text(self):
        state, details = RUN.summarize_probe(self.probe("Connection timed out to 192.0.2.1"), ["cp", "worker"])
        self.assertEqual(state, "OBSERVED-FUNCTIONAL-CONNECTIVITY-FAILURE")
        failed = [item for item in details["paths"] if item["category"] != "PASS"]
        self.assertEqual(len(failed), 4)
        self.assertTrue(all("192.0.2.1" not in str(item) for item in failed))

    def test_probe_summary_passes_all_paths(self):
        state, details = RUN.summarize_probe(self.probe(), ["cp", "worker"])
        self.assertEqual(state, "PASS-CURRENT-FUNCTIONAL-CONNECTIVITY")
        self.assertEqual(details["pathCount"], 8)

    def test_grant_template_is_no_go(self):
        template = yaml.safe_load((HERE / "network-functional-diagnostic-grant-v1.template.yaml").read_text())
        self.assertEqual(template["spec"]["decision"], "NO-GO")
        self.assertTrue(all(not value for key, value in template["spec"].items() if key.endswith("Granted")))


if __name__ == "__main__":
    unittest.main()
