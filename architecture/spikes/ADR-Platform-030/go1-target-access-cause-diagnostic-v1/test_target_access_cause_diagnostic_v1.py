import importlib.util
import json
import sys
import unittest
from pathlib import Path

import yaml


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("ok141_target_cause_test", HERE / "bounded_target_access_cause_diagnostic_v1.py")
CAUSE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = CAUSE
assert SPEC.loader is not None
SPEC.loader.exec_module(CAUSE)


class TargetCauseTests(unittest.TestCase):
    def test_candidate_is_inert(self):
        value = CAUSE.validate_candidate()
        self.assertEqual(value["spec"]["authorization"]["decision"], "NO-GO")

    def test_template_is_no_go(self):
        value = yaml.safe_load((HERE / "target-access-cause-diagnostic-grant-v1.template.yaml").read_text())
        self.assertEqual(value["spec"]["decision"], "NO-GO")
        self.assertTrue(all(not item for key, item in value["spec"].items() if key.endswith("Granted")))

    def test_classification_categories(self):
        cases = [
            (0, b'{"kind":"Namespace"}', b"", "SUCCESS"),
            (1, b"", b"dial tcp: connect: connection refused", "TARGET-CONNECTION"),
            (1, b"", b"lookup target: no such host", "DNS"),
            (1, b"", b"x509: certificate signed by unknown authority", "TLS"),
            (1, b'{"reason":"Unauthorized","code":401}', b"", "AUTHENTICATION"),
            (1, b'{"reason":"Forbidden","code":403}', b"", "AUTHORIZATION"),
            (1, b'{"reason":"NotFound","code":404}', b"", "NOT-FOUND"),
            (1, b"", b"opaque error", "UNKNOWN"),
        ]
        for code, stdout, stderr, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(CAUSE.classify(code, stdout, stderr)[0], expected)

    def test_classification_retains_only_status_code(self):
        category, status = CAUSE.classify(1, json.dumps({"reason": "Forbidden", "message": "sensitive target text", "code": 403}).encode(), b"")
        self.assertEqual((category, status), ("AUTHORIZATION", 403))

    def test_authority_sets_are_disjoint(self):
        self.assertFalse(set(CAUSE.TRUE) & set(CAUSE.FALSE))
        self.assertIn("mutationGranted", CAUSE.FALSE)
        self.assertIn("happyRunResumeGranted", CAUSE.FALSE)

    def test_publication_scope_is_redacted_and_bound(self):
        publication = yaml.safe_load((HERE / "publication-candidate-v1.yaml").read_text())
        self.assertEqual(publication["spec"]["decision"], "BLOCKED-NO-PUBLICATION")
        self.assertIn("private Evidence under /private/tmp", publication["spec"]["excludes"])
        for name, digest in publication["spec"]["scope"]["files"].items():
            if name != "test_target_access_cause_diagnostic_v1.py":
                self.assertEqual(CAUSE.sha(HERE / name), digest)


if __name__ == "__main__":
    unittest.main()
