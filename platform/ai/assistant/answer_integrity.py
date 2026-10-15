"""Conservative, offline answer gate for a future OK AI public gateway.

Prototype only. A passing result is NOT a semantic or security proof.
No network calls, model calls, or Kubernetes access.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from docs_mcp import validate_index

FENCE = re.compile(r"(?m)^```(?:bash|sh)\s*\n(.*?)^```\s*$", re.S | re.M)
ANY_FENCE = re.compile(r"(?m)^```[^\n]*\n.*?^```\s*$", re.S | re.M)
LINK = re.compile(r"\[([^\]\n]+)\]\((https://[^)\s]+)\)")
URL = re.compile(r"https?://[^\s<>)\]]+")
SOURCE_TOKEN = re.compile(r"source_id\s*[:=]\s*[0-9a-f]{16}", re.I)


@dataclass(frozen=True)
class Verdict:
    accepted: bool
    reasons: tuple[str, ...]


def validate_answer(answer: str, retrieval: dict, index: dict) -> Verdict:
    """Validate restricted Markdown with exact copied shell blocks and links.

    retrieval must be the results from the SAME question's docs_search tool call.
    Reject rather than silently stripping suspect content.
    """
    reasons: list[str] = []
    if not isinstance(answer, str) or not answer.strip() or len(answer) > 20_000:
        return Verdict(False, ("invalid_answer",))
    try:
        corpus = validate_index(index)["corpus"]
    except (ValueError, TypeError, KeyError):
        return Verdict(False, ("invalid_index",))
    indexed = {d["source_id"]: d for d in corpus}
    items = retrieval.get("results") if isinstance(retrieval, dict) else None
    if not isinstance(items, list) or not items or len(items) > 8:
        return Verdict(False, ("invalid_retrieval",))
    trusted = {}
    for hit in items:
        if not isinstance(hit, dict):
            return Verdict(False, ("invalid_retrieval",))
        doc = indexed.get(hit.get("source_id"))
        if doc is None or any(hit.get(k) != expected for k, expected in (
            ("url", doc["url"]), ("snippet", doc["text"]),
            ("commit_sha", doc["revision"]), ("path", doc["path"]),
            ("repo", doc["repo"]), ("title", doc["section"]),
        )):
            return Verdict(False, ("retrieval_mismatch",))
        trusted[doc["url"]] = trusted.get(doc["url"], "") + "\n" + doc["text"]

    # This strict MVP intentionally rejects all inline backticks, raw HTML,
    # reference-style Markdown links and non-shell fenced blocks. These can
    # be supported later through a proper structured response contract.
    fences = list(FENCE.finditer(answer))
    all_fences = list(ANY_FENCE.finditer(answer))
    if len(fences) != len(all_fences) or answer.count("```") != 2 * len(fences):
        reasons.append("unsupported_or_unclosed_fence")
    prose = ANY_FENCE.sub("", answer)
    if "`" in prose or "<" in prose or ">" in prose or re.search(r"\]\[[^\]]+\]", prose):
        reasons.append("unsupported_markup")
    links = list(LINK.finditer(prose))
    if not links:
        reasons.append("missing_clickable_citation")
    for match in links:
        if match.group(2) not in trusted:
            reasons.append("untrusted_citation")
    # Remove parsed markdown links: any remaining URL is untrusted text,
    # not a clickable citation with vetted metadata.
    without_links = LINK.sub("", prose)
    if URL.search(without_links) or SOURCE_TOKEN.search(without_links):
        reasons.append("bare_url_or_source_token")
    passages = "\n".join(trusted.values()).replace("\r\n", "\n")
    for fence in fences:
        block = fence.group(1).replace("\r\n", "\n")
        if not block.strip() or block not in passages:
            reasons.append("unverified_shell_block")
    return Verdict(not reasons, tuple(dict.fromkeys(reasons)))
