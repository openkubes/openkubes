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
    # Structural diagnostics only: never expose the offending line or words.
    lines = answer.splitlines()
    fence_lines = [line for line in lines if "```" in line]
    standalone = sum(bool(re.fullmatch(r" {0,3}```[^\x60]*", line))
                     for line in fence_lines)
    table_embedded = sum("|" in line for line in fence_lines)
    list_embedded = sum(bool(re.match(r"\s*(?:[-*+] |\d+[.)] )", line))
                        for line in fence_lines)
    # Inline code and other Markdown patterns are counts, not permission
    # to bypass the strict response validator.
    tables = sum(bool(re.match(r"\s*\|.*\|\s*$", line)) for line in lines)
    # source IDs are counted but never emitted.
    return {
        "fence_marker_count": answer.count("```"),
        "lines_containing_fences": len(fence_lines),
        "standalone_fence_lines": standalone,
        "table_embedded_fence_lines": table_embedded,
        "list_embedded_fence_lines": list_embedded,
        "markdown_table_like_lines": tables,
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


# v2 uses only a closed set of labels. Never return raw language tags, URLs,
# snippets or answer text: these can contain secrets or user-supplied content.
_FENCE_LINE = re.compile(r"^ {0,3}`{3}([^\x60]*)$")
_INLINE_CODE = re.compile(r"(?<!`)`(?!`)")
_ALLOWED_LANGUAGES = frozenset(("bash", "sh", "json", "yaml", "yml", "text",
                                "python", "console", "shell", "markdown"))


def format_diagnostics_v2(answer: str, retrieval: dict) -> dict:
    """Privacy-preserving structural analysis; never a validation bypass.

    Marker positions are 1-based line numbers; user content, paths, domains,
    language tokens and absolute URLs are never returned.
    """
    if not isinstance(answer, str) or len(answer) > 20_000:
        raise ValueError("Expected bounded text")
    if not isinstance(retrieval, dict) or not isinstance(retrieval.get("results"), list):
        raise ValueError("Expected retrieval results")
    hits = retrieval["results"]
    trusted_urls = {h.get("url") for h in hits if isinstance(h, dict)}
    lines = answer.splitlines()
    language_counts = {k: 0 for k in ("bash", "sh", "json", "yaml", "text",
                                      "python", "console", "shell", "markdown",
                                      "empty", "other")}
    markers = []
    in_fence = False
    unexpected_markers = 0
    for line_no, line in enumerate(lines, 1):
        if "```" not in line:
            continue
        match = _FENCE_LINE.fullmatch(line)
        if match is None:
            unexpected_markers += line.count("```")
            continue
        markers.append(line_no)
        if not in_fence:
            label = match.group(1).strip().split(maxsplit=1)
            tag = label[0].lower() if label else "empty"
            if tag not in _ALLOWED_LANGUAGES and tag != "empty":
                tag = "other"
            language_counts[tag] += 1
        in_fence = not in_fence

    # Conservative: the existing validator remains the authority. For
    # malformed fences report counts without trying to repair the model text.
    outside = ANY_FENCE.sub("", answer)
    bare_text = LINK.sub("", outside)
    bare_urls = URL.findall(bare_text)
    url_classes = {"github_https": 0, "other_https": 0, "http": 0}
    for url in bare_urls:
        if url.startswith("http://"):
            url_classes["http"] += 1
        elif url.startswith("https://github.com/"):
            url_classes["github_https"] += 1
        else:
            url_classes["other_https"] += 1
    links = list(LINK.finditer(outside))
    return {
        "fence_languages": language_counts,
        "standalone_fence_line_numbers": markers[:32],
        "standalone_fence_line_count": len(markers),
        "embedded_fence_marker_count": unexpected_markers,
        "unmatched_standalone_fence": in_fence,
        "inline_single_backtick_count_outside_recognized_fences": len(_INLINE_CODE.findall(outside)),
        "angle_bracket_count_outside_recognized_fences": outside.count("<") + outside.count(">"),
        "bare_url_classes": url_classes,
        "markdown_link_count": len(links),
        "trusted_markdown_link_count": sum(m.group(2) in trusted_urls for m in links),
        "notes": "Structural diagnostic only; no model or source text is included.",
    }
