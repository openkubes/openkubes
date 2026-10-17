"""Offline regression tests for private gateway -> context-only A2A probe."""
import hashlib
import json
import socket
import urllib.error
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from docs_mcp import DocsRetriever
from public_beta.private_context_gateway_probe import (
    CONTEXT_A2A_URL, MAX_A2A_RESPONSE_BYTES, A2ADiagnosticError,
    run_private_gateway_probe, send_private_context,
)

REPO = "openkubes/ok-local"
REV = "a" * 40
PATH = "docs/tutorial-basic.md"
TEXT = "OpenKubes Local installation overview."
SID = hashlib.sha256(f"{REPO}:{REV}:{PATH}:0".encode()).hexdigest()[:16]
QUESTION = "How do I install OpenKubes Local?"


def fixture():
    return {"schema_version": 1, "corpus": [{
        "source_id": SID, "repo": REPO, "path": PATH, "revision": REV,
        "chunk_number": 0, "section": "Installation",
        "url": f"https://github.com/{REPO}/blob/{REV}/{PATH}",
        "sha256": hashlib.sha256(TEXT.encode()).hexdigest(), "text": TEXT,
    }]}


def answer(ids=None, text="Read the installation overview."):
    return json.dumps({"version": "0.1", "steps": [
        {"text": text, "source_ids": [SID] if ids is None else ids},
    ]})


