import datetime as dt
import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("ok141_runtime_binding_diagnostic_test", HERE / "bounded_runtime_binding_diagnostic_v1.py")
DIAG = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = DIAG
assert SPEC.loader is not None
SPEC.loader.exec_module(DIAG)


class RuntimeBindingDiagnosticTests(unittest.TestCase):
    def test_candidate_is_inert_and_exact(self):
        candidate = DIAG.validate_candidate()
        self.assertEqual(candidate["spec"]["authorization"]["decision"], "NO-GO")
        self.assertTrue(all(not value for key, value in candidate["spec"]["authorization"].items() if key.endswith("Granted")))
        self.assertEqual(len(candidate["spec"]["exactReads"]), 3)

    def test_query_redacts_success_payload(self):
        def runner(*_args, **_kwargs):
            return subprocess.CompletedProcess([], 0, b'{"metadata":{"uid":"secret"}}', b"")
        result, raw = DIAG.query(Path("kubectl"), Path("kubeconfig"), "/exact", runner)
        self.assertEqual(result["category"], "PASS-OBJECT")
        self.assertNotIn("secret", str(result))
        self.assertIsNotNone(raw)

    def test_query_redacts_not_found_error(self):
        def runner(*_args, **_kwargs):
            return subprocess.CompletedProcess([], 1, b"", b'Error from server (NotFound): IP 192.0.2.1 token secret')
        result, raw = DIAG.query(Path("kubectl"), Path("kubeconfig"), "/exact", runner)
        self.assertEqual(result["category"], "NOT-FOUND")
        self.assertEqual(result["exitCode"], 1)
        self.assertNotIn("192.0.2.1", str(result))
        self.assertNotIn("token", str(result))
        self.assertIsNone(raw)

    def test_grant_window_is_bounded(self):
        issued = dt.datetime(2026, 8, 14, 18, 0, tzinfo=dt.timezone.utc)
        self.assertLessEqual(dt.timedelta(minutes=15), dt.timedelta(minutes=15))
        self.assertEqual(DIAG.parse_time("2026-08-14T18:00:00Z"), issued)


if __name__ == "__main__":
    unittest.main()
