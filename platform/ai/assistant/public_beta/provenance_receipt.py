"""Offline prototype for authenticated MCP retrieval receipts (NOT LIVE).

Only a trusted MCP handler possessing a separately provisioned signing key may
issue a receipt. No agent-generated receipt is trusted. A valid receipt proves
its metadata was signed; it does NOT prove the LLM saw the results or that
the text of a claim is supported. Runtime request propagation is unimplemented.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re

from docs_mcp import validate_index

HEX = re.compile(r"^[0-9a-f]{16}$")
NONCE = re.compile(r"^[0-9a-f]{32}$")
DIGEST = re.compile(r"^[0-9a-f]{64}$")
ALLOWED = frozenset({"version", "request_id", "question_sha256", "tool", "source_ids", "signature"})


class ProvenanceRejected(ValueError):
    """Expose only stable reason tokens, not raw document or model text."""


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical(obj: dict) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _validate_request(request_id: str, question: str, key: bytes) -> None:
    if not isinstance(request_id, str) or not NONCE.fullmatch(request_id):
        raise ProvenanceRejected("invalid_request_id")
    if not isinstance(question, str) or not 1 <= len(question.strip()) <= 500:
        raise ProvenanceRejected("invalid_question")
    if not isinstance(key, bytes) or len(key) < 32:
        raise ProvenanceRejected("invalid_key")


def issue_receipt(*, key: bytes, request_id: str, question: str, results: dict) -> dict:
    """Use ONLY inside a trusted MCP tool handler after an actual tool call.

    Caller must independently authenticate the transport's request_id and
    must not accept model-supplied request identifiers or tool results.
    """
    _validate_request(request_id, question, key)
    hits = results.get("results") if isinstance(results, dict) else None
    if not isinstance(hits, list) or not 1 <= len(hits) <= 8:
        raise ProvenanceRejected("invalid_tool_results")
    ids = [hit.get("source_id") if isinstance(hit, dict) else None for hit in hits]
    if (any(not isinstance(sid, str) or not HEX.fullmatch(sid) for sid in ids)
            or len(set(ids)) != len(ids)):
        raise ProvenanceRejected("invalid_source_ids")
    payload = {"version": "0.1", "request_id": request_id,
               "question_sha256": _digest(question), "tool": "docs_search",
               "source_ids": ids}
    return {**payload, "signature": hmac.new(key, _canonical(payload), hashlib.sha256).hexdigest()}


def verify_receipt(*, key: bytes, request_id: str, question: str,
                   receipt: dict, index: dict, rendered_source_ids: list[str]) -> None:
    """Fail closed unless an authentic same-request signed ID list covers all cited IDs.

    Local reference index validation is independent of the signature.
    This does not verify model consumption or semantic grounding.
    """
    _validate_request(request_id, question, key)
    if not isinstance(receipt, dict) or set(receipt) != ALLOWED:
        raise ProvenanceRejected("invalid_receipt_shape")
    signature = receipt.get("signature")
    if not isinstance(signature, str) or not DIGEST.fullmatch(signature):
        raise ProvenanceRejected("invalid_signature")
    unsigned = {k: v for k, v in receipt.items() if k != "signature"}
    expected = hmac.new(key, _canonical(unsigned), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise ProvenanceRejected("signature_mismatch")
    if (receipt["version"] != "0.1" or receipt["tool"] != "docs_search"
            or receipt["request_id"] != request_id
            or receipt["question_sha256"] != _digest(question)):
        raise ProvenanceRejected("request_mismatch")
    ids = receipt["source_ids"]
    if (not isinstance(ids, list) or not 1 <= len(ids) <= 8
            or any(not isinstance(sid, str) or not HEX.fullmatch(sid) for sid in ids)
            or len(set(ids)) != len(ids)):
        raise ProvenanceRejected("invalid_source_ids")
    corpus = validate_index(index)["corpus"]
    known = {item["source_id"] for item in corpus}
    if any(sid not in known for sid in ids):
        raise ProvenanceRejected("unknown_sources")
    if (not isinstance(rendered_source_ids, list) or not rendered_source_ids
            or any(not isinstance(sid, str) or sid not in ids for sid in rendered_source_ids)):
        raise ProvenanceRejected("unattested_citation")