class ContextGatewayProbeTests(unittest.TestCase):
    def setUp(self):
        self.index = fixture()

    def test_completed_structured_response(self):
        seen = []
        def sender(encoded):
            seen.append(json.loads(encoded))
            return answer()
        outcome = run_private_gateway_probe(self.index, QUESTION, send=sender)
        self.assertEqual(outcome["status"], "PASS")
        self.assertEqual(outcome["semantic_grounding"], "UNVERIFIED")
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0]["sources"][0]["source_id"], SID)
        self.assertEqual(seen[0]["sources"][0]["snippet"], TEXT)
        self.assertEqual(outcome["retrieved_chunks"], 1)
        self.assertNotIn("raw_answer", outcome)

    def test_invalid_source_id_fails_closed(self):
        outcome = run_private_gateway_probe(self.index, QUESTION,
            send=lambda _: answer(ids=["f" * 16]))
        self.assertEqual(outcome["status"], "REJECT")
        self.assertEqual(outcome["reason"], "invalid_sources")

    def test_invalid_json_fails_closed(self):
        outcome = run_private_gateway_probe(self.index, QUESTION,
            send=lambda _: "{bad-json")
        self.assertEqual(outcome["reason"], "invalid_json")

    def test_no_sources_never_calls_a2a(self):
        outcome = run_private_gateway_probe(self.index, "xyzzy nothing matching",
            send=lambda _: self.fail("A2A must never be called"))
        self.assertEqual(outcome["status"], "NO_SOURCES")

    def test_invalid_question_never_calls_a2a(self):
        for question in ("", " leading", "x" * 501, "line\nbreak"):
            with self.subTest(question=question[:12]):
                outcome = run_private_gateway_probe(self.index, question,
                    send=lambda _: self.fail("A2A must never be called"))
                self.assertEqual(outcome["reason"], "invalid_question")

    def test_transport_failure_has_no_exception_text(self):
        secret = "secret-token-value-do-not-log"
        def sender(_):
            raise RuntimeError(secret)
        outcome = run_private_gateway_probe(self.index, QUESTION, send=sender)
        self.assertEqual(outcome["status"], "ERROR")
        self.assertNotIn(secret, json.dumps(outcome))
        self.assertEqual(outcome["reason"], "a2a_transport_or_task_error")

    def test_http_gateway_timeout_is_classified_without_body(self):
        secret = "private upstream error body"
        def sender(_):
            raise urllib.error.HTTPError(
                CONTEXT_A2A_URL, 504, secret, {}, None)
        outcome = run_private_gateway_probe(self.index, QUESTION, send=sender)
        self.assertEqual(outcome["reason"], "a2a_http_504")
        self.assertNotIn(secret, json.dumps(outcome))

    def test_http_bad_gateway_classified(self):
        def sender(_):
            raise urllib.error.HTTPError(
                CONTEXT_A2A_URL, 502, "sensitive", {}, None)
        outcome = run_private_gateway_probe(self.index, QUESTION, send=sender)
        self.assertEqual(outcome["reason"], "a2a_http_502")

    def test_other_http_status_classified_without_status_reflection(self):
        def sender(_):
            raise urllib.error.HTTPError(
                CONTEXT_A2A_URL, 503, "sensitive", {}, None)
        outcome = run_private_gateway_probe(self.index, QUESTION, send=sender)
        self.assertEqual(outcome["reason"], "a2a_http_error")

    def test_client_timeout_is_classified(self):
        def sender(_):
            raise socket.timeout("sensitive timeout details")
        outcome = run_private_gateway_probe(self.index, QUESTION, send=sender)
        self.assertEqual(outcome["reason"], "a2a_client_timeout")

    def test_url_error_timeout_is_classified(self):
        def sender(_):
            raise urllib.error.URLError(socket.timeout("sensitive"))
        outcome = run_private_gateway_probe(self.index, QUESTION, send=sender)
        self.assertEqual(outcome["reason"], "a2a_client_timeout")

    def test_url_error_connection_is_classified(self):
        def sender(_):
            raise urllib.error.URLError("sensitive")
        outcome = run_private_gateway_probe(self.index, QUESTION, send=sender)
        self.assertEqual(outcome["reason"], "a2a_connection_error")

    def test_incomplete_task_error_classified(self):
        def sender(_):
            raise A2ADiagnosticError("a2a_task_incomplete")
        outcome = run_private_gateway_probe(self.index, QUESTION, send=sender)
        self.assertEqual(outcome["reason"], "a2a_task_incomplete")

    def test_refuses_command_looking_answer(self):
        outcome = run_private_gateway_probe(self.index, QUESTION,
            send=lambda _: answer(text="Run kubectl get pods."))
        self.assertEqual(outcome["reason"], "unsupported_text")

    def test_a2a_endpoint_is_fixed_and_loopback(self):
        self.assertEqual(CONTEXT_A2A_URL,
            "http://127.0.0.1:8083/api/a2a/"
            "openkubes-assistant/openkubes-docs-agent-context-lab/")

    def test_transport_rejects_oversized_context_before_connection(self):
        with patch("urllib.request.build_opener") as opener:
            with self.assertRaises(ValueError):
                send_private_context("x" * (24 * 1024 + 1))
            opener.assert_not_called()

    def test_transport_sends_exact_serialized_context(self):
        index = fixture()
        hits = DocsRetriever(index).docs_search(QUESTION, limit=8)
        self.assertEqual(len(hits["results"]), 1)
        encoded = '{"kind":"openkubes.gateway.docs-context"}'
        completed = {"jsonrpc": "2.0", "result": {
            "kind": "task", "status": {"state": "completed"},
            "artifacts": [{"parts": [{"kind": "text", "text": answer()}]}],
        }}
        response = MagicMock()
        response.status = 200
        response.read.return_value = json.dumps(completed).encode()
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value = response
        with patch("urllib.request.build_opener", return_value=opener) as factory:
            self.assertEqual(send_private_context(encoded), answer())
        request = opener.open.call_args.args[0]
        posted = json.loads(request.data)
        self.assertEqual(posted["params"]["message"]["parts"][0]["text"], encoded)
        self.assertEqual(request.full_url, CONTEXT_A2A_URL)
        self.assertEqual(posted["params"]["configuration"], {"blocking": True})
        self.assertEqual(len(factory.call_args.args), 2)

    def test_incomplete_a2a_fails_closed(self):
        encoded = '{"x":1}'
        incomplete = {"jsonrpc": "2.0", "result": {
            "kind": "task", "status": {"state": "input-required"},
            "artifacts": [{"parts": [{"kind": "text", "text": answer()}]}],
        }}
        response = MagicMock()
        response.status = 200
        response.read.return_value = json.dumps(incomplete).encode()
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value = response
        with patch("urllib.request.build_opener", return_value=opener):
            with self.assertRaisesRegex(A2ADiagnosticError, "a2a_task_incomplete"):
                send_private_context(encoded)

    def test_jsonrpc_error_is_sanitized(self):
        response = MagicMock()
        response.status = 200
        response.read.return_value = json.dumps({
            "jsonrpc": "2.0",
            "error": {"code": -32000, "message": "private server details"},
        }).encode()
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value = response
        with patch("urllib.request.build_opener", return_value=opener):
            with self.assertRaisesRegex(A2ADiagnosticError, "a2a_jsonrpc_error"):
                send_private_context('{"x":1}')

    def test_invalid_jsonrpc_envelope_is_sanitized(self):
        response = MagicMock()
        response.status = 200
        response.read.return_value = b'{"unexpected":"response"}'
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value = response
        with patch("urllib.request.build_opener", return_value=opener):
            with self.assertRaisesRegex(A2ADiagnosticError, "a2a_invalid_jsonrpc"):
                send_private_context('{"x":1}')

    def test_unexpected_result_is_sanitized(self):
        response = MagicMock()
        response.status = 200
        response.read.return_value = b'{"jsonrpc":"2.0","result":{"kind":"message"}}'
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value = response
        with patch("urllib.request.build_opener", return_value=opener):
            with self.assertRaisesRegex(A2ADiagnosticError, "a2a_unexpected_result"):
                send_private_context('{"x":1}')

    def test_completed_task_without_artifact_is_sanitized(self):
        response = MagicMock()
        response.status = 200
        response.read.return_value = b'{"jsonrpc":"2.0","result":{"kind":"task","status":{"state":"completed"},"artifacts":[]}}'
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value = response
        with patch("urllib.request.build_opener", return_value=opener):
            with self.assertRaisesRegex(A2ADiagnosticError, "a2a_invalid_artifact"):
                send_private_context('{"x":1}')

    def test_oversized_response_is_rejected(self):
        response = MagicMock()
        response.status = 200
        response.read.return_value = b"x" * (MAX_A2A_RESPONSE_BYTES + 1)
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value = response
        with patch("urllib.request.build_opener", return_value=opener):
            with self.assertRaisesRegex(A2ADiagnosticError, "a2a_response_oversized"):
                send_private_context('{"x":1}')


if __name__ == "__main__":
    unittest.main()
