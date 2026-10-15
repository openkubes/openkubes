"""Privacy-preserving counters for rejected A2A answers.

Reports ONLY fixed field names, booleans and counts. Never outputs text,
URLs, code, source IDs, hashes or excerpts. Diagnostic, not a validator.
"""
from __future__ import annotations

import re

from answer_integrity import ANY_FENCE, FENCE, LINK, SOURCE_TOKEN, URL


def diagnostic_counts(answer: str, retrieval: dict) -> dict:
    if not isinstance(answer, str):
        raise ValueError("Expected text")
    hits = retrieval.get("results", [])
    if not isinstance(hits, list):
        raise ValueError("Expected hits")
    passages = "\n".join(
        h["snippet"] for h in hits
        if isinstance(h, dict) and isinstance(h.get("snippet"), str)
    ).replace("\r\n", "\n")
    fences = list(FENCE.finditer(answer))
    all_fences = list(ANY_FENCE.finditer(answer))
    outside_fences = ANY_FENCE.sub("", answer)
    parsed_links = list(LINK.finditer(outside_fences))
    urls = {h.get("url") for h in hits if isinstance(h, dict)}
    unmatched = sum(
        not m.group(1).strip() or m.group(1).replace("\r\n", "\n") not in passages
        for m in fences
    )
    # source IDs are counted but never emitted.
    return {
        "fence_marker_count": answer.count("```"),
        "recognized_shell_fences": len(fences),
        "recognized_all_fences": len(all_fences),
        "unverified_shell_fences": unmatched,
        "has_inline_backticks_outside_fences": "`" in outside_fences,
        "has_angle_brackets_outside_fences": "<" in outside_fences or ">" in outside_fences,
        "markdown_links": len(parsed_links),
        "trusted_markdown_links": sum(m.group(2) in urls for m in parsed_links),
        "bare_url_count": len(URL.findall(LINK.sub("", outside_fences))),
        "bare_source_token_count": len(SOURCE_TOKEN.findall(outside_fences)),
        "retrieval_at_limit": len(hits) == 8,
    }
