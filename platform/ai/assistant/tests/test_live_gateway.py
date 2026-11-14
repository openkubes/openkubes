"""Live gateway isolation and fail-closed behavior (no network in tests)."""
import hashlib
import socket
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from public_beta.live_gateway import FALLBACK, LiveGateway

REV = "a" * 40
REPO = "openkubes/ok-local"
PATH = "docs/tutorial-basic.md"
URL = f"https://github.com/{REPO}/blob/{REV}/{PATH}"
TEXT = "Install on Ubuntu VM.\n\n" + chr(96) * 3 + "bash\necho safe\n" + chr(96) * 3
SID = hashlib.sha256(f"{REPO}:{REV}:{PATH}:0".encode()).hexdigest()[:16]


def index():
    return {"schema_version": 1, "corpus": [{
        "source_id": SID, "repo": REPO, "path": PATH, "revision": REV,
        "chunk_number": 0, "section": "Install", "url": URL,
        "sha256": hashlib.sha256(TEXT.encode()).hexdigest(), "text": TEXT,
    }]}


class LiveGatewayTests(unittest.TestCase):
    def test_validated_answer_is_explicitly_lab_only(self):
        answer = "Read [Install](" + URL + ")\n\n" + chr(96) * 3 + "bash\necho safe\n" + chr(96) * 3
        gateway = LiveGateway(index(), agent=lambda question: answer)
        status, reply = gateway.ask("Install ok-local")
        self.assertEqual(status, 200)
        self.assertFalse(reply["demo"])
        self.assertTrue(reply["lab_only"])
        self.assertEqual(reply["provenance"], "independent_local_retrieval")
        self.assertEqual(reply["answer"], answer)

    def test_unverified_command_fails_closed_without_leak(self):
        answer = "SECRET_PRIVATE_TEXT\n" + chr(96) * 3 + "bash\necho invented\n" + chr(96) * 3 + "\n[Source](" + URL + ")"
        gateway = LiveGateway(index(), agent=lambda question: answer)
        status, reply = gateway.ask("Install ok-local")
        self.assertEqual(status, 422)
        self.assertEqual(reply, {"error": "answer_rejected", "message": FALLBACK})
        self.assertNotIn("SECRET_PRIVATE_TEXT", str(reply))
        self.assertNotIn("echo invented", str(reply))

    def test_untrusted_citation_fails_closed(self):
        gateway = LiveGateway(index(), agent=lambda question: "[Source](https://example.org/untrusted)")
        status, reply = gateway.ask("Install ok-local")
        self.assertEqual(status, 422)
        self.assertEqual(reply["error"], "answer_rejected")
        self.assertNotIn("example.org", str(reply))

    def test_timeout_returns_safe_error(self):
        def timeout(question):
            raise socket.timeout("PRIVATE kagent URL")
        gateway = LiveGateway(index(), agent=timeout)
        status, reply = gateway.ask("Install ok-local")
        self.assertEqual(status, 503)
        self.assertEqual(reply, {"error": "agent_unavailable", "message": FALLBACK})
        self.assertNotIn("PRIVATE", str(reply))

    def test_no_source_does_not_call_agent(self):
        def forbidden(question):
            raise AssertionError("agent must not be invoked")
        gateway = LiveGateway(index(), agent=forbidden)
        status, body = gateway.ask("zzzzunmatched")
        self.assertEqual(status, 422)
        self.assertEqual(body["error"], "no_verified_source")

    def test_invalid_question_does_not_call_agent(self):
        gateway = LiveGateway(index(), agent=lambda question: self.fail("called"))
        status, body = gateway.ask(" ")
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "invalid_question")


if __name__ == "__main__":
    unittest.main()
