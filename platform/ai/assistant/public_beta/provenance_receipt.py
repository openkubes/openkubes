"""Offline, fail-closed MCP receipt protocol v0.2. NOT runtime attestation.

Only trusted MCP instrumentation may create events/sign receipts. The caller
MUST authenticate that boundary; this library cannot prove a tool was called,
that model consumed results, or that cited claims are semantically supported.
No production keys or Kubernetes credentials in this module.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from collections.abc import Callable

from docs_mcp import validate_index

NONCE = re.compile(r"^[0-9a-f]{32}$")
HEX = re.compile(r"^[0-9a-f]{16}$")
DIGEST = re.compile(r"^[0-9a-f]{64}$")
IDENT = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._/-]{0,127}$")
FIELDS = frozenset({
    "version", "key_id", "issuer", "audience", "agent_id", "request_id",
    "event_id", "question_sha256", "tool", "arguments_sha256",
    "results_sha256", "index_sha256", "source_ids", "issued_at",
    "expires_at", "signature",
})
MAX_TTL = 300


class ProvenanceRejected(ValueError):
    """Only fixed error labels. Never include document content or secrets."""


def _fail(code: str):
    raise ProvenanceRejected(code)


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (ValueError, TypeError, OverflowError):
        _fail("invalid_canonical_data")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _validate_identity(value: str) -> bool:
    return isinstance(value, str) and bool(IDENT.fullmatch(value))


def _check_key(key: bytes):
    # Entropy must be guaranteed by external CSPRNG key provisioning.
    if not isinstance(key, bytes) or len(key) != 32:
        _fail("invalid_key")


def _check_context(request_id: str, question: str, *, issuer: str,
                   audience: str, agent_id: str, key_id: str, event_id: str):
    if (not isinstance(request_id, str) or not NONCE.fullmatch(request_id)
            or not isinstance(event_id, str) or not NONCE.fullmatch(event_id)):
        _fail("invalid_request_context")
    if (not isinstance(question, str) or not 1 <= len(question.strip()) <= 500
            or any(not _validate_identity(x) for x in
                   (issuer, audience, agent_id, key_id))):
        _fail("invalid_request_context")


def _snapshot(index: dict) -> tuple[dict, str]:
    try:
        validated = validate_index(index)
    except (ValueError, KeyError, TypeError):
        _fail("invalid_index")
    return validated, _digest(validated)


def _tool_results(results: dict, validated: dict) -> tuple[list[str], str]:
    if not isinstance(results, dict) or set(results) != {"results"}:
        _fail("invalid_tool_results")
    hits = results["results"]
    if not isinstance(hits, list) or not 1 <= len(hits) <= 8:
        _fail("invalid_tool_results")
    by_id = {doc["source_id"]: doc for doc in validated["corpus"]}
    ids = []
    for hit in hits:
        if not isinstance(hit, dict) or set(hit) != {
                "source_id", "title", "snippet", "repo", "path",
                "commit_sha", "url"}:
            _fail("invalid_tool_results")
        sid = hit.get("source_id")
        if not isinstance(sid, str) or not HEX.fullmatch(sid):
            _fail("invalid_tool_results")
        doc = by_id.get(sid)
        if doc is None or any(hit.get(k) != v for k, v in (
                ("title", doc["section"]), ("snippet", doc["text"]),
                ("repo", doc["repo"]), ("path", doc["path"]),
                ("commit_sha", doc["revision"]), ("url", doc["url"]))):
            _fail("tool_result_mismatch")
        ids.append(sid)
    if len(set(ids)) != len(ids):
        _fail("duplicate_source_ids")
    return ids, _digest(results)


def _valid_time(issued_at: int, expires_at: int, now: int):
    if (any(type(t) is not int for t in (issued_at, expires_at, now))
            or not 0 < expires_at - issued_at <= MAX_TTL
            or issued_at > now + 5 or now >= expires_at):
        _fail("expired_or_invalid_receipt")


def issue_receipt(*, key: bytes, key_id: str, issuer: str, audience: str,
                  agent_id: str, request_id: str, event_id: str,
                  question: str, arguments: dict, results: dict,
                  index: dict, issued_at: int, expires_at: int,
                  now: int | None = None) -> dict:
    """Offline helper; caller MUST attest the actual MCP tool event externally.

    Arguments/results are trusted only if supplied by an authenticated handler.
    Do not use model JSON or independently run the retriever to mint receipts.
    """
    _check_key(key)
    _check_context(request_id, question, issuer=issuer, audience=audience,
                   agent_id=agent_id, key_id=key_id, event_id=event_id)
    _valid_time(issued_at, expires_at, int(time.time()) if now is None else now)
    if not isinstance(arguments, dict) or set(arguments) != {"query", "limit"}:
        _fail("invalid_tool_arguments")
    if (arguments["query"] != question
            or type(arguments["limit"]) is not int
            or not 1 <= arguments["limit"] <= 8):
        _fail("invalid_tool_arguments")
    validated, index_sha = _snapshot(index)
    ids, results_sha = _tool_results(results, validated)
    unsigned = {
        "version": "0.2", "key_id": key_id, "issuer": issuer,
        "audience": audience, "agent_id": agent_id,
        "request_id": request_id, "event_id": event_id,
        "question_sha256": hashlib.sha256(question.encode("utf-8")).hexdigest(),
        "tool": "docs_search", "arguments_sha256": _digest(arguments),
        "results_sha256": results_sha, "index_sha256": index_sha,
        "source_ids": ids, "issued_at": issued_at, "expires_at": expires_at,
    }
    return {**unsigned, "signature": hmac.new(
        key, _canonical(unsigned), hashlib.sha256).hexdigest()}


def verify_receipt(*, keys: dict[str, bytes], issuer: str, audience: str,
                   agent_id: str, request_id: str, question: str,
                   arguments: dict, results: dict, index: dict,
                   receipt: dict, cited_source_ids: list[str],
                   consume: Callable[[str, str, str], bool],
                   now: int | None = None) -> None:
    """Requires an ATOMIC external one-time receipt ledger (consume).

    Return true only if (issuer, request_id, event_id) was not consumed before.
    In-memory fixture sets are for tests only; production needs durable atomic
    persistence. No semantic entailment or model-use proof is implied.
    """
    if not isinstance(receipt, dict) or set(receipt) != FIELDS:
        _fail("invalid_receipt_shape")
    key_id = receipt.get("key_id")
    event_id = receipt.get("event_id")
    _check_context(request_id, question, issuer=issuer, audience=audience,
                   agent_id=agent_id, key_id=key_id, event_id=event_id)
    if not isinstance(keys, dict) or key_id not in keys:
        _fail("unknown_key")
    key = keys[key_id]
    _check_key(key)
    sig = receipt["signature"]
    if not isinstance(sig, str) or not DIGEST.fullmatch(sig):
        _fail("invalid_signature")
    unsigned = {k: v for k, v in receipt.items() if k != "signature"}
    expected = hmac.new(key, _canonical(unsigned), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        _fail("signature_mismatch")
    _valid_time(receipt["issued_at"], receipt["expires_at"],
                int(time.time()) if now is None else now)
    if (receipt["version"] != "0.2" or receipt["tool"] != "docs_search"
            or receipt["issuer"] != issuer or receipt["audience"] != audience
            or receipt["agent_id"] != agent_id
            or receipt["request_id"] != request_id
            or receipt["question_sha256"] != hashlib.sha256(
                question.encode("utf-8")).hexdigest()):
        _fail("request_mismatch")
    if not isinstance(arguments, dict) or arguments.get("query") != question:
        _fail("invalid_tool_arguments")
    if receipt["arguments_sha256"] != _digest(arguments):
        _fail("tool_arguments_mismatch")
    validated, index_sha = _snapshot(index)
    ids, results_sha = _tool_results(results, validated)
    if (receipt["results_sha256"] != results_sha
            or receipt["index_sha256"] != index_sha
            or receipt["source_ids"] != ids):
        _fail("tool_evidence_mismatch")
    if (not isinstance(cited_source_ids, list) or not cited_source_ids
            or any(not isinstance(sid, str) or sid not in ids
                   for sid in cited_source_ids)):
        _fail("unattested_citation")
    if not callable(consume):
        _fail("missing_replay_guard")
    try:
        fresh = consume(issuer, request_id, event_id)
    except Exception:
        _fail("replay_guard_unavailable")
    if fresh is not True:
        _fail("receipt_replayed")
