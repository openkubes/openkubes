import importlib.util
import json
import sys
import unittest
from pathlib import Path

import yaml


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("ok141_platform_diag_test", HERE / "bounded_platform_convergence_diagnostic_v1.py")
DIAG = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = DIAG
assert SPEC.loader is not None
SPEC.loader.exec_module(DIAG)


class PlatformDiagnosticTests(unittest.TestCase):
    def test_candidate_is_inert_and_exact(self):
        candidate = DIAG.validate_candidate()
        self.assertEqual(candidate["spec"]["authorization"]["decision"], "NO-GO")
        self.assertEqual(len(candidate["spec"]["argo"]["applications"]), 3)
        self.assertFalse(candidate["spec"]["failedRun"]["retryAllowed"])

    def test_template_is_no_go(self):
        value = yaml.safe_load((HERE / "platform-convergence-diagnostic-grant-v1.template.yaml").read_text())
        self.assertEqual(value["spec"]["decision"], "NO-GO")
        self.assertTrue(all(not item for key, item in value["spec"].items() if key.endswith("Granted")))

    def test_summary_redacts_messages_and_resource_names(self):
        value = {
            "kind": "Application", "metadata": {"name": "app"},
            "spec": {"source": {"targetRevision": "commit"}},
            "status": {
                "sync": {"status": "OutOfSync", "revision": "old"}, "health": {"status": "Degraded"},
                "conditions": [{"type": "ComparisonError", "message": "failed to load target state from private URL"}],
                "operationState": {"phase": "Failed", "message": "forbidden secret text"},
                "resources": [{"group": "apps", "kind": "Deployment", "name": "private-name", "status": "OutOfSync", "health": {"status": "Degraded"}}],
            },
        }
        summary = DIAG.summarize_application(value, "app", "commit")
        rendered = json.dumps(summary)
        self.assertNotIn("private URL", rendered)
        self.assertNotIn("secret text", rendered)
        self.assertNotIn("private-name", rendered)
        self.assertEqual(summary["conditions"][0]["messageCategory"], "SOURCE-OR-RENDER")
        self.assertEqual(summary["operation"]["messageCategory"], "AUTHORIZATION")

    def test_ready_requires_exact_revision_sync_and_health(self):
        base = {"kind": "Application", "metadata": {"name": "app"}, "spec": {"source": {"targetRevision": "commit"}}, "status": {"sync": {"status": "Synced", "revision": "commit"}, "health": {"status": "Healthy"}}}
        self.assertTrue(DIAG.summarize_application(base, "app", "commit")["ready"])
        base["status"]["sync"]["revision"] = "other"
        self.assertFalse(DIAG.summarize_application(base, "app", "commit")["ready"])

    def test_authority_sets_are_disjoint(self):
        self.assertFalse(set(DIAG.TRUE) & set(DIAG.FALSE))
        self.assertIn("mutationGranted", DIAG.FALSE)
        self.assertIn("secretReadGranted", DIAG.FALSE)


if __name__ == "__main__":
    unittest.main()
