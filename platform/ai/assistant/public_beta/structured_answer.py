"""Experimental structured answer contract, offline only, NOT public-ready.

Schema/metadata checks are not evidence of semantic answer correctness or
attested same-request tool calls. No arbitrary shell or Markdown is allowed.
"""
from __future__ import annotations

import json
import re

from answer_integrity import validate_answer
from docs_mcp import validate_index

SOURCE_ID = re.compile(r"^[0-9a-f]{16}$")
URL = re.compile(r"https?://", re.I)
CONTROL = re.compile(r"[\x00-\x1f\x7f]")
# v0.1 deliberately rejects formatting and command-looking text.
MARKUP = re.compile(r"[\x60<>\\\[\]|*#]|(?:^|\s)(?:sudo|kubectl|curl|wget|bash|sh|rm|chmod|helm)\s", re.I)


class ContractRejected(ValueError):
    """Never forward raw model output or error arguments to end users."""


def validate_and_render(raw: str, retrieval: dict, index: dict) -> str:
    """Render source-bound links without trusting model-supplied URLs.

    Strict syntax/metadata controls only; does NOT assess semantic grounding.
    """
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > 8192:
        raise ContractRejected("invalid_payload")
    try:
        payload = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except ValueError:
        raise ContractRejected("invalid_json") from None
    if not isinstance(payload, dict) or set(payload) != {"version", "steps"} or payload["version"] != "0.1":
        raise ContractRejected("invalid_shape")
    steps = payload["steps"]
    if not isinstance(steps, list) or not 1 <= len(steps) <= 6:
        raise ContractRejected("invalid_steps")
    try:
        corpus = validate_index(index)["corpus"]
    except (ValueError, TypeError, KeyError):
        raise ContractRejected("invalid_index") from None
    docs_by_id = {doc["source_id"]: doc for doc in corpus}
    hits = retrieval.get("results") if isinstance(retrieval, dict) else None
    if not isinstance(hits, list) or not 1 <= len(hits) <= 8:
        raise ContractRejected("invalid_retrieval")
    allowed = {}
    for hit in hits:
        if not isinstance(hit, dict):
            raise ContractRejected("invalid_retrieval")
        doc = docs_by_id.get(hit.get("source_id"))
        if doc is None or any(hit.get(field) != expected for field, expected in (
            ("url", doc["url"]), ("snippet", doc["text"]), ("commit_sha", doc["revision"]),
            ("path", doc["path"]), ("repo", doc["repo"]), ("title", doc["section"]),
        )):
            raise ContractRejected("retrieval_mismatch")
        allowed[doc["source_id"]] = doc
    rendered = []
    for number, step in enumerate(steps, 1):
        if not isinstance(step, dict) or set(step) != {"text", "source_ids"}:
            raise ContractRejected("invalid_step")
        text = step["text"]
        ids = step["source_ids"]
        if (not isinstance(text, str) or not 1 <= len(text) <= 600
                or text != text.strip() or CONTROL.search(text)
                or URL.search(text) or MARKUP.search(text)):
            raise ContractRejected("unsupported_text")
        if (not isinstance(ids, list) or not 1 <= len(ids) <= 3
                or any(not isinstance(sid, str) or not SOURCE_ID.fullmatch(sid)
                       or sid not in allowed for sid in ids)
                or len(set(ids)) != len(ids)):
            raise ContractRejected("invalid_sources")
        links = ", ".join(
            f"[Source {ordinal}]({allowed[sid]['url']})"
            for ordinal, sid in enumerate(ids, 1)
        )
        rendered.append(f"{number}. {text} {links}")
    answer = "\n\n".join(rendered)
    verdict = validate_answer(answer, retrieval, index)
    if not verdict.accepted:
        raise ContractRejected("legacy_integrity_reject")
    return answer
