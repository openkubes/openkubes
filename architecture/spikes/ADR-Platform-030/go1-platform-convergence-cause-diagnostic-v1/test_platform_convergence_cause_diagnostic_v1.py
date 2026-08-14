import importlib.util
import json
import sys
import unittest
from pathlib import Path

import yaml


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("ok141_platform_cause_test", HERE / "bounded_platform_convergence_cause_diagnostic_v1.py")
CAUSE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = CAUSE
assert SPEC.loader is not None
SPEC.loader.exec_module(CAUSE)


class PlatformCauseDiagnosticTests(unittest.TestCase):
    def test_candidate_is_inert(self):
        candidate = CAUSE.validate_candidate()
        self.assertEqual(candidate["spec"]["authorization"]["decision"], "NO-GO")
        self.assertFalse(candidate["spec"]["classification"]["rawMessagesRetained"])

    def test_template_is_no_go(self):
        value = yaml.safe_load((HERE / "platform-convergence-cause-diagnostic-grant-v1.template.yaml").read_text())
        self.assertEqual(value["spec"]["decision"], "NO-GO")
        self.assertTrue(all(not item for key, item in value["spec"].items() if key.endswith("Granted")))

    def test_target_tls_and_rpc_are_separate_indicators(self):
        result = CAUSE.classify("rpc error: code = Unavailable: failed to load live state: dial tcp: x509: certificate signed by unknown authority")
        self.assertEqual(result["indicators"], ["RPC", "TARGET-CONNECTION", "TLS"])
        self.assertEqual(result["rpcCodes"], ["Unavailable"])
        self.assertNotIn("live state", json.dumps(result))

    def test_manifest_and_repository_are_separate(self):
        result = CAUSE.classify("failed to generate manifest: unable to resolve git revision")
        self.assertEqual(result["indicators"], ["MANIFEST-GENERATION", "REPOSITORY"])

    def test_application_output_has_no_raw_message(self):
        value = {"kind": "Application", "metadata": {"name": "app"}, "status": {"sync": {"status": "Unknown", "revision": "rev"}, "health": {"status": "Healthy"}, "conditions": [{"type": "ComparisonError", "message": "forbidden super-private-value"}]}}
        result = CAUSE.application_causes(value, "app", "rev")
        self.assertNotIn("super-private-value", json.dumps(result))
        self.assertEqual(result["messages"][0]["indicators"], ["AUTHORIZATION"])

    def test_authority_sets_are_disjoint(self):
        self.assertFalse(set(CAUSE.TRUE) & set(CAUSE.FALSE))
        self.assertIn("mutationGranted", CAUSE.FALSE)


if __name__ == "__main__":
    unittest.main()
