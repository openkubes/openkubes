"""Offline HTTP boundary regressions: loopback-only, auth, rate, body limits."""
import hashlib
import http.client
import json
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from public_beta.curated_lite import REQUIRED_QUOTE
from public_beta.curated_lite_http import build_server, SlidingWindowLimiter

REPO = "openkubes/ok-local"
PATH = "docs/tutorial-basic.md"
REV = "a" * 40
TOKEN = "test-only-token-" + "x" * 48


def fixture():
    sid = hashlib.sha256(f"{REPO}:{REV}:{PATH}:0".encode()).hexdigest()[:16]
    return {"schema_version": 1, "corpus": [{
        "source_id": sid, "repo": REPO, "path": PATH,
        "revision": REV, "chunk_number": 0, "section": "Overview",
        "url": f"https://github.com/{REPO}/blob/{REV}/{PATH}",
        "text": REQUIRED_QUOTE,
        "sha256": hashlib.sha256(REQUIRED_QUOTE.encode()).hexdigest(),
    }]}


class HTTPBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.server = build_server(fixture(), TOKEN, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, body=None, token=TOKEN, path="/api/beta1-lite/question",
                method="POST", content_type="application/json", headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=2)
        data = (json.dumps({"question": "What is OpenKubes Local?"}).encode()
                if body is None else body)
        h = {"Content-Type": content_type}
        if token is not None:
            h["Authorization"] = "Bearer " + token
        if headers:
            h.update(headers)
        conn.request(method, path, body=data, headers=h)
        response = conn.getresponse()
        status = response.status
        payload = json.loads(response.read())
        metadata = dict(response.getheaders())
        conn.close()
        return status, payload, metadata

    def test_valid_curated_answer_is_source_bound(self):
        status, result, headers = self.request()
        self.assertEqual(status, 200)
        self.assertEqual(result["status"], "ANSWER")
        self.assertFalse(result["generative"])
        self.assertEqual(result["sources"][0]["revision"], REV)
        self.assertEqual(headers["Cache-Control"], "no-store")

    def test_bad_or_missing_bearer_is_rejected(self):
        for token in (None, "wrong-token"):
            with self.subTest(token=token):
                self.assertEqual(self.request(token=token)[0], 401)

    def test_no_unapproved_paths(self):
        self.assertEqual(self.request(path="/api/a2a/")[0], 404)
        self.assertEqual(self.request(method="GET", path="/")[0], 404)
        self.assertEqual(self.request(method="OPTIONS")[0], 405)

    def test_unknown_question_is_unsupported_not_generated(self):
        status, result, _ = self.request(body=json.dumps(
            {"question": "Explain OpenKubes Runner."}).encode())
        self.assertEqual(status, 200)
        self.assertEqual(result["status"], "UNSUPPORTED")
        self.assertEqual(result["sources"], [])

    def test_oversized_and_bad_json_are_rejected(self):
        self.assertEqual(self.request(body=b"x" * 1025)[0], 413)
        self.assertEqual(self.request(body=b"{bad")[0], 400)

    def test_extra_fields_and_bad_content_type_are_rejected(self):
        self.assertEqual(self.request(body=b'{"question":"x","extra":true}')[0], 400)
        self.assertEqual(self.request(content_type="text/plain")[0], 415)

    def test_rate_limit_is_bounded(self):
        limiter = SlidingWindowLimiter(limit=2, window=60, clock=lambda: 100)
        self.assertTrue(limiter.allow())
        self.assertTrue(limiter.allow())
        self.assertFalse(limiter.allow())

    def test_expired_rate_window_resets(self):
        clock = [100]
        limiter = SlidingWindowLimiter(limit=1, window=60, clock=lambda: clock[0])
        self.assertTrue(limiter.allow())
        self.assertFalse(limiter.allow())
        clock[0] = 160
        self.assertTrue(limiter.allow())

    def test_non_loopback_bind_refused(self):
        with self.assertRaisesRegex(ValueError, "loopback_only"):
            build_server(fixture(), TOKEN, host="0.0.0.0", port=0)

    def test_short_token_refused(self):
        with self.assertRaisesRegex(ValueError, "beta_auth_token_invalid"):
            build_server(fixture(), "short", port=0)

    def test_wrong_source_integrity_refused_at_startup(self):
        index = fixture()
        index["corpus"][0]["sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            build_server(index, TOKEN, port=0)


if __name__ == "__main__":
    unittest.main()
