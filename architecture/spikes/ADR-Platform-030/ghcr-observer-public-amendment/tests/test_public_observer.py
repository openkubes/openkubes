import datetime as dt
import importlib.util
import sys
import unittest
import urllib.error
from email.message import Message
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("ok141_public_observer_test", HERE / "observe_public_ghcr_evidence.py")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

DIGEST = "sha256:c9bdeadf1ee859c69ed0ab1136ec6b590139fe931eff44039265c144cea76dc8"
NOW = dt.datetime(2026, 8, 11, 17, 50, tzinfo=dt.timezone.utc)


class Response:
    def __init__(self, digest):
        self.headers = {"Docker-Content-Digest": digest}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class PublicObserverTests(unittest.TestCase):
    def test_anonymous_exact_digest_succeeds(self):
        result = MODULE.observe_public(DIGEST, lambda _request, timeout: Response(DIGEST), NOW)
        self.assertEqual((result["status"], result["observedDigest"]), ("PRESENT", DIGEST))
        self.assertEqual(result["reason"], "AnonymousManifestHeadSucceeded")

    def test_mismatch_remains_visible_to_frozen_evaluator(self):
        wrong = "sha256:" + "d" * 64
        result = MODULE.observe_public(DIGEST, lambda _request, timeout: Response(wrong), NOW)
        self.assertEqual(result["observedDigest"], wrong)

    def test_denied_missing_and_other_errors_fail_closed(self):
        expected = {401: ("DENIED", "PackageReadDenied"), 403: ("DENIED", "PackageReadDenied"), 404: ("MISSING", "DigestMissing"), 500: ("UNVERIFIABLE", "RegistryHTTP500")}
        for status, outcome in expected.items():
            def opener(request, timeout, code=status):
                raise urllib.error.HTTPError(request.full_url, code, "error", Message(), None)
            with self.subTest(status=status):
                result = MODULE.observe_public(DIGEST, opener, NOW)
                self.assertEqual((result["status"], result["reason"]), outcome)

    def test_missing_digest_header_is_unverifiable(self):
        result = MODULE.observe_public(DIGEST, lambda _request, timeout: Response(None), NOW)
        self.assertEqual((result["status"], result["reason"]), ("UNVERIFIABLE", "DigestHeaderMissing"))

    def test_no_credential_inputs_or_output(self):
        result = MODULE.observe_public(DIGEST, lambda _request, timeout: Response(DIGEST), NOW)
        rendered = str(result)
        for forbidden in ("token", "password", "authorization", "kubeconfig"):
            self.assertNotIn(forbidden, rendered.lower())


if __name__ == "__main__":
    unittest.main()
