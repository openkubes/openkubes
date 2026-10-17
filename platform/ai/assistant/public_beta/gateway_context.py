"""Offline gateway-owned, deterministic documentation context envelope.

This does NOT send A2A requests, certify model consumption, sign provenance,
or perform semantic grounding. Only trusted gateway code may supply retrieval.
"""
from __future__ import annotations

import hashlib
import json
import re

from docs_mcp import validate_index

SOURCE_ID = re.compile(r"^[0-9a-f]{16}$")
MAX_QUESTION_CHARS = 500
MAX_RESULTS = 8
MAX_CONTEXT_BYTES = 24 * 1024
MAX_SNIPPET_CHARS = 2600


class ContextRejected(ValueError):
    """Stable rejection reason only; never surface raw document content."""


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, OverflowError):
        raise ContextRejected("invalid_context_data") from None


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def build_context_envelope(question: str, retrieval: dict, index: dict) -> dict:
    """Construct immutable-by-convention JSON data from one trusted retrieval.

    The caller must not regenerate retrieval after model output, or accept
    retrieval or index objects supplied by the model or end user.
    """
    if (not isinstance(question, str) or not 1 <= len(question.strip()) <= MAX_QUESTION_CHARS
            or question != question.strip() or any(ord(c) < 32 or ord(c) == 127 for c in question)):
        raise ContextRejected("invalid_question")
    try:
        validated = validate_index(index)
    except (TypeError, ValueError, KeyError):
        raise ContextRejected("invalid_index") from None
    if not isinstance(retrieval, dict) or set(retrieval) != {"results"}:
        raise ContextRejected("invalid_retrieval")
    hits = retrieval["results"]
    if not isinstance(hits, list) or not 1 <= len(hits) <= MAX_RESULTS:
        raise ContextRejected("invalid_retrieval")
    docs = {doc["source_id"]: doc for doc in validated["corpus"]}
    sources = []
    seen = set()
    for hit in hits:
        if not isinstance(hit, dict) or set(hit) != {
                "source_id", "title", "snippet", "repo", "path", "commit_sha", "url"}:
            raise ContextRejected("invalid_hit")
        sid = hit["source_id"]
        if not isinstance(sid, str) or not SOURCE_ID.fullmatch(sid) or sid in seen:
            raise ContextRejected("invalid_source_id")
        doc = docs.get(sid)
        if doc is None or any(hit[k] != expected for k, expected in (
            ("title", doc["section"]), ("snippet", doc["text"]),
            ("repo", doc["repo"]), ("path", doc["path"]),
            ("commit_sha", doc["revision"]), ("url", doc["url"]))):
            raise ContextRejected("retrieval_mismatch")
        if len(doc["text"]) > MAX_SNIPPET_CHARS:
            raise ContextRejected("oversized_snippet")
        seen.add(sid)
        sources.append({
            "source_id": sid,
            "snippet": doc["text"],
            "snippet_sha256": hashlib.sha256(doc["text"].encode("utf-8")).hexdigest(),
        })
    # Source content is *data*, not an instruction. Deliberately JSON-encode
    # all content instead of string concatenation or markdown fences.
    payload = {
        "version": "0.1",
        "kind": "openkubes.gateway.docs-context",
        "question": question,
        "index_sha256": _sha(validated),
        "retrieval_sha256": _sha(retrieval),
        "sources": sources,
    }
    raw = _canonical(payload)
    if len(raw) > MAX_CONTEXT_BYTES:
        raise ContextRejected("oversized_context")
    return {"payload": payload, "context_sha256": hashlib.sha256(raw).hexdigest()}


def encode_context_envelope(envelope: dict) -> str:
    """Return deterministic serialized data for a future no-tools A2A agent.

    This encoder is NOT evidence that an A2A request was delivered.
    """
    if not isinstance(envelope, dict) or set(envelope) != {"payload", "context_sha256"}:
        raise ContextRejected("invalid_envelope")
    raw = _canonical(envelope["payload"])
    if (len(raw) > MAX_CONTEXT_BYTES
            or hashlib.sha256(raw).hexdigest() != envelope["context_sha256"]):
        raise ContextRejected("envelope_hash_mismatch")
    # No prompt concatenation: the future agent's system instructions must
    # label this entire serialized blob as untrusted documentary data.
    return raw.decode("utf-8")
