import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path

import yaml


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("ok141_post_remediation_observer_test", HERE / "bounded_post_remediation_platform_observer_v1.py")
OBSERVER = importlib.util.module_from_spec(SPEC); sys.modules[SPEC.name] = OBSERVER
assert SPEC.loader is not None; SPEC.loader.exec_module(OBSERVER)


class ObserverTests(unittest.TestCase):
    def test_candidate_and_template_are_inert(self):
        value = OBSERVER.validate_candidate()
        self.assertEqual(value["spec"]["authorization"]["decision"], "NO-GO")
        template = yaml.safe_load((HERE / "post-remediation-platform-observer-grant-v1.template.yaml").read_text())
        self.assertEqual(template["spec"]["decision"], "NO-GO")

    def test_authority_is_read_only(self):
        self.assertFalse(set(OBSERVER.TRUE) & set(OBSERVER.FALSE))
        self.assertIn("mutationGranted", OBSERVER.FALSE)
        self.assertIn("capabilityTestGranted", OBSERVER.FALSE)

    def test_summarizer_requires_exact_revision_sync_and_health(self):
        value = {"kind": "Application", "metadata": {"name": "app"}, "spec": {"source": {"targetRevision": "rev"}}, "status": {"sync": {"revision": "rev", "status": "Synced"}, "health": {"status": "Healthy"}}}
        self.assertTrue(OBSERVER.DIAG.summarize_application(value, "app", "rev")["ready"])
        value["status"]["sync"]["revision"] = "old"
        self.assertFalse(OBSERVER.DIAG.summarize_application(value, "app", "rev")["ready"])


if __name__ == "__main__": unittest.main()
