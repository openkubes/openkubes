"""Private gateway-owned documentation RAG -> context-only A2A experiment.

NOT a web gateway, production transport, source provenance proof, or public
beta gate. Only a fixed loopback controller route is reachable. Never print
raw prompts, context snippets, model output, token material or internal URLs.
"""
from __future__ import annotations

import argparse
import json
import socket
import urllib.error
import urllib.request
import uuid

from docs_mcp import DocsRetriever, load_index
from public_beta.gateway_context import (
    ContextRejected, MAX_CONTEXT_BYTES, build_context_envelope,
    encode_context_envelope,
)
from public_beta.private_a2a_probe import _NoRedirect, extract_answer
from public_beta.structured_answer import ContractRejected, validate_and_render

CONTEXT_A2A_URL = (
    "http://127.0.0.1:8083/api/a2a/"
    "openkubes-assistant/openkubes-docs-agent-context-lab/"
)
MAX_A2A_RESPONSE_BYTES = 256 * 1024
A2A_TIMEOUT_SECONDS = 90
DEFAULT_QUESTION = "How do I install OpenKubes Local on macOS?"


class A2ADiagnosticError(Exception):
    """Static sanitized diagnosis; never store remote response details."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _transport_reason(exc: Exception) -> str:
    """Map errors to an explicit fixed allowlist, no exception text."""
    if isinstance(exc, A2ADiagnosticError):
        return exc.code
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code == 504:
            return "a2a_http_504"
        if exc.code == 502:
            return "a2a_http_502"
        return "a2a_http_error"
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return "a2a_client_timeout"
    if isinstance(exc, urllib.error.URLError):
        if isinstance(exc.reason, (TimeoutError, socket.timeout)):
            return "a2a_client_timeout"
        return "a2a_connection_error"
    return "a2a_transport_or_task_error"


def send_private_context(encoded_context: str) -> str:
    """Deliver only a bounded gateway envelope to one fixed localhost route.

    Caller has already performed trusted retrieval and index verification.
    This proves delivery/completed-task status, NOT model context consumption.
    """
    if not isinstance(encoded_context, str) or not (
        1 <= len(encoded_context.encode("utf-8")) <= MAX_CONTEXT_BYTES
    ):
        raise ValueError("invalid_encoded_context")
    message = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "message/send",
        "params": {
            "message": {
                "kind": "message",
                "role": "user",
                "messageId": str(uuid.uuid4()),
                "parts": [{"kind": "text", "text": encoded_context}],
            },
            "configuration": {"blocking": True},
        },
    }
    req = urllib.request.Request(
        CONTEXT_A2A_URL,
        data=json.dumps(message, separators=(",", ":")).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    # Disable environment-configured HTTP(S) proxies: no accidental off-box
    # forwarding of private context. Reject redirects regardless of status.
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), _NoRedirect()
    )
    with opener.open(req, timeout=A2A_TIMEOUT_SECONDS) as response:
        if response.status != 200:
            raise A2ADiagnosticError("a2a_http_error")
        data = response.read(MAX_A2A_RESPONSE_BYTES + 1)
    if len(data) > MAX_A2A_RESPONSE_BYTES:
        raise A2ADiagnosticError("a2a_response_oversized")
    try:
        payload = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise A2ADiagnosticError("a2a_protocol_error") from None
    try:
        return extract_answer(payload)
    except ValueError as exc:
        # Only inspect our own static extraction errors, never return text.
        if str(exc) == "A2A task did not complete":
            raise A2ADiagnosticError("a2a_task_incomplete") from None
        raise A2ADiagnosticError("a2a_protocol_error") from None


def run_private_gateway_probe(index: dict, question: str, *, send=None) -> dict:
    """Single authoritative retrieval; returned data is sanitized metadata.

    send(encoded_context) is injectable for offline tests. No reretrieval
    after inference, no agent-selected sources and no model-authored URL.
    """
    def outcome(status: str, reason: str, *, retrieved_chunks=0,
                context_sha256=None, rendered_chars=None) -> dict:
        result = {"status": status, "accepted": status == "PASS",
                  "reason": reason, "retrieved_chunks": retrieved_chunks,
                  "semantic_grounding": "UNVERIFIED"}
        if context_sha256 is not None:
            result["context_sha256"] = context_sha256
        if rendered_chars is not None:
            result["rendered_chars"] = rendered_chars
        return result

    try:
        # Reject invalid question BEFORE expensive retrieval or network calls.
        from public_beta.gateway_context import MAX_QUESTION_CHARS
        if (not isinstance(question, str) or
            not 1 <= len(question.strip()) <= MAX_QUESTION_CHARS or
            question != question.strip() or
            any(ord(ch) < 32 or ord(ch) == 127 for ch in question)):
            return outcome("REJECT", "invalid_question")
        hits = DocsRetriever(index).docs_search(question, limit=8)
        count = len(hits["results"])
        if not count:
            return outcome("NO_SOURCES", "no_verified_source")
        envelope = build_context_envelope(question, hits, index)
        encoded = encode_context_envelope(envelope)
    except (ValueError, TypeError, KeyError, ContextRejected):
        return outcome("REJECT", "invalid_gateway_context")

    sender = send if send is not None else send_private_context
    try:
        raw = sender(encoded)
    except Exception as exc:
        # Only fixed status codes; never log exception arguments or response.
        return outcome("ERROR", _transport_reason(exc),
                       retrieved_chunks=count,
                       context_sha256=envelope["context_sha256"])
    try:
        rendered = validate_and_render(raw, hits, index)
    except (ContractRejected, ValueError, TypeError, KeyError) as exc:
        # ContractRejected uses code-defined static reason strings only.
        reason = str(exc) if isinstance(exc, ContractRejected) else "invalid_answer"
        return outcome("REJECT", reason,
                       retrieved_chunks=count,
                       context_sha256=envelope["context_sha256"])
    return outcome("PASS", "format_and_source_ids_only",
                   retrieved_chunks=count,
                   context_sha256=envelope["context_sha256"],
                   rendered_chars=len(rendered))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", required=True)
    parser.add_argument("--question", default=DEFAULT_QUESTION)
    args = parser.parse_args()
    try:
        outcome = run_private_gateway_probe(load_index(args.index), args.question)
    except Exception:
        outcome = {"status": "ERROR", "accepted": False,
                   "reason": "index_or_runtime_error",
                   "semantic_grounding": "UNVERIFIED"}
    print(json.dumps(outcome, indent=2))
    if not outcome["accepted"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
