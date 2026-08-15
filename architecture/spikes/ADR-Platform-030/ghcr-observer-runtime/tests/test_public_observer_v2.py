import datetime as dt
import importlib.util
import json
import sys
import unittest
import urllib.error
from email.message import Message
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("ok141_public_observer_v2_test", HERE / "observe_public_ghcr_evidence_v2.py")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

DIGEST = "sha256:c9bdeadf1ee859c69ed0ab1136ec6b590139fe931eff44039265c144cea76dc8"
NOW = dt.datetime(2026, 8, 11, 17, 50, tzinfo=dt.timezone.utc)


class Response:
    def __init__(self, digest=None, payload=None):
        self.headers = {"Docker-Content-Digest": digest}
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


class PublicObserverV2Tests(unittest.TestCase):
    def test_public_bearer_challenge_succeeds_without_credentials(self):
        challenge = 'Bearer realm="https://ghcr.io/token",service="ghcr.io",scope="repository:openkubes/ok141-evidence:pull"'
        calls = []

        def opener(request, timeout):
            calls.append(request)
            if len(calls) == 1:
                headers = Message()
                headers["WWW-Authenticate"] = challenge
                raise urllib.error.HTTPError(request.full_url, 401, "auth", headers, None)
            if len(calls) == 2:
                return Response(payload={"token": "ephemeral-public-pull-token"})
            return Response(DIGEST)

        result = MODULE.observe_public(DIGEST, opener, NOW)
        self.assertEqual((result["status"], result["observedDigest"]), ("PRESENT", DIGEST))
        self.assertEqual(len(calls), 3)
        self.assertIsNone(calls[1].get_header("Authorization"))
        self.assertNotIn("ephemeral-public-pull-token", str(result))

    def test_direct_public_head_succeeds(self):
        result = MODULE.observe_public(DIGEST, lambda _request, timeout: Response(DIGEST), NOW)
        self.assertEqual((result["status"], result["reason"]), ("PRESENT", "AnonymousManifestHeadSucceeded"))

    def test_rejected_challenge_fails_closed(self):
        def opener(request, timeout):
            raise urllib.error.HTTPError(request.full_url, 401, "auth", Message(), None)

        result = MODULE.observe_public(DIGEST, opener, NOW)
        self.assertEqual((result["status"], result["reason"]), ("DENIED", "RegistryChallengeRejected"))

    def test_error_classes_fail_closed(self):
        expected = {403: ("DENIED", "PackageReadDenied"), 404: ("MISSING", "DigestMissing"), 500: ("UNVERIFIABLE", "RegistryHTTP500")}
        for status, outcome in expected.items():
            def opener(request, timeout, code=status):
                raise urllib.error.HTTPError(request.full_url, code, "error", Message(), None)

            with self.subTest(status=status):
                result = MODULE.observe_public(DIGEST, opener, NOW)
                self.assertEqual((result["status"], result["reason"]), outcome)


if __name__ == "__main__":
    unittest.main()
