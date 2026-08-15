import importlib.util
import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path

import yaml


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("ok141_default_audience_test", HERE / "bounded_default_audience_diagnostic_v1.py")
AUDIENCE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = AUDIENCE
assert SPEC.loader is not None
SPEC.loader.exec_module(AUDIENCE)


class DefaultAudienceTests(unittest.TestCase):
    def test_candidate_is_inert(self):
        value = AUDIENCE.validate_candidate()
        self.assertEqual(value["spec"]["authorization"]["decision"], "NO-GO")

    def test_template_is_no_go(self):
        value = yaml.safe_load((HERE / "default-audience-diagnostic-grant-v1.template.yaml").read_text())
        self.assertEqual(value["spec"]["decision"], "NO-GO")
        self.assertTrue(all(not item for key, item in value["spec"].items() if key.endswith("Granted")))

    def test_token_request_uses_server_default_audience(self):
        value = AUDIENCE.token_request_document(600)
        self.assertEqual(value["spec"], {"expirationSeconds": 600})
        self.assertNotIn("audiences", value["spec"])

    def test_raw_request_is_exact(self):
        calls = []

        def runner(command, **kwargs):
            calls.append((command, kwargs))
            return subprocess.CompletedProcess(command, 0, b"{}", b"")

        payload = json.dumps(AUDIENCE.token_request_document(600)).encode()
        result = AUDIENCE.raw_request(Path("/tmp/kubectl"), Path("/tmp/config"), "create", "/token", payload, runner)
        self.assertEqual(result[0], 0)
        self.assertEqual(calls[0][0], ["/tmp/kubectl", "--kubeconfig", "/tmp/config", "create", "--raw", "/token", "--filename", "-"])
        self.assertEqual(calls[0][1]["input"], payload)

    def test_authority_sets_are_disjoint(self):
        self.assertFalse(set(AUDIENCE.TRUE) & set(AUDIENCE.FALSE))
        self.assertIn("persistentMutationGranted", AUDIENCE.FALSE)
        self.assertIn("happyRunResumeGranted", AUDIENCE.FALSE)

    def test_publication_candidate_binds_only_redacted_files(self):
        publication = yaml.safe_load((HERE / "publication-candidate-v1.yaml").read_text())
        self.assertEqual(publication["spec"]["decision"], "BLOCKED-NO-PUBLICATION")
        self.assertEqual(publication["spec"]["validation"]["testsPassed"], 6)
        self.assertNotIn("publication-candidate-v1.yaml", publication["spec"]["scope"]["files"])
        for name, expected in publication["spec"]["scope"]["files"].items():
            actual = "sha256:" + hashlib.sha256((HERE / name).read_bytes()).hexdigest()
            self.assertEqual(actual, expected, name)


if __name__ == "__main__":
    unittest.main()
